"""One inference worker, one latest pending line, atomic epoch/sequence gates."""
from collections import OrderedDict
from datetime import datetime, timezone
import re
import json
import logging
import threading
import time
import uuid
from engine import ClientError, assess_risks
from translation_quality import normalize, rejection, protect_controls
from execution_policy import preferences

CANCEL_REASONS = frozenset(('user_cancelled', 'superseded', 'session_reset', 'engine_stopped', 'client_disconnected'))


def now():
    return datetime.now(timezone.utc).isoformat()


class Request:
    def __init__(self, body, wait_for_engine=False):
        self.body = dict(body)
        self.wait_for_engine = wait_for_engine
        self.events = []
        self.condition = threading.Condition()
        self.cancel = threading.Event()
        self.reason = 'user_cancelled'
        self.terminal = False
        self.readers = 0
        self.started = time.monotonic()
        self.inference_started = None
        self.quality_failed = False
        self.generation_count = 0
        self.repair_ms = 0
        self.model_timings = {}

    def emit(self, name, **data):
        with self.condition:
            if self.terminal:
                return
            identity = {k: self.body[k] for k in ('request_id', 'session_id', 'epoch', 'sequence')}
            self.events.append((name, {**identity, **data}))
            self.terminal = name in ('final', 'cancelled', 'error')
            self.condition.notify_all()


