"""v0.3 identity, durable deferred input, migration, ownership and recovery contracts."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from game_session import GameSession,validate_game
from core import Client,now
from storage import Storage
from engine import ClientError
from test_backend import FakeEngine,ended,body
import test_backend as baseline


class RecoveryEngine(FakeEngine):
    def __init__(self):super().__init__();self.error=None;self.free=4000;self.layers=6;self.starts=0;self.caps=[]
    def status(self):return {'state':self.state,'model':{'gpu_layers':self.layers},'gpu':None,'last_error':self.error}
    def start(self):self.starts+=1;self.state='loading';self.error=None
    def recovery_sample(self):return {'free_mib':self.free}
    def set_recovery_cap(self,cap):self.caps.append(cap)

class GameTests(unittest.TestCase):
    def test_window_rebind_waits_for_owned_stop_then_restarts(self):
        self.engine.state='stopping'
        with patch.object(self.engine,'start',side_effect=ClientError('ENGINE_STOPPING','仍在退出',409)):
            self.game._start()
        self.assertEqual(self.game.recovery,'waiting_owned_stop');self.assertIsNone(self.game.recovery_error)
        self.game.tick();self.assertEqual(self.game.recovery,'waiting_owned_stop')
        self.engine.state='stopped';self.game.tick()
        self.assertEqual(self.game.recovery,'loading');self.assertEqual(self.engine.state,'loading')
    def test_foreign_port_block_retains_diagnosis_and_finishes_deferred_source(self):
        self.engine.state='stopped'
        with patch.object(self.engine,'start',side_effect=ClientError('ENGINE_IN_USE','内部端口已有模型服务',409)):
            self.game._start()
        self.game.update({'action':'heartbeat','notice':None},'desktop')
        self.assertEqual(self.game.status()['recovery_error']['code'],'ENGINE_IN_USE')
        self.assertEqual(self.game.status()['notice'],'内部端口已有模型服务')
        result=self.game.event(self.event(),'desktop');req=self.client.get_request(result['request_id'])
        terminal,data=ended(req);self.assertEqual(terminal,'error');self.assertEqual(data['code'],'ENGINE_IN_USE')
        self.assertEqual(self.storage.history()[0]['source_text'],'今日は晴れです。')
        self.assertEqual(self.engine.calls,[]);starts=self.engine.starts;self.game.tick();self.assertEqual(self.engine.starts,starts)
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.storage=Storage(Path(self.tmp.name)/'game.db')
        self.storage.save_profile({'id':'game','name':'游戏','glossary':[],'prefs':{},'game':{'executable':'F:/game.exe','region':{'x':0,'y':.7,'width':1,'height':.2}}})
        self.engine=RecoveryEngine();self.client=Client(self.engine,self.storage);self.clock=100.;self.game=GameSession(self.client,lambda:self.clock,threaded=False)
        self.bound=self.game.update({'action':'bind','profile_id':'game','pid':123,'hwnd':456,'foreground':True},'desktop')
        self.engine.state='ready'
    def tearDown(self):self.game.close();self.client.close();self.storage.close();self.tmp.cleanup()
    def event(self,phase='stable',line=1,text='今日は晴れです。',event=None):
        return {'game_session_id':self.bound['game_session_id'],'epoch':self.client.session['epoch'],'line_id':line,'event_id':event or f'{phase}-{line}',
            'phase':phase,'source_text':text,'source_kind':'hook','captured_at':now(),'timings':{'capture_ms':0,'ocr_ms':0,'stable_wait_ms':300}}
    def test_event_sequence_backend_owned_and_idempotent(self):
        b=self.event();r=self.game.event(b,'desktop');req=self.client.get_request(r['request_id']);name,data=ended(req)
        self.assertEqual(name,'final');self.assertEqual(data['sequence'],r['sequence']);self.assertEqual(len(self.engine.calls),1)
        self.assertEqual(self.game.event(b,'desktop'),r);self.assertEqual(len(self.engine.calls),1)
        b2={**b,'source_text':'違う台詞'}
        with self.assertRaises(ClientError) as e:self.game.event(b2,'desktop')
        self.assertEqual(e.exception.code,'REQUEST_CONFLICT')
        self.assertIn('queue_ms',self.storage.history()[0]['timings'])
    def test_automatic_capabilities_require_actual_host_and_components(self):
        caps=self.client.status()['capabilities']
        self.assertFalse(caps['text_events']);self.assertFalse(caps['ocr']);self.assertFalse(caps['hook'])
        self.game.update({'action':'heartbeat','ocr_available':True},'desktop')
        self.assertFalse(self.client.status()['capabilities']['text_events'])
        self.client.ocr_available=lambda:True
        self.assertTrue(self.client.status()['capabilities']['ocr'])
        self.game.update({'action':'heartbeat','ocr_available':False,'hook_available':True},'desktop')
        caps=self.client.status()['capabilities'];self.assertTrue(caps['text_events']);self.assertTrue(caps['hook']);self.assertFalse(caps['ocr'])
        self.game.update({'action':'heartbeat','ocr_available':True},'desktop')
        self.game.update({'action':'unbind'},'desktop')
        self.assertFalse(self.client.status()['capabilities']['text_events'])
        self.assertFalse(self.game.status()['ocr_available']);self.assertFalse(self.game.status()['hook_available'])
    def test_subtitle_placement_is_additive_validated_and_durable(self):
        old={'executable':'F:/game.exe','region':{'x':0,'y':.7,'width':1,'height':.2}}
        self.assertEqual(validate_game(old),old)
        for placement in ('auto','above','below','left','right','outside'):
            config=validate_game({**old,'subtitle_placement':placement})
            self.storage.save_profile({'id':'game','name':'游戏','game':config,'glossary':[],'prefs':{}})
            self.assertEqual(self.storage.profile('game')['game']['subtitle_placement'],placement)
        for bad in ('center',True,{},None):
            with self.assertRaises(ClientError):validate_game({**old,'subtitle_placement':bad})
    def test_single_input_choices_are_opt_in_and_durable(self):
        old=self.storage.profile('game')['game']
        self.assertNotIn('hide_input',validate_game(old))
        for value in ['none','mouse_left','mouse_right','mouse_middle','key:A','key:9','key:F1','key:F12','key:Space','key:Tab','key:Escape']:
            profile=self.storage.profile('game');profile['game']=validate_game({**old,'hide_input':value})
            self.storage.save_profile(profile);self.assertEqual(self.storage.profile('game')['game']['hide_input'],value)
        for value in ['Ctrl+A','key:a','key:F13','key:Alt','left',True,None,{}]:
            with self.assertRaises(ClientError):validate_game({**old,'hide_input':value})
    def test_dialogue_box_is_separate_from_capture_and_validated(self):
        old=self.storage.profile('game')['game'];box={'x':.05,'y':.65,'width':.9,'height':.3}
        profile=self.storage.profile('game');profile['game']=validate_game({**old,'dialogue_box':box,'hide_input':'key:F8'})
        self.storage.save_profile(profile);saved=self.storage.profile('game')['game']
        self.assertEqual(saved['region'],old['region']);self.assertEqual(saved['dialogue_box'],box)
        self.assertEqual(saved['hide_input'],'key:F8')
        for value in [None,{},{'x':0,'y':0,'width':2,'height':1},{**box,'height':float('nan')},{**box,'x':True}]:
            with self.assertRaises(ClientError):validate_game({**old,'dialogue_box':value})
        profile['game']={k:v for k,v in profile['game'].items() if k!='dialogue_box'}
        self.storage.save_profile(profile);self.assertNotIn('dialogue_box',self.storage.profile('game')['game'])
    def test_ocr_visual_wrap_can_reflow_without_losing_captured_history(self):
        def generate(text,context,glossary,cancel,on_delta):
            on_delta('新的住处就在山脚下。');return '新的住处就在山脚下。'
        self.engine.generate=generate
        source='新しい住まいは山を降りたと\nころにあった。'
        result=self.game.event({**self.event(text=source),'source_kind':'ocr'},'desktop')
        name,data=ended(self.client.get_request(result['request_id']))
        self.assertEqual(name,'final');self.assertEqual(data['warnings'][0]['code'],'ocr_line_reflow')
        self.assertEqual(self.storage.history()[0]['source_text'],source)
    def test_hook_line_breaks_and_ocr_variables_remain_strict(self):
        self.engine.generate=lambda text,context,glossary,cancel,on_delta:'新的住处。'
        for line,source,kind in [(1,'新しい住まいは\nここ。','hook'),(2,'名前は{name}です。','ocr')]:
            result=self.game.event({**self.event(line=line,text=source),'source_kind':kind},'desktop')
            name,data=ended(self.client.get_request(result['request_id']))
            self.assertEqual(name,'error');self.assertEqual(data['code'],'FORMAT_DAMAGE')
    def test_auto_event_rejects_caller_sequence_and_boolean_epoch(self):
        before=self.client.session['sequence']
        for extra in ({'sequence':9000},{'request_id':'caller-id'},{'session_id':'caller-session'},{'epoch':True}):
            with self.assertRaises(ClientError) as e:self.game.event({**self.event(),**extra},'desktop')
            self.assertEqual(e.exception.code,'INVALID_INPUT')
        self.assertEqual(self.client.session['sequence'],before)
    def test_new_preview_clears_old_final_and_has_no_request_identity(self):
        r=self.game.event(self.event(),'desktop');ended(self.client.get_request(r['request_id']))
        self.game.event(self.event('preview',2,'次'),'desktop')
        self.assertEqual(self.client.subtitle['zh'],'');self.assertEqual(self.client.subtitle['state'],'capturing');self.assertIsNone(self.client.subtitle['request_id'])
    def test_preview_of_same_completed_line_cannot_clear_final(self):
        result=self.game.event(self.event(),'desktop');ended(self.client.get_request(result['request_id']))
        final=dict(self.client.subtitle)
        self.game.event(self.event('preview',text='今日は晴れです。',event='same-line-preview'),'desktop')
        self.assertEqual(self.client.subtitle,final)
        self.assertEqual(len(self.engine.calls),1)
    def test_deferred_original_and_latest_pending_survive_loading(self):
        self.engine.state='loading'
        old=self.game.event(self.event(),'desktop');time.sleep(.1);self.assertFalse(self.engine.calls)
        new=self.game.event(self.event(line=2,text='また明日。'),'desktop')
        self.assertEqual(ended(self.client.get_request(old['request_id']))[0],'cancelled')
        self.engine.state='ready';ended(self.client.get_request(new['request_id']))
        self.assertEqual([h['source_text'] for h in self.storage.history()],['また明日。','今日は晴れです。'])
        self.assertEqual(len(self.engine.calls),1)
    def test_stale_scope_owner_epoch_and_line_are_rejected(self):
        b=self.event();self.game.event(b,'desktop')
        for altered,owner in [({**b,'game_session_id':'old'},'desktop'),(b,'another'),({**b,'epoch':0},'desktop')]:
            with self.assertRaises(ClientError):self.game.event(altered,owner)
        self.game.event(self.event('preview',2,'次'),'desktop')
        with self.assertRaises(ClientError) as e:self.game.event(self.event(event='late'),'desktop')
        self.assertEqual(e.exception.code,'STALE_SEQUENCE')
    def test_reset_new_epoch_can_restart_line_numbers(self):
        self.game.event(self.event('preview',8,'古い場面'),'desktop');self.client.reset(self.client.session['session_id'])
        r=self.game.event(self.event(line=1),'desktop');self.assertEqual(ended(self.client.get_request(r['request_id']))[0],'final')
    def test_duplicate_stable_line_with_new_id_does_not_repeat_inference(self):
        b=self.event();r=self.game.event(b,'desktop');ended(self.client.get_request(r['request_id']))
        self.assertEqual(self.game.event({**b,'event_id':'duplicate'},'desktop'),r);self.assertEqual(len(self.engine.calls),1)
    def test_foreground_pause_and_expiry(self):
        self.game.update({'action':'heartbeat','foreground':False},'desktop')
        with self.assertRaises(ClientError):self.game.event(self.event(),'desktop')
        self.game.update({'action':'pause'},'desktop');self.clock+=10;self.game.tick();self.assertFalse(self.game.bound)
        self.assertEqual(self.engine.state,'stopped')
    def test_recovery_stability_cap_retry_limit_and_manual_stop(self):
        self.game.tick();self.engine.state='paused';self.engine.error={'code':'VRAM_LOW'}
        initial=self.engine.starts
        self.game.tick();self.clock+=14;self.game.alive_at=self.clock;self.game.tick();self.assertEqual(self.engine.starts,initial)
        self.clock+=1;self.game.alive_at=self.clock;self.game.tick();self.assertEqual(self.engine.starts,initial+1);self.assertEqual(self.engine.caps[-1],5)
        for interval in (30,60):
            self.engine.state='paused';self.engine.error={'code':'VRAM_LOW'};self.clock+=interval;self.game.alive_at=self.clock;self.game.tick();self.clock+=15;self.game.alive_at=self.clock;self.game.tick()
        self.engine.state='paused';self.engine.error={'code':'VRAM_LOW'};self.game.tick();self.assertEqual(self.game.recovery,'retry_limit')
        self.game.manual_stop();self.engine.state='stopped';self.clock+=130;self.game.alive_at=self.clock;self.game.tick();self.assertEqual(self.engine.starts,initial+3)
    def test_monitor_error_never_triggers_recovery(self):
        self.engine.state='error';self.engine.error={'code':'GPU_MONITOR_UNAVAILABLE'};initial=self.engine.starts
        self.clock+=100;self.game.alive_at=self.clock;self.game.tick();self.assertEqual(self.engine.starts,initial)
    def test_first_vram_failure_recovers_without_forcing_zero_gpu_layers(self):
        self.game.old_layers=None;self.engine.layers=None;self.engine.config={'max_gpu_layers':32}
        self.engine.state='paused';self.engine.error={'code':'VRAM_LOW'}
        self.game.tick();self.clock+=15;self.game.alive_at=self.clock;self.game.tick()
        self.assertEqual(self.engine.caps[-1],31)
    def test_cpu_layer_count_zero_is_preserved_during_recovery(self):
        self.engine.layers=0;self.game.tick();self.assertEqual(self.game.old_layers,0)
        self.engine.state='paused';self.engine.error={'code':'VRAM_LOW'}
        self.game.tick();self.clock+=15;self.game.alive_at=self.clock;self.game.tick()
        self.assertEqual(self.engine.caps[-1],0)
    def test_desktop_cpu_recovery_requires_stable_reserve_and_never_offloads(self):
        self.engine.cpu_fallback=True;self.engine.free=2300;self.engine.state='paused';self.engine.error={'code':'VRAM_LOW'}
        initial=self.engine.starts;self.game.tick();self.clock+=14;self.game.alive_at=self.clock;self.game.tick()
        self.assertEqual(self.engine.starts,initial)
        self.clock+=1;self.game.alive_at=self.clock;self.game.tick()
        self.assertEqual(self.engine.starts,initial+1);self.assertEqual(self.engine.caps[-1],0)
    def test_cpu_recovery_never_spends_reserve_or_restarts_manual_pause(self):
        self.engine.cpu_fallback=True;self.engine.free=2047;self.engine.state='paused';self.engine.error={'code':'VRAM_LOW'}
        initial=self.engine.starts;self.game.tick();self.clock+=30;self.game.alive_at=self.clock;self.game.tick()
        self.assertEqual(self.engine.starts,initial)
        self.engine.free=2300;self.game.manual_stop();self.clock+=30;self.game.alive_at=self.clock;self.game.tick()
        self.assertEqual(self.engine.starts,initial)
    def test_invalid_game_configuration_has_no_nan_or_command_fields(self):
        for config in ({'region':{'x':0,'y':0,'width':float('nan'),'height':.1}},{'run_command':'bad'},{'input_mode':'invalid'}):
            with self.assertRaises(ClientError):validate_game(config)

class MigrationTests(unittest.TestCase):
    def test_legacy_profiles_keep_history_and_get_empty_game(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'old.db';db=sqlite3.connect(path)
            db.execute('CREATE TABLE profiles (id TEXT PRIMARY KEY,name TEXT,glossary TEXT,prefs TEXT,glossary_version INTEGER)')
            db.execute("INSERT INTO profiles VALUES ('default','旧配置','[]','{}',4)");db.commit();db.close()
            storage=Storage(path);self.assertEqual(storage.profile('default')['glossary_version'],4);self.assertEqual(storage.profile('default')['game'],{})
            p=storage.profile('default');p['game']={'executable':'F:/game.exe'};storage.save_profile(p);storage.close()
            storage=Storage(path);self.assertEqual(storage.profile('default')['game']['executable'],'F:/game.exe');storage.close()

class GameHttpTests(unittest.TestCase):
    # Do not rerun the inherited baseline tests in this suite.
    setUp=baseline.HttpTests.setUp
    tearDown=baseline.HttpTests.tearDown
    request=baseline.HttpTests.request
    def test_patch_keeps_other_fields_and_invalid_updates_are_atomic(self):
        prefs={'font':24,'opacity':62,'mode':'zh'};game={'executable':'E:/game.exe','hide_input':'key:F8','anchor':{'dx':.1,'dy':.2},'hotkeys':{'visibility':'Ctrl+Shift+H','backlog':'Ctrl+Shift+B'},'dialogue_box':{'x':0,'y':.6,'width':1,'height':.4}}
        self.request('/api/v1/profiles','PUT',{'id':'game','name':'游戏','prefs':prefs,'game':game})
        self.server.client.create_session('game')
        self.assertEqual(self.request('/api/v1/profiles','PATCH',{'id':'game','prefs':{'opacity':70},'game':{'hotkeys':{'backlog':'Ctrl+Alt+B'},'anchor':{'dx':0}}})[0],200)
        saved=self.server.storage.profile('game')
        self.assertEqual(saved['prefs'],{**prefs,'opacity':70});self.assertEqual(saved['game']['anchor'],{'dx':0,'dy':.2})
        self.assertEqual(saved['game']['hotkeys']['visibility'],'Ctrl+Shift+H');self.assertEqual(saved['game']['hide_input'],'key:F8')
        self.assertEqual(json.loads(self.request('/api/v1/subtitle')[1])['prefs'],saved['prefs'])
        self.assertEqual(self.request('/api/v1/profiles','PATCH',{'id':'game','name':'不应保存','prefs':{'opacity':50},'game':{'hide_input':'Alt+A'}})[0],400)
        self.assertEqual(self.server.storage.profile('game'),saved)
    def test_patch_clear_defaults_missing_profile_and_malformed_identity(self):
        self.request('/api/v1/profiles','PUT',{'id':'game','name':'游戏','prefs':{'opacity':80},'game':{'dialogue_box':{'x':0,'y':0,'width':1,'height':1}}})
        self.assertEqual(self.request('/api/v1/profiles','PATCH',{'id':'game','game':{'dialogue_box':None},'prefs':{'opacity':None}})[0],200)
        saved=self.server.storage.profile('game');self.assertNotIn('dialogue_box',saved['game']);self.assertNotIn('opacity',saved['prefs'])
        for body in [{'id':{}},{'id':True},{'id':'game','game':{'unsupported':None}},{'id':'game','game':{'region':None}}]:
            self.assertEqual(self.request('/api/v1/profiles','PATCH',body)[0],400)
        self.assertEqual(self.request('/api/v1/profiles','PATCH',{'id':'missing','prefs':{'opacity':70}})[0],404)
        self.assertEqual(self.server.storage.profile('game'),saved)
    def test_bootstrap_has_explicit_desktop_protocol(self):
        result=json.loads(self.request('/bootstrap',extra={'Authorization':''})[1])
        self.assertEqual(result['desktop_protocol'],2);self.assertTrue(result['backend_build'])
        self.assertEqual(result['database_path'],self.server.storage.path)
        self.assertTrue(result['backend_root']);self.assertEqual(result['instance_id'],self.server.instance_id)
    def test_special_region_patch_is_validated_without_changing_primary(self):
        primary={'x':0,'y':.7,'width':1,'height':.2};special={'x':.1,'y':.1,'width':.8,'height':.8}
        self.request('/api/v1/profiles','PUT',{'id':'game','name':'游戏','game':{'region':primary}})
        self.assertEqual(self.request('/api/v1/profiles','PATCH',{'id':'game','game':{'special_region':special}})[0],200)
        saved=self.server.storage.profile('game');self.assertEqual(saved['game']['region'],primary)
        self.assertEqual(self.request('/api/v1/profiles','PATCH',{'id':'game','game':{'special_region':{**special,'width':2}}})[0],400)
        self.assertEqual(self.server.storage.profile('game'),saved)
        self.assertEqual(self.request('/api/v1/profiles','PATCH',{'id':'game','game':{'special_region':None}})[0],200)
        self.assertNotIn('special_region',self.server.storage.profile('game')['game'])
    def test_native_display_options_roundtrip_and_invalid_update_is_atomic(self):
        prefs={'opacity':62,'font':24,'mode':'zh'}
        region={'x':.1,'y':.8,'width':.8,'height':.1}
        game={'executable':'E:/Flowers/FLOWERS.exe','region':region,'dialogue_box':{'x':.05,'y':.65,'width':.9,'height':.3},'hide_input':'key:F8'}
        self.assertEqual(self.request('/api/v1/profiles','PUT',{'id':'flowers','name':'Flowers','prefs':prefs,'game':game})[0],200)
        saved=self.server.storage.profile('flowers');self.assertEqual(saved['game'],game)
        response=json.loads(self.request('/api/v1/profiles')[1]);self.assertEqual(next(p for p in response if p['id']=='flowers')['game'],game)
        invalid={**game,'hide_input':'Ctrl+F8'}
        self.assertEqual(self.request('/api/v1/profiles','PUT',{'id':'flowers','name':'Changed','prefs':{'opacity':100},'game':invalid})[0],400)
        self.assertEqual(self.server.storage.profile('flowers'),saved)
    def test_game_only_save_preserves_browser_display_preferences(self):
        prefs={'font':32,'opacity':75,'mode':'zh','source_kind':'manual'}
        self.assertEqual(self.request('/api/v1/profiles','PUT',{'id':'game','name':'游戏','prefs':prefs})[0],200)
        self.server.client.create_session('game')
        game={'executable':'F:/game.exe','subtitle_placement':'right'}
        self.assertEqual(self.request('/api/v1/profiles','PUT',{'id':'game','name':'游戏','game':game})[0],200)
        stored=self.server.storage.profile('game')
        self.assertEqual(stored['prefs'],prefs);self.assertEqual(stored['game'],game)
        self.assertEqual(json.loads(self.request('/api/v1/subtitle')[1])['prefs'],prefs)
        self.assertEqual(self.request('/api/v1/profiles','PUT',{'id':'game','name':'游戏','game':{**game,'subtitle_placement':'center'}})[0],400)
        self.assertEqual(self.server.storage.profile('game'),stored)
    def test_game_contract_and_legacy_submission_boundary(self):
        self.assertEqual(self.request('/api/v1/profiles','PUT',{'id':'game','name':'游戏','prefs':{},'game':{'executable':'F:/game.exe'}})[0],200)
        owner={'X-Client-Id':'desktop'}
        code,raw=self.request('/api/v1/game-session','PUT',{'action':'bind','profile_id':'game','pid':1,'hwnd':2,'foreground':True},extra=owner)
        self.assertEqual(code,200);game=json.loads(raw)
        s=self.server.client.session
        self.assertEqual(self.request('/api/v1/translate','POST',body(s))[0],409)
        self.assertEqual(self.request('/api/v1/clipboard','PUT',{'enabled':True})[0],409)
        code,data=self.request('/api/v1/text-events','POST',{'game_session_id':game['game_session_id'],'epoch':1,'line_id':1,'event_id':'test-game','phase':'stable','source_kind':'hook','source_text':'今日。','captured_at':now()},extra=owner)
        self.assertEqual(code,202);request_id=json.loads(data)['request_id'];ended(self.server.client.get_request(request_id))
        self.assertEqual(self.server.storage.history('game')[0]['source_kind'],'hook')
        self.assertEqual(self.request('/api/v1/game-session','PUT',{'action':'unbind'},extra=owner)[0],200)


if __name__=='__main__':unittest.main()
