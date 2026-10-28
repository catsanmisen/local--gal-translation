"""Behavioral tests for scheduling, persistence, auth, and event identity."""
import http.client
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'src'))
from core import Client, now
from engine import ClientError
from storage import Storage
from server import Server
from unittest.mock import patch
from engine import Engine

def body(session, seq=1, text='今日は晴れです。', request_id=None):
    return {'request_id':request_id or 'req-'+str(seq),'session_id':session['session_id'],'epoch':session['epoch'],
        'sequence':seq,'source_text':text,'source_kind':'manual','speaker':None,'captured_at':now(),'complete':True,'stream':True}

def ended(req):
    with req.condition:
        if not req.condition.wait_for(lambda:req.terminal,timeout=3): raise AssertionError('no terminal')
        return req.events[-1]

class FakeEngine:
    def __init__(self):
        self.state='ready'
        self.entered=threading.Event()
        self.release=threading.Event()
        self.release.set()
        self.calls=[]
        self.parallel=0
        self.max_parallel=0
        self.output='今天是晴天。'
        self.failure=None
        self.cancel_released=threading.Event()
        self.cancel_released.set()
    def status(self): return {'state':self.state,'model':{},'gpu':None,'last_error':None}
    def start(self): self.state='ready'
    def interrupt(self): pass
    def request_stop(self): self.state='stopped';self.release.set();self.cancel_released.set()
    def stop(self): self.request_stop()
    def generate(self,text,context,glossary,cancel,on_delta):
        self.parallel+=1;self.max_parallel=max(self.parallel,self.max_parallel)
        self.calls.append((text,list(context),glossary));self.entered.set()
        try:
            while not self.release.wait(.01):
                if cancel.is_set(): break
            if cancel.is_set():
                self.cancel_released.wait(2)
                return ''
            if self.failure: raise self.failure
            on_delta(self.output[:2])
            return self.output
        finally:self.parallel-=1

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.storage=Storage(Path(self.tmp.name)/'test.db')
        self.engine=FakeEngine()
        self.client=Client(self.engine,self.storage)
        self.session=self.client.create_session()
    def tearDown(self):
        self.client.close();self.storage.close();self.tmp.cleanup()
    def test_original_and_final_persist(self):
        source='  今日は晴れです。  '
        req=self.client.submit(body(self.session,text=source))
        name,event=ended(req)
        self.assertEqual(name,'final')
        self.assertEqual(self.storage.history()[0]['source_text'],source)
        self.assertEqual(event['translation'],'今天是晴天。')
        self.assertEqual(self.client.context,['今天是晴天。'])
    def test_duplicate_id_is_one_inference(self):
        b=body(self.session)
        first=self.client.submit(b)
        self.assertIs(first,self.client.submit(b));ended(first)
        self.assertEqual(len(self.engine.calls),1)
        self.assertIs(first,self.client.submit(b))
    def test_conflicting_id(self):
        b=body(self.session);ended(self.client.submit(b));b['source_text']='違う文。'
        with self.assertRaises(ClientError) as caught:self.client.submit(b)
        self.assertEqual(caught.exception.code,'REQUEST_CONFLICT')
    def test_latest_pending_and_slot_wait(self):
        self.engine.release.clear();self.engine.cancel_released.clear()
        a=self.client.submit(body(self.session,1))
        self.assertTrue(self.engine.entered.wait(1))
        b=self.client.submit(body(self.session,2))
        c=self.client.submit(body(self.session,3))
        self.assertEqual(ended(b)[0],'cancelled')
        self.assertEqual(len(self.engine.calls),1)
        self.assertFalse(a.terminal)
        self.engine.cancel_released.set();self.engine.release.set()
        self.assertEqual(ended(a)[0],'cancelled');self.assertEqual(ended(c)[0],'final')
        self.assertEqual(self.engine.max_parallel,1)
        self.assertEqual(len(self.engine.calls),2)
        self.assertEqual(self.client.subtitle['request_id'],c.body['request_id'])
        self.assertEqual(len(self.client.context),1)
    def test_reset_blocks_stale_commit(self):
        self.engine.release.clear()
        req=self.client.submit(body(self.session));self.engine.entered.wait(1)
        newer=self.client.reset(self.session['session_id'])
        self.engine.release.set()
        self.assertEqual(ended(req)[0],'cancelled')
        self.assertFalse(self.client.context);self.assertEqual(self.client.subtitle['ja'],'')
        with self.assertRaises(ClientError): self.client.submit(body(self.session,2))
        self.assertEqual(newer['epoch'],2)
    def test_cancel_has_full_identity_and_one_terminal(self):
        self.engine.release.clear();req=self.client.submit(body(self.session));self.engine.entered.wait(1)
        self.client.cancel(req.body['request_id']);self.client.cancel(req.body['request_id'])
        event=ended(req)[1]
        for key in ('request_id','session_id','epoch','sequence'):self.assertEqual(event[key],req.body[key])
        self.assertEqual(len([e for e in req.events if e[0] in ('final','error','cancelled')]),1)
    def test_glossary_version_and_reset(self):
        updated=self.client.glossary(self.session['session_id'],[{'source':'葵','target':'小葵','note':'姓名'}])
        self.assertEqual(updated['epoch'],2);self.assertEqual(updated['glossary_version'],2)
        new_session=self.client.create_session()
        self.assertEqual(new_session['glossary_version'],2)
        ended(self.client.submit(body(new_session)))
        self.assertIn('葵->小葵',self.engine.calls[-1][2])
    def test_invalid_glossary_is_atomic(self):
        with self.assertRaises(ClientError) as err:self.client.glossary(self.session['session_id'],[{'source':'','target':'葵'}])
        self.assertEqual(err.exception.extra['row'],0)
        self.assertEqual(self.client.session['epoch'],1);self.assertEqual(self.storage.profile('default')['glossary'],[])
    def test_format_damage_is_not_final(self):
        self.engine.output='变量丢失'
        req=self.client.submit(body(self.session,text='名前は{name}です。'))
        self.assertEqual(ended(req)[0],'error')
        self.assertEqual(self.storage.history()[0]['translation'],None)
        self.assertFalse(self.client.context);self.assertEqual(self.client.subtitle['zh'],'')
    def test_inferred_gender_not_committed(self):
        self.engine.output='她已经走了。'
        req=self.client.submit(body(self.session,text='もう行った。'))
        result=ended(req)[1]
        self.assertFalse(result['context_committed']);self.assertFalse(self.client.context)
    def test_truncation_keeps_original(self):
        self.engine.failure=ClientError('GENERATION_TRUNCATED','输出截断',502)
        req=self.client.submit(body(self.session))
        self.assertEqual(ended(req)[0],'error');self.assertFalse(self.client.context)
        self.assertEqual(self.storage.history()[0]['source_text'],req.body['source_text'])
    def test_validation_and_stale_sequence(self):
        ended(self.client.submit(body(self.session,2)))
        with self.assertRaises(ClientError) as err:self.client.submit(body(self.session,1))
        self.assertEqual(err.exception.code,'STALE_SEQUENCE')
        for override in ({'source_text':'x'*2001},{'complete':False},{'epoch':True},{'captured_at':'bad'},{'source_kind':'ocr'}):
            b=body(self.session,3);b.update(override)
            with self.assertRaises(ClientError): self.client.submit(b)
    def test_restart_recovers_unfinished_original(self):
        b=body(self.session)
        self.storage.add(b,'default')
        self.client.close();self.storage.close()
        self.storage=Storage(Path(self.tmp.name)/'test.db');self.client=Client(FakeEngine(),self.storage)
        h=self.storage.history()[0];self.assertEqual(h['terminal'],'interrupted');self.assertEqual(h['source_text'],b['source_text'])
    def test_profile_isolation(self):
        self.storage.save_profile({'id':'other','name':'另一游戏','glossary':[],'prefs':{'font':26}})
        ended(self.client.submit(body(self.session)))
        other=self.client.create_session('other');ended(self.client.submit(body(other,request_id='other-req')))
        self.assertEqual(len(self.storage.history('default')),1);self.assertEqual(len(self.storage.history('other')),1)
        self.assertEqual(self.client.subtitle['prefs']['font'],26)

class HttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.engine=FakeEngine()
        self.server=Server(0,Path(self.tmp.name)/'api.db',self.engine)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):
        self.server.shutdown();self.server.dispose();self.thread.join();self.tmp.cleanup()
    def request(self,path,method='GET',body=None,auth=True,extra=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        headers={'Content-Type':'application/json'}
        if auth:headers['Authorization']='Bearer '+self.server.token
        if extra:headers.update(extra)
        conn.request(method,path,json.dumps(body).encode() if body is not None else None,headers)
        response=conn.getresponse();blob=response.read();status=response.status;conn.close()
        return status,blob
    def test_auth_origin_and_asset_allowlist(self):
        self.assertEqual(self.request('/api/v1/status',auth=False)[0],401)
        self.assertEqual(self.request('/api/v1/status',extra={'Authorization':'Bearer é'})[0],401)
        self.assertEqual(self.request('/')[0],302)
        self.assertEqual(self.request('/api/v1/status',extra={'Origin':'https://evil.example'})[0],403)
        self.assertEqual(self.request('/api/v1/status',extra={'Host':'evil.example'})[0],403)
        for path in ['/data/client.sqlite3','/backend/galtransl4/models/Galtransl-v4-4B-2601.gguf','/logs/engine.log','/bridge/../src/core.py']:
            self.assertEqual(self.request(path)[0],404)
        status,data=self.request('/app/')
        self.assertEqual(status,200);self.assertIn(b'/bridge/client.js',data);self.assertNotIn(b'js/mock-api.js',data)
        self.assertNotIn(b'https://unpkg.com',data)
        self.assertIn(b'href="/vendor/phosphor/style.css"',data)
        self.assertEqual(self.request('/vendor/phosphor/Phosphor.woff2')[0],200)
    def test_sse_and_request_query(self):
        _,data=self.request('/api/v1/sessions','POST',{})
        session=json.loads(data)
        b=body(session)
        status,data=self.request('/api/v1/translate','POST',b)
        self.assertEqual(status,200);self.assertIn(b'event: final',data)
        status,data=self.request('/api/v1/requests/'+b['request_id'])
        self.assertEqual(json.loads(data)['status'],'final')
        status,data=self.request('/api/v1/sessions/'+session['session_id']+'/history')
        self.assertEqual(len(json.loads(data)['items']),1)
    def test_disconnect_cancels_and_releases(self):
        self.engine.release.clear()
        session=self.server.client.create_session()
        b=body(session)
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
        conn.request('POST','/api/v1/translate',json.dumps(b),{'Authorization':'Bearer '+self.server.token,'Content-Type':'application/json'})
        response=conn.getresponse();response.readline();response.close();conn.close()
        req=self.server.client.get_request(b['request_id'])
        event,data=ended(req)
        self.assertEqual(event,'cancelled')
        self.assertEqual(data['reason'],'client_disconnected')
    def test_history_pagination_and_profile_validation(self):
        self.assertEqual(self.request('/api/v1/history?limit=-1')[0],400)
        self.assertEqual(self.request('/api/v1/profiles','PUT',{'id':'test','name':'测试','prefs':{'font':26}})[0],200)
        self.assertEqual(self.request('/api/v1/profiles','PUT',{'id':'test','name':'测试','prefs':{'font':99}})[0],400)
        self.assertEqual(self.request('/api/v1/clipboard','PUT',{'enabled':'true'})[0],400)

    def test_port_conflict_does_not_mutate_running_history(self):
        self.engine.release.clear()
        session=self.server.client.create_session()
        req=self.server.client.submit(body(session))
        self.assertTrue(self.engine.entered.wait(1))
        with self.assertRaises(OSError):
            Server(self.server.server_port,Path(self.tmp.name)/'api.db',FakeEngine())
        with self.server.storage.lock:
            row=self.server.storage.db.execute('SELECT result FROM history WHERE id=?',(req.body['request_id'],)).fetchone()
        self.assertIsNone(row[0])
        self.assertFalse(req.terminal)

    def test_history_delete_is_explicit_scoped_and_authenticated(self):
        s=self.server.client.create_session()
        ended(self.server.client.submit(body(s)))
        self.server.storage.save_profile({'id':'other','name':'另一个游戏','glossary':[],'prefs':{}})
        other=self.server.client.create_session('other')
        ended(self.server.client.submit(body(other,request_id='other-history')))
        self.assertEqual(self.request('/api/v1/history','DELETE')[0],400)
        self.assertEqual(self.request('/api/v1/history?profile_id=default&profile_id=other','DELETE')[0],400)
        self.assertEqual(self.request('/api/v1/history?profile_id=missing','DELETE')[0],404)
        self.assertEqual(self.request('/api/v1/history?profile_id=default','DELETE',auth=False)[0],401)
        code,data=self.request('/api/v1/history?profile_id=default','DELETE')
        self.assertEqual(code,200);self.assertEqual(json.loads(data)['deleted'],1)
        self.assertFalse(self.server.storage.history('default'))
        self.assertEqual(len(self.server.storage.history('other')),1)
        self.assertEqual(self.request('/api/v1/history?profile_id=default','DELETE')[0],200)

    def test_history_delete_rejects_unfinished_originals(self):
        self.engine.release.clear()
        s=self.server.client.create_session()
        req=self.server.client.submit(body(s))
        self.assertTrue(self.engine.entered.wait(1))
        code,data=self.request('/api/v1/history?profile_id=default','DELETE')
        self.assertEqual(code,409);self.assertEqual(json.loads(data)['error']['code'],'HISTORY_BUSY')
        self.engine.release.set();ended(req)
        self.assertEqual(len(self.server.storage.history('default')),1)

class WatchdogTests(unittest.TestCase):
    def test_low_vram_never_spawns(self):
        engine=Engine()
        with patch('engine.gal_service.health',return_value=False), patch('engine.gal_service.status',return_value={}), \
             patch('engine.gal_service.gpu',return_value={'free_mib':100,'used_mib':8000,'total_mib':8151}), \
             patch('engine.OwnedProcess') as spawn:
            engine.start();engine.thread.join(2)
            self.assertEqual(engine.status()['state'],'paused')
            self.assertEqual(engine.status()['last_error']['code'],'VRAM_LOW')
            spawn.assert_not_called()
        engine.stop()
    def test_stop_during_start_has_no_late_spawn(self):
        engine=Engine();entered=threading.Event();release=threading.Event()
        def gpu():
            entered.set();release.wait(2)
            return {'free_mib':4000,'used_mib':4000,'total_mib':8151}
        with patch('engine.gal_service.health',return_value=False), patch('engine.gal_service.status',return_value={}), \
             patch('engine.gal_service.gpu',side_effect=gpu), patch('engine.OwnedProcess') as spawn:
            engine.start();self.assertTrue(entered.wait(1));engine.request_stop();release.set();engine.stop()
            self.assertEqual(engine.status()['state'],'stopped');spawn.assert_not_called()
    def test_monitor_failure_is_reported_without_spawn(self):
        engine=Engine()
        with patch('engine.gal_service.health',return_value=False), patch('engine.gal_service.status',return_value={}), \
             patch('engine.gal_service.gpu',side_effect=OSError('driver unavailable')),patch('engine.OwnedProcess') as spawn:
            engine.start();engine.thread.join(2)
            self.assertEqual(engine.status()['last_error']['code'],'GPU_MONITOR_UNAVAILABLE');spawn.assert_not_called()
        engine.stop()
    def test_stale_sample_is_not_ready(self):
        engine=Engine();engine.state='ready'
        engine.gpu={'free_mib':3000,'reserve_mib':2048,'sampled_at':now(),'_at':time.monotonic()-10}
        status=engine.status()
        self.assertIsNone(status['gpu']);self.assertEqual(status['state'],'recovering')
        self.assertEqual(status['last_error']['code'],'GPU_MONITOR_UNAVAILABLE')
    def test_never_adopts_foreign_model(self):
        engine=Engine()
        with patch('engine.gal_service.health',return_value=True),patch('engine.OwnedProcess') as spawn:
            with self.assertRaises(ClientError) as err:engine.start()
            self.assertEqual(err.exception.code,'ENGINE_IN_USE');spawn.assert_not_called()

if __name__=='__main__':unittest.main(verbosity=2)
