"""Owned llama lifecycle, fresh VRAM samples, and verified slot cancellation."""
from datetime import datetime, timezone
import http.client
import json
import os
import secrets
import logging
import socket
import sys
import threading
import time
from pathlib import Path
from owned_process import OwnedProcess

ROOT = Path(__file__).resolve().parents[2]
MODEL_ROOT = ROOT / 'backend' / 'galtransl4'
sys.path.insert(0, str(MODEL_ROOT))
from gal_translate import payload, assess_risks, REPAIR_EXAMPLE_SOURCE, REPAIR_EXAMPLE_RESULT
import gal_service
from execution_policy import preferences

def utcnow():
    return datetime.now(timezone.utc).isoformat()

class ClientError(Exception):
    def __init__(self, code, message, status=400, **extra):
        super().__init__(message)
        self.code, self.message, self.status, self.extra = code, message, status, extra
    def json(self):
        return {'code': self.code, 'message': self.message, 'retryable': self.status >= 500, **self.extra}

class Engine:
    def __init__(self, wallpaper=None):
        self.config = json.loads((MODEL_ROOT / 'service-config.json').read_text(encoding='utf-8'))
        self.lock = threading.RLock()
        self.lifecycle = threading.Lock()
        self.process = self.thread = self.connection = self.log = None
        self.state, self.gpu, self.layers, self.last_error = 'stopped', None, None, None
        self.started = 0
        self.stop_event = threading.Event()
        self.key = secrets.token_urlsafe(32)
        self.stop_diagnostic = None
        self.last_generation_timings = {}
        self.last_generation_trace = {}
        self.launch_parameters = None

        self.gpu_layer_cap = None
        self.cpu_fallback = False
        self.execution_mode = None
        self.requested_mode = 'auto'
        self.start_margin = self.config['minimum_start_free_mib']-self.config['minimum_free_mib']
        self.wallpaper=wallpaper;self.preserve_wallpaper=False

    def set_wallpaper_relief(self, enabled):
        if self.wallpaper:self.wallpaper.configure(enabled)

    def release_wallpaper(self):
        if self.wallpaper:self.wallpaper.restore()

    def configure_execution(self, mode, reserve):
        try:preferences(delta={'model_mode':mode,'gpu_reserve_mib':reserve})
        except ValueError as error:raise ClientError('INVALID_SETTINGS',str(error)) from error
        with self.lifecycle,self.lock:
            if self.thread and self.thread.is_alive():raise ClientError('ENGINE_STOPPING','请等待所属模型完整停止后切换设置。',409)
            self.requested_mode=mode;self.config['minimum_free_mib']=reserve
            self.config['minimum_start_free_mib']=reserve+self.start_margin
            self.gpu_layer_cap=None;self.execution_mode=None;self.layers=None

    def set_cpu_fallback(self, enabled):
        with self.lock:self.cpu_fallback=bool(enabled)

    def offload_plan(self, free_mib, metadata):
        if self.requested_mode=='cpu':return 0,True
        reserve=self.config['minimum_free_mib']
        fallback=self.cpu_fallback and self.requested_mode=='auto'
        if free_mib<self.config['minimum_start_free_mib'] and not (fallback and free_mib>=reserve):
            raise ClientError('VRAM_LOW', f"启动需要 {self.config['minimum_start_free_mib']} MiB 可用显存，当前 {free_mib} MiB。", 503)
        budget=free_mib-reserve-self.config['reserve_headroom_mib']-self.config['runtime_allowance_mib']
        cap=self.config['max_gpu_layers'] if self.gpu_layer_cap is None else min(self.config['max_gpu_layers'],self.gpu_layer_cap)
        layers=max((int(n) for n,size in metadata['gpu_offload_weight_mib'].items() if int(n)<=cap and size<=budget),default=0)
        if self.requested_mode=='gpu' and layers==0:
            raise ClientError('VRAM_LOW','GPU 可用显存不足以加载模型层；已保留 GPU 选择，请等待显存恢复、降低预留或主动切换 CPU。',503)
        return layers, bool(fallback and layers==0)

    def recovery_sample(self):
        return self._sample()

    def set_recovery_cap(self, cap):
        with self.lock:
            self.gpu_layer_cap = cap

    def status(self):
        with self.lock:
            gpu = dict(self.gpu) if self.gpu and time.monotonic() - self.gpu['_at'] < 4 else None
            if gpu:
                gpu.pop('_at')
            state, error = self.state, self.last_error or self.stop_diagnostic
            if state == 'ready' and gpu is None and self.execution_mode!='cpu':
                state = 'recovering'
                error = ClientError('GPU_MONITOR_UNAVAILABLE', '显存样本过期，等待新的监测结果。', 503).json()
            return {'state': state, 'message': state, 'gpu': gpu, 'last_error': error,
                'wallpaper':self.wallpaper.status() if self.wallpaper else {'available':False,'state':'unavailable','message':'当前运行入口未启用自动壁纸控制。'},
                'owned_pid': self.process.pid if self.process and self.process.poll() is None else None,
                'loading_elapsed_ms': round((time.monotonic() - self.started) * 1000) if self.state in ('starting', 'loading') else None,
                'model': {'id': 'galtransl4-ja-zh', 'quantization': 'Q6_K', 'context_tokens': self.config['context_tokens'], 'gpu_layers': self.layers,'execution_mode':self.execution_mode,
                    'requested_mode':self.requested_mode,'gpu_reserve_mib':self.config['minimum_free_mib'],'gpu_monitor_required':self.execution_mode!='cpu' and self.requested_mode!='cpu'}}

    def start(self):
        with self.lifecycle, self.lock:
            if self.thread and self.thread.is_alive():
                if self.state == 'stopping':
                    raise ClientError('ENGINE_STOPPING', '模型正在停止，请稍后启动。', 409)
                return
            if gal_service.health(self.config['port']):
                raise ClientError('ENGINE_IN_USE', '内部端口已有模型服务，请先停止原启动器。', 409)
            raw = gal_service.status()
            if time.time() - raw.get('heartbeat_unix', 0) < 20 and raw.get('state') in ('starting', 'loading', 'ready'):
                raise ClientError('ENGINE_IN_USE', '原模型启动器仍在运行，请先停止它。', 409)
            self.stop_event.clear()
            self.preserve_wallpaper=False
            self.stop_diagnostic = None
            self.last_error, self.state, self.started = None, 'starting', time.monotonic()
            self.thread = threading.Thread(target=self._run, daemon=True, name='model-watchdog')
            self.thread.start()

    def _sample(self):
        sample = gal_service.gpu()
        with self.lock:
            self.gpu = {**sample, 'reserve_mib': self.config['minimum_free_mib'], 'sampled_at': utcnow(), '_at': time.monotonic()}
        return sample

    def _run(self):
        failure = None
        try:
            baseline={'free_mib':0}
            if self.requested_mode!='cpu':
                try:baseline = self._sample()
                except Exception as error:
                    raise ClientError('GPU_MONITOR_UNAVAILABLE', '无法读取显存；GPU/自动模式需要可用的 NVIDIA 监测，可主动选择 CPU。', 503) from error
            manifest = json.loads((MODEL_ROOT / 'installation.json').read_text(encoding='utf-8'))
            runtime = (MODEL_ROOT / manifest['runtime_directory']).resolve()
            executable = runtime / 'llama-server.exe'
            model = MODEL_ROOT / 'models' / manifest['model_file']
            if not executable.is_file() or not model.is_file():
                raise ClientError('MODEL_MISSING', '模型或运行库缺失，请检查安装目录。', 503)
            metadata = json.loads((MODEL_ROOT / 'model-metadata.json').read_text(encoding='utf-8'))
            if metadata['metadata'].get('general.architecture') != 'qwen3' or metadata['metadata'].get('general.file_type') != 18:
                raise ClientError('MODEL_INVALID', '模型元数据与已验证的 Q6_K 模型不一致。', 503)
            full=max(map(int,metadata['gpu_offload_weight_mib']))
            budget=baseline['free_mib']-self.config['minimum_free_mib']-self.config['reserve_headroom_mib']-self.config['runtime_allowance_mib']
            pressure=self.requested_mode=='cpu' or metadata['gpu_offload_weight_mib'][str(full)]>budget
            if self.wallpaper and not self.stop_event.is_set() and self.wallpaper.acquire(pressure,self.stop_event.is_set) and self.requested_mode!='cpu':
                deadline=time.monotonic()+5
                while not self.stop_event.is_set():
                    baseline=self._sample()
                    if baseline['free_mib']-self.config['minimum_free_mib']-self.config['reserve_headroom_mib']-self.config['runtime_allowance_mib']>=metadata['gpu_offload_weight_mib'][str(full)]:break
                    if time.monotonic()>=deadline:break
                    self.stop_event.wait(.25)
            if self.stop_event.is_set():return
            self.layers,cpu_only=self.offload_plan(baseline['free_mib'],metadata)
            self.execution_mode='cpu' if cpu_only else 'gpu' if self.layers>=max(map(int,metadata['gpu_offload_weight_mib'])) else 'hybrid'
            # Prefill is matrix work; decoding remains memory-bound. The real
            # whole-page replay improved with wider CPU prefill, while reducing
            # decode workers or forcing P-core affinity regressed. Bound the
            # wider phase and retain the existing hybrid/generation baseline.
            batch_threads=min(16,os.cpu_count() or 8) if cpu_only else 8
            args = [str(executable), '--model', str(model), '--alias', 'galtransl4-ja-zh', '--host', '127.0.0.1',
                '--port', str(self.config['port']), '--ctx-size', str(self.config['context_tokens']), '--parallel', '1',
                '--batch-size', '256', '--ubatch-size', '128', '--threads', '8', '--threads-batch', str(batch_threads),
                '--gpu-layers', str(self.layers), '--fit', 'off', '--flash-attn', 'on', '--jinja', '--reasoning', 'off',
                '--reasoning-budget', '0', '--temp', '0.1', '--top-p', '0.8', '--top-k', '20', '--repeat-penalty', '1.0',
                '--seed', '42', '--predict', '384', '--log-verbosity', '2', '--slots', '--no-webui', '--cors-origins', 'localhost']
            if cpu_only:args.extend(['--device','none','--no-kv-offload'])
            self.launch_parameters={'arguments':args,'threads':8,'threads_batch':batch_threads,
                'cache_type_k':'f16','cache_type_v':'f16','gpu_layers':self.layers}
            with self.lock:
                if self.stop_event.is_set():
                    return
                (ROOT / 'logs').mkdir(exist_ok=True)
                self.log = (ROOT / 'logs' / 'engine.log').open('wb')
                self.process = OwnedProcess(args, runtime, self.log, {**os.environ, 'LLAMA_API_KEY': self.key})
                self.state = 'loading'
            last_health, errors = 0, 0
            while not self.stop_event.wait(0.75):
                if self.process.poll() is not None:
                    raise ClientError('ENGINE_FAILED', '模型进程意外退出，详见 logs/engine.log。', 503)
                try:
                    sample = self._sample() if not cpu_only else None
                    errors = 0
                    if sample is not None and sample['free_mib'] < self.config['minimum_free_mib']:
                        raise ClientError('VRAM_LOW', f"可用显存 {sample['free_mib']} MiB，低于保留阈值，已停止模型。", 503)
                except ClientError:
                    raise
                except Exception:
                    errors += 1
                    with self.lock:
                        self.gpu = None
                        self.last_error = ClientError('GPU_MONITOR_UNAVAILABLE', '显存采样失败，暂停提交新台词。', 503).json()
                    if errors >= 3:
                        raise ClientError('GPU_MONITOR_UNAVAILABLE', '显存连续三次采样失败，已停止模型。', 503)
                    continue
                with self.lock:
                    self.last_error = None
                if self.state == 'loading' and time.monotonic() - last_health >= 1:
                    last_health = time.monotonic()
                    if gal_service.health(self.config['port']):
                        with self.lock:
                            if not self.stop_event.is_set():
                                self.state = 'ready'
                    elif time.monotonic() - self.started > 180:
                        raise ClientError('ENGINE_TIMEOUT', '模型加载超时，请检查模型日志。', 503)
                if (ROOT / 'logs' / 'engine.log').stat().st_size > 8 * 1024 * 1024:
                    raise ClientError('LOG_LIMIT', '模型日志异常增长，已停止模型，请检查日志。', 503)
        except Exception as error:
            if not isinstance(error, ClientError):
                logging.exception('Model startup or monitor failed')
            failure = error if isinstance(error, ClientError) else ClientError('ENGINE_FAILED', '模型启动失败，请检查安装路径与日志。', 503)
        finally:
            self.interrupt()
            try:
                if self.process:
                    if self.process.poll() is None:
                        self.process.terminate()
                        self.process.wait(timeout=10)
                    self.process.close()
            finally:
                if self.log:
                    self.log.close()
                    self.log = None
                with self.lock:
                    self.process = None
                    self.state = ('paused' if failure.code == 'VRAM_LOW' else 'error') if failure and not self.stop_event.is_set() else 'stopped'
                    self.last_error = failure.json() if failure and not self.stop_event.is_set() else None
                if not self.preserve_wallpaper:self.release_wallpaper()

    def request_stop(self, preserve_wallpaper=False):
        release=False
        with self.lifecycle, self.lock:
            self.preserve_wallpaper=preserve_wallpaper
            self.stop_event.set()
            self.stop_diagnostic = None
            if self.thread and self.thread.is_alive():
                self.state = 'stopping'
            else:
                self.state, self.last_error = 'stopped', None
                release=not preserve_wallpaper
            self.interrupt()
        if release:self.release_wallpaper()

    def stop(self):
        self.request_stop()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=20)

    def stop_for_reload(self, preserve_wallpaper):
        self.request_stop(preserve_wallpaper)
        if self.thread and self.thread is not threading.current_thread():self.thread.join(timeout=20)

    def rpc(self, path, body=None, timeout=5):
        conn = http.client.HTTPConnection('127.0.0.1', self.config['port'], timeout=timeout)
        try:
            conn.request('POST' if body is not None else 'GET', path,
                json.dumps(body, ensure_ascii=False).encode('utf-8') if body is not None else None,
                {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self.key})
            response = conn.getresponse()
            data = json.loads(response.read())
            if response.status != 200:
                raise ClientError('ENGINE_ERROR', '模型服务拒绝请求。', 502)
            return data
        finally:
            conn.close()

    def interrupt(self):
        conn = self.connection
        if conn is not None:
            try:
                if conn.sock:
                    conn.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            conn.close()

    def _idle(self, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.status()['state'] in ('stopped', 'paused', 'error'):
                return
            try:
                slots = self.rpc('/slots', timeout=min(2, max(0.05, deadline - time.monotonic())))
                if isinstance(slots, list) and not any(slot.get('is_processing') for slot in slots):
                    return
            except (OSError, ClientError, ValueError):
                if self.stop_event.is_set():
                    self.stop()
                    return
            time.sleep(0.1)
        self.stop()
        diagnostic = ClientError('CANCEL_TIMEOUT', f'取消或断流后等待 {timeout:g} 秒，计算槽仍未释放；已停止本客户端模型，请重新启动。', 503, occurred_at=utcnow())
        with self.lock:
            self.stop_diagnostic = diagnostic.json()
        logging.warning('CANCEL_TIMEOUT: slot release exceeded %ss; stopped the owned engine', timeout)
        raise diagnostic

    def generate_repair(self, text, context, glossary, cancel, on_delta):
        return self.generate(text,context,glossary,cancel,on_delta,repair=True)

    def generate(self, text, context, glossary, cancel, on_delta, *, repair=False):
        self.last_generation_timings={};self.last_generation_trace={};started=time.perf_counter()
        history = list(context)
        while True:
            if cancel.is_set():
                return ''
            body = payload(text, '\n'.join(history), glossary, **({'repair':True} if repair else {}))
            template = self.rpc('/apply-template', {'messages': body['messages']})['prompt']
            count = len(self.rpc('/tokenize', {'content': template, 'add_special': True})['tokens'])
            if count + body['max_tokens'] + 16 <= self.config['context_tokens']:
                break
            if history:
                history.pop(0)
            else:
                raise ClientError('CONTEXT_LIMIT', '原文与术语超出上下文预算，请缩短后重试。')
        if cancel.is_set():
            return ''
        body.update(stream=True, stream_options={'include_usage':True}, cache_prompt=True, chat_template_kwargs={'enable_thinking': False})
        prepared=time.perf_counter();first_token=None
        conn = http.client.HTTPConnection('127.0.0.1', self.config['port'], timeout=30)
        self.connection = conn
        output, finish, reasoning = [], None, ''
        statistics={}
        finished = threading.Event()
        try:
            conn.connect()
            stream_socket = conn.sock
            def cancel_socket():
                while not finished.wait(0.05):
                    if cancel.is_set() or self.stop_event.is_set():
                        try:
                            stream_socket.shutdown(socket.SHUT_RDWR)
                        except OSError:
                            pass
                        return
            threading.Thread(target=cancel_socket, daemon=True).start()
            conn.request('POST', '/v1/chat/completions', json.dumps(body, ensure_ascii=False).encode('utf-8'),
                {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self.key})
            response = conn.getresponse()
            if response.status != 200:
                raise ClientError('ENGINE_ERROR', '推理请求失败，请检查模型状态。', 502)
            while not cancel.is_set():
                line = response.readline(65537)
                if len(line) > 65536:
                    raise ClientError('ENGINE_ERROR', '模型事件超过大小限制。', 502)
                if not line:
                    break
                if not line.startswith(b'data:'):
                    continue
                raw = line[5:].strip()
                if raw == b'[DONE]':
                    break
                data = json.loads(raw)
                if data.get('error'):
                    raise ClientError('ENGINE_ERROR', '模型返回推理错误。', 502)
                usage=data.get('usage') or {};server=data.get('timings') or {}
                for name,value in (('output_tokens',usage.get('completion_tokens')),('prompt_tokens',usage.get('prompt_tokens')),
                                   ('server_decode_ms',server.get('predicted_ms'))):
                    if type(value) in (int,float) and value>=0:statistics[name]=value
                choices = data.get('choices', [])
                if not choices:
                    continue
                choice = choices[0]
                if choice.get('delta', {}).get('reasoning_content'):
                    reasoning=choice['delta']['reasoning_content']
                    raise ClientError('FORMAT_DAMAGE', '模型意外产生推理内容。', 502)
                delta = choice.get('delta', {}).get('content', '')
                if delta:
                    if first_token is None:first_token=time.perf_counter()
                    output.append(delta)
                    on_delta(delta)
                if choice.get('finish_reason'):
                    finish = choice['finish_reason']
            if not cancel.is_set() and finish != 'stop':
                raise ClientError('GENERATION_TRUNCATED', '译文未正常完成，请拆分长句后重试。', 502)
            return ''.join(output).strip()
        finally:
            completed=time.perf_counter()
            self.last_generation_trace={'raw_output':''.join(output),'reasoning_output':reasoning,'finish_reason':finish}
            finished.set()
            conn.close()
            self.connection = None
            try:self._idle()
            finally:
                released=time.perf_counter()
                timing={'prepare_ms':round((prepared-started)*1000,3),
                    'slot_release_ms':round((released-completed)*1000,3),
                    'generation_ms':round((released-started)*1000,3)}
                if first_token is not None:
                    timing.update(first_token_ms=round((first_token-prepared)*1000,3),
                        decode_ms=round((completed-first_token)*1000,3))
                self.last_generation_timings={**timing,**statistics}
