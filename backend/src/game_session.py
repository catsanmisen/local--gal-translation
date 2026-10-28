"""Desktop-owned game scope, durable latest-line scheduling and bounded VRAM recovery."""
from collections import OrderedDict, deque
import math
import re
import threading
import time
import uuid
from core import now
from engine import ClientError

ID = re.compile(r'[A-Za-z0-9_-]{1,100}\Z')


def validate_game(value):
    if not isinstance(value, dict):raise ClientError('INVALID_PROFILE', '游戏配置必须是对象。')
    allowed={'executable','input_mode','region','dialogue_box','special_region','hide_input','anchor','hook','auto_recovery','enabled','hotkeys','subtitle_placement'}
    if set(value)-allowed:raise ClientError('INVALID_PROFILE', '游戏配置含不支持的字段。')
    if 'executable' in value and (not isinstance(value['executable'],str) or not value['executable'] or len(value['executable'])>1024):
        raise ClientError('INVALID_PROFILE','游戏程序路径不正确。')
    if value.get('input_mode','ocr') not in ('ocr','hook'):raise ClientError('INVALID_PROFILE','取词方式不正确。')
    if value.get('subtitle_placement','auto') not in ('auto','above','below','left','right','outside'):
        raise ClientError('INVALID_PROFILE','字幕摆放方向不正确。')
    for key in ('enabled','auto_recovery'):
        if key in value and type(value[key]) is not bool:raise ClientError('INVALID_PROFILE',key+' 必须是布尔值。')
    hide=value.get('hide_input','none')
    if not isinstance(hide,str) or (hide not in ('none','mouse_left','mouse_right','mouse_middle') and not re.fullmatch(r'key:(?:[A-Z0-9]|F(?:[1-9]|1[0-2])|Space|Tab|Escape)',hide)):
        raise ClientError('INVALID_PROFILE','单键隐藏输入不正确。')
    for region_key in ('region','dialogue_box','special_region'):
        if region_key not in value:continue
        r=value[region_key]
        if not isinstance(r,dict) or set(r)!=set(('x','y','width','height')) or any(type(n) not in (float,int) or not math.isfinite(n) for n in r.values()):
            raise ClientError('INVALID_PROFILE','台词区域不正确。')
        if r['width']<=0 or r['height']<=0 or min(r['x'],r['y'])<0 or r['x']+r['width']>1.001 or r['y']+r['height']>1.001:
            raise ClientError('INVALID_PROFILE','台词区域必须在游戏客户区内。')
    if 'anchor' in value:
        a=value['anchor']
        if not isinstance(a,dict) or set(a)-{'dx','dy'} or any(type(n) not in (float,int) or not math.isfinite(n) or abs(n)>2 for n in a.values()):
            raise ClientError('INVALID_PROFILE','字幕偏移不正确。')
    if 'hook' in value:
        h=value['hook']
        if not isinstance(h,dict) or set(h)-{'code','name','context','context2'} or any(not isinstance(n,str) or len(n)>400 or '\n' in n or '\r' in n for n in h.values()):
            raise ClientError('INVALID_PROFILE','HOOK 标识不正确。')
        if h.get('code') and not re.fullmatch(r'[HR][^\s\x00]{1,399}',h['code']):
            raise ClientError('INVALID_PROFILE','HOOK 码必须是单个 H/R 码，不能包含进程命令。')
    if 'hotkeys' in value:
        h=value['hotkeys']
        if not isinstance(h,dict) or set(h)-{'visibility','pause','reset','backlog'} or any(not isinstance(n,str) or len(n)>60 for n in h.values()):
            raise ClientError('INVALID_PROFILE','快捷键不正确。')
    return value


