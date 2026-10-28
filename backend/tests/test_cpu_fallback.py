"""Preserve the VRAM reserve and legacy mode while allowing native CPU-only use."""
from pathlib import Path
import sys
import unittest
import tempfile
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from engine import Engine,ClientError

class CpuFallbackTests(unittest.TestCase):
    def setUp(self):
        self.engine=Engine();self.meta={'gpu_offload_weight_mib':{'0':0,'1':160,'2':320,'10':1600}}
    def test_browser_mode_keeps_original_start_requirement(self):
        with self.assertRaises(ClientError):self.engine.offload_plan(2350,self.meta)
    def test_desktop_cpu_mode_keeps_2048_mib_reserve(self):
        self.engine.set_cpu_fallback(True)
        self.assertEqual(self.engine.offload_plan(2350,self.meta),(0,True))
        with self.assertRaises(ClientError):self.engine.offload_plan(2047,self.meta)
    def test_available_gpu_budget_still_selects_gpu_layers(self):
        self.engine.set_cpu_fallback(True)
        self.assertEqual(self.engine.offload_plan(3200,self.meta),(2,False))
    def test_recovery_cap_zero_selects_cpu_without_kv_gpu_offload(self):
        self.engine.set_cpu_fallback(True);self.engine.set_recovery_cap(0)
        self.assertEqual(self.engine.offload_plan(6000,self.meta),(0,True))

    def launch_args(self,cpu,processors):
        engine=self.engine;captured=[]
        class Process:
            pid=1
            def poll(self):return 0
            def close(self):pass
        def launch(args,*rest):captured.extend(args);engine.stop_event.set();return Process()
        with tempfile.TemporaryDirectory() as folder,patch('engine.ROOT',Path(folder)), \
             patch.object(engine,'_sample',return_value={'free_mib':4000}), \
             patch.object(engine,'offload_plan',return_value=(0 if cpu else 2,cpu)), \
             patch('engine.os.cpu_count',return_value=processors),patch('engine.OwnedProcess',side_effect=launch):
            engine._run()
        return captured

    def test_cpu_prefill_uses_available_cores_without_changing_generation_threads(self):
        args=self.launch_args(True,16)
        self.assertEqual(args[args.index('--threads-batch')+1],'16')
        self.assertEqual(args[args.index('--threads')+1],'8')
        self.assertEqual(args[args.index('--device')+1],'none')

    def test_cpu_prefill_is_bounded_on_large_machines(self):
        args=self.launch_args(True,64)
        self.assertEqual(args[args.index('--threads-batch')+1],'16')

    def test_small_cpu_and_gpu_mode_do_not_receive_sixteen_batch_workers(self):
        args=self.launch_args(True,4)
        self.assertEqual(args[args.index('--threads-batch')+1],'4')
        self.engine=Engine();args=self.launch_args(False,16)
        self.assertEqual(args[args.index('--threads-batch')+1],'8')
