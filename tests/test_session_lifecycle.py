import asyncio
import json
from contextlib import ExitStack
from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agents.realtime.model_events import (
    RealtimeModelAudioEvent, RealtimeModelAudioDoneEvent, RealtimeModelToolCallEvent,
    RealtimeModelTranscriptDeltaEvent, RealtimeModelTurnStartedEvent, RealtimeModelTurnEndedEvent,
)
from agents.realtime.model_inputs import RealtimeModelSendToolOutput, RealtimeModelSendUserInput
from agents.realtime.testing import ScriptedRealtimeModel

import main
import audio_io
import observation_sidecars
from test_proactive_voice import noteworthy


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.005)


class Audio:
    tracker = object()
    closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True

    def playback_active(self):
        return False

    async def send_microphone(self, session):
        await asyncio.Event().wait()


def test_native_audio_start_failure_uses_compatibility_backend(monkeypatch):
    class FailedNative(Audio):
        def __enter__(self):
            raise RuntimeError("Could not start macOS voice audio: CoreAudio -10875")

    fallback = Audio()
    events = []
    monkeypatch.setattr(audio_io, "AudioIO", lambda: fallback)
    with ExitStack() as stack:
        chosen = main.enter_voice_audio(
            stack, FailedNative(), hands_free=True,
            runtime=SimpleNamespace(emit=lambda *args, **kwargs: events.append((args, kwargs))),
        )
        assert chosen is fallback
    assert fallback.closed
    assert events == [(("audio_fallback",), {"reason": "voice_processing_start_failed"})]


def test_unrelated_audio_error_is_not_hidden_by_fallback(monkeypatch):
    class FailedNative(Audio):
        def __enter__(self):
            raise RuntimeError("microphone conversion failed")

    monkeypatch.setattr(audio_io, "AudioIO", lambda: pytest.fail("unexpected fallback"))
    with ExitStack() as stack, pytest.raises(RuntimeError, match="microphone conversion failed"):
        main.enter_voice_audio(stack, FailedNative(), hands_free=True)


@pytest.mark.parametrize("trigger", ["noteworthy_task", "combined_task_difficulty"])
async def test_sidecar_offer_plays_before_any_user_input_then_explicit_request_delegates_and_stop_ends_all(monkeypatch, trigger):
    class Model(ScriptedRealtimeModel):
        def __init__(self):
            super().__init__(strict=False)
            self.notifications = []

        async def send_proactive_response(self, text, send_if):
            if not send_if():
                return False
            self.notifications.append(json.loads(text))
            await self.emit(
                RealtimeModelTurnStartedEvent(response_id="offer"),
                RealtimeModelTranscriptDeltaEvent(item_id="offer_audio", response_id="offer",
                                                 delta="Would you like help inspecting that Python error?"),
                RealtimeModelAudioEvent(data=b"synthetic-pcm", response_id="offer", item_id="offer_audio", content_index=0),
                RealtimeModelAudioDoneEvent(item_id="offer_audio", content_index=0),
                RealtimeModelTurnEndedEvent(response_id="offer"),
            )
            return True

    closed = asyncio.Event()

    async def sidecars(*args, hub, started, **kwargs):
        now = monotonic()
        payload = noteworthy() if trigger == "noteworthy_task" else noteworthy(
            progress="in_progress", noteworthy=False, notification=None, possible_blocker="A Python syntax error is visible.",
        )
        hub.publish("computer", observed_at=now, expires_at=now + 20, payload=payload)
        hub.publish("camera", observed_at=now, expires_at=now + 10,
                    payload={"stable_expression": None, "cues": ["furrowed_brow"], "interpretation": "visible_cues_only"})
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0.02)
            closed.set()

    monkeypatch.setattr(observation_sidecars, "run_sidecars", sidecars)
    class PlaybackAudio(Audio):
        def __init__(self):
            self.played = []

        def play(self, data, item_id, content_index):
            self.played.append((data, item_id, content_index))

        def response_started(self):
            pass

        def response_finished(self):
            pass

        def finish(self, *args):
            pass

    audio = PlaybackAudio()
    monkeypatch.setattr(main, "create_audio_io", lambda *_: audio)
    model = Model()
    create_runner = main.create_voice_runner
    monkeypatch.setattr(main, "create_voice_runner", lambda *args, **kwargs: create_runner(*args, model=model, **kwargs))
    worker = SimpleNamespace(active=None, perform=AsyncMock(return_value="Inspected the Python error."), stop=AsyncMock())
    args = SimpleNamespace(push_to_talk=False, observe=True, observe_computer=True, proactive=True, camera_device=0)
    task = asyncio.create_task(main.run_voice(worker, main.Settings(), args))
    try:
        await until(lambda: bool(audio.played))
        assert audio.played == [(b"synthetic-pcm", "offer_audio", 0)]
        assert model.notifications[0]["trigger"] == trigger
        assert model.notifications[0]["camera"]["payload"]["cues"] == ["furrowed_brow"]
        assert not any(isinstance(event, RealtimeModelSendUserInput) for event in model.sent_events)
        assert {tool.name for tool in model.connect_calls[0]["initial_model_settings"]["tools"]} == {
            "use_computer", "stop_computer", "exit_agent",
        }
        worker.perform.assert_not_awaited()
        await model.emit(RealtimeModelToolCallEvent(name="use_computer", call_id="approved",
                                                  arguments='{"task":"Inspect the Python error."}'))
        await until(lambda: any(isinstance(event, RealtimeModelSendToolOutput)
                                and event.output == "Inspected the Python error." for event in model.sent_events))
        worker.perform.assert_awaited_once_with("Inspect the Python error.")
        await model.emit(RealtimeModelToolCallEvent(name="stop_computer", call_id="stop_session", arguments="{}"))
        async with asyncio.timeout(3):
            await task
        assert closed.is_set() and audio.closed
        count = len(model.notifications)
        await asyncio.sleep(0.05)
        assert len(model.notifications) == count
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("end", ["disconnect", "cancel"])
async def test_session_end_waits_for_observation_cleanup_before_returning(monkeypatch, end):
    started = asyncio.Event()
    cleanup_finished = asyncio.Event()
    disconnected = asyncio.Event()

    async def sidecars(*args, **kwargs):
        kwargs["started"].set()
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0.02)
            cleanup_finished.set()

    class Session:
        model = SimpleNamespace(send_event=AsyncMock())
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def __aiter__(self):
            await disconnected.wait()
            if False:
                yield

    class Runner:
        async def run(self, **kwargs):
            return Session()

    audio = Audio()
    monkeypatch.setattr(main, "create_audio_io", lambda *_: audio)
    monkeypatch.setattr(main, "create_voice_runner", lambda *args, **kwargs: Runner())
    monkeypatch.setattr(observation_sidecars, "run_sidecars", sidecars)
    worker = SimpleNamespace(active=None, stop=AsyncMock())
    task = asyncio.create_task(main.run_voice(worker, main.Settings(), SimpleNamespace(push_to_talk=False, observe=True)))
    await started.wait()
    if end == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        disconnected.set()
        await task
    assert cleanup_finished.is_set() and audio.closed