class GameSession:
    def __init__(self, client, clock=time.monotonic, threaded=True):
        self.client=client;self.clock=clock;self.closed=threading.Event()
        self.bound=None;self.owner=None;self.alive_at=0;self.foreground=False;self.manual_paused=False
        self.native=False;self.ocr=False;self.hook=False;self.notice=None;self.recovery_error=None
        self.line=0;self.line_text=None;self.epoch=0;self.events=OrderedDict()
        self.stable_line=0;self.stable_result=None
        self.retries=deque();self.stable_since=None;self.stable_target=None;self.next_attempt=0;self.recovery='idle';self.old_layers=None
        client.game=self
        self.thread=threading.Thread(target=self._run,daemon=True,name='game-recovery') if threaded else None
        if self.thread:self.thread.start()

    def status(self):
        # All callers hold client.lock; no second lock with reversed acquisition order.
        return {**(self.bound or {}),'bound':self.bound is not None,'foreground':self.foreground,
            'paused':self.manual_paused,'native_subtitle':self.native,'ocr_available':bool(self.bound and self.ocr and self.client.ocr_available()),'hook_available':bool(self.bound and self.hook),
            'auto_recovery':bool(self.bound and self.bound['auto_recovery']), 'recovery':self.recovery,
            'execution_mode':self.client.engine.status().get('model',{}).get('execution_mode'),
            'recovery_target':self.stable_target,
            'notice':self.recovery_error['message'] if self.recovery=='blocked' and self.recovery_error else self.notice,
            'recovery_error':self.recovery_error,'epoch':self.client.session['epoch'] if self.bound and self.client.session else None}

    def update(self, body, owner):
        if not ID.fullmatch(owner or ''):raise ClientError('INVALID_INPUT','桌面客户端编号缺失。')
        op=body.get('action','heartbeat')
        for k in ('foreground','native_subtitle','ocr_available','hook_available'):
            if k in body and type(body[k]) is not bool:raise ClientError('INVALID_INPUT',k+' 必须是布尔值。')
        notice=body.get('notice')
        if notice is not None and (not isinstance(notice,str) or len(notice)>300):raise ClientError('INVALID_INPUT','状态提示不正确。')
        with self.client.lock:
            if op=='bind':
                profile=self.client.storage.profile(body.get('profile_id',''))
                if not profile:raise ClientError('PROFILE_NOT_FOUND','游戏配置不存在。',404)
                game=profile.get('game',{})
                if not game.get('executable'):raise ClientError('INVALID_PROFILE','请先保存游戏程序和台词区域。')
                for key in ('pid','hwnd'):
                    if type(body.get(key)) is not int or body[key]<=0:raise ClientError('INVALID_INPUT','游戏窗口身份不正确。')
                if self.bound and self.owner!=owner:raise ClientError('GAME_IN_USE','已有桌面宿主管理当前游戏。',409)
                session=self.client.create_session(profile['id'])
                self.bound={'game_session_id':'game-'+uuid.uuid4().hex,'profile_id':profile['id'],
                    'pid':body['pid'],'hwnd':body['hwnd'],'auto_recovery':game.get('auto_recovery',True)}
                self.owner=owner;self.line=0;self.line_text=None;self.stable_line=0;self.stable_result=None;self.epoch=session['epoch'];self.events.clear()
                self.retries.clear();self.stable_since=None;self.stable_target=None;self.next_attempt=0;self.recovery='idle';self.manual_paused=False
                self.old_layers=None;self.recovery_error=None
                if hasattr(self.client.engine,'set_recovery_cap'):self.client.engine.set_recovery_cap(None)
                if hasattr(self.client.engine,'set_cpu_fallback'):self.client.engine.set_cpu_fallback(True)
            elif self.bound and self.owner!=owner:
                raise ClientError('GAME_IN_USE','只有当前桌面宿主可控制游戏会话。',409)
            if op=='unbind':
                self._unbind();return self.status()
            if op=='pause':
                self.manual_paused=True;self.client._cancel_all('user_cancelled');self.client.session['sequence']+=1
                self.client.subtitle.update(zh='',state='paused',request_id=None)
                self.stable_since=None;self.stable_target=None;self.recovery='manual_paused'
            elif op=='resume':
                self.manual_paused=False;self.retries.clear();self.next_attempt=0;self.stable_since=None;self.stable_target=None
                if self.bound:self._start()
            elif op=='reset':
                if self.bound:self.client.reset(self.client.session['session_id'])
            elif op not in ('bind','heartbeat','pause','resume','reset'):
                raise ClientError('INVALID_INPUT','游戏会话操作不正确。')
            for k in ('foreground','native_subtitle','ocr_available','hook_available'):
                if k in body and type(body[k]) is not bool:raise ClientError('INVALID_INPUT',k+' 必须是布尔值。')
            self.foreground=body.get('foreground',self.foreground)
            self.native=body.get('native_subtitle',self.native);self.ocr=body.get('ocr_available',self.ocr);self.hook=body.get('hook_available',self.hook)
            notice=body.get('notice')
            if notice is not None and (not isinstance(notice,str) or len(notice)>300):raise ClientError('INVALID_INPUT','状态提示不正确。')
            self.notice=notice
            self.alive_at=self.clock()
            if op=='bind' and self.foreground:self._start()
            return self.status()

    def _start(self):
        if self.client.model_reloading:self.recovery='loading';return
        try:self.client.start();self.recovery='loading';self.recovery_error=None
        except ClientError as e:
            self.notice=e.extra.get('message',e.message)
            if e.code=='ENGINE_STOPPING':
                # A splash-to-main-window rebind may race the prior owned exit.
                self.recovery='waiting_owned_stop';self.recovery_error=None
            else:
                self.recovery='blocked';self.recovery_error=e.json();self._fail_deferred()

    def _fail_deferred(self):
        req=self.client.pending
        if self.recovery=='blocked' and self.recovery_error and req and req.wait_for_engine and not req.terminal:
            self.client.pending=None;self.client._finish(req,'error',**self.recovery_error)

    def _unbind(self):
        if self.bound:
            if self.client.session and self.client.session['profile_id']==self.bound['profile_id']:
                self.client.reset(self.client.session['session_id'])
            self.client.request_stop()
        self.bound=None;self.owner=None;self.native=False;self.foreground=False;self.manual_paused=False
        if hasattr(self.client.engine,'set_cpu_fallback'):self.client.engine.set_cpu_fallback(False)
        self.line=0;self.line_text=None;self.recovery='idle';self.recovery_error=None;self.stable_target=None;self.events.clear()

    def event(self, body, owner):
        with self.client.lock:
            if not self.bound or owner!=self.owner or body.get('game_session_id')!=self.bound['game_session_id']:
                raise ClientError('STALE_GAME','游戏会话已改变。',409)
            s=self.client.session
            if not s or s['profile_id']!=self.bound['profile_id'] or body.get('epoch')!=s['epoch']:
                raise ClientError('STALE_EPOCH','请使用最新游戏场景。',409)
            allowed={'game_session_id','epoch','line_id','event_id','phase','source_text','source_kind','speaker','captured_at','timings'}
            if set(body)-allowed or type(body.get('epoch')) is not int:raise ClientError('INVALID_INPUT','自动台词不得提供序号、请求身份或未约定字段。')
            if self.manual_paused or not self.foreground:raise ClientError('CAPTURE_PAUSED','采集已暂停。',409)
            eid=body.get('event_id');phase=body.get('phase','stable');line=body.get('line_id');text=body.get('source_text','')
            if not isinstance(eid,str) or not ID.fullmatch(eid) or type(line) is not int or line<1 or phase not in ('preview','stable','empty'):
                raise ClientError('INVALID_INPUT','台词事件身份不正确。')
            if self.epoch!=s['epoch']:self.line=0;self.line_text=None;self.stable_line=0;self.events.clear();self.epoch=s['epoch']
            if eid in self.events:
                previous,result=self.events[eid]
                if previous!=body:raise ClientError('REQUEST_CONFLICT','事件编号已用于其他内容。',409)
                return result
            if line<self.line:raise ClientError('STALE_SEQUENCE','旧台词事件已丢弃。',409)
            if not isinstance(text,str) or len(text)>2000:raise ClientError('INPUT_TOO_LONG','台词超出 2000 字符。')
            try:text.encode('utf-8')
            except UnicodeError:raise ClientError('INVALID_INPUT','台词含无效 Unicode。')
            kind=body.get('source_kind')
            if kind not in ('ocr','hook'):raise ClientError('INVALID_INPUT','自动台词来源不正确。')
            timings=body.get('timings',{})
            if not isinstance(timings,dict) or set(timings)-{'capture_ms','ocr_ms','stable_wait_ms'} or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=600000 for v in timings.values()):
                raise ClientError('INVALID_INPUT','分段耗时不正确。')
            if phase=='stable':
                # Validate the complete input before invalidating the current caption.
                self.client.validate({'request_id':'auto-'+eid,'session_id':s['session_id'],'epoch':s['epoch'],
                    'sequence':s['sequence']+1,'source_text':text,'source_kind':kind,'speaker':body.get('speaker'),
                    'captured_at':body.get('captured_at'),'complete':True,'stream':True})
            if line==self.line and self.line_text is not None and phase!='empty' and text!=self.line_text:
                raise ClientError('REQUEST_CONFLICT','同一台词身份的文字发生改变。',409)
            if line>self.line or phase=='empty':
                self.stable_line=0;self.stable_result=None
                self.client._cancel_all('superseded');s['sequence']+=1
                self.client.subtitle.update(ja=text,zh='',state='capturing' if phase!='empty' else 'idle',request_id=None,
                    source_kind=kind,
                    session_id=s['session_id'],epoch=s['epoch'],sequence=s['sequence'],reason=None,elapsed_ms=None,warnings=[])
                self.line=line;self.line_text=text if phase!='empty' else None
            if phase=='stable':
                if self.stable_line==line:return self.stable_result
                b={'request_id':'auto-'+eid,'session_id':s['session_id'],'epoch':s['epoch'],'sequence':s['sequence']+1,
                    'source_text':text,'source_kind':kind,'speaker':body.get('speaker'),'captured_at':body.get('captured_at'),
                    'complete':True,'stream':True,'timings':timings}
                req=self.client.submit(b,wait_for_engine=True)
                self._fail_deferred()
                result={'accepted':True,'request_id':req.body['request_id'],'sequence':req.body['sequence']}
                self.stable_line=line;self.stable_result=result
            else:result={'accepted':True,'request_id':None}
            self.events[eid]=(dict(body),result)
            while len(self.events)>128:self.events.popitem(last=False)
            return result

    def tick(self):
        with self.client.lock:
            if not self.bound:return
            at=self.clock()
            if at-self.alive_at>8:self._unbind();return
            if not self.client.session or self.client.session['profile_id']!=self.bound['profile_id']:
                self._unbind();return
            if self.client.model_reloading:return
            st=self.client.engine.status()
            actual_layers=st.get('model',{}).get('gpu_layers')
            if self.old_layers is None and actual_layers is not None:self.old_layers=actual_layers
            if st['state']=='ready':
                if actual_layers is not None:self.old_layers=actual_layers
                self.recovery='ready';self.stable_since=None;self.stable_target=None;return
            if self.manual_paused or not self.foreground:return
            if st['state']=='stopped' and self.recovery not in ('manual_stopped','blocked'):
                self._start();return
            error=st.get('last_error') or {}
            if error.get('code')!='VRAM_LOW' or st['state'] not in ('paused','error') or not self.bound['auto_recovery']:return
            if self.stable_line and self.stable_result:
                req=self.client.requests.get(self.stable_result.get('request_id'))
                if req and req.terminal and req.events[-1][0]=='error':
                    # Retry a model-stopped line only if it is still the latest game line. Keep the
                    # original terminal intact and create one new durable deferred request.
                    b={**req.body,'request_id':'recover-'+uuid.uuid4().hex,'sequence':self.client.session['sequence']+1}
                    queued=self.client.submit(b,wait_for_engine=True)
                    self.stable_result={'accepted':True,'request_id':queued.body['request_id'],'sequence':queued.body['sequence']}
            while self.retries and at-self.retries[0]>600:self.retries.popleft()
            if len(self.retries)>=3:self.recovery='retry_limit';return
            try:sample=self.client.engine.recovery_sample()
            except Exception:self.stable_since=None;self.recovery='monitor_unavailable';return
            reserve=getattr(self.client.engine,'config',{}).get('minimum_free_mib',2048)
            threshold=reserve+1024
            cpu_retry=bool(getattr(self.client.engine,'requested_mode','auto')=='auto' and getattr(self.client.engine,'cpu_fallback',False) and reserve<=sample['free_mib']<threshold)
            if sample['free_mib']<threshold and not cpu_retry:self.stable_since=None;self.stable_target=None;self.recovery='waiting_vram';return
            target='cpu' if cpu_retry else 'gpu'
            if self.stable_since is None or self.stable_target!=target:self.stable_since=at
            self.stable_target=target
            self.recovery='waiting_stable_vram'
            if at-self.stable_since<15 or at<self.next_attempt:return
            self.retries.append(at);self.next_attempt=at+(30,60,120)[len(self.retries)-1];self.stable_since=None
            if self.old_layers is None:self.old_layers=getattr(self.client.engine,'config',{}).get('max_gpu_layers',100)
            self.old_layers=max(1 if getattr(self.client.engine,'requested_mode','auto')=='gpu' else 0,self.old_layers-1)
            if hasattr(self.client.engine,'set_recovery_cap'):self.client.engine.set_recovery_cap(0 if cpu_retry else self.old_layers)
            self._start()

    def manual_stop(self):
        with self.client.lock:self.manual_paused=True;self.recovery='manual_stopped'

    def _run(self):
        while not self.closed.wait(.5):
            try:self.tick()
            except Exception:
                import logging
                logging.exception('Game recovery failed')

    def close(self):
        self.closed.set()
        if self.thread:self.thread.join(timeout=3)
