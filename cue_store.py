"""Short-lived local journal of visible camera cue changes, without images."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ambient import CuePacket


class CueStore:
    def __init__(self, path, *, retention_hours=24, max_events=500):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.retention = timedelta(hours=retention_hours)
        self.max_events = max_events
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS camera_cue_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stream_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            observed_at TEXT NOT NULL,
            received_at TEXT NOT NULL,
            usable INTEGER NOT NULL,
            cues_json TEXT NOT NULL,
            scores_json TEXT NOT NULL,
            inference_ms REAL NOT NULL,
            detection_ms REAL NOT NULL,
            UNIQUE(stream_id, sequence)
        )""")
        self.db.execute("CREATE INDEX IF NOT EXISTS cue_events_received ON camera_cue_events(received_at)")
        self.db.commit()
        self.path.chmod(0o600)
        self.prune()

    def prune(self, now=None):
        now = now or datetime.now(timezone.utc)
        cutoff = (now - self.retention).isoformat()
        with self.db:
            self.db.execute("DELETE FROM camera_cue_events WHERE received_at < ?", (cutoff,))
            self.db.execute("""DELETE FROM camera_cue_events WHERE id NOT IN (
                SELECT id FROM camera_cue_events ORDER BY id DESC LIMIT ?
            )""", (self.max_events,))

    def record(self, packet: CuePacket, *, now=None):
        """Save only accepted state changes, not every camera frame."""
        now = now or datetime.now(timezone.utc)
        cues = sorted(set(packet.cues)) if packet.usable else []
        scores = packet.scores if packet.usable else {}
        cues_json = json.dumps(cues)
        previous = self.db.execute("""SELECT usable, cues_json FROM camera_cue_events
            WHERE stream_id=? ORDER BY id DESC LIMIT 1""", (packet.stream_id,)).fetchone()
        if previous and bool(previous["usable"]) == packet.usable and previous["cues_json"] == cues_json:
            return None
        with self.db:
            cursor = self.db.execute("""INSERT OR IGNORE INTO camera_cue_events
                (stream_id, sequence, observed_at, received_at, usable, cues_json, scores_json,
                 inference_ms, detection_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (packet.stream_id, packet.sequence, (now - timedelta(milliseconds=packet.age_ms)).isoformat(),
                 now.isoformat(), int(packet.usable), cues_json, json.dumps(scores, sort_keys=True),
                 packet.inference_ms, packet.detection_ms))
            event_id = cursor.lastrowid if cursor.rowcount else None
        if event_id is not None:
            self.prune(now)
        return event_id

    def list(self, limit=50):
        self.prune()
        rows = self.db.execute("""SELECT * FROM camera_cue_events
            ORDER BY id DESC LIMIT ?""", (min(max(limit, 1), 100),)).fetchall()
        return [{"id": row["id"], "stream_id": row["stream_id"], "sequence": row["sequence"],
                 "observed_at": row["observed_at"], "received_at": row["received_at"],
                 "usable": bool(row["usable"]), "cues": json.loads(row["cues_json"]),
                 "scores": json.loads(row["scores_json"]), "inference_ms": row["inference_ms"],
                 "detection_ms": row["detection_ms"]} for row in rows]

    def close(self):
        self.db.close()
