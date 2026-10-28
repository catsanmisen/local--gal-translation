"""Bounded durable history and per-game settings, without third-party dependencies."""
import json
import sqlite3
import threading
from data_tools import DatabaseLease
from pathlib import Path


class Storage:
    def __init__(self, path):
        self.path = str(Path(path).resolve())
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lease = DatabaseLease(path)
        self.lock = threading.RLock()
        try:
            self.db = sqlite3.connect(path, check_same_thread=False)
            self._initialize()
        except Exception:
            if hasattr(self,'db'):self.db.close()
            self.lease.close()
            raise

    def _initialize(self):
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS history (id TEXT PRIMARY KEY, session TEXT, profile TEXT, body TEXT, result TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS profiles (id TEXT PRIMARY KEY, name TEXT, glossary TEXT, prefs TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS settings (id TEXT PRIMARY KEY, value TEXT)')
        # SQLite secondary indexes already carry rowid; equality on profile/session supports reverse history order.
        self.db.execute('CREATE INDEX IF NOT EXISTS history_profile_finished ON history(profile) WHERE result IS NOT NULL')
        self.db.execute('CREATE INDEX IF NOT EXISTS history_session_finished ON history(session) WHERE result IS NOT NULL')
        if 'glossary_version' not in [r[1] for r in self.db.execute('PRAGMA table_info(profiles)')]:
            self.db.execute('ALTER TABLE profiles ADD COLUMN glossary_version INTEGER NOT NULL DEFAULT 1')
        if 'game' not in [r[1] for r in self.db.execute('PRAGMA table_info(profiles)')]:
            self.db.execute("ALTER TABLE profiles ADD COLUMN game TEXT NOT NULL DEFAULT '{}'")
        self.db.execute("INSERT OR IGNORE INTO profiles (id,name,glossary,prefs) VALUES ('default', '默认配置', '[]', '{}')")
        # Preserve original text for requests interrupted by an unexpected process exit.
        for request_id, raw in self.db.execute('SELECT id, body FROM history WHERE result IS NULL').fetchall():
            body = json.loads(raw)
            self.db.execute('UPDATE history SET result=? WHERE id=?', (json.dumps({
                'request_id': request_id, 'at': body['captured_at'], 'source_text': body['source_text'],
                'source_kind': body['source_kind'], 'speaker': body.get('speaker'), 'terminal': 'interrupted',
                'translation': None, 'reason': '客户端意外退出', 'elapsed_ms': None, 'warnings': []}, ensure_ascii=False), request_id))
        self.db.commit()

    def add(self, body, profile):
        with self.lock, self.db:
            if self.db.execute('SELECT 1 FROM history WHERE id=?', (body['request_id'],)).fetchone():
                from engine import ClientError
                raise ClientError('REQUEST_CONFLICT', '请求编号曾经使用，不能再次推理。', 409)
            self.db.execute('INSERT INTO history VALUES (?,?,?,?,NULL)',
                (body['request_id'], body['session_id'], profile, json.dumps(body, ensure_ascii=False)))

    def finish(self, body, event, data):
        entry = {'request_id': body['request_id'], 'at': body['captured_at'], 'source_text': body['source_text'],
            'source_kind': body['source_kind'], 'speaker': body.get('speaker'), 'terminal': event,
            'translation': data.get('translation') if event == 'final' else None,
            'reason': data.get('reason', data.get('message')), 'elapsed_ms': data.get('elapsed_ms'), 'warnings': data.get('warnings', [])}
        if 'timings' in data:entry['timings']=data['timings']
        with self.lock, self.db:
            self.db.execute('UPDATE history SET result=? WHERE id=?', (json.dumps(entry, ensure_ascii=False), body['request_id']))
            self.db.execute('DELETE FROM history WHERE rowid IN (SELECT rowid FROM history WHERE result IS NOT NULL ORDER BY rowid DESC LIMIT -1 OFFSET 10000)')

    def history(self, profile=None, limit=200, offset=0, session=None):
        with self.lock:
            sql, args = 'SELECT result FROM history WHERE result IS NOT NULL', []
            if profile:
                sql += ' AND profile=?'
                args.append(profile)
            if session:
                sql += ' AND session=?'
                args.append(session)
            rows = self.db.execute(sql + ' ORDER BY rowid DESC LIMIT ? OFFSET ?', (*args, limit, offset)).fetchall()
            return [json.loads(row[0]) for row in rows]

    def clear_history(self, profile):
        from engine import ClientError
        with self.lock, self.db:
            if self.db.execute('SELECT 1 FROM history WHERE profile=? AND result IS NULL LIMIT 1', (profile,)).fetchone():
                raise ClientError('HISTORY_BUSY', '本游戏还有未完成台词，请等待完成或取消后再删除历史。', 409)
            return self.db.execute('DELETE FROM history WHERE profile=? AND result IS NOT NULL', (profile,)).rowcount

    def profiles(self):
        with self.lock:
            return [{'id': r[0], 'name': r[1], 'glossary': json.loads(r[2]), 'prefs': json.loads(r[3]), 'glossary_version': r[4], 'game': json.loads(r[5])}
                for r in self.db.execute('SELECT id,name,glossary,prefs,glossary_version,game FROM profiles').fetchall()]

    def profile(self, profile_id):
        with self.lock:
            row = self.db.execute('SELECT id,name,glossary,prefs,glossary_version,game FROM profiles WHERE id=?', (profile_id,)).fetchone()
            return {'id': row[0], 'name': row[1], 'glossary': json.loads(row[2]), 'prefs': json.loads(row[3]),
                'glossary_version': row[4], 'game': json.loads(row[5])} if row else None

    def save_profile(self, profile):
        with self.lock, self.db:
            self.db.execute('INSERT OR REPLACE INTO profiles (id,name,glossary,prefs,glossary_version,game) VALUES (?,?,?,?,?,?)',
                (profile['id'], profile['name'], json.dumps(profile['glossary'], ensure_ascii=False),
                    json.dumps(profile['prefs'], ensure_ascii=False), profile.get('glossary_version', 1),
                    json.dumps(profile.get('game', {}), ensure_ascii=False)))

    def settings(self, value=None):
        with self.lock, self.db:
            if value is not None:
                self.db.execute("INSERT OR REPLACE INTO settings VALUES ('global',?)", (json.dumps(value, ensure_ascii=False),))
            row = self.db.execute("SELECT value FROM settings WHERE id='global'").fetchone()
            return json.loads(row[0]) if row else {'theme': 'dark'}

    def close(self):
        with self.lock:
            self.db.close()
            self.lease.close()
