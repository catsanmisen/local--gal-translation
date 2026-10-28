"""Player CPU/GPU intent, durable partial settings and latest-line reload."""
import json,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from engine import Engine,ClientError
from core import Client
from storage import Storage
from game_session import GameSession
from ui_contract import validate_layout
from test_backend import FakeEngine,body,ended
import test_backend as baseline

class ChoiceTests(unittest.TestCase):
    def setUp(self):self.engine=Engine();self.meta={'gpu_offload_weight_mib':{'1':160,'2':320,'10':1600}}
    def test_wallpaper_preference_is_additive_and_defaults_enabled(self):
        from execution_policy import preferences
        self.assertIn('wallpaper_relief',preferences())
        self.assertTrue(preferences()['wallpaper_relief'])
    def test_forced_cpu_ignores_gpu_reserve_and_available_vram(self):
        self.engine.configure_execution('cpu',2048)
        self.assertEqual(self.engine.offload_plan(0,self.meta),(0,True))
    def test_forced_gpu_never_becomes_cpu_even_with_desktop_fallback_enabled(self):
        self.engine.set_cpu_fallback(True);self.engine.configure_execution('gpu',2048)
        with self.assertRaises(ClientError) as error:self.engine.offload_plan(2350,self.meta)
        self.assertEqual(error.exception.code,'VRAM_LOW')
    def test_forced_gpu_zero_fitting_layers_is_an_explicit_error(self):
        self.engine.configure_execution('gpu',2048)
        with self.assertRaises(ClientError):self.engine.offload_plan(2800,self.meta)
    def test_smaller_reserve_allows_more_layers_without_removing_headroom(self):
        self.engine.configure_execution('gpu',2048);before=self.engine.offload_plan(3600,self.meta)[0]
        self.engine.configure_execution('gpu',1024);after=self.engine.offload_plan(3600,self.meta)[0]
        self.assertGreater(after,before);self.assertFalse(self.engine.offload_plan(3600,self.meta)[1])
    def test_invalid_or_noninteger_settings_cannot_change_engine_policy(self):
        for mode,reserve in [('cuda',1024),('gpu',512),('cpu',True),('gpu','1024')]:
            with self.assertRaises(ClientError):self.engine.configure_execution(mode,reserve)
        self.assertEqual(self.engine.requested_mode,'auto');self.assertEqual(self.engine.config['minimum_free_mib'],2048)
    def test_ready_cpu_is_healthy_without_a_gpu_sample(self):
        self.engine.configure_execution('cpu',1024);self.engine.state='ready';self.engine.execution_mode='cpu'
        self.assertEqual(self.engine.status()['state'],'ready');self.assertIsNone(self.engine.status()['gpu'])
    def test_forced_cpu_launch_works_when_nvidia_monitor_is_unavailable(self):
        captured=[];engine=self.engine;engine.configure_execution('cpu',2048)
        class Process:
            pid=1
            def poll(self):return 0
            def close(self):pass
        def launch(args,*rest):captured.extend(args);engine.stop_event.set();return Process()
        with tempfile.TemporaryDirectory() as folder,patch('engine.ROOT',Path(folder)), \
             patch.object(engine,'_sample',side_effect=OSError('no NVIDIA driver')),patch('engine.OwnedProcess',side_effect=launch):
            engine._run()
        self.assertTrue(captured);self.assertEqual(captured[captured.index('--device')+1],'none')
        self.assertEqual(captured[captured.index('--gpu-layers')+1],'0')

class PolicyEngine(FakeEngine):
    def __init__(self):
        super().__init__();self.mode='auto';self.reserve=2048;self.stops=0;self.starts=0
        self.stop_entered=threading.Event();self.stop_release=threading.Event();self.stop_release.set()
    def configure_execution(self,mode,reserve):self.mode=mode;self.reserve=reserve
    @property
    def requested_mode(self):return self.mode
    @requested_mode.setter
    def requested_mode(self,value):self.mode=value
    def status(self):return {**super().status(),'model':{'execution_mode':'cpu' if self.mode=='cpu' else 'hybrid','requested_mode':self.mode}}
    def stop(self):
        self.stops+=1;self.state='stopping';self.stop_entered.set();self.stop_release.wait(3);super().stop()
    def start(self):self.starts+=1;super().start()

