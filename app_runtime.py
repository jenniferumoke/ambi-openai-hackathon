"""Local app session ownership. The UI never receives provider credentials."""
from __future__ import annotations

import asyncio
import os
from collections import deque
from time import monotonic
from types import SimpleNamespace
from uuid import uuid4

from ambient import AmbientClassifier, AmbientLoop, FastCamera
from main import ComputerWorker, RealtimeSessionError, Settings, run_voice
from observation_hub import ObservationHub
from proactive_controller import TurnActivity, TurnContext


class UnavailableWorker:
    active = None
    computer = SimpleNamespace(generation=0)

    async def perform(self, task):
        return "Computer control is unavailable. Enable Accessibility and Screen Recording for the launching terminal, then restart Ambi."

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
        self.transcript = deque(maxlen=40)
        self._decision_task = None
        self._message_lock = asyncio.Lock()

    @staticmethod
    def permissions():
        try:
            from desktop import mac_permissions
            return mac_permissions()
        except Exception:
            return {"Accessibility": False, "Screen Recording": False}

    def emit(self, event, **fields):
        if event == "job_started":
            self.job = {"id": uuid4().hex, "task": fields["task"], "status": "running", "started_at": monotonic()}
        elif event == "job_finished" and self.job:
            self.job.update(status=fields["status"], result=fields.get("result", "")[:4000])
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
            self.worker = (ComputerWorker(Desktop(), settings, memory=self.memory, emit=self.emit)
                           if permissions and all(permissions.values()) else UnavailableWorker())
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
        memories = self.memory.list(limit=50)
        return {"status": self.status, "phase": phase, "error": self.error, "focus": self.focus,
                "microphone_enabled": self.microphone_enabled,
                "proactive": {"status": "paused", "reason": blocked} if blocked else dict(self.proactive),
                "observations": self.hub.snapshot(context=ctx),
                "camera": self.camera.latest if self.camera.latest and now - self.camera.latest["received_at"] < 2 else None,
                "suggestion": self.suggestion, "job": self.job, "transcript": list(self.transcript),
                "events": list(self.events)[-12:], "memories": [{**m, "body": m["body"][:800]} for m in memories]}
