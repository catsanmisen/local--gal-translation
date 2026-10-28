"""Benchmark wiring only; startup intentionally fails before any model process."""
import json
import logging
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import real_model_choice as benchmark
from engine import ClientError, Engine
from wallpaper import WallpaperController
from test_wallpaper import Adapter

class BenchmarkWiring(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=benchmark.ROOT/'work');self.folder=Path(self.tmp.name)
        self.out=self.folder/'report.json';self.evidence=self.folder/'evidence.json'
        self.evidence.write_text(json.dumps({'cold_pages':[{'source':'朝。'}],
            'old_failures':[{'source':'長い原文。'}]},ensure_ascii=False),encoding='utf-8')
    def tearDown(self):self.tmp.cleanup()
    def run_benchmark(self,*extra):
        args=['benchmark','--mode','cpu','--reserve','2048','--output',str(self.out),'--evidence',str(self.evidence),*extra]
        with patch.object(sys,'argv',args),patch.object(Engine,'start',side_effect=ClientError('DRY_RUN','No model startup')), \
            patch.object(benchmark.gal_service,'gpu',return_value={'free_mib':4000}):
            with self.assertRaises(ClientError):benchmark.main()
        return json.loads(self.out.read_text(encoding='utf-8'))
    def test_default_benchmark_does_not_touch_wallpaper_or_claim_relief(self):
        with patch.object(benchmark,'WallpaperController',create=True,side_effect=AssertionError('Unexpected wallpaper action')):
            report=self.run_benchmark()
        self.assertFalse(report['requested']['wallpaper_relief'])
        self.assertFalse(report['wallpaper_control_enabled']);self.assertEqual(report['cases'],[])
        self.assertIsNone(report['game_running'])
        self.assertEqual(report['physical_display'],'not_measured')
        self.assertEqual(report['gpu_sampling']['target_interval_seconds'],.75)
        self.assertTrue(report['gpu_sampling']['samples'])
        self.assertIsNone(report['gpu_sampling']['sampled_peak_used_mib'])

    def test_gpu_peak_uses_observed_memory_not_the_reserved_budget(self):
        with patch.object(benchmark.gal_service,'gpu',return_value={'used_mib':2345,'free_mib':1751}):
            with patch.object(sys,'argv',['benchmark','--mode','cpu','--reserve','2048','--output',str(self.out),'--evidence',str(self.evidence)]), \
                 patch.object(Engine,'start',side_effect=ClientError('DRY_RUN','No model startup')):
                with self.assertRaises(ClientError):benchmark.main()
        report=json.loads(self.out.read_text(encoding='utf-8'))
        self.assertEqual(report['gpu_sampling']['sampled_peak_used_mib'],2345)
        self.assertIn('at',report['gpu_sampling']['samples'][0])

    def test_observed_game_state_is_preserved_with_its_evidence(self):
        path=self.folder/'environment.json'
        observation={'observed_at':'2026-10-23T06:00:00Z','method':'Get-Process',
            'game_running':True,'games':[{'pid':123,'name':'SeaBed'}]}
        path.write_text(json.dumps(observation),encoding='utf-8')
        report=self.run_benchmark('--environment',str(path))
        self.assertTrue(report['game_running']);self.assertEqual(report['environment'],observation)

    def test_game_state_without_detection_evidence_is_unknown(self):
        path=self.folder/'environment.json';path.write_text('{"game_running": false}',encoding='utf-8')
        report=self.run_benchmark('--environment',str(path))
        self.assertIsNone(report['game_running'])

    def test_opt_in_uses_real_controller_recovery_and_can_select_long_page(self):
        adapter=Adapter();journal=self.folder/'journal.json';previous=WallpaperController(adapter,journal)
        previous.acquire(True);adapter.fail.add('play')
        with self.assertLogs(level='ERROR'):previous.close()
        adapter.fail.clear();adapter.commands.clear();guard=WallpaperController(adapter,journal)
        with patch.object(benchmark,'WallpaperController',create=True,return_value=guard):
            report=self.run_benchmark('--wallpaper-relief','--long-page')
        self.assertEqual(adapter.commands,['play']);self.assertFalse(journal.exists());self.assertTrue(guard.closed)
        self.assertTrue(report['requested']['wallpaper_relief']);self.assertTrue(report['wallpaper_control_enabled'])
        self.assertEqual(report['source'],'長い原文。');self.assertEqual(report['cases'],[])

    def test_standalone_benchmark_keeps_rejected_output_without_external_logging_setup(self):
        calls=[]
        def start(engine):engine.state='ready';engine.execution_mode='cpu';engine.layers=0
        def generate(engine,*args,**kwargs):
            calls.append(args[0]);return '' if len(calls)==1 else '早晨。'
        args=['benchmark','--mode','cpu','--reserve','2048','--output',str(self.out),'--evidence',str(self.evidence)]
        root_logger=logging.getLogger()
        with patch.object(root_logger,'level',logging.WARNING),patch.object(sys,'argv',args), \
             patch.object(Engine,'start',start),patch.object(Engine,'generate',generate), \
             patch.object(benchmark.gal_service,'gpu',return_value={'free_mib':4000}):
            benchmark.main()
            self.assertEqual(root_logger.level,logging.WARNING)
        path=self.out.with_suffix('.quality.log');self.assertTrue(path.is_file(),'standalone diagnostic file missing')
        records=[json.loads(line.split('translation_quality ',1)[1]) for line in path.read_text(encoding='utf-8').splitlines()
                 if 'translation_quality ' in line]
        self.assertEqual([r['stage'] for r in records],['initial','repair','terminal'])
        self.assertEqual(records[0]['raw_output'],'');self.assertEqual(records[-1]['terminal'],'final')
        report=json.loads(self.out.read_text(encoding='utf-8'));self.assertEqual(report['cases'][0]['data']['timings']['generation_count'],2)

if __name__=='__main__':unittest.main()
