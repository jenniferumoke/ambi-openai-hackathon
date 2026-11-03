import asyncio
import json
from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx2
import pytest
from agents.models.openai_responses import OpenAIResponsesModel
from agents.realtime.model_events import RealtimeModelToolCallEvent
from agents.realtime.model_inputs import RealtimeModelSendToolOutput, RealtimeModelSendUserInput
from agents.realtime.testing import ScriptedRealtimeModel
from openai import AsyncOpenAI

import expression_monitor
import main
import observation_sidecars
import screen_observer
from camera import CameraError, CameraFrame
from observation_hub import ObservationHub
from screen_capture import ScreenCaptureError, ScreenFrame
from test_agent import computer_call, final_message, response
from test_observation import decision_response
from test_screen_observer import description


async def until(predicate):
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(0.005)


@pytest.mark.parametrize("failure", [None, "camera", "computer"])
@pytest.mark.parametrize("stop_tool", ["exit_agent", "stop_computer"])
async def test_both_sidecars_share_context_preserve_delegation_and_fail_independently(monkeypatch, desktop, failure, stop_tool):
    camera_closed = asyncio.Event()
    screen_closed = asyncio.Event()
    logs = []
    captures = [0, 0]

    class Camera:
        async def __aenter__(self):
            if failure == "camera":
                raise CameraError("Camera unavailable.")
            return self

        async def __aexit__(self, *_):
            await asyncio.sleep(0.01)
            camera_closed.set()

        async def capture(self):
            captures[0] += 1
            return CameraFrame(monotonic(), b"camera-frame")

    class Screen:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            await asyncio.sleep(0.01)
            screen_closed.set()

        async def capture(self):
            captures[1] += 1
            if failure == "computer":
                raise ScreenCaptureError("Screen Recording denied.")
            return ScreenFrame(monotonic(), b"screen-frame", "Editor", "window-a")

        async def context_id(self):
            return "window-a"

    monkeypatch.setattr(expression_monitor, "MacCamera", lambda _: Camera())
    monkeypatch.setattr(screen_observer, "ReadOnlyScreenCapture", Screen)
    screen_requests = []
    worker_requests = []

    async def observe_http(request):
        if request.url.path == "/v1/decisions":
            return httpx2.Response(200, json=decision_response())
        body = json.loads(request.content)
        screen_requests.append(body)
        output = [{"id": "screen_msg", "type": "message", "role": "assistant", "status": "completed",
                   "content": [{"type": "output_text", "text": description().model_dump_json(), "annotations": []}]}]
        return httpx2.Response(200, json=response(output, len(screen_requests)))

    async def worker_http(request):
        worker_requests.append(json.loads(request.content))
        output = [computer_call()] if len(worker_requests) == 1 else [final_message()]
        return httpx2.Response(200, json=response(output, len(worker_requests)))

    camera_client = AsyncOpenAI(api_key="offline", max_retries=0,
                                http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(observe_http)))
    screen_client = AsyncOpenAI(api_key="offline", max_retries=0,
                                http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(observe_http)))
    worker_client = AsyncOpenAI(api_key="offline", max_retries=0,
                                http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(worker_http)))
    monkeypatch.setattr(expression_monitor, "AsyncOpenAI", lambda **_: camera_client)
    monkeypatch.setattr(screen_observer, "AsyncOpenAI", lambda **_: screen_client)
    hub = ObservationHub()
    actual_sidecars = observation_sidecars.run_sidecars

    async def sidecars(*args, **kwargs):
        await actual_sidecars(*args, **kwargs, hub=hub, log=lambda event, **fields: logs.append((event, fields)))

    monkeypatch.setattr(observation_sidecars, "run_sidecars", sidecars)

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

    audio = Audio()
    monkeypatch.setattr(main, "create_audio_io", lambda *_: audio)
    voice = ScriptedRealtimeModel(strict=False)
    actual_runner = main.create_voice_runner
    allow_connection = asyncio.Event()

    class DelayedConnection:
        def __init__(self, *args, **kwargs):
            self.runner = actual_runner(*args, model=voice, **kwargs)

        async def run(self, **kwargs):
            # Both sources must begin initialization before voice connects.
            assert any(event == "starting" for event, _ in logs)
            assert any(event == "screen_starting" for event, _ in logs)
            await allow_connection.wait()
            return await self.runner.run(**kwargs)

    monkeypatch.setattr(main, "create_voice_runner", DelayedConnection)
    worker = main.ComputerWorker(desktop, main.Settings())
    initial_generation = desktop.generation
    worker.agent.model = OpenAIResponsesModel("gpt-6.1-terra", worker_client)
    args = SimpleNamespace(push_to_talk=False, observe=True, observe_computer=True, camera_device=0)
    task = asyncio.create_task(main.run_voice(
        worker, main.Settings(), args,
        expression_monitor.ObservationSettings(interval=0.5, ttl=2),
        screen_observer.ScreenObservationSettings(interval=0.5, ttl=3),
    ))
    try:
        def expected_state():
            snapshot = hub.snapshot()
            return (snapshot["camera"]["status"] == ("disabled" if failure == "camera" else "available")
                    and snapshot["computer"]["status"] == ("disabled" if failure == "computer" else "available"))

        await until(expected_state)
        # No connected voice transport, microphone input, or speech event is
        # needed for real observer/SDK results to reach the shared hub.
        assert not voice.connect_calls
        assert all(fields["runtime"]["user_turn_generation"] == 0
                   for event, fields in logs if event == "joint_observation")
        assert logs[0] == ("observation_starting", {
            "sources": ["camera", "computer"], "startup_trigger": "session_start", "waits_for_user_speech": False,
        })
        assert worker_requests == []
        assert worker.history == []
        desktop.gui.click.assert_not_called()
        desktop.gui.screenshot.assert_not_called()
        desktop.clipboard.copy.assert_not_called()
        assert not any(isinstance(event, RealtimeModelSendUserInput) for event in voice.sent_events)
        if failure is None:
            assert hub.snapshot()["pair"]["aligned"]
        if failure != "computer":
            assert screen_requests and all(request["tools"] == [] for request in screen_requests)
        allow_connection.set()
        await until(lambda: bool(voice.connect_calls))
        await voice.emit(RealtimeModelToolCallEvent(name="use_computer", call_id="work_1",
                                                  arguments='{"task":"Type a greeting in the focused test document."}'))
        await until(lambda: any(isinstance(event, RealtimeModelSendToolOutput)
                                and event.output == "Verified the text on screen." for event in voice.sent_events))
        desktop.gui.click.assert_called_once_with(20, 30, button="left")
        assert len(worker_requests) == 2
        assert worker_requests[0]["tools"][0] == {"type": "computer"}
        assert worker_requests[0]["tools"][1]["name"] == "open_application"
        assert desktop.generation == initial_generation + 1
        assert {tool.name for tool in voice.connect_calls[0]["initial_model_settings"]["tools"]} == {
            "use_computer", "stop_computer", "exit_agent",
        }
        await voice.emit(RealtimeModelToolCallEvent(name=stop_tool, call_id="bye", arguments="{}"))
        async with asyncio.timeout(3):
            await task
        final_captures = captures.copy()
        final_logs = len(logs)
        await asyncio.sleep(0.05)
        assert captures == final_captures
        assert len(logs) == final_logs
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.gather(camera_client.close(), screen_client.close(), worker_client.close())
    assert audio.closed
    assert screen_closed.is_set()
    if failure != "camera":
        assert camera_closed.is_set()
    assert hub.snapshot()["computer"]["status"] != "available"
    assert hub.snapshot()["camera"]["status"] != "available"


@pytest.mark.parametrize("arguments,camera_enabled,screen_enabled", [
    (["--observe-computer-only"], False, True),
    (["--observe-only", "--observe-computer"], True, True),
])
async def test_standalone_flags_select_sources_without_starting_action_worker(monkeypatch, arguments, camera_enabled, screen_enabled):
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-key")
    monkeypatch.setattr(main, "load_dotenv", lambda *_: None)
    monkeypatch.setattr("main.sys.argv", ["main.py", *arguments])
    sidecars = AsyncMock()
    monkeypatch.setattr(observation_sidecars, "run_sidecars", sidecars)
    desktop = Mock(side_effect=AssertionError("Observation must not construct the action adapter"))
    permissions = Mock(side_effect=AssertionError("Observation does not need Accessibility permission"))
    monkeypatch.setattr(main, "Desktop", desktop)
    monkeypatch.setattr(main, "mac_permissions", permissions)
    await main.main()
    sidecars.assert_awaited_once()
    camera, screen = sidecars.call_args.args
    assert (camera is not None) == camera_enabled
    assert (screen is not None) == screen_enabled
    desktop.assert_not_called()
    permissions.assert_not_called()
