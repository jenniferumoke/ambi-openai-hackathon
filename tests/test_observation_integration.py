import asyncio
from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx2
import pytest
from agents.realtime.model_events import RealtimeModelRawServerEvent, RealtimeModelToolCallEvent
from agents.realtime.model_inputs import RealtimeModelSendToolOutput, RealtimeModelSendUserInput
from agents.realtime.testing import ScriptedRealtimeModel
from openai import AsyncOpenAI

import expression_monitor
import main
from camera import CameraError, CameraFrame
from expression_monitor import ObservationSettings
from test_observation import decision_response


async def wait_for(predicate):
    async with asyncio.timeout(4):
        while not predicate():
            await asyncio.sleep(0.005)


@pytest.mark.parametrize("mode", ["off", "observing", "camera_denied"])
async def test_camera_sidecar_preserves_voice_tools_and_never_sends_observations_to_voice(monkeypatch, mode):
    camera_closed = asyncio.Event()
    logs = []
    requests = []

    class Camera:
        async def __aenter__(self):
            if mode == "camera_denied":
                raise CameraError("Camera access denied.")
            return self

        async def __aexit__(self, *_):
            camera_closed.set()

        async def capture(self):
            return CameraFrame(monotonic(), b"synthetic-image")

    camera_factory = Mock(side_effect=lambda _: Camera())
    monkeypatch.setattr(expression_monitor, "MacCamera", camera_factory)

    async def handler(request):
        requests.append(request)
        return httpx2.Response(200, json=decision_response())

    # The real classifier/SDK runs concurrently with the real Realtime runner;
    # only hardware and HTTP/WebSocket transports are replaced.
    client = AsyncOpenAI(api_key="offline-test-key", max_retries=0,
                         http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))
    monkeypatch.setattr(expression_monitor, "AsyncOpenAI", lambda **_: client)
    real_observer = expression_monitor.run_observation

    async def observer(*args, **kwargs):
        await real_observer(*args, **kwargs, log=lambda event, **fields: logs.append((event, fields)))

    monkeypatch.setattr(expression_monitor, "run_observation", observer)

    class Audio:
        tracker = object()
        closed = False
        sender_stopped = False

        def __enter__(self):
            return self

        def __exit__(self, *_):
            self.closed = True

        def playback_active(self):
            return False

        def response_started(self):
            pass

        def response_finished(self):
            pass

        async def send_microphone(self, session):
            try:
                await asyncio.Event().wait()
            finally:
                self.sender_stopped = True

    audio = Audio()
    monkeypatch.setattr(main, "create_audio_io", lambda *_: audio)
    model = ScriptedRealtimeModel(strict=False)
    real_runner = main.create_voice_runner
    monkeypatch.setattr(main, "create_voice_runner", lambda *args, **kwargs: real_runner(*args, model=model, **kwargs))
    worker = SimpleNamespace(active=None, perform=AsyncMock(return_value="Opened TextEdit."), stop=AsyncMock())
    args = SimpleNamespace(push_to_talk=False, observe=mode != "off", camera_device=0)
    task = asyncio.create_task(main.run_voice(worker, main.Settings(), args,
                                            ObservationSettings(interval=0.5, ttl=2, request_timeout=1)))
    try:
        await wait_for(lambda: bool(model.connect_calls))
        if mode == "observing":
            await model.emit(RealtimeModelRawServerEvent(data={"type": "input_audio_buffer.speech_started", "item_id": "noise"}))
            await wait_for(lambda: any(fields.get("reason") == "user_speaking" for _, fields in logs))
            assert not any(fields.get("action") == "would_check_in" for _, fields in logs)
            await model.emit(RealtimeModelRawServerEvent(data={"type": "input_audio_buffer.speech_stopped", "item_id": "noise"}))
            await model.emit(RealtimeModelRawServerEvent(data={"type": "conversation.item.input_audio_transcription.completed", "item_id": "noise", "transcript": ""}))
            await model.emit(RealtimeModelRawServerEvent(data={"type": "response.done"}))
            await wait_for(lambda: any(fields.get("action") == "would_check_in" for _, fields in logs))
            assert len(requests) >= 3
        elif mode == "camera_denied":
            await wait_for(lambda: any(event == "disabled" for event, _ in logs))
            assert not requests
        else:
            camera_factory.assert_not_called()
            assert not logs

        worker.perform.assert_not_awaited()
        assert not any(isinstance(event, RealtimeModelSendUserInput) for event in model.sent_events)
        await model.emit(RealtimeModelToolCallEvent(name="use_computer", call_id="work_1",
                                                  arguments='{"task":"Open TextEdit"}'))
        await wait_for(lambda: any(isinstance(event, RealtimeModelSendToolOutput)
                                  and event.output == "Opened TextEdit." for event in model.sent_events))
        worker.perform.assert_awaited_once_with("Open TextEdit")
        tools = model.connect_calls[0]["initial_model_settings"]["tools"]
        assert {tool.name for tool in tools} == {"use_computer", "stop_computer", "exit_agent"}
        await model.emit(RealtimeModelToolCallEvent(name="exit_agent", call_id="bye", arguments="{}"))
        async with asyncio.timeout(4):
            await task
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await client.close()
    assert audio.closed and audio.sender_stopped
    if mode == "observing":
        assert camera_closed.is_set()
        assert logs[-1][0] == "stopped"


async def test_standalone_observation_does_not_require_desktop_or_voice(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-key")
    monkeypatch.setattr(main, "load_dotenv", lambda *_: None)
    monkeypatch.setattr("main.sys.argv", ["main.py", "--observe-only", "--camera-device", "1"])
    observer = AsyncMock()
    monkeypatch.setattr(expression_monitor, "run_observation", observer)
    desktop = Mock(side_effect=AssertionError("Standalone observation must not open the desktop"))
    voice = AsyncMock(side_effect=AssertionError("Standalone observation must not start voice"))
    permissions = Mock(side_effect=AssertionError("Desktop permissions are unrelated to camera mode"))
    monkeypatch.setattr(main, "Desktop", desktop)
    monkeypatch.setattr(main, "run_voice", voice)
    monkeypatch.setattr(main, "mac_permissions", permissions)
    await main.main()
    observer.assert_awaited_once()
    assert observer.call_args.kwargs["device_index"] == 1
    desktop.assert_not_called()
    voice.assert_not_awaited()
    permissions.assert_not_called()
