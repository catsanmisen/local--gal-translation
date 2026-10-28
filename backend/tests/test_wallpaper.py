"""Wallpaper lifecycle tests use a fake command adapter, never the player's wallpaper."""
import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import wallpaper
from execution_policy import preferences
from engine import Engine

class Adapter:
    supported=True
    def __init__(self):
        self.snapshot={'pid':123,'created':'456','executable':'D:/wallpaper_engine/wallpaper64.exe','gpu_mib':3072}
        self.commands=[];self.alive=True;self.fail=set()
    def inspect(self):return dict(self.snapshot) if self.alive else None
    def matches(self,snapshot):return self.alive and snapshot['created']==self.snapshot['created']
    def command(self,snapshot,operation):
        self.commands.append(operation)
        if operation in self.fail:raise OSError('fake command failure')

class WallpaperTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'lease.json';self.adapter=Adapter()
        self.guard=wallpaper.WallpaperController(self.adapter,self.path)
    def tearDown(self):self.adapter.fail.clear();self.guard.close();self.tmp.cleanup()
    def test_heavy_wallpaper_is_held_once_until_model_session_ends(self):
        self.assertTrue(self.guard.acquire(True));self.assertTrue(self.guard.acquire(True))
        self.assertEqual(self.adapter.commands,['stop']);self.assertEqual(self.guard.status()['state'],'stopped')
        self.guard.restore();self.guard.restore();self.assertEqual(self.adapter.commands,['stop','play'])
    def test_disabled_control_keeps_wallpaper_running(self):
        self.guard.configure(False);self.assertFalse(self.guard.acquire(True));self.assertEqual(self.adapter.commands,[])
    def test_gpu_without_resource_pressure_does_not_stop_wallpaper(self):
        self.assertFalse(self.guard.acquire(False));self.assertEqual(self.adapter.commands,[])
    def test_light_wallpaper_is_not_stopped(self):
        self.adapter.snapshot['gpu_mib']=900;self.assertFalse(self.guard.acquire(True));self.assertEqual(self.adapter.commands,[])
    def test_inspection_failure_is_a_notice_and_does_not_block_model_start(self):
        with patch.object(self.adapter,'inspect',side_effect=OSError('monitor unavailable')):
            self.assertFalse(self.guard.acquire(True))
        self.assertEqual(self.guard.status()['state'],'unavailable');self.assertEqual(self.adapter.commands,[])
    def test_no_running_wallpaper_is_not_launched(self):
        self.adapter.alive=False;self.assertFalse(self.guard.acquire(True));self.guard.restore();self.assertEqual(self.adapter.commands,[])
    def test_manual_wallpaper_exit_is_respected(self):
        self.guard.acquire(True);self.adapter.alive=False;self.guard.restore();self.assertEqual(self.adapter.commands,['stop'])
        self.assertFalse(self.path.exists());self.assertFalse(self.guard.status()['held'])
    def test_restarted_wallpaper_process_is_not_given_old_restore(self):
        self.guard.acquire(True);self.adapter.snapshot['created']='new';self.guard.restore();self.assertEqual(self.adapter.commands,['stop'])
    def test_stop_failure_is_compensated_without_claiming_it_stopped(self):
        self.adapter.fail.add('stop');self.assertFalse(self.guard.acquire(True));self.assertEqual(self.adapter.commands,['stop','play'])
        self.assertFalse(self.guard.status()['held'])
    def test_restore_failure_retains_journal_for_retry(self):
        self.guard.acquire(True);self.adapter.fail.add('play');self.guard.restore()
        self.assertEqual(self.guard.status()['state'],'restore_failed');self.assertTrue(self.path.exists())
        self.adapter.fail.clear();self.guard.restore();self.assertFalse(self.path.exists())
    def test_cannot_stop_without_durable_restore_record(self):
        with patch.object(self.guard,'_write',side_effect=OSError('disk full')):self.assertFalse(self.guard.acquire(True))
        self.assertEqual(self.adapter.commands,[])
    def test_another_client_cannot_take_the_existing_wallpaper_lease(self):
        self.guard.acquire(True);other=wallpaper.WallpaperController(self.adapter,self.path)
        try:self.assertFalse(other.acquire(True));self.assertEqual(self.adapter.commands,['stop'])
        finally:other.close()
    def test_abandoned_stop_is_restored_by_next_client(self):
        self.guard.acquire(True);self.guard.lease.close();self.guard.lease=None;self.guard.held=None
        other=wallpaper.WallpaperController(self.adapter,self.path)
        try:other.recover();self.assertEqual(self.adapter.commands,['stop','play']);self.assertFalse(self.path.exists())
        finally:other.close()
    def test_recovery_still_restores_when_new_preference_is_disabled(self):
        self.guard.acquire(True);self.guard.lease.close();self.guard.lease=None;self.guard.held=None
        other=wallpaper.WallpaperController(self.adapter,self.path);other.configure(False)
        try:other.recover();self.assertEqual(self.adapter.commands,['stop','play'])
        finally:other.close()
    def test_invalid_journal_never_executes_a_path(self):
        self.path.write_text(json.dumps({'executable':'bad.exe'}));self.guard.recover()
        self.assertEqual(self.adapter.commands,[]);self.assertEqual(self.guard.status()['state'],'restore_failed')
    def test_setting_is_strict_boolean_and_preserves_other_preferences(self):
        self.assertTrue(preferences()['wallpaper_relief']);self.assertFalse(preferences({'model_mode':'gpu'}, {'wallpaper_relief':False})['wallpaper_relief'])
        for value in (0,1,'true',None):
            with self.assertRaises(ValueError):preferences(delta={'wallpaper_relief':value})
    def test_closed_controller_cannot_restore_a_new_clients_lease(self):
        self.guard.acquire(True);self.adapter.fail.add('play');self.guard.close();self.adapter.fail.clear()
        other=wallpaper.WallpaperController(self.adapter,self.path)
        try:
            other.recover();other.acquire(True);before=list(self.adapter.commands)
            self.guard.restore();self.guard.tick();self.assertFalse(self.guard.acquire(True))
            self.assertEqual(self.adapter.commands,before);self.assertTrue(self.path.exists());self.assertTrue(other.status()['held'])
        finally:other.close()

class EngineWallpaperTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.adapter=Adapter();self.guard=wallpaper.WallpaperController(self.adapter,Path(self.tmp.name)/'lease.json')
        self.engine=Engine(wallpaper=self.guard)
    def tearDown(self):self.engine.stop();self.guard.close();self.tmp.cleanup()
    def test_explicit_stop_restores_a_held_wallpaper_without_a_live_model(self):
        self.guard.acquire(True);self.engine.request_stop();self.assertEqual(self.adapter.commands,['stop','play'])
    def test_reload_preserves_wallpaper_lease_until_a_real_stop(self):
        self.guard.acquire(True);self.engine.stop_for_reload(True);self.assertEqual(self.adapter.commands,['stop'])
        self.engine.request_stop();self.assertEqual(self.adapter.commands,['stop','play'])
    def test_start_failure_restores_wallpaper_and_keeps_gpu_choice(self):
        self.engine.configure_execution('gpu',2048);self.guard.acquire(True)
        with patch.object(self.engine,'_sample',side_effect=OSError('GPU gone')):self.engine._run()
        self.assertEqual(self.adapter.commands,['stop','play']);self.assertEqual(self.engine.requested_mode,'gpu')
    def test_explicit_cpu_uses_its_device_after_wallpaper_relief(self):
        captured=[];engine=self.engine;engine.configure_execution('cpu',2048)
        class Process:
            pid=999
            def poll(self):return 0
            def close(self):pass
        def launch(args,*rest):captured.extend(args);engine.stop_event.set();return Process()
        with patch('engine.ROOT',Path(self.tmp.name)),patch('engine.OwnedProcess',side_effect=launch):engine._run()
        self.assertEqual(captured[captured.index('--device')+1],'none');self.assertEqual(self.adapter.commands,['stop','play'])
    def test_gpu_replans_after_wallpaper_memory_is_released(self):
        engine=self.engine;engine.configure_execution('gpu',2048);captured=[]
        class Process:
            pid=999
            def poll(self):return 0
            def close(self):pass
        def launch(args,*rest):captured.extend(args);engine.stop_event.set();return Process()
        with patch('engine.ROOT',Path(self.tmp.name)),patch.object(engine,'_sample',side_effect=[{'free_mib':2800},{'free_mib':7500}]), \
             patch('engine.OwnedProcess',side_effect=launch):engine._run()
        self.assertEqual(captured[captured.index('--gpu-layers')+1],'37');self.assertEqual(self.adapter.commands,['stop','play'])
    def test_no_gpu_budget_after_relief_still_does_not_fall_back_to_cpu(self):
        engine=self.engine;engine.configure_execution('gpu',2048);engine.set_cpu_fallback(True)
        with patch.object(engine,'_sample',return_value={'free_mib':2800}),patch('engine.time.monotonic',side_effect=[0,10]), \
             patch('engine.OwnedProcess') as launch:engine._run()
        launch.assert_not_called();self.assertEqual(engine.state,'paused');self.assertEqual(engine.requested_mode,'gpu')
        self.assertEqual(self.adapter.commands,['stop','play'])
    def test_cancel_during_wallpaper_inspection_does_not_stop_it(self):
        engine=self.engine;engine.configure_execution('cpu',2048)
        def inspect():engine.stop_event.set();return dict(self.adapter.snapshot)
        with patch.object(self.adapter,'inspect',side_effect=inspect),patch('engine.OwnedProcess') as launch:engine._run()
        launch.assert_not_called();self.assertEqual(self.adapter.commands,[])

if __name__=='__main__':unittest.main()
