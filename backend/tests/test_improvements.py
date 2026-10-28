"""Regression tests for the backend review, using isolated storage and no GPU."""
import argparse
from contextlib import redirect_stderr
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import sqlite3
import socket
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from core import Client, CANCEL_REASONS
from engine import Engine, ClientError
from cli_config import add_client_port
from ui_contract import validate_layout, REQUIRED_IDS, REQUIRED_SCRIPTS
import test_backend as baseline
from test_backend import FakeEngine, body, ended
from clipboard import Clipboard
from server import Server


class ClientFixture(unittest.TestCase):
    def setUp(self):baseline.CoreTests.setUp(self)
    def tearDown(self):baseline.CoreTests.tearDown(self)

class PersistenceReviewTests(ClientFixture):
    def test_glossary_disk_failure_leaves_live_session_alone(self):
        self.engine.release.clear()
        req=self.client.submit(body(self.session))
        self.assertTrue(self.engine.entered.wait(1))
        before=dict(self.client.session)
        with patch.object(self.storage,'save_profile',side_effect=OSError('disk unavailable')),self.assertLogs(level='ERROR'):
            with self.assertRaises(ClientError) as caught:
                self.client.glossary(self.session['session_id'],[{'source':'葵','target':'小葵'}])
        self.assertEqual(caught.exception.code,'STORAGE_ERROR')
        self.assertEqual(self.client.session,before)
        self.assertFalse(req.cancel.is_set())
        self.assertEqual(self.storage.profile('default')['glossary'],[])
        self.engine.release.set();self.assertEqual(ended(req)[0],'final')

    def test_terminal_save_failure_keeps_worker_alive_without_commit(self):
        with self.assertLogs(level='ERROR'),patch.object(self.storage,'finish',side_effect=OSError('disk unavailable')):
            req=self.client.submit(body(self.session))
            event,data=ended(req)
            self.assertEqual(event,'error');self.assertEqual(data['code'],'STORAGE_ERROR')
        self.assertTrue(self.client.worker.is_alive());self.assertFalse(self.client.context)
        with self.storage.lock:
            row=self.storage.db.execute('SELECT body,result FROM history WHERE id=?',(req.body['request_id'],)).fetchone()
        self.assertEqual(json.loads(row[0])['source_text'],req.body['source_text']);self.assertIsNone(row[1])
        self.assertEqual(ended(self.client.submit(body(self.session,2)))[0],'final')

    def test_cancel_timeout_retains_diagnostic_and_cancel_reason(self):
        self.engine.release.clear()
        self.engine.failure=ClientError('CANCEL_TIMEOUT','模型计算槽未释放，已停止。',503)
        def failed_cancel(text,context,glossary,cancel,delta):
            self.engine.entered.set();cancel.wait(2)
            raise self.engine.failure
        with patch.object(self.engine,'generate',side_effect=failed_cancel):
            req=self.client.submit(body(self.session));self.assertTrue(self.engine.entered.wait(1))
            self.client.cancel(req.body['request_id'],'client_disconnected')
            event,data=ended(req)
        self.assertEqual(event,'cancelled');self.assertEqual(data['reason'],'client_disconnected')
        self.assertEqual(data['diagnostic']['code'],'CANCEL_TIMEOUT')
        self.assertEqual(self.client.status()['last_error']['code'],'CANCEL_TIMEOUT')

    def test_cancel_reason_validation(self):
        self.assertIn('client_disconnected',CANCEL_REASONS)
        req=self.client.submit(body(self.session));ended(req)
        with self.assertRaises(ClientError):self.client.cancel(req.body['request_id'],'arbitrary')

    def test_clipboard_busy_keeps_one_incident_until_recovery(self):
        error={'code':'CLIPBOARD_BUSY','message':'剪贴板被占用，正在重试。','retryable':True}
        self.client.set_clipboard_error(error,'notice')
        first=dict(self.client.clipboard_error)
        for _ in range(20):self.client.set_clipboard_error(error,'notice')
        self.assertEqual(self.client.clipboard_error,first)
        self.client.set_clipboard_error(None);self.client.set_clipboard_error(error,'notice')
        self.assertGreater(self.client.clipboard_error['revision'],first['revision'])
        self.assertEqual(self.client.status()['clipboard']['last_error']['severity'],'notice')

    def test_history_filter_uses_partial_indexes(self):
        ended(self.client.submit(body(self.session)))
        with self.storage.lock:
            plan=self.storage.db.execute('EXPLAIN QUERY PLAN SELECT result FROM history WHERE result IS NOT NULL AND profile=? ORDER BY rowid DESC LIMIT ? OFFSET ?',('default',5,0)).fetchall()
            session_plan=self.storage.db.execute('EXPLAIN QUERY PLAN SELECT result FROM history WHERE result IS NOT NULL AND session=? ORDER BY rowid DESC LIMIT ? OFFSET ?',(self.session['session_id'],5,0)).fetchall()
        self.assertTrue(any('history_profile_finished' in row[3] for row in plan))
        self.assertTrue(any('history_session_finished' in row[3] for row in session_plan))
        self.assertFalse(any('TEMP B-TREE' in row[3] for row in plan+session_plan))

    def test_reset_clears_subtitle_identity_and_metadata(self):
        ended(self.client.submit(body(self.session)))
        self.client.reset(self.session['session_id'])
        self.assertIsNone(self.client.subtitle['request_id']);self.assertEqual(self.client.subtitle['epoch'],2)
        self.assertEqual(self.client.subtitle['state'],'idle');self.assertIsNone(self.client.subtitle['elapsed_ms'])

    def test_invalid_unicode_is_rejected_before_storage(self):
        for values in ({'source_text':'\ud800'},{'speaker':'\ud800'}):
            request=body(self.session);request.update(values)
            with self.assertRaises(ClientError) as caught:self.client.submit(request)
            self.assertEqual(caught.exception.code,'INVALID_INPUT')
        self.assertFalse(self.storage.history())

