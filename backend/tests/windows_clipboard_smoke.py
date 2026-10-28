"""Explicit opt-in real Windows clipboard/model integration test, using a test server.

Overwrites the system clipboard. Run only after the user authorizes Windows API writes.
Restores previous Unicode text when available; other clipboard formats cannot be restored.
"""
import argparse
import ctypes
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import sys
import time
from real_smoke import Api, ROOT
sys.path.insert(0, str(ROOT / 'backend/src'))
from cli_config import add_client_port
from clipboard import Clipboard


class WindowsWriter:
    def __init__(self):
        self.user=ctypes.WinDLL('user32',use_last_error=True)
        self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        for name,args,ret in [
            ('CreateWindowExW',[w.DWORD,w.LPCWSTR,w.LPCWSTR,w.DWORD,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,w.HWND,w.HMENU,w.HINSTANCE,ctypes.c_void_p],w.HWND),
            ('DestroyWindow',[w.HWND],w.BOOL),('OpenClipboard',[w.HWND],w.BOOL),
            ('CloseClipboard',[],w.BOOL),('EmptyClipboard',[],w.BOOL),
            ('SetClipboardData',[w.UINT,w.HANDLE],w.HANDLE)]:
            fn=getattr(self.user,name);fn.argtypes,fn.restype=args,ret
        for name,args,ret in [('GlobalAlloc',[w.UINT,ctypes.c_size_t],w.HANDLE),
            ('GlobalLock',[w.HANDLE],ctypes.c_void_p),('GlobalUnlock',[w.HANDLE],w.BOOL),('GlobalFree',[w.HANDLE],w.HANDLE)]:
            fn=getattr(self.kernel,name);fn.argtypes,fn.restype=args,ret
        self.owner=self.user.CreateWindowExW(0,'STATIC','GalTransl test clipboard owner',0,0,0,0,0,None,None,None,None)
        if not self.owner:raise ctypes.WinError(ctypes.get_last_error())

    def write(self,text):
        raw=(text+'\0').encode('utf-16-le')
        handle=self.kernel.GlobalAlloc(2,len(raw))
        if not handle:raise ctypes.WinError(ctypes.get_last_error())
        try:
            ptr=self.kernel.GlobalLock(handle)
            if not ptr:raise ctypes.WinError(ctypes.get_last_error())
            try:ctypes.memmove(ptr,raw,len(raw))
            finally:self.kernel.GlobalUnlock(handle)
            deadline=time.monotonic()+3
            while not self.user.OpenClipboard(self.owner):
                if time.monotonic()>deadline:raise ctypes.WinError(ctypes.get_last_error())
                time.sleep(.05)
            try:
                if not self.user.EmptyClipboard() or not self.user.SetClipboardData(13,handle):
                    raise ctypes.WinError(ctypes.get_last_error())
                handle=None  # Ownership now belongs to Windows.
            finally:self.user.CloseClipboard()
        finally:
            if handle:self.kernel.GlobalFree(handle)

    def close(self):self.user.DestroyWindow(self.owner)


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__);add_client_port(parser)
    parser.add_argument('--allow-system-clipboard-write',action='store_true',required=True)
    parser.add_argument('--output',type=Path,default=ROOT/'work/windows-clipboard-smoke.json')
    args=parser.parse_args()
    if os.name!='nt':parser.error('Windows only')
    api=Api(args.port);status=api.call('/status')
    assert status['state']=='ready' and status['session'],'ready test session required'
    profile=status['session']['profile_id']
    reader=Clipboard.__new__(Clipboard)  # Read API only; do not create another monitor.
    reader.user=ctypes.WinDLL('user32',use_last_error=True)
    reader.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    reader.user.OpenClipboard.argtypes=[w.HWND];reader.user.OpenClipboard.restype=w.BOOL
    reader.user.GetClipboardData.argtypes=[w.UINT];reader.user.GetClipboardData.restype=w.HANDLE
    reader.kernel.GlobalSize.argtypes=[w.HANDLE];reader.kernel.GlobalSize.restype=ctypes.c_size_t
    reader.kernel.GlobalLock.argtypes=[w.HANDLE];reader.kernel.GlobalLock.restype=ctypes.c_void_p
    reader.kernel.GlobalUnlock.argtypes=[w.HANDLE];reader.kernel.GlobalUnlock.restype=w.BOOL
    previous=reader.read()
    writer=WindowsWriter();report={'cases':[]}
    def history():return api.call('/history?profile_id='+profile+'&limit=200')['items']
    try:
        api.call('/clipboard',{'enabled':False},'PUT')
        baseline=len(history())
        writer.write('起動前の台詞：この文は翻訳しない。')
        api.call('/clipboard',{'enabled':True},'PUT');time.sleep(1)
        assert len(history())==baseline,'old clipboard was ingested on opt-in'
        report['cases'].append('enable skips old contents')
        source='葵、明日もここで会いましょう。'
        started=time.monotonic();writer.write(source)
        deadline=time.monotonic()+30
        while True:
            items=history()
            match=[h for h in items if h['source_text']==source and h['source_kind']=='clipboard']
            if match:break
            assert time.monotonic()<deadline,'system clipboard did not produce a terminal'
            time.sleep(.2)
        item=match[0];assert item['terminal']=='final' and '小葵' in item['translation'],item
        report['translation']=item;report['end_to_end_ms']=round((time.monotonic()-started)*1000)
        report['cases'].append('Windows clipboard -> live model -> durable final')
        time.sleep(1)
        assert len(history())==baseline+1,'one clipboard sequence was submitted twice'
        report['cases'].append('unchanged sequence does not repeat')
        writer.write('あ'*2001)
        deadline=time.monotonic()+4
        while (api.call('/status')['clipboard'].get('last_error') or {}).get('code')!='INPUT_TOO_LONG':
            assert time.monotonic()<deadline,'missing overlong notice'
            time.sleep(.1)
        assert len(history())==baseline+1
        report['cases'].append('overlong clipboard rejects before inference')
        api.call('/clipboard',{'enabled':False},'PUT')
        writer.write('停止後の台詞：この文は翻訳しない。');time.sleep(1)
        assert len(history())==baseline+1
        report['cases'].append('disabled listener ignores changes')
        report['result']='PASS'
    finally:
        api.call('/clipboard',{'enabled':False},'PUT')
        if previous is not None:writer.write(previous)
        report['previous_text_restored']=previous is not None
        writer.close()
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Windows clipboard integration '+report.get('result','FAIL'))
    print(source+' => '+item['translation']+' ('+str(report['end_to_end_ms'])+' ms including capture/poll)')


if __name__=='__main__':main()