class Client:
    def __init__(self, engine, storage):
        self.engine, self.storage = engine, storage
        self.lock = threading.RLock()
        self.condition = threading.Condition(self.lock)
        self.requests = OrderedDict()
        self.session = None
        self.context = []
        self.active = self.pending = None
        self.closing = False
        self.subtitle = {'ja': '', 'zh': '', 'state': 'idle', 'prefs': {}}
        self.clipboard_on = False
        self.clipboard_error = None
        self.clipboard_error_revision = 0
        self.last_error = None
        self.game = None
        self.ocr_available = lambda: False
        self.model_settings=preferences(storage.settings());self.model_reloading=False
        self.model_reload_thread=None;self.reload_restart=False
        if hasattr(engine,'configure_execution'):engine.configure_execution(self.model_settings['model_mode'],self.model_settings['gpu_reserve_mib'])
        if hasattr(engine,'set_wallpaper_relief'):engine.set_wallpaper_relief(self.model_settings['wallpaper_relief'])
        self.worker = threading.Thread(target=self._work, daemon=True)
        self.worker.start()

    def status(self):
        with self.lock:
            status = self.engine.status()
            if self.model_reloading:status={**status,'state':'recovering','message':'正在切换模型设备'}
            if status['state'] == 'ready' and self.active:
                status['state'] = 'translating'
            status['last_error'] = status.get('last_error') or self.last_error
            game = self.game.status() if self.game else None
            ocr = bool(game and game.get('bound') and game.get('ocr_available') and self.ocr_available())
            hook = bool(game and game.get('bound') and game.get('hook_available'))
            return {**status, 'model_preferences':dict(self.model_settings),'model_reloading':self.model_reloading,
                'api_version': '0.3', 'active_request_id': self.active.body['request_id'] if self.active else None,
                'game_session': game,
                'session': dict(self.session) if self.session else None,
                'clipboard': {'enabled': self.clipboard_on, 'last_error': dict(self.clipboard_error) if self.clipboard_error else None},
                'capabilities': {'streaming': True, 'cancel': True, 'auto_recovery': bool(game and game.get('auto_recovery')),
                    'text_events': ocr or hook, 'ocr': ocr, 'hook': hook, 'clipboard': __import__('os').name == 'nt',
                    'native_subtitle': bool(game and game.get('native_subtitle')), 'history': True, 'profiles': True,'model_device_choice':True,
                    'wallpaper_control':bool(status.get('wallpaper',{}).get('available'))}}

    def create_session(self, profile_id='default'):
        with self.lock:
            if not self.storage.profile(profile_id):
                raise ClientError('PROFILE_NOT_FOUND', '游戏配置不存在。', 404)
            self._cancel_all('session_reset')
            self.context.clear()
            self.session = {'session_id': 'session-' + uuid.uuid4().hex, 'epoch': 1, 'glossary_version': self.storage.profile(profile_id).get('glossary_version', 1),
                'profile_id': profile_id, 'sequence': 0}
            self.clipboard_on = False
            self.set_clipboard_error(None)
            self.subtitle.update(ja='', zh='', state='idle', source_kind=None, prefs=self.storage.profile(profile_id)['prefs'])
            self.subtitle.update(request_id=None, session_id=self.session['session_id'], epoch=1, sequence=0,
                reason=None, warnings=[], elapsed_ms=None, diagnostic=None)
            return dict(self.session)

    def reset(self, session_id):
        with self.lock:
            self._session(session_id)
            self._cancel_all('session_reset')
            self.session['epoch'] += 1
            self.session['sequence'] = 0
            self.context.clear()
            self.subtitle.update(ja='', zh='', state='idle', source_kind=None)
            self.subtitle.update(request_id=None, epoch=self.session['epoch'], sequence=0, reason=None,
                warnings=[], elapsed_ms=None, diagnostic=None)
            return dict(self.session)

    def _session(self, session_id):
        if not self.session or self.session['session_id'] != session_id:
            raise ClientError('SESSION_NOT_FOUND', '当前游戏会话不存在，请重新连接。', 404)

    def glossary(self, session_id, entries):
        if not isinstance(entries, list) or len(entries) > 100:
            raise ClientError('INVALID_GLOSSARY', '术语表必须是最多 100 条的数组。')
        clean, seen = [], set()
        for i, e in enumerate(entries):
            if not isinstance(e, dict) or any(not isinstance(e.get(k, ''), str) for k in ('source', 'target', 'note')):
                raise ClientError('INVALID_GLOSSARY', '术语字段必须是文本。', row=i)
            item = {k: e.get(k, '').strip() for k in ('source', 'target', 'note')}
            if not item['source'] or not item['target'] or any(len(v) > 120 or '\n' in v or '\r' in v or '->' in v for v in item.values()) or item['source'] in seen:
                raise ClientError('INVALID_GLOSSARY', f'第 {i+1} 行为空、重复、过长或包含换行/箭头。', row=i)
            seen.add(item['source'])
            clean.append(item)
        with self.lock:
            self._session(session_id)
            profile = self.storage.profile(self.session['profile_id'])
            profile['glossary'] = clean
            profile['glossary_version'] = self.session['glossary_version'] + 1
            # Persist first: a failed write must not cancel requests or change the live epoch/version.
            try:
                self.storage.save_profile(profile)
            except Exception as error:
                logging.exception('Glossary persistence failed')
                raise ClientError('STORAGE_ERROR', '术语保存失败，原术语版本和翻译上下文保持不变，请稍后重试。', 503) from error
            self.reset(session_id)
            self.session['glossary_version'] += 1
            return dict(self.session)

    def submit(self, body, wait_for_engine=False):
        self.validate(body)
        if not wait_for_engine and body.get('source_kind') not in ('manual','clipboard'):
            raise ClientError('INVALID_INPUT','OCR/HOOK 必须经自动台词入口提交。')
        with self.condition:
            existing = self.requests.get(body['request_id'])
            if existing:
                if existing.body != body:
                    raise ClientError('REQUEST_CONFLICT', '相同请求编号对应不同内容。', 409)
                return existing
            self._session(body['session_id'])
            if body['epoch'] != self.session['epoch']:
                raise ClientError('STALE_EPOCH', '场景已重置，请使用最新会话。', 409)
            if body['sequence'] <= self.session['sequence']:
                raise ClientError('STALE_SEQUENCE', '台词序号已过期。', 409)
            status = self.engine.status()
            cpu=status.get('model',{}).get('execution_mode')=='cpu'
            if self.model_reloading and not wait_for_engine:raise ClientError('MODEL_RECONFIGURING','模型设备正在切换，请就绪后再翻译。',409)
            if not wait_for_engine and not cpu and status.get('last_error') and status['last_error']['code'] == 'GPU_MONITOR_UNAVAILABLE':
                raise ClientError('GPU_MONITOR_UNAVAILABLE', '显存采样不可用，请等待恢复。', 503)
            if not wait_for_engine and status['state'] == 'paused':
                raise ClientError('VRAM_LOW', '显存不足，翻译已暂停。', 503)
            if not wait_for_engine and not cpu and status.get('gpu') and status['gpu']['free_mib'] < status['gpu']['reserve_mib']:
                raise ClientError('VRAM_LOW', '显存低于保留阈值，停止提交新台词。', 503)
            if not wait_for_engine and status['state'] != 'ready':
                raise ClientError('ENGINE_NOT_READY', '模型尚未就绪，请先启动模型。', 503)
            req = Request(body, wait_for_engine)
            self.storage.add(body, self.session['profile_id'])
            self.session['sequence'] = body['sequence']
            self._cancel_all('superseded')
            self.requests[body['request_id']] = req
            self.pending = req
            self.subtitle.update(ja=body['source_text'], zh='', state='streaming', request_id=body['request_id'],
                source_kind=body['source_kind'],
                session_id=body['session_id'], epoch=body['epoch'], sequence=body['sequence'], reason=None,
                warnings=[], elapsed_ms=None, diagnostic=None)
            req.emit('meta', status='queued')
            self.condition.notify_all()
            self._prune()
            return req

    @staticmethod
    def validate(body):
        if not isinstance(body, dict):
            raise ClientError('INVALID_INPUT', '请求必须是 JSON 对象。')
        for key in ('request_id', 'session_id'):
            if not isinstance(body.get(key), str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', body[key]):
                raise ClientError('INVALID_INPUT', f'{key} 格式不正确。')
        if any(type(body.get(k)) is not int or body[k] < 1 for k in ('epoch', 'sequence')):
            raise ClientError('INVALID_INPUT', 'epoch 和 sequence 必须是正整数。')
        text = body.get('source_text')
        if not isinstance(text, str) or not text.strip():
            raise ClientError('INVALID_INPUT', '请输入日文原文。')
        if len(text) > 2000:
            raise ClientError('INPUT_TOO_LONG', '原文超过 2000 字符，请拆分后重试。')
        try:
            text.encode('utf-8')
            if isinstance(body.get('speaker'), str):body['speaker'].encode('utf-8')
        except UnicodeError:
            raise ClientError('INVALID_INPUT', '原文或说话人包含无效 Unicode 字符。')
        if body.get('source_kind') not in ('manual', 'clipboard', 'ocr', 'hook') or body.get('complete') is not True:
            raise ClientError('INVALID_INPUT', '只接受受支持来源的完整台词。')
        if body.get('speaker') is not None and (not isinstance(body['speaker'], str) or len(body['speaker']) > 120):
            raise ClientError('INVALID_INPUT', '说话人格式不正确。')
        if not isinstance(body.get('captured_at'), str) or len(body['captured_at']) > 80:
            raise ClientError('INVALID_INPUT', '缺少捕获时间。')
        try:
            captured = datetime.fromisoformat(body['captured_at'].replace('Z', '+00:00'))
            if captured.tzinfo is None:
                raise ValueError()
        except ValueError:
            raise ClientError('INVALID_INPUT', '捕获时间必须包含时区。')
        if body.get('stream', True) is not True:
            raise ClientError('INVALID_INPUT', '此接口要求 stream=true。')

    def _valid(self, req):
        b, s = req.body, self.session
        return s and b['session_id'] == s['session_id'] and b['epoch'] == s['epoch'] and b['sequence'] == s['sequence'] and not req.cancel.is_set()

    def cancel(self, request_id, reason='user_cancelled'):
        if reason not in CANCEL_REASONS:
            raise ClientError('INVALID_INPUT', '取消原因不正确。')
        with self.condition:
            req = self.get_request(request_id)
            if not req.terminal:
                req.reason = reason
                req.cancel.set()
                if req is self.pending:
                    self.pending = None
                    self._finish(req, 'cancelled', reason=reason)
                elif req is self.active:
                    self.engine.interrupt()

    def _cancel_all(self, reason):
        for req in (self.pending, self.active):
            if req:
                self.cancel(req.body['request_id'], reason)

    def get_request(self, request_id):
        req = self.requests.get(request_id)
        if not req:
            raise ClientError('REQUEST_NOT_FOUND', '请求已过期或不存在。', 404)
        return req

    def _finish(self, req, event, **data):
        if req.terminal:
            return False
        if req.body.get('timings') is not None:
            data['timings']={**req.body['timings'], **req.model_timings,
                'generation_count':req.generation_count,'repair_ms':round(req.repair_ms,3),
                'queue_ms':round(((req.inference_started or time.monotonic())-req.started)*1000),
                'inference_ms':round((time.monotonic()-req.inference_started)*1000) if req.inference_started else 0}
        try:
            self.storage.finish(req.body, event, data)
            self.last_error = None
        except Exception:
            # The accepted source is already durable. Do not emit final or poison context after a failed commit.
            logging.exception('Request terminal persistence failed')
            self.last_error = ClientError('STORAGE_ERROR', '译文结果保存失败，本条未标为完成；已登记的原文保留。', 503, occurred_at=now()).json()
            event, data = 'error', dict(self.last_error)
        if data.get('diagnostic'):
            self.last_error = dict(data['diagnostic'])
        if req.quality_failed:
            self._quality_event(req,'terminal',terminal=event,code=data.get('code'),reason=data.get('reason'),
                translation=data.get('translation'))
        req.emit(event, **data)
        b, s = req.body, self.session
        if s and all(b[k] == s[k] for k in ('session_id', 'epoch', 'sequence')):
            self.subtitle.update(state=event, zh=data.get('translation', '') if event == 'final' else '')
            self.subtitle.update(reason=data.get('message', data.get('reason')), warnings=data.get('warnings', []),
                elapsed_ms=data.get('elapsed_ms'), diagnostic=data.get('diagnostic'))
        return event == 'final'

    def _prune(self):
        ended = [k for k, v in self.requests.items() if v.terminal and v.readers == 0]
        for key in ended[:-128]:
            del self.requests[key]

    @staticmethod
    def _quality_event(req, stage, **details):
        # The existing rotating local log is the only destination for rejected
        # output. Keep it out of SSE/history and bound pathological generations.
        truncated=[]
        for key,value in details.items():
            if isinstance(value,str) and len(value)>8000:
                details[key]=value[:8000];truncated.append(key)
            elif key=='context':
                if len(value)>4 or any(len(text)>8000 for text in value):truncated.append(key)
                details[key]=[text[:8000] for text in value[-4:]]
        record={k:req.body[k] for k in ('request_id','session_id','epoch','sequence','source_kind')}
        logging.info('translation_quality %s',json.dumps({**record,'at':now(),'stage':stage,
            **details,'truncated_fields':truncated},ensure_ascii=False))

    def _translate_checked(self, req, context, glossary, delta):
        source, kind = req.body['source_text'], req.body['source_kind']
        # Automatic game captions never expose unvalidated output/history echoes.
        first_delta = delta if kind in ('manual', 'clipboard') else lambda _: None
        raw_result = self._generate(req, source, context, glossary, first_delta)
        result, warnings = normalize(source, raw_result)
        problem = rejection(source, result, kind)
        if problem:
            req.quality_failed=True
            self._quality_event(req,'initial',source_text=source,context=context,glossary=glossary,
                raw_output=raw_result,normalized_output=result,rejection=problem[0])
        # HOOK line breaks may carry engine formatting: retain the strict v0.2
        # guarantee instead of synthesizing a replacement row structure.
        if problem and problem[0]=='LINE_FORMAT_DAMAGE' and kind=='hook':
            raise ClientError('FORMAT_DAMAGE','HOOK 译文分行与原文不一致，原文已保留。',502)
        if problem:
            with self.lock:
                if not self._valid(req):return '', []
                req.emit('meta', status='retrying', replace_buffer=True)
                self.subtitle['zh'] = ''
            # One repair pass, never an unbounded background retry. Keep the same
            # request identity, source/history row, glossary and inference slot.
            if problem[0] == 'LINE_FORMAT_DAMAGE' and source.count('\n') < 8:
                repaired=[]
                for row in source.replace('\r\n','\n').replace('\r','\n').strip().split('\n'):
                    with self.lock:
                        if not self._valid(req):return '', []
                    if not row.strip():repaired.append('');continue
                    raw_part=self._generate(req,row, [], glossary, lambda _:None)
                    part, _ = normalize(row, raw_part)
                    row_problem=rejection(row, part, kind)
                    self._quality_event(req,'repair',input_text=row,raw_output=raw_part,
                        normalized_output=part,rejection=row_problem[0] if row_problem else None)
                    if row_problem:raise ClientError(*row_problem, 502)
                    repaired.append(part)
                result='\n'.join(repaired)
            else:
                with self.lock:
                    if not self._valid(req):return '', []
                retry_source,tokens=protect_controls(source) if problem[0]=='FORMAT_DAMAGE' else (source,{})
                raw_result=self._generate(req,retry_source, [], glossary, lambda _:None,protected=bool(tokens))
                result,extra=normalize(retry_source,raw_result);warnings.extend(extra)
                retry_problem=rejection(retry_source,result,kind)
                self._quality_event(req,'repair',input_text=retry_source,raw_output=raw_result,
                    normalized_output=result,rejection=retry_problem[0] if retry_problem else None)
                if retry_problem:raise ClientError(*retry_problem,502)
                if tokens:
                    for marker,original in tokens.items():result=result.replace(marker,original)
            result, extra=normalize(source, result);warnings.extend(extra)
            problem=rejection(source, result, kind)
            if problem:raise ClientError(*problem, 502)
            warnings.append({'code':'translation_repaired','message':'首次输出未通过校验，已自动修复；原文和请求身份保持不变。'})
        return result, warnings

    def _generate(self, req, source, context, glossary, delta, *, protected=False):
        generate=getattr(self.engine,'generate_repair',self.engine.generate) if protected else self.engine.generate
        repair=req.generation_count>0;req.generation_count+=1;started=time.perf_counter()
        try:
            result=generate(source,context,glossary,req.cancel,delta)
            # Preserve the actual stream whitespace for diagnostics; normalize
            # still decides the only text allowed into final/history/context.
            return getattr(self.engine,'last_generation_trace',{}).get('raw_output',result)
        except ClientError as error:
            if error.code in ('FORMAT_DAMAGE','GENERATION_TRUNCATED'):
                req.quality_failed=True
                self._quality_event(req,'generation_error',source_text=req.body['source_text'],input_text=source,
                    context=context,glossary=glossary,code=error.code,repair=repair,
                    **getattr(self.engine,'last_generation_trace',{}))
            raise
        finally:
            if repair:req.repair_ms+=(time.perf_counter()-started)*1000
            for key,value in getattr(self.engine,'last_generation_timings',{}).items():
                name='model_'+key;req.model_timings[name]=round(req.model_timings.get(name,0)+value,3)

    def _work(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.closing or (not self.model_reloading and self.pending and
                    (not self.pending.wait_for_engine or self.engine.status()['state'] == 'ready')), timeout=.25)
                if self.closing:
                    return
                if self.model_reloading or not self.pending or (self.pending.wait_for_engine and self.engine.status()['state'] != 'ready'):
                    continue
                req, self.pending = self.pending, None
                self.active = req
                req.inference_started = time.monotonic()
                context = list(self.context)
                profile = self.storage.profile(self.session['profile_id'])
                glossary = '\n'.join(f"{e['source']}->{e['target']}" + (f" #{e['note']}" if e['note'] else '') for e in profile['glossary'])
                req.emit('meta', status='running')
            try:
                engine_status = self.engine.status()
                if engine_status['state'] != 'ready':
                    raise ClientError('ENGINE_STOPPED', '排队期间模型已停止或暂停，请就绪后重试；原文已保留。', 503)
                def delta(text):
                    with self.lock:
                        if self._valid(req):
                            req.emit('delta', text=text)
                            self.subtitle['zh'] += text
                result, repair_warnings = self._translate_checked(req, context, glossary, delta)
                with self.lock:
                    if not self._valid(req):
                        self._finish(req, 'cancelled', reason=req.reason)
                    else:
                        warnings = assess_risks(req.body['source_text'], result) + repair_warnings
                        if req.body['source_kind']=='ocr':
                            # OCR rows are screen wrapping, not executable formatting.
                            # Preserve the captured rows in history and let the native
                            # caption wrap Chinese naturally; variable damage is fatal.
                            warnings=[{'code':'ocr_line_reflow','message':'译文按中文长度重新排版，历史保留原始识别换行。'}
                                if w['code']=='line_count_changed' else w for w in warnings]
                        committed = not any(w['code'] == 'inferred_gender' for w in warnings)
                        saved = self._finish(req, 'final', translation=result, warnings=warnings,
                            elapsed_ms=round((time.monotonic() - req.started) * 1000), context_committed=committed)
                        if committed and saved:
                            self.context = (self.context + [result])[-4:]
            except Exception as error:
                with self.lock:
                    if req.cancel.is_set():
                        diagnostic = error.json() if isinstance(error, ClientError) and error.code == 'CANCEL_TIMEOUT' else None
                        self._finish(req, 'cancelled', reason=req.reason, **({'diagnostic': diagnostic} if diagnostic else {}))
                    else:
                        err = error if isinstance(error, ClientError) else ClientError('ENGINE_ERROR', '推理或保存失败，请检查后台日志。', 502)
                        self._finish(req, 'error', **err.json())
            finally:
                with self.condition:
                    self.active = None
                    self._prune()
                    self.condition.notify_all()

    def stop(self):
        with self.lock:
            self.reload_restart=False
            self.clipboard_on = False
            self.set_clipboard_error(None)
            self.last_error = None
            self._cancel_all('engine_stopped')
        self.engine.stop()

    def request_stop(self):
        with self.lock:
            self.reload_restart=False
            self.clipboard_on = False
            self.set_clipboard_error(None)
            self.last_error = None
            self._cancel_all('engine_stopped')
        self.engine.request_stop()

    def start(self):
        with self.lock:
            if self.closing:raise ClientError('CLIENT_CLOSING','客户端正在退出。',409)
            if self.model_reloading:raise ClientError('MODEL_RECONFIGURING','模型设备正在切换，请等待完成。',409)
            if hasattr(self.engine,'configure_execution') and (
                getattr(self.engine,'requested_mode',self.model_settings['model_mode'])!=self.model_settings['model_mode'] or
                getattr(self.engine,'config',{}).get('minimum_free_mib',self.model_settings['gpu_reserve_mib'])!=self.model_settings['gpu_reserve_mib']):
                self.engine.configure_execution(self.model_settings['model_mode'],self.model_settings['gpu_reserve_mib'])
            if hasattr(self.engine,'set_wallpaper_relief'):self.engine.set_wallpaper_relief(self.model_settings['wallpaper_relief'])
            self.engine.start()
            self.last_error = None

    def settings(self):
        with self.lock:
            try:return preferences(self.storage.settings())
            except ValueError as error:raise ClientError('INVALID_SETTINGS',str(error)) from error

    def update_settings(self, delta):
        with self.condition:
            if self.closing:raise ClientError('CLIENT_CLOSING','客户端正在退出。',409)
            try:target=preferences(self.settings(),delta)
            except ValueError as error:raise ClientError('INVALID_SETTINGS',str(error)) from error
            except OSError as error:raise ClientError('STORAGE_ERROR','设置读取失败，运行模式保持不变。',503) from error
            changed=any(target[k]!=self.model_settings[k] for k in ('model_mode','gpu_reserve_mib','wallpaper_relief'))
            if self.model_reloading and changed:raise ClientError('MODEL_RECONFIGURING','上一项设备设置仍在应用，请稍后切换。',409)
            try:self.storage.settings(target)
            except Exception as error:raise ClientError('STORAGE_ERROR','设置保存失败，运行模式保持不变。',503) from error
            self.model_settings=target
            if not changed:return {**target,'model_reloading':self.model_reloading}
            state=self.engine.status()['state']
            self.reload_restart=state not in ('stopped','stopping') and not bool(self.game and self.game.manual_paused)
            latest=self.pending or self.active
            if latest is None and self.game and self.game.stable_result:
                latest=self.requests.get(self.game.stable_result.get('request_id'))
            if latest and latest.terminal and latest.events[-1][0]=='final':latest=None
            restore=dict(latest.body) if latest and latest.wait_for_engine and self._valid(latest) else None
            self.model_reloading=True;self._cancel_all('engine_stopped');self.last_error=None
            if restore:self.subtitle.update(zh='',state='capturing',reason='正在切换模型设备')
            self.model_reload_thread=threading.Thread(target=self._reload_model,args=(dict(target),restore),daemon=True,name='model-reconfigure')
            self.model_reload_thread.start()
            return {**target,'model_reloading':True}

    def _reload_model(self, target, restore):
        try:
            if hasattr(self.engine,'stop_for_reload'):self.engine.stop_for_reload(target['wallpaper_relief'] and self.reload_restart)
            else:self.engine.stop()
            if hasattr(self.engine,'configure_execution'):self.engine.configure_execution(target['model_mode'],target['gpu_reserve_mib'])
            if hasattr(self.engine,'set_wallpaper_relief'):self.engine.set_wallpaper_relief(target['wallpaper_relief'])
            with self.condition:
                if self.game:
                    self.game.retries.clear();self.game.old_layers=None;self.game.stable_since=None;self.game.stable_target=None
                    self.game.recovery='manual_stopped' if self.game.manual_paused else 'idle';self.game.recovery_error=None
                if self.reload_restart and not self.closing and not (self.game and self.game.manual_paused):self.engine.start()
                elif hasattr(self.engine,'release_wallpaper'):self.engine.release_wallpaper()
                s=self.session;g=self.game
                if restore and not self.closing and g and g.bound and not g.manual_paused and self.pending is None \
                    and s and all(restore[k]==s[k] for k in ('session_id','epoch','sequence')) and g.line==g.stable_line:
                    b={**restore,'request_id':'device-'+uuid.uuid4().hex,'sequence':s['sequence']+1}
                    req=self.submit(b,wait_for_engine=True)
                    g.stable_result={'accepted':True,'request_id':req.body['request_id'],'sequence':req.body['sequence']}
        except Exception as error:
            if hasattr(self.engine,'release_wallpaper'):self.engine.release_wallpaper()
            with self.condition:
                self.last_error=error.json() if isinstance(error,ClientError) else ClientError('MODEL_RECONFIGURE_FAILED','设置已保存，模型重载失败；请重新启动翻译。',503).json()
                if self.game and self.game.bound:
                    self.game.recovery='blocked';self.game.recovery_error=self.last_error;self.game._fail_deferred()
        finally:
            with self.condition:self.model_reloading=False;self.condition.notify_all()

    def set_clipboard_error(self, error, severity='error'):
        with self.lock:
            if error is None:
                self.clipboard_error = None
                return
            fields = ('code', 'message', 'retryable')
            if self.clipboard_error and self.clipboard_error.get('severity') == severity and all(
                    self.clipboard_error.get(k) == error.get(k) for k in fields):
                return
            self.clipboard_error_revision += 1
            self.clipboard_error = {**error, 'severity': severity, 'occurred_at': now(), 'revision': self.clipboard_error_revision}

    def close(self):
        with self.condition:self.closing=True;self.reload_restart=False;self.condition.notify_all()
        self.stop()
        if self.model_reload_thread and self.model_reload_thread is not threading.current_thread():self.model_reload_thread.join(timeout=25)
        with self.condition:
            self.closing = True
            self.condition.notify_all()
        self.worker.join(timeout=40)
        if self.worker.is_alive():
            raise RuntimeError('Inference worker did not shut down')