@pytest.mark.parametrize("failure", ["audio", "connection", "session_enter"])
async def test_setup_failure_closes_observers_before_raising(monkeypatch, failure):
    observing = asyncio.Event()
    cleanup_finished = asyncio.Event()

    async def sidecars(*args, started, **kwargs):
        observing.set()
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0.02)
            cleanup_finished.set()

    class SetupAudio(Audio):
        def __enter__(self):
            assert observing.is_set()
            if failure == "audio":
                raise RuntimeError("audio setup failed")
            return super().__enter__()

    class Session:
        model = SimpleNamespace(send_event=AsyncMock())
        async def __aenter__(self):
            raise RuntimeError("session entry failed")

        async def __aexit__(self, *_):
            pass

    class Runner:
        async def run(self, **kwargs):
            assert observing.is_set()
            if failure == "connection":
                raise RuntimeError("connection failed")
            return Session()

    audio = SetupAudio()
    monkeypatch.setattr(main, "create_audio_io", lambda *_: audio)
    monkeypatch.setattr(main, "create_voice_runner", lambda *args, **kwargs: Runner())
    monkeypatch.setattr(observation_sidecars, "run_sidecars", sidecars)
    worker = SimpleNamespace(active=None, stop=AsyncMock())
    with pytest.raises(ExceptionGroup) as error:
        await main.run_voice(worker, main.Settings(), SimpleNamespace(push_to_talk=False, observe=True))
    assert isinstance(error.value.exceptions[0], RuntimeError)
    assert cleanup_finished.is_set()
    if failure != "audio":
        assert audio.closed


@pytest.mark.parametrize("phase", ["observer_startup", "connection"])
async def test_cancellation_before_voice_connects_waits_for_observer_cleanup(monkeypatch, phase):
    observing = asyncio.Event()
    connecting = asyncio.Event()
    cleanup_finished = asyncio.Event()

    async def sidecars(*args, started, **kwargs):
        observing.set()
        try:
            if phase == "connection":
                started.set()
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0.02)
            cleanup_finished.set()

    class Runner:
        async def run(self, **kwargs):
            connecting.set()
            await asyncio.Event().wait()

    audio = Audio()
    monkeypatch.setattr(main, "create_audio_io", lambda *_: audio)
    monkeypatch.setattr(main, "create_voice_runner", lambda *args, **kwargs: Runner())
    monkeypatch.setattr(observation_sidecars, "run_sidecars", sidecars)
    worker = SimpleNamespace(active=None, stop=AsyncMock())
    task = asyncio.create_task(main.run_voice(worker, main.Settings(), SimpleNamespace(push_to_talk=False, observe=True)))
    try:
        await asyncio.wait_for(observing.wait() if phase == "observer_startup" else connecting.wait(), 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 3)
        assert cleanup_finished.is_set()
        if phase == "connection":
            assert audio.closed
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
