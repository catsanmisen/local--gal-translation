import json
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from data_tools import backup_database,restore_database,DataInUseError
from storage import Storage

class DataToolTests(unittest.TestCase):
    def test_legacy_snapshot_upgrades_and_can_roll_back_without_losing_history(self):
        with tempfile.TemporaryDirectory() as folder:
            old=Path(folder)/'legacy.db';snapshot=Path(folder)/'old-snapshot.db';current=Path(folder)/'current.db'
            entry={'request_id':'case','source_text':'ありがとう。','terminal':'final','translation':'谢谢。'}
            with closing(sqlite3.connect(old)) as db:
                db.execute('CREATE TABLE profiles (id TEXT PRIMARY KEY,name TEXT,glossary TEXT,prefs TEXT)')
                db.execute('CREATE TABLE history (id TEXT PRIMARY KEY,session TEXT,profile TEXT,body TEXT,result TEXT)')
                db.execute('CREATE TABLE settings (id TEXT PRIMARY KEY,value TEXT)')
                db.execute('INSERT INTO profiles VALUES (?,?,?,?)',('default','旧配置',json.dumps([{'source':'名前','target':'名字','note':''}]),json.dumps({'opacity':70})))
                db.execute('INSERT INTO history VALUES (?,?,?,?,?)',('case','s','default','{}',json.dumps(entry)));db.commit()
            backup_database(old,snapshot);restore_database(snapshot,current);storage=Storage(current)
            try:
                self.assertEqual(storage.history()[0],entry);self.assertEqual(storage.profile('default')['glossary'][0]['target'],'名字')
                self.assertEqual(storage.profile('default')['game'],{});p=storage.profile('default');p['prefs']['opacity']=62;storage.save_profile(p)
            finally:storage.close()
            restore_database(snapshot,current);storage=Storage(current)
            try:self.assertEqual(storage.profile('default')['prefs']['opacity'],70);self.assertEqual(storage.history()[0],entry)
            finally:storage.close()
    def test_backup_includes_committed_wal_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source.db';copy=Path(folder)/'copy.db';storage=Storage(source)
            try:
                p=storage.profile('default');p['prefs']={'opacity':62};p['game']={'executable':'D:/game.exe'};storage.save_profile(p)
                backup_database(source,copy)
                with closing(sqlite3.connect(copy)) as db:self.assertEqual(json.loads(db.execute('SELECT game FROM profiles').fetchone()[0]),p['game'])
                self.assertEqual(storage.profile('default')['prefs'],p['prefs'])
                with self.assertRaises(FileExistsError):backup_database(source,copy)
            finally:storage.close()
    def test_restore_refuses_open_client_and_rolls_back_configuration(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source.db';copy=Path(folder)/'copy.db';storage=Storage(source)
            backup_database(source,copy)
            with self.assertRaises(DataInUseError):restore_database(copy,source)
            p=storage.profile('default');p['prefs']={'font':40};storage.save_profile(p);storage.close()
            restore_database(copy,source);restored=Storage(source)
            try:self.assertEqual(restored.profile('default')['prefs'],{})
            finally:restored.close()
    def test_second_client_cannot_interrupt_first_client_history(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'source.db';storage=Storage(path)
            try:
                with self.assertRaises(DataInUseError):Storage(path)
                self.assertEqual(storage.profile('default')['name'],'默认配置')
            finally:storage.close()
    def test_invalid_snapshot_never_overwrites_valid_target(self):
        with tempfile.TemporaryDirectory() as folder:
            bad=Path(folder)/'bad.db';target=Path(folder)/'target.db';bad.write_bytes(b'not sqlite')
            storage=Storage(target);storage.close();before=target.read_bytes()
            with self.assertRaises(sqlite3.DatabaseError):restore_database(bad,target)
            self.assertEqual(target.read_bytes(),before)
            self.assertEqual(list(Path(folder).glob('*.restore-*')),[])
    @unittest.skipUnless(sys.platform=='win32','Windows legacy handle compatibility')
    def test_restore_refuses_legacy_open_without_new_lease(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'target.db';copy=Path(folder)/'copy.db';storage=Storage(target);storage.close()
            backup_database(target,copy)
            legacy=sqlite3.connect(target);legacy.execute('PRAGMA journal_mode=DELETE');legacy.execute('SELECT * FROM profiles').fetchall()
            try:
                with self.assertRaises(DataInUseError):restore_database(copy,target)
                self.assertEqual(legacy.execute('SELECT name FROM profiles').fetchone()[0],'默认配置')
            finally:legacy.close()
