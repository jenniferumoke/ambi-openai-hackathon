"""Private local message/task archive plus a bounded restart checkpoint."""
import json
import sqlite3
from datetime import datetime, timezone


class HistoryStore:
    def __init__(self, db):
        self.db = db
        self.last = None
        self.cache = {}
        self.error = ''
        db.execute('CREATE TABLE IF NOT EXISTS companion_journal (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS companion_history (seq INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, item_id TEXT NOT NULL, payload TEXT NOT NULL, UNIQUE(kind,item_id))')
        db.commit()

    def load(self):
        row = self.db.execute('SELECT payload FROM companion_journal WHERE id=1').fetchone()
        try:
            data = json.loads(row[0]) if row else {}
            if not isinstance(data, dict): return {}
            data['transcript'] = [item for item in data.get('transcript', []) if isinstance(item, dict) and isinstance(item.get('id'), str) and item.get('role') in {'user', 'assistant'} and isinstance(item.get('text'), str)][-200:]
            data['activity'] = [item for item in data.get('activity', []) if isinstance(item, dict) and isinstance(item.get('id'), str)][-200:]
            for item in data['activity']:
                item['at'] = 0  # Monotonic timestamps cannot cross process boundaries.
                if item.get('status') == 'running':
                    item.update(status='cancelled', detail='Interrupted when Ambi stopped. Review earlier changes before starting a new task.')
            for key in ('workspace', 'model', 'codex_thread'):
                if not isinstance(data.get(key), str): data[key] = None
            return data
        except (ValueError, TypeError, KeyError):
            return {}

    def save(self, transcript, activity, codex_thread=None, workspace=None, model=None):
        data = {'transcript': list(transcript)[-200:], 'activity': list(activity)[-200:], 'codex_thread': codex_thread, 'workspace': workspace, 'model': model}
        serialized = json.dumps(data, ensure_ascii=True)
        if serialized == self.last:
            return not self.error
        data['saved_at'] = datetime.now(timezone.utc).isoformat()
        changes = {}
        try:
            with self.db:
                for kind, rows in [('message', data['transcript']), ('activity', data['activity'])]:
                    for row in rows:
                        value = json.dumps(row, ensure_ascii=True)
                        key = (kind, row['id'])
                        if self.cache.get(key) != value:
                            self.db.execute('INSERT INTO companion_history(kind,item_id,payload) VALUES (?,?,?) ON CONFLICT(kind,item_id) DO UPDATE SET payload=excluded.payload', (kind, row['id'], value))
                            changes[key] = value
                self.db.execute('INSERT OR REPLACE INTO companion_journal VALUES (1, ?)', (json.dumps(data),))
            self.cache.update(changes)
            # Keep the in-memory comparison cache bounded; the archive is not pruned.
            current = {(kind, row['id']) for kind, rows in [('message', data['transcript']), ('activity', data['activity'])] for row in rows}
            self.cache = {key: value for key, value in self.cache.items() if key in current}
            self.last, self.error = serialized, ''
            return True
        except sqlite3.Error:
            self.error = 'History could not be saved. Check free disk space before closing Ambi.'
            return False

    def cursor(self, item_id):
        row = self.db.execute("SELECT seq FROM companion_history WHERE kind='message' AND item_id=?", (item_id,)).fetchone()
        return row[0] if row else None

    def has_before(self, cursor):
        return bool(cursor and self.db.execute("SELECT 1 FROM companion_history WHERE kind='message' AND seq<? LIMIT 1", (cursor,)).fetchone())

    def messages(self, before=None, limit=40):
        rows = self.db.execute("SELECT seq,payload FROM companion_history WHERE kind='message' AND (? IS NULL OR seq<?) ORDER BY seq DESC LIMIT ?", (before, before, limit + 1)).fetchall()
        selected = rows[:limit]
        return {'messages': [json.loads(row[1]) for row in reversed(selected)], 'cursor': selected[-1][0] if selected else None, 'has_more': len(rows) > limit}
