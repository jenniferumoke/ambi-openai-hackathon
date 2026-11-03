"""Local app session ownership. The UI never receives provider credentials."""
from __future__ import annotations

import asyncio
import os
import sys
from collections import deque
from time import monotonic
from types import SimpleNamespace
from uuid import uuid4

from app_version import VERSION
from codex_bridge import CodexBridge
from history_store import HistoryStore
from pathlib import Path

from ambient import AmbientClassifier, AmbientLoop, FastCamera
from main import ComputerWorker, RealtimeSessionError, Settings, run_voice
from observation_hub import ObservationHub
from proactive_controller import TurnActivity, TurnContext


class UnavailableWorker:
    active = None
    computer = SimpleNamespace(generation=0)

    async def perform(self, task):
        return "Computer control is off or unavailable. Review computer access in Setup & connections and the operating system permissions, then restart the voice session."

    async def stop(self):
        return "No computer task is running."


class AppRuntime:
    def __init__(self, memory, *, demo_profile=None):
        self.memory = memory
        self.demo_profile = demo_profile
        self.hub = ObservationHub(mode="ellis_demo" if demo_profile else "ambient")
        self.hub.unavailable("computer", "session_not_started", status="disabled")
        self.camera = FastCamera(self.hub)
        self.status = "idle"
        self.error = None
        self.task = None
        self.session = None
        self.worker = None
        self.audio = None
        self.activity = TurnActivity()
        self.context = lambda: TurnContext()
        self.exit_requested = None
        self.focus = False
        self.microphone_enabled = True
        self.connected_at = 0
        self.suggestion = None
        self.proactive = {"status": "paused", "reason": "session_not_connected"}
        self.job = None
        self.events = deque(maxlen=40)
        self.activity_log = deque(maxlen=200)
        self.history_store = HistoryStore(memory.db)
        saved = self.history_store.load()
        self.transcript = deque(saved.get("transcript", []), maxlen=200)
        self.activity_log.extend(saved.get("activity", []))
        self.codex = CodexBridge(self._codex_event)
        self.codex_thread = saved.get("codex_thread")
        self.codex_task = None
        self.codex.state["model"] = saved.get("model")
        default_workspace = Path(os.getenv("AMBI_WORKSPACE", str(memory.path.parent / "workspace"))).expanduser().resolve()
        selected = Path(saved["workspace"]).expanduser() if saved.get("workspace") else default_workspace
        self.workspace_notice = ""
        if not selected.is_dir() and selected != default_workspace:
            selected = default_workspace
            self.workspace_notice = "Your previous folder is unavailable. Ambi is using its private folder; choose another folder to continue there."
            self.codex_thread = None
        self.workspace = str(selected.resolve())
        Path(self.workspace).mkdir(parents=True, exist_ok=True, mode=0o700)
        self.computer_enabled = False
        self._decision_task = None
        self._message_lock = asyncio.Lock()

    def save_history(self):
        self.history_store.save(self.transcript, self.activity_log, self.codex_thread, self.workspace, self.codex.state.get("model"))

    def _codex_event(self, event, params):
        item = params.get("item", {})
        if event == "item/agentMessage/delta":
            identity = params.get("itemId", "codex-reply")
            previous = next((t for t in self.transcript if t["id"] == identity), None)
            if previous:
                previous["text"] = (previous["text"] + params.get("delta", ""))[-16000:]
            else:
                self.transcript.append({"id": identity, "role": "assistant", "text": params.get("delta", "")[:16000]})
        elif event == "item/started" and item.get("type") in {"commandExecution", "fileChange", "mcpToolCall", "webSearch"}:
            titles = {"commandExecution": "Running a command", "fileChange": "Updating files", "mcpToolCall": "Using a connected tool", "webSearch": "Searching the web"}
            self.activity_log.append({"id": item["id"], "kind": "action", "title": titles[item["type"]],
                "status": "running", "at": monotonic(), "detail": "Codex tool operation. Permission requests are shown separately."})
        elif event == "item/completed":
            if item.get("type") == "agentMessage":
                previous = next((t for t in self.transcript if t["id"] == item["id"]), None)
                if previous:
                    previous["text"] = item.get("text", previous["text"])[-16000:]
                else:
                    self.transcript.append({"id": item["id"], "role": "assistant", "text": item.get("text", "")[-16000:]})
            row = next((row for row in self.activity_log if row["id"] == item.get("id")), None)
            if row:
                row.update(status="completed" if item.get("status") == "completed" else "failed", detail=f"Operation returned. Exit code: {item.get('exitCode', 'not reported')}.")
        elif event == "connection_lost":
            if self.job and self.job.get("status") == "running" and self.job.get("engine") == "codex":
                self.emit("job_finished", status="failed", result="Codex disconnected. Earlier changes may have completed. Review them before retrying.")
        elif event == "turn_completed":
            turn = params.get("turn", {})
            status = {"completed": "completed", "interrupted": "cancelled"}.get(turn.get("status"), "failed")
            self.emit("job_finished", status=status, result="Codex returned." if status == "completed" else self.codex.state.get("error") or "Codex task stopped. Earlier changes are not undone.")
        self.save_history()

    async def send_codex(self, text, *, writable=False, new_thread=False, client_id=None):
        if not isinstance(text, str) or not text.strip() or len(text) > 4000:
            raise ValueError("Enter a message of 1–4000 characters.")
        if self.job and self.job.get("status") == "running":
            raise ValueError("Stop the current task before starting another.")
        self.transcript.append({"id": uuid4().hex, "role": "user", "text": text.strip()})
        self.emit("job_started", task=text.strip())
        self.job["engine"] = "codex"
        self.job["client_id"] = client_id
        try:
            self.codex_thread = await self.codex.start(text.strip(), self.workspace, writable=writable,
                                                thread_id=None if new_thread else self.codex_thread)
        except Exception:
            if self.job and self.job.get("status") == "running":
                self.emit("job_finished", status="failed", result="Codex could not start. Check Setup & connections.")
            raise
        finally:
            self.save_history()

    async def stop_work(self):
        codex_job = self.job and self.job.get("engine") == "codex" and self.job.get("status") == "running"
        if codex_job and self.codex.state["status"] not in {"running", "approval-required"}:
            await self.codex.close()
        else:
            await self.codex.interrupt()
        if codex_job:
            self.emit("job_finished", status="cancelled", result="Stopped. Earlier changes are not undone.")
        if self.worker:
            await self.worker.stop()

    async def shutdown(self):
        self.save_history()
        await self.codex.close()
        await self.stop()

    @staticmethod
    def permissions():
        try:
            from desktop import mac_permissions
            return mac_permissions()
        except Exception:
            return {"Accessibility": False, "Screen Recording": False}

    def emit(self, event, **fields):
        now = monotonic()
        if event == "job_started":
            self.job = {"id": uuid4().hex, "task": fields["task"], "status": "running", "started_at": monotonic()}
            self.activity_log.append({"id": self.job["id"], "kind": "task", "title": fields["task"][:4000],
                                      "status": "running", "at": now, "detail": "Computer worker started."})
        elif event == "job_finished" and self.job:
            self.job.update(status=fields["status"], result=fields.get("result", "")[:4000])
            row = next((row for row in self.activity_log if row["id"] == self.job["id"]), None)
            if row:
                row.update(status=("checked" if fields.get('reviewed') else "returned") if fields["status"] == "completed" else fields["status"],
                           detail=fields.get("result", "")[:4000])
        elif event == 'goal_checkpoint' and self.job:
            self.job.update(goal_id=fields['goal_id'], goal_status=fields['status'], review_round=fields['round'])
        elif event in {'goal_review_started', 'goal_review', 'goal_next_step'}:
            review_id = fields['goal_id'] + '-review-' + str(fields['round'])
            row = next((row for row in self.activity_log if row['id']==review_id), None)
            if event == 'goal_review' and row:
                row.update(status='completed', title='Progress checked', detail=fields.get('summary','')[:2000])
            else:
                self.activity_log.append({'id':uuid4().hex if event=='goal_next_step' else review_id,'kind':'review',
                    'title':'Next step selected' if event=='goal_next_step' else 'Checking progress',
                    'status':'completed' if event=='goal_next_step' else 'running','at':now,
                    'detail':fields.get('summary','')[:2000], 'job_id':self.job['id'] if self.job else None})
        elif event == "computer_step_started":
            self.activity_log.append({"id": fields["step_id"], "kind": "action", "title": fields["label"][:250],
                                      "status": "running", "at": now, "detail": "Desktop action in progress.",
                                      "job_id": self.job["id"] if self.job else None})
        elif event == "computer_step_finished":
            row = next((row for row in self.activity_log if row["id"] == fields["step_id"]), None)
            if row:
                row.update(status=fields["status"], detail=fields.get("detail", "")[:500])
        elif event in {"connected", "session_stopped", "audio_fallback", "session_error"}:
            titles = {"connected": "Voice session connected", "session_stopped": "Session ended",
                      "audio_fallback": "Using compatibility audio", "session_error": "Session needs attention"}
            detail = (fields.get("message", "") if event == "session_error" else
                      "Spoken interruption during playback is unavailable." if event == "audio_fallback" else "")
            self.activity_log.append({"id": uuid4().hex, "kind": "session", "title": titles[event],
                                      "status": "failed" if event == "session_error" else "completed",
                                      "at": now, "detail": detail})
        if event not in {"joint_observation", "screen_unchanged", "screen_sample"}:
            # Logs contain summaries/labels, never camera frames or credentials.
            self.events.append({"id": uuid4().hex, "type": event, "at": monotonic(), **fields})

    def attach(self, session, activity, audio, exit_requested, context):
        self.session, self.activity, self.audio = session, activity, audio
        audio.microphone_enabled = self.microphone_enabled
        self.exit_requested, self.context = exit_requested, context
        self.status, self.connected_at = "connected", monotonic()
        self.emit("connected")
        self._decision_task = asyncio.create_task(self._decisions())

    def set_microphone(self, enabled):
        self.microphone_enabled = bool(enabled)
        if self.audio:
            self.audio.microphone_enabled = self.microphone_enabled

    async def _decisions(self):
        if self.demo_profile is not None:
            from eval.test.demo import DemoLoop
            await DemoLoop(self, self.demo_profile).run()
            return
        from openai import AsyncOpenAI
        async with AsyncOpenAI(max_retries=0, timeout=3) as client:
            await AmbientLoop(self, AmbientClassifier(client, os.getenv("DECISIONS_MODEL", "gpt-6-luna"))).run()

    def quiet_reason(self):
        ctx = self.context()
        for blocked, reason in (
            (self.status != "connected", "session_not_connected"),
            (self.focus, "focus_mode"), (ctx.user_speaking, "user_speaking"),
            (ctx.response_active, "response_in_progress"), (ctx.audio_playing, "audio_playing"),
            (ctx.computer_busy, "computer_task_running"),
            (monotonic() - ctx.last_user_activity <= 2, "recent_user_activity"),
        ):
            if blocked:
                return reason
        return None

    def quiet(self):
        return self.quiet_reason() is None

    def set_proactive(self, status, reason):
        state = {"status": status, "reason": reason}
        if state != self.proactive:
            self.proactive = state
            self.emit("proactive_status", **state)

    def on_voice_event(self, event):
        if event.type != "raw_model_event":
            return
        data = event.data
        if data.type == "transcript_delta":
            item_id = data.item_id
            previous = next((t for t in self.transcript if t["id"] == item_id), None)
            if previous:
                previous["text"] = (previous["text"] + data.delta)[-8000:]
            else:
                self.transcript.append({"id": item_id, "role": "assistant", "text": data.delta})
        elif data.type == "raw_server_event":
            raw = data.data if isinstance(data.data, dict) else data.data.model_dump()
            if raw.get("type") == "conversation.item.input_audio_transcription.completed":
                from voice_input import SpeechGate
                if SpeechGate.rejection(raw) is None:
                    self.transcript.append({"id": raw["item_id"], "role": "user", "text": raw["transcript"][:8000]})
                    self.suggestion = None

    async def start(self, *, observe_screen=True):
        if self.task and not self.task.done():
            return
        if not os.getenv("OPENAI_API_KEY"):
            raise ValueError("Add OPENAI_API_KEY to the local .env file, then restart the server.")
        self.status, self.error = "connecting", None
        self.suggestion = None
        self.set_proactive("paused", "session_not_connected")
        self.hub = ObservationHub(mode="ellis_demo" if self.demo_profile else "ambient")
        self.camera = FastCamera(self.hub)
        self.activity = TurnActivity()
        self.task = asyncio.create_task(self._run(observe_screen))

    async def _run(self, observe_screen):
        from desktop import Desktop
        settings = Settings.from_env()
        permissions = self.permissions()
        try:
            self.worker = (ComputerWorker(Desktop(emit=self.emit), settings, memory=self.memory, emit=self.emit,
                allowed=lambda: self.computer_enabled and not (self.job and self.job.get("status") == "running"),
                review=True, verification_root=self.workspace)
                           if self.computer_enabled and permissions and all(permissions.values()) else UnavailableWorker())
            screen = observe_screen and permissions.get("Screen Recording", False)
            if not screen:
                reason = "screen_permission_missing" if observe_screen else "screen_observation_off"
                self.hub.unavailable("computer", reason, status="disabled")
                self.emit("screen_disabled", reason=reason)
            args = SimpleNamespace(push_to_talk=False, observe=False, observe_computer=screen,
                                   proactive=True, camera_device=0, input_device=None, output_device=None)
            await run_voice(self.worker, settings, args, memory=self.memory, runtime=self)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            while isinstance(exc, BaseExceptionGroup):
                exc = exc.exceptions[0]
            import traceback
            frames = traceback.extract_tb(exc.__traceback__)
            location = f"{frames[-1].filename.rsplit('/', 1)[-1]}:{frames[-1].lineno}" if frames else "unknown"
            print(f"Ambi session failure: {type(exc).__name__} at {location}", flush=True)
            # Provider errors may contain private request data. Surface a type and
            # actionable setup hint rather than the raw response/body.
            self.error = (str(exc) if isinstance(exc, RealtimeSessionError) else
                          f"Session stopped ({type(exc).__name__}). Check your API access, microphone permission, and audio device.")
            self.status = "error"
            self.emit("session_error", message=self.error, error_type=type(exc).__name__, location=location,
                      code=exc.code if isinstance(exc, RealtimeSessionError) else None)
        finally:
            if self._decision_task:
                self._decision_task.cancel()
                await asyncio.gather(self._decision_task, return_exceptions=True)
                self._decision_task = None
            if self.worker:
                await self.worker.stop()
            self.session = self.audio = self.exit_requested = None
            self.suggestion = None
            self.camera.clear()
            if self.hub.snapshot()["computer"]["status"] != "disabled":
                self.hub.unavailable("computer", "session_stopped", status="stopped")
            self.context = lambda: TurnContext()
            if self.status != "error":
                self.status = "idle"
            self.emit("session_stopped")

    async def stop(self):
        self.emit("session_end_requested", source="app_session_control")
        if self.task and not self.task.done():
            self.status = "stopping"
            if self.exit_requested:
                self.exit_requested.set()
            else:
                self.task.cancel()
            try:
                async with asyncio.timeout(6):
                    await asyncio.shield(self.task)
            except (TimeoutError, asyncio.CancelledError):
                if not self.task.done():
                    self.task.cancel()
                await asyncio.gather(self.task, return_exceptions=True)
        self.camera.clear()
        self.suggestion = None
        self.status = "idle"

    async def send_text(self, text):
        text = text.strip()
        if not text or len(text) > 4000:
            raise ValueError("Enter a message of 1–4000 characters.")
        async with self._message_lock:
            if not self.session or self.status != "connected":
                raise ValueError("Start a session before sending a message.")
            self.suggestion = None
            self.activity.confirmed_speech()
            await self.session.interrupt()
            self.audio.clear()
            self.transcript.append({"id": uuid4().hex, "role": "user", "text": text})
            await self.session.send_message(text)

    async def accept(self, suggestion_id):
        item = self.suggestion
        if not item or item["id"] != suggestion_id or monotonic() >= item["expires_at"]:
            raise ValueError("This suggestion has expired.")
        if not item["task"]:
            self.suggestion = None
            return
        await self.send_text(item["task"])

    def snapshot(self):
        now = monotonic()
        if self.suggestion and now >= self.suggestion["expires_at"]:
            self.suggestion = None
        ctx = self.context()
        blocked = self.quiet_reason()
        phase = ("working" if ctx.computer_busy else "listening" if ctx.user_speaking else
                 "speaking" if ctx.audio_playing or ctx.response_active else "ready")
        self.save_history()
        first_message = self.transcript[-40] if len(self.transcript) >= 40 else self.transcript[0] if self.transcript else None
        history_cursor = self.history_store.cursor(first_message["id"]) if first_message else None
        memories = self.memory.list(limit=50)
        return {"version": VERSION, "platform": sys.platform, "codex": dict(self.codex.state), "workspace": self.workspace, "computer_enabled": self.computer_enabled,
                "permissions": self.permissions(), "history_saved": not self.history_store.error, "history_error": self.history_store.error,
                "history_cursor": history_cursor, "history_has_more": self.history_store.has_before(history_cursor),
                "workspace_notice": self.workspace_notice, "status": self.status, "phase": phase, "error": self.error, "focus": self.focus,
                "microphone_enabled": self.microphone_enabled,
                "proactive": {"status": "paused", "reason": blocked} if blocked else dict(self.proactive),
                "observations": self.hub.snapshot(context=ctx),
                "camera": self.camera.latest if self.camera.latest and now - self.camera.latest["received_at"] < 2 else None,
                "suggestion": self.suggestion, "job": self.job, "transcript": list(self.transcript)[-40:],
                "events": list(self.events)[-12:], "activity": list(self.activity_log),
                "memories": [{**m, "body": m["body"][:800]} for m in memories]}