class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'client.db';self.storage=Storage(self.path)
        self.engine=PolicyEngine();self.client=Client(self.engine,self.storage);self.session=self.client.create_session()
    def tearDown(self):
        self.engine.stop_release.set();self.client.close();self.storage.close();self.tmp.cleanup()
    def settle(self):
        with self.client.condition:self.assertTrue(self.client.condition.wait_for(lambda:not self.client.model_reloading,4))
    def test_old_theme_only_settings_receive_defaults_without_losing_theme(self):
        self.storage.settings({'theme':'light'})
        self.assertEqual(self.client.settings()['theme'],'light');self.assertEqual(self.client.settings()['model_mode'],'auto')
    def test_wallpaper_setting_is_applied_after_owned_stop_and_persists(self):
        applied=[]
        with patch.object(self.engine,'set_wallpaper_relief',create=True,side_effect=applied.append):
            self.client.update_settings({'wallpaper_relief':False});self.settle()
        self.assertEqual(applied,[False]);self.assertFalse(self.client.settings()['wallpaper_relief'])
        self.client.update_settings({'theme':'light'});self.assertFalse(self.client.settings()['wallpaper_relief'])
    def test_running_device_reload_preserves_wallpaper_lease_until_restart(self):
        preserved=[]
        def stop(preserve):preserved.append(preserve);self.engine.stop()
        with patch.object(self.engine,'stop_for_reload',create=True,side_effect=stop):
            self.client.update_settings({'model_mode':'cpu'});self.settle()
        self.assertEqual(preserved,[True])
    def test_paused_device_reload_releases_wallpaper_without_restart(self):
        self.game_bind();self.game.update({'action':'pause'},'desktop');released=[]
        with patch.object(self.engine,'release_wallpaper',create=True,side_effect=lambda:released.append(True)):
            self.client.update_settings({'model_mode':'cpu'});self.settle()
        self.assertEqual(released,[True])
    def test_theme_update_cannot_clobber_model_settings(self):
        self.client.update_settings({'model_mode':'cpu','gpu_reserve_mib':1024});self.settle()
        self.client.update_settings({'theme':'light'})
        self.assertEqual(self.client.settings(),{'theme':'light','model_mode':'cpu','gpu_reserve_mib':1024,'wallpaper_relief':True})
    def test_stopped_engine_saves_choice_without_starting_it(self):
        self.engine.state='stopped';self.client.update_settings({'model_mode':'gpu','gpu_reserve_mib':1536});self.settle()
        self.assertEqual(self.engine.starts,0);self.assertEqual(self.engine.mode,'gpu')
    def test_invalid_patch_is_atomic(self):
        before=self.storage.settings()
        with self.assertRaises(ClientError):self.client.update_settings({'theme':'light','gpu_reserve_mib':0})
        self.assertEqual(self.storage.settings(),before)
    def test_gpu_preference_survives_new_client_lifetime(self):
        self.engine.state='stopped';self.client.update_settings({'model_mode':'gpu','gpu_reserve_mib':1024});self.settle()
        self.client.close();self.client=Client(PolicyEngine(),self.storage)
        self.assertEqual(self.client.engine.mode,'gpu');self.assertEqual(self.client.engine.reserve,1024)
    def test_failed_persistence_keeps_running_policy_unchanged(self):
        with patch.object(self.storage,'settings',side_effect=OSError('disk unavailable')):
            with self.assertRaises(ClientError):self.client.update_settings({'model_mode':'cpu'})
        self.assertEqual(self.engine.mode,'auto');self.assertEqual(self.engine.stops,0)
    def test_cpu_manual_translation_is_not_blocked_by_gpu_reserve(self):
        original=self.engine.status
        with patch.object(self.engine,'status',side_effect=lambda:{**original(),'model':{'execution_mode':'cpu'},'gpu':{'free_mib':0,'reserve_mib':2048}}):
            self.assertEqual(ended(self.client.submit(body(self.session)))[0],'final')
    def test_manual_stop_during_reload_prevents_automatic_restart(self):
        self.engine.stop_release.clear();self.client.update_settings({'model_mode':'cpu'})
        self.assertTrue(self.engine.stop_entered.wait(1));self.client.request_stop();self.engine.stop_release.set();self.settle()
        self.assertEqual(self.engine.starts,0);self.assertEqual(self.engine.state,'stopped')
    def test_second_model_change_during_reload_is_rejected_without_overwriting(self):
        self.engine.stop_release.clear();self.client.update_settings({'model_mode':'cpu'})
        self.assertTrue(self.engine.stop_entered.wait(1))
        with self.assertRaises(ClientError):self.client.update_settings({'model_mode':'gpu'})
        self.assertEqual(self.client.settings()['model_mode'],'cpu');self.engine.stop_release.set();self.settle()
    def test_start_reapplies_saved_policy_after_a_reload_failure(self):
        self.engine.state='stopped'
        with patch.object(self.engine,'configure_execution',side_effect=ClientError('ENGINE_STOPPING','still stopping',409)):
            self.client.update_settings({'model_mode':'cpu'});self.settle()
        self.assertEqual(self.engine.mode,'auto');self.client.start();self.assertEqual(self.engine.mode,'cpu')
    def test_exit_during_reload_cannot_add_a_restored_history_row(self):
        self.game_bind();self.engine.release.clear();self.line(1,'退出时的台词。');self.assertTrue(self.engine.entered.wait(1))
        self.engine.stop_release.clear();self.client.update_settings({'model_mode':'cpu'});self.assertTrue(self.engine.stop_entered.wait(1))
        closed=threading.Thread(target=self.client.close);closed.start()
        with self.client.condition:
            self.client.condition.wait_for(lambda:self.client.closing,0.2)
        self.engine.stop_release.set();closed.join(4);self.assertFalse(closed.is_alive())
        self.assertEqual(self.storage.db.execute('SELECT COUNT(*) FROM history').fetchone()[0],1);self.assertEqual(self.engine.starts,1)
    def test_start_is_rejected_after_client_exit_begins(self):
        self.client.close();starts=self.engine.starts
        with self.assertRaises(ClientError) as error:self.client.start()
        self.assertEqual(error.exception.code,'CLIENT_CLOSING');self.assertEqual(self.engine.starts,starts)

    def game_bind(self):
        self.storage.save_profile({'id':'game','name':'test','glossary':[],'prefs':{},'game':{'executable':'test.exe','region':{'x':0,'y':0,'width':1,'height':1}}})
        self.game=GameSession(self.client,threaded=False);self.client.ocr_available=lambda:True
        bound=self.game.update({'action':'bind','profile_id':'game','pid':1,'hwnd':1,'foreground':True,'ocr_available':True},'desktop')
        self.session=dict(self.client.session);return bound['game_session_id']
    def line(self,id,text):
        return self.game.event({'game_session_id':self.game.bound['game_session_id'],'epoch':self.client.session['epoch'],
            'line_id':id,'event_id':'line-'+str(id),'phase':'stable','source_kind':'ocr','source_text':text,'captured_at':body(self.client.session)['captured_at']},'desktop')
    def test_latest_new_game_line_wins_during_device_reload(self):
        self.game_bind();self.engine.release.clear();first=self.line(1,'旧台词。')
        self.assertTrue(self.engine.entered.wait(1));self.engine.stop_release.clear()
        self.client.update_settings({'model_mode':'cpu'});self.assertTrue(self.engine.stop_entered.wait(1))
        newest=self.line(2,'最新台词。');self.engine.stop_release.set();self.settle()
        self.assertEqual(ended(self.client.get_request(newest['request_id']))[0],'final')
        self.assertEqual(ended(self.client.get_request(first['request_id']))[0],'cancelled')
        self.assertEqual(self.client.subtitle['ja'],'最新台词。');self.assertEqual(self.engine.calls[-1][0],'最新台词。')
        self.assertEqual(self.engine.max_parallel,1);self.assertEqual(len(self.engine.calls),2)
    def test_still_current_unfinished_game_line_resumes_once(self):
        self.game_bind();self.engine.release.clear();first=self.line(1,'当前台词。')
        self.assertTrue(self.engine.entered.wait(1));self.client.update_settings({'model_mode':'cpu'});self.settle()
        restored=self.game.stable_result['request_id'];self.assertNotEqual(first['request_id'],restored)
        self.assertEqual(ended(self.client.get_request(restored))[0],'final')
        self.assertEqual(self.client.subtitle['ja'],'当前台词。');self.assertEqual(len(self.engine.calls),2)
    def test_completed_game_caption_is_kept_without_duplicate_inference(self):
        self.game_bind();first=self.line(1,'完整台词。');self.assertEqual(ended(self.client.get_request(first['request_id']))[0],'final')
        before=dict(self.client.subtitle);self.client.update_settings({'model_mode':'cpu'});self.settle()
        self.assertEqual(self.client.subtitle,before);self.assertEqual(len(self.engine.calls),1)
    def test_just_final_active_request_is_not_restored_as_unfinished(self):
        self.game_bind();first=self.line(1,'刚完成的台词。');req=self.client.get_request(first['request_id']);self.assertEqual(ended(req)[0],'final')
        with self.client.lock:
            # The real worker has this state after committing final and before
            # its finally block reacquires the lock to clear active.
            self.client.active=req;before=dict(self.client.subtitle)
            self.client.update_settings({'model_mode':'cpu'})
            self.assertEqual(self.client.subtitle,before)
        self.settle();self.assertEqual(len(self.engine.calls),1);self.client.active=None
    def test_paused_game_stays_paused_after_model_choice(self):
        self.game_bind();self.game.update({'action':'pause'},'desktop');starts=self.engine.starts
        self.client.update_settings({'model_mode':'cpu'});self.settle()
        self.assertTrue(self.game.manual_paused);self.assertEqual(self.engine.starts,starts)
    def test_pause_while_reloading_prevents_new_model_start(self):
        self.game_bind();starts=self.engine.starts;self.engine.stop_release.clear()
        self.client.update_settings({'model_mode':'cpu'});self.assertTrue(self.engine.stop_entered.wait(1))
        self.game.update({'action':'pause'},'desktop');self.engine.stop_release.set();self.settle()
        self.assertEqual(self.engine.starts,starts);self.assertEqual(self.engine.state,'stopped')
    def test_gpu_recovery_from_one_layer_retains_a_nonzero_gpu_cap(self):
        self.game_bind();clock=[0.0];self.game.clock=lambda:clock[0];self.game.alive_at=0
        self.engine.requested_mode='gpu';self.engine.cpu_fallback=True;self.engine.config={'minimum_free_mib':1024};self.game.old_layers=1
        with patch.object(self.engine,'status',return_value={'state':'paused','model':{'gpu_layers':1},'last_error':{'code':'VRAM_LOW'}}), \
             patch.object(self.engine,'recovery_sample',create=True,return_value={'free_mib':3000}), \
             patch.object(self.engine,'set_recovery_cap',create=True) as cap:
            self.game.tick();clock[0]=16;self.game.alive_at=16;self.game.tick()
        self.assertGreaterEqual(cap.call_args[0][0],1)