@unittest.skipUnless(os.name=='nt','Windows clipboard monitor')
class ClipboardReviewTests(ClientFixture):
    def setUp(self):
        super().setUp()
        self.clipboard=Clipboard(self.client)
        class Sequences:
            value=0
            observed=threading.Event()
            def GetClipboardSequenceNumber(self):
                if self.value:self.observed.set()
                return self.value
        self.sequences=Sequences()
        self.clipboard.user=self.sequences
    def tearDown(self):
        self.clipboard.close();super().tearDown()
    def test_busy_backoff_does_not_publish_duplicate_incidents(self):
        with patch.object(self.clipboard,'read',side_effect=OSError('occupied')) as read:
            self.clipboard.enable(True);self.sequences.value=1
            deadline=time.monotonic()+2
            while not self.client.clipboard_error and time.monotonic()<deadline:time.sleep(.02)
            first=dict(self.client.clipboard_error)
            time.sleep(.65)
            self.assertEqual(self.client.clipboard_error,first)
            self.assertEqual(first['code'],'CLIPBOARD_BUSY');self.assertLessEqual(read.call_count,4)
    def test_scene_reset_drops_unsubmitted_clipboard_event(self):
        self.engine.state='stopped'
        with patch.object(self.clipboard,'read',return_value='今日は晴れです。') as read:
            self.clipboard.enable(True);self.sequences.value=1
            self.assertTrue(self.sequences.observed.wait(1))
            self.client.reset(self.session['session_id']);self.engine.state='ready'
            time.sleep(.5)
            read.assert_not_called();self.assertFalse(self.engine.calls)
    def test_submission_failure_is_reported_and_monitor_survives(self):
        with patch.object(self.clipboard,'read',return_value='今日は晴れです。'), \
             patch.object(self.storage,'add',side_effect=sqlite3.OperationalError('disk error')),self.assertLogs(level='ERROR'):
            self.clipboard.enable(True);self.sequences.value=1
            deadline=time.monotonic()+2
            while not self.client.clipboard_error and time.monotonic()<deadline:time.sleep(.02)
            self.assertEqual(self.client.clipboard_error['code'],'CLIPBOARD_ERROR')
            self.assertTrue(self.clipboard.thread.is_alive())

class EngineReviewTests(unittest.TestCase):
    def test_idle_timeout_survives_status_and_normal_cleanup(self):
        engine=Engine();engine.state='ready'
        with self.assertLogs(level='WARNING') as logs,patch.object(engine,'rpc',return_value=[{'is_processing':True}]):
            with self.assertRaises(ClientError) as caught:engine._idle(timeout=.01)
        self.assertEqual(caught.exception.code,'CANCEL_TIMEOUT')
        self.assertEqual(engine.status()['last_error']['code'],'CANCEL_TIMEOUT')
        self.assertIsNone(engine.status()['owned_pid'])
        self.assertTrue(any('stopped the owned engine' in record for record in logs.output))
        engine.request_stop();self.assertIsNone(engine.status()['last_error'])

    def test_observed_idle_does_not_stop_engine(self):
        engine=Engine();engine.state='ready'
        with patch.object(engine,'rpc',return_value=[{'is_processing':False}]),patch.object(engine,'stop') as stop:
            engine._idle(timeout=.5)
        stop.assert_not_called()

class LayoutReviewTests(unittest.TestCase):
    def layout(self):
        return '<html><head></head><body>'+''.join('<div id="'+name+'"></div>' for name in REQUIRED_IDS)+''.join('<script src="'+name+'"></script>' for name in REQUIRED_SCRIPTS)+'</body></html>'
    def test_expected_layout_is_accepted(self):validate_layout(self.layout())
    def test_missing_control_returns_actionable_diagnostic(self):
        with self.assertRaises(ClientError) as caught:validate_layout(self.layout().replace('id="input-ja"','id="renamed"'))
        self.assertEqual(caught.exception.code,'UI_LAYOUT_MISMATCH');self.assertIn('input-ja',caught.exception.message)
    def test_duplicate_control_is_rejected(self):
        with self.assertRaises(ClientError):validate_layout(self.layout().replace('</body>','<div id="input-ja"></div></body>'))
    def test_changed_script_entry_is_rejected(self):
        with self.assertRaises(ClientError):validate_layout(self.layout().replace('js/app.js','js/other.js'))

class PortReviewTests(unittest.TestCase):
    def parse(self,args):
        parser=argparse.ArgumentParser();add_client_port(parser);return parser.parse_args(args).port
    def test_environment_default(self):
        with patch.dict(os.environ,{'GALTRANSL_CLIENT_PORT':'18049'}):self.assertEqual(self.parse([]),18049)
    def test_explicit_flag_wins_even_with_bad_environment(self):
        with patch.dict(os.environ,{'GALTRANSL_CLIENT_PORT':'bad'}):self.assertEqual(self.parse(['--port','18059']),18059)
    def test_invalid_ports_fail_before_launch(self):
        for value in ('0','-1','65536','bad'):
            with self.subTest(value=value),redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):self.parse(['--port',value])
    def test_model_port_conflict_fails_before_opening_database(self):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
        engine=FakeEngine();engine.config={'port':port}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'must-not-exist.db'
            with self.assertRaises(ClientError) as caught:Server(port,path,engine)
            self.assertEqual(caught.exception.code,'INVALID_CONFIG');self.assertFalse(path.exists())

