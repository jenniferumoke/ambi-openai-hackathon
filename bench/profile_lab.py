"""Simple profile sessions: fictional context, isolated memory, human-reviewed suggestions."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
import hashlib
from html import escape
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
from urllib.parse import quote
from urllib.request import build_opener, ProxyHandler
from urllib.error import URLError
from uuid import uuid4

from memory_store import MemoryStore
from bench.paths import ROOT, FIXTURES, git

PROFILES = Path(__file__).with_name("profiles")


def now():
    return datetime.now(timezone.utc).isoformat()


def read_app_state():
    # Fixed loopback destination; never follow environment proxy settings.
    try:
        with build_opener(ProxyHandler({})).open(
            "http://127.0.0.1:8765/api/bootstrap", timeout=3
        ) as response:
            return json.load(response)["state"]
    except (URLError, TimeoutError, OSError, ValueError, KeyError) as exc:
        raise ValueError(
            "Could not reach the isolated AMBI session. Check that it is still running."
        ) from exc


def profiles():
    items = [json.loads(path.read_text()) for path in PROFILES.glob("*.json")]
    order = {"rowan": 0, "ellis": 1, "nora": 2}
    return sorted(items, key=lambda item: (order.get(item["id"], 3), item["id"]))


def profile_by_id(profile_id):
    for item in profiles():
        if item["id"] == profile_id:
            return item
    raise ValueError("Unknown demo profile")


class ProfileLab:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.process = None
        self.active_id = None

    def _path(self, session_id):
        if not isinstance(session_id, str) or not re.fullmatch(
            r"[a-f0-9]{32}", session_id
        ):
            raise ValueError("Invalid profile session")
        path = self.root / session_id
        if path.is_symlink() or not path.resolve().is_relative_to(self.root):
            raise ValueError("Invalid profile session path")
        return path

    def load(self, session_id):
        return json.loads((self._path(session_id) / "session.json").read_text())

    def save(self, item):
        path = self._path(item["id"]) / "session.json"
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(item, indent=2, ensure_ascii=False) + "\n")
        temp.chmod(0o600)
        temp.replace(path)
        return item

    def sessions(self):
        result = []
        for path in sorted(
            self.root.glob("*/session.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:12]:
            try:
                result.append(json.loads(path.read_text()))
            except (OSError, ValueError):
                continue
        return result

    def app_state(self):
        return {
            "running": self.process is not None and self.process.poll() is None,
            "session_id": self.active_id,
            "url": "http://127.0.0.1:8765",
        }

    def prepare(self, profile_id):
        profile = profile_by_id(profile_id)
        session_id = uuid4().hex
        folder = self._path(session_id)
        desktop = folder / "desktop"
        desktop.mkdir(parents=True)
        for pack in profile["packs"]:
            if (
                not re.fullmatch(r"[a-z][a-z0-9_-]*", pack)
                or (FIXTURES / pack).is_symlink()
            ):
                raise ValueError("Invalid source pack")
            shutil.copytree(
                FIXTURES / pack,
                desktop / pack,
                ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"),
            )
        for path in desktop.rglob("*"):
            if not path.is_file():
                continue
            relative = str(path.relative_to(desktop))
            saved_at = profile.get("source_saved_at", {}).get(
                relative, profile["history"][-1][0] + "T12:00:00+00:00"
            )
            if re.match(r"\d{4}-\d{2}-\d{2}", path.name):
                saved_at = path.name[:10] + "T12:00:00+00:00"
            at = datetime.fromisoformat(saved_at).timestamp()
            os.utime(path, (at, at))
        (desktop / "desktop.html").write_text(
            self._desktop_page(profile, session_id, desktop)
        )
        sources = {
            str(p.relative_to(desktop)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(desktop.rglob("*"))
            if p.is_file()
        }
        memory = MemoryStore(folder / "memory.sqlite3")
        try:
            memory.put(
                item_id="bench-profile-session",
                kind="preference",
                title="Fictional demo identity",
                body=f"Session {session_id}. You are assisting {profile['name']}, {profile['role']}. All loaded sources and memories are fictional. Snapshot date: {profile['snapshot'][:10]}. Ask before taking external actions.",
                source="AMBI-Bench profile loader",
            )
            for index, entry in enumerate(profile["memory"]):
                key = f"{profile_id}-{index}"
                memory.put(
                    item_id=key,
                    **{
                        k: entry[k]
                        for k in ("kind", "title", "body", "source", "status")
                    },
                )
                with memory.db:
                    memory.db.execute(
                        "UPDATE memories SET created_at=?, updated_at=? WHERE id=?",
                        (entry["at"], entry["at"], key),
                    )
        finally:
            memory.close()
        (folder / "memory.json").write_text(
            json.dumps(profile["memory"], indent=2, ensure_ascii=False) + "\n"
        )
        item = {
            "id": session_id,
            "profile": profile,
            "created_at": now(),
            "path": str(folder),
            "sources": sources,
            "fixture_hash": hashlib.sha256(
                json.dumps(
                    {k: v for k, v in sources.items() if k != "desktop.html"},
                    sort_keys=True,
                ).encode()
            ).hexdigest(),
            "profile_hash": hashlib.sha256(
                json.dumps(profile, sort_keys=True).encode()
            ).hexdigest(),
            "commit": git("rev-parse", "HEAD"),
            "observations": {},
            "reviews": [],
        }
        return self.save(item)

    def source_file(self, session_id, relative):
        item = self.load(session_id)
        if relative not in item["sources"]:
            raise ValueError("Not a source file in this profile")
        base = self._path(session_id) / "desktop"
        target = base / relative
        if not target.resolve().is_relative_to(base.resolve()) or any(
            p.is_symlink() for p in [target, *target.parents] if p != base.parent
        ):
            raise ValueError("Source symlinks are not accepted")
        return target

    @staticmethod
    def _page(title, content):
        return f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)}</title><style>
        *{{box-sizing:border-box}}body{{font:14px/1.6 -apple-system,BlinkMacSystemFont,Arial,sans-serif;color:#25282c;margin:0;background:#fff}}header{{padding:16px 28px;border-bottom:1px solid #ddd;display:flex;justify-content:space-between;gap:20px}}header small{{color:#737980}}main{{max-width:1050px;padding:30px;margin:auto}}h1{{font-size:25px;margin:0 0 8px}}h2{{font-size:16px;margin-top:26px}}p{{margin:8px 0 16px}}a{{color:#325b99;text-decoration:none}}a:hover{{text-decoration:underline}}ul{{padding:0;list-style:none}}li{{border-bottom:1px solid #e8eaed;padding:9px 0}}small,.muted{{color:#707780}}pre{{font:13px/1.7 ui-monospace,monospace;white-space:pre-wrap;overflow-wrap:anywhere;background:#f7f8fa;padding:20px;border:1px solid #e1e4e8}}.email{{font:15px/1.8 -apple-system,BlinkMacSystemFont,Arial,sans-serif;background:white;border:0;padding:15px 0}}.headers{{padding:16px 0;border-block:1px solid #ddd}}.headers p{{margin:4px 0;font-size:13px}}iframe{{width:100%;height:80vh;border:1px solid #ddd}}.folders{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:32px}}</style><header><strong>{escape(title)}</strong><small>Fictional local sources · no live accounts</small></header><main>{content}</main></html>"""

    def _desktop_page(self, profile, session_id, desktop):
        content = f"<h1>{escape(profile['name'])}'s workspace</h1><p>{escape(profile['summary'])}</p><p class='muted'>Saved context: {escape(profile['snapshot'][:10])}. Open a document or message to continue working.</p><div class='folders'>"
        for pack in profile["packs"]:
            content += f"<section><h2>{escape(pack.title())}</h2><ul>"
            for path in sorted((desktop / pack).rglob("*")):
                if path.is_file():
                    relative = str(path.relative_to(desktop))
                    content += f'<li><a href="/profile-view/{session_id}/{quote(relative)}">{escape(str(path.relative_to(desktop / pack)))}</a></li>'
            content += "</ul></section>"
        return self._page("Demo workspace", content + "</div>")

    def source_view(self, session_id, relative):
        path = self.source_file(session_id, relative)
        back = (
            f'<p><a href="/profile-files/{session_id}/desktop.html">← Workspace</a></p>'
        )
        if path.suffix == ".pdf":
            content = (
                back
                + f'<h1>{escape(path.stem)}</h1><p><a href="/profile-files/{session_id}/{quote(relative)}" target="_blank" rel="noopener">Open PDF</a></p><iframe title="Source document" src="/profile-files/{session_id}/{quote(relative)}"></iframe>'
            )
        elif path.suffix == ".eml":
            message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
            content = (
                back
                + f'<h1>{escape(str(message.get("Subject", "Message")))}</h1><div class="headers">'
            )
            for key in ("From", "To", "Cc", "Date"):
                if message.get(key):
                    content += (
                        f"<p><strong>{key}:</strong> {escape(str(message[key]))}</p>"
                    )
            body = message.get_content()
            content += (
                '</div><pre class="email">'
                + escape(body if isinstance(body, str) else str(body))
                + "</pre>"
            )
        else:
            content = (
                back
                + f"<h1>{escape(path.name)}</h1><pre>{escape(path.read_text())}</pre>"
            )
        return self._page("Demo sources", content)

    def open_editor(self, session_id):
        item = self.load(session_id)
        if "code" not in item["profile"]["packs"]:
            raise ValueError(
                "This profile uses documents and the demo inbox. Open its desktop sources instead."
            )
        folder = self._path(session_id) / "desktop/code"
        command = shutil.which("code")
        if not command:
            raise ValueError(
                "No code editor CLI found. Open the displayed folder manually."
            )
        subprocess.run(
            [
                command,
                "--new-window",
                str(folder / "pairmatch.code-workspace"),
                str(folder / "exercise.py"),
                str(folder / "logs/test-session.txt"),
            ],
            check=True,
            timeout=10,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    async def launch(self, session_id):
        item = self.load(session_id)
        if self.app_state()["running"]:
            if self.active_id == session_id:
                return self.app_state()
            raise ValueError(
                "Stop the current demo AMBI session before launching another profile."
            )
        if not (ROOT / "ui/dist/index.html").is_file():
            raise ValueError(
                "Build the team UI first: cd ui && npm ci && npm run build"
            )
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", 8765)) == 0:
                raise ValueError(
                    "Port 8765 is already in use. Stop that AMBI server yourself; it will not be replaced."
                )
        with (self._path(session_id) / "app.log").open("ab") as log:
            self.process = subprocess.Popen(
                [sys.executable, "-m", "bench.profile_app", "--session", session_id],
                cwd=ROOT,
                stdout=log,
                stderr=log,
                env={**os.environ, "AMBI_BENCH_PROFILE_ROOT": str(self.root)},
            )
        self.active_id = session_id
        for _ in range(40):
            if self.process.poll() is not None:
                raise ValueError(
                    "Demo AMBI exited during startup. Check its local app.log."
                )
            try:
                await self._app_snapshot(session_id)
                return self.app_state()
            except ValueError:
                await asyncio.sleep(0.1)
        raise ValueError(
            "Demo AMBI is still starting. Retry after a moment or inspect its local app.log."
        )

    async def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                await asyncio.to_thread(self.process.wait, timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                await asyncio.to_thread(self.process.wait)
        self.process = None
        self.active_id = None

    async def _app_snapshot(self, session_id):
        if not self.app_state()["running"] or self.active_id != session_id:
            raise ValueError("Launch AMBI with this demo profile first.")
        snapshot = await asyncio.to_thread(read_app_state)
        marker = next(
            (m for m in snapshot["memories"] if m["id"] == "bench-profile-session"),
            None,
        )
        if not marker or session_id not in marker["body"]:
            raise ValueError(
                "AMBI is not using this isolated profile. No session data was captured."
            )
        return snapshot

    @staticmethod
    def scenario(item, scenario_id):
        for scenario in item["profile"]["scenarios"]:
            if scenario["id"] == scenario_id:
                return scenario
        raise ValueError("Unknown profile scenario")

    async def observe(self, session_id, scenario_id):
        item = self.load(session_id)
        self.scenario(item, scenario_id)
        snapshot = await self._app_snapshot(session_id)
        if snapshot["status"] != "connected" or snapshot["phase"] != "ready":
            raise ValueError(
                "Start the AMBI session and wait for its greeting to finish, then begin observation."
            )
        item["observations"][scenario_id] = {
            "started_at": now(),
            "baseline_ids": [t["id"] for t in snapshot["transcript"]],
            "baseline_event_ids": [event["id"] for event in snapshot.get("events", [])],
            "baseline_suggestion": (snapshot.get("suggestion") or {}).get("id"),
            "captures": [],
        }
        return self.save(item)

    async def capture(self, session_id, scenario_id):
        item = self.load(session_id)
        self.scenario(item, scenario_id)
        observation = item["observations"].get(scenario_id)
        if not observation:
            raise ValueError(
                "Begin observation after the greeting before capturing a response."
            )
        snapshot = await self._app_snapshot(session_id)
        suggestion = snapshot.get("suggestion")
        if suggestion and suggestion.get("id") == observation["baseline_suggestion"]:
            suggestion = None
        texts = [
            t["text"]
            for t in snapshot["transcript"]
            if t["role"] == "assistant" and t["id"] not in observation["baseline_ids"]
        ]
        offers = [
            event["text"]
            for event in snapshot.get("events", [])
            if event.get("type") == "suggestion"
            and event["id"] not in observation.get("baseline_event_ids", [])
            and event.get("text")
        ]
        capture = {
            "at": now(),
            "suggestion": suggestion,
            "assistant_text": texts,
            "focus": snapshot["focus"],
            "suggestion_events": offers,
            "user_prompted": any(
                t["role"] == "user" and t["id"] not in observation["baseline_ids"]
                for t in snapshot["transcript"]
            ),
            "phase": snapshot["phase"],
            "status": snapshot["status"],
            "camera_present": snapshot.get("camera") is not None,
            "elapsed_seconds": round(
                (
                    datetime.now(timezone.utc)
                    - datetime.fromisoformat(observation["started_at"])
                ).total_seconds(),
                1,
            ),
        }
        observation["captures"].append(capture)
        observation["captures"] = observation["captures"][-20:]
        return self.save(item)

    def review(self, session_id, scenario_id, verdict, notes):
        item = self.load(session_id)
        scenario = self.scenario(item, scenario_id)
        if verdict not in {"helpful", "unwanted", "quiet", "missed", "not_tested"}:
            raise ValueError("Choose a review result")
        if not isinstance(notes, str) or len(notes) > 3000:
            raise ValueError("Keep notes under 3000 characters")
        observation = item["observations"].get(scenario_id)
        item["reviews"].append(
            {
                "id": uuid4().hex,
                "scenario_id": scenario_id,
                "at": now(),
                "verdict": verdict,
                "notes": notes,
                "expected": scenario["expectation"],
                "assessment": "operator review; not an automated model grade",
                "observation": observation,
                "app_commit": git("rev-parse", "HEAD"),
            }
        )
        return self.save(item)