class HttpChoiceTests(unittest.TestCase):
    setUp=baseline.HttpTests.setUp;tearDown=baseline.HttpTests.tearDown;request=baseline.HttpTests.request
    def test_additive_settings_endpoint_and_theme_only_compatibility(self):
        code,raw=self.request('/api/v1/settings');self.assertEqual(code,200);self.assertEqual(json.loads(raw)['model_mode'],'auto')
        code,_=self.request('/api/v1/settings','PATCH',{'model_mode':'gpu','gpu_reserve_mib':1024});self.assertEqual(code,200)
        code,_=self.request('/api/v1/settings','PUT',{'theme':'light'});self.assertEqual(code,200)
        saved=json.loads(self.request('/api/v1/settings')[1]);self.assertEqual(saved,{'theme':'light','model_mode':'gpu','gpu_reserve_mib':1024,'wallpaper_relief':True})
    def test_bad_preferences_and_unauthenticated_change_are_rejected(self):
        for delta in ({'gpu_reserve_mib':True},{'gpu_reserve_mib':512},{'model_mode':'cuda'},{'arbitrary':1}):
            self.assertEqual(self.request('/api/v1/settings','PATCH',delta)[0],400)
        self.assertEqual(self.request('/api/v1/settings','PATCH',{'model_mode':'cpu'},auth=False)[0],401)
    def test_missing_model_controls_fail_the_layout_contract(self):
        html=(Path(__file__).resolve().parents[2]/'frontend/index.html').read_text(encoding='utf-8')
        with self.assertRaises(ClientError) as error:validate_layout(html.replace('id="model-mode"','id="missing-model-mode"'))
        self.assertEqual(error.exception.code,'UI_LAYOUT_MISMATCH')

if __name__=='__main__':unittest.main()
