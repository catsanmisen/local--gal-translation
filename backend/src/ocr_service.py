"""One offline CPU OCR worker. Images stay in memory; no accepted-text side effects."""
import base64
import hashlib
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import uuid
from engine import ROOT,ClientError


class OcrService:
    def __init__(self):
        self.lock=threading.Lock();self.process=None;self.output=queue.Queue();self.reader=None
        self.folder=ROOT/'backend/vendor/ocr';self.available=False;self.manifest=None
        portable=ROOT/'backend/runtime/python/python.exe'
        self.python=portable if portable.exists() else ROOT/'.venv-ocr/Scripts/python.exe'
        try:
            self.manifest=json.loads((self.folder/'manifest.json').read_text(encoding='utf-8'))
            self.available=self.python.exists() and all(hashlib.sha256((self.folder/f['path']).read_bytes()).hexdigest()==f['sha256'] for f in self.manifest['files'])
        except (OSError,ValueError,KeyError):pass

    def _start(self):
        if self.process and self.process.poll() is None:return
        self.output=queue.Queue()
        self.process=subprocess.Popen([str(self.python),'-B',str(ROOT/'backend/src/ocr_worker.py')],
            cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
        proc=self.process;out=self.output
        def read():
            try:
                for line in proc.stdout:
                    try:out.put(json.loads(line))
                    except ValueError:pass
            finally:out.put({'error':'OCR 进程已退出。'})
        self.reader=threading.Thread(target=read,daemon=True,name='ocr-json-reader');self.reader.start()

    def recognize(self,png):
        if not self.available:raise ClientError('OCR_UNAVAILABLE','OCR 组件或模型未通过校验，请重新构建离线组件。',503)
        if not self.lock.acquire(blocking=False):raise ClientError('OCR_BUSY','上一帧仍在识别，已跳过本帧。',429)
        try:
            self._start();rid=uuid.uuid4().hex
            self.process.stdin.write(json.dumps({'id':rid,'png':base64.b64encode(png).decode('ascii')})+'\n');self.process.stdin.flush()
            try:result=self.output.get(timeout=15)
            except queue.Empty:self.close();raise ClientError('OCR_TIMEOUT','识别超时，本帧未提交。',503)
            if result.get('error'):raise ClientError('OCR_FAILED',result['error'],503)
            if result.get('id')!=rid:raise ClientError('OCR_FAILED','OCR 响应身份失配。',503)
            return {k:v for k,v in result.items() if k!='id'}
        except (OSError,BrokenPipeError) as e:
            self.close();raise ClientError('OCR_FAILED','OCR 进程不可用，本帧未提交。',503) from e
        finally:self.lock.release()

    def close(self):
        proc=self.process;self.process=None
        if proc:
            if proc.poll() is None:proc.terminate()
            try:proc.wait(timeout=3)
            except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=3)
            if proc.stdin:proc.stdin.close()
            if proc.stdout:proc.stdout.close()

