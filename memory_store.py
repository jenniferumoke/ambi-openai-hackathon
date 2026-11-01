"""Small, local, source-attributed memory. Sensor guesses are never durable facts."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

KINDS = {"task", "note", "email", "preference", "result"}


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class MemoryStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS memories (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL,
            body TEXT NOT NULL, source TEXT NOT NULL, status TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""")
        self.db.commit()
        self.path.chmod(0o600)

    def put(self, *, kind, title, body="", source="You", item_id=None, status="active"):
        if kind not in KINDS or status not in {"active", "done"}:
            raise ValueError("Unsupported memory kind or status")
        title, body, source = title.strip(), body.strip(), source.strip()
        if not title or len(title) > 160 or len(body) > 8000 or not source or len(source) > 120:
            raise ValueError("A title is required; keep titles under 160 and content under 8000 characters.")
        item_id, now = item_id or uuid4().hex, timestamp()
        with self.db:
            self.db.execute("""INSERT INTO memories VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET kind=excluded.kind, title=excluded.title,
                body=excluded.body, source=excluded.source, status=excluded.status,
                updated_at=excluded.updated_at""",
                (item_id, kind, title, body, source, status, now, now))
        return self.get(item_id)

    def get(self, item_id):
        row = self.db.execute("SELECT * FROM memories WHERE id=?", (item_id,)).fetchone()
        return dict(row) if row else None

    def list(self, query="", limit=50):
        # Parameterized LIKE, with wildcard characters treated literally.
        query = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")[:200]
        rows = self.db.execute("""SELECT * FROM memories
            WHERE title LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\'
            ORDER BY CASE WHEN kind='task' AND status='active' THEN 0
                WHEN kind='preference' THEN 1 WHEN kind='result' THEN 2 ELSE 3 END,
                updated_at DESC LIMIT ?""", (f"%{query}%", f"%{query}%", min(max(limit, 1), 100))).fetchall()
        return [dict(row) for row in rows]

    def delete(self, item_id):
        with self.db:
            return self.db.execute("DELETE FROM memories WHERE id=?", (item_id,)).rowcount > 0

    def complete(self, item_id):
        with self.db:
            changed = self.db.execute("UPDATE memories SET status='done', updated_at=? WHERE id=? AND kind='task'",
                                      (timestamp(), item_id)).rowcount
        return self.get(item_id) if changed else None

    def brief(self, query="", max_chars=6000):
        items = []
        for row in self.list(query, limit=12):
            entry = {key: row[key] for key in ("id", "kind", "title", "body", "source", "status", "updated_at")}
            entry["body"] = entry["body"][:1200]
            candidate = json.dumps(items + [entry], ensure_ascii=False)
            if len(candidate) > max_chars:
                break
            items.append(entry)
        return json.dumps(items, ensure_ascii=False)

    def seed_project(self):
        """Only the project facts the user supplied; no invented personal inbox."""
        if self.get("ambi-project-brief"):
            return
        self.put(item_id="ambi-project-brief", kind="task", title="Get Ambi demo-ready by 5pm",
                 body="Deadline: 1 November 2026, 17:00 Europe/London. Build a fast camera signal path, "
                      "persistent memory, a proactive greeting, and a simple UI. Reuse the existing voice "
                      "and computer-use prototype. Commit and push on a separate branch.",
                 source="Your hackathon brief")

    def close(self):
        self.db.close()
