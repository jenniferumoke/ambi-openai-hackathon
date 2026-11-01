import asyncio
import base64
import io
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx2
import pytest
from agents.models.openai_responses import OpenAIResponsesModel
from agents.realtime.model_events import RealtimeModelToolCallEvent
from agents.realtime.model_inputs import RealtimeModelSendToolOutput
from agents.realtime.openai_realtime import OpenAIRealtimeWebSocketModel
from agents.realtime.testing import ScriptedRealtimeModel
from openai import AsyncOpenAI
from PIL import Image

from main import ComputerWorker, Settings, create_voice_runner, run_voice


def response(output, number):
    return {
        "id": f"resp_{number}", "object": "response", "created_at": 1,
        "model": "gpt-6.1-terra", "status": "completed", "output": output,
        "error": None, "incomplete_details": None, "parallel_tool_calls": False,
        "tool_choice": "auto", "tools": [], "metadata": {},
        "usage": {"input_tokens": 10, "output_tokens": 10, "total_tokens": 20,
                  "input_tokens_details": {"cached_tokens": 0},
                  "output_tokens_details": {"reasoning_tokens": 0}},
    }


def computer_call(checks=None):
    return {
        "id": "cu_1", "type": "computer_call", "call_id": "call_1", "status": "completed",
        "pending_safety_checks": checks or [],
        "actions": [
            {"type": "click", "x": 20, "y": 30, "button": "left", "keys": ["SHIFT"]},
            {"type": "type", "text": "Hello, café 👋"},
        ],
    }


def final_message():
    return {
        "id": "msg_1", "type": "message", "role": "assistant", "status": "completed",
        "content": [{"type": "output_text", "text": "Verified the text on screen.", "annotations": []}],
    }


async def test_real_sdk_sends_ga_computer_tool_executes_batch_and_returns_screenshot(desktop):
    requests = []

    async def handler(request):
        requests.append(json.loads(request.content))
        output = [computer_call()] if len(requests) == 1 else [final_message()]
        return httpx2.Response(200, json=response(output, len(requests)))

    async with AsyncOpenAI(
        api_key="offline-test-key", max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    ) as client:
        worker = ComputerWorker(desktop, Settings())
        worker.agent.model = OpenAIResponsesModel("gpt-6.1-terra", client)
        result = await worker.perform("Type a greeting in the focused test document.")

    assert result == "Verified the text on screen."
    assert len(requests) == 2
    assert requests[0]["model"] == "gpt-6.1-terra"
    assert requests[0]["tools"] == [{"type": "computer"}]
    assert requests[0]["store"] is False
    desktop.gui.click.assert_called_once_with(20, 30, button="left")
    desktop.gui.keyDown.assert_any_call("shift")
    desktop.gui.keyUp.assert_any_call("shift")
    desktop.clipboard.copy.assert_any_call("Hello, café 👋")
    output = next(item for item in requests[1]["input"] if item.get("type") == "computer_call_output")
    assert output["call_id"] == "call_1"
    encoded = output["output"]["image_url"].split(",", 1)[1]
    assert Image.open(io.BytesIO(base64.b64decode(encoded))).size == (100, 80)


async def test_model_safety_check_blocks_all_actions(desktop):
    requests = []

    async def handler(request):
        requests.append(request)
        call = computer_call([{"id": "check_1", "code": "malicious_instructions",
                               "message": "Review the page instructions."}])
        return httpx2.Response(200, json=response([call], 1))

    async with AsyncOpenAI(
        api_key="offline-test-key", max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    ) as client:
        worker = ComputerWorker(desktop, Settings())
        worker.agent.model = OpenAIResponsesModel("gpt-6.1-terra", client)
        result = await worker.perform("Inspect the test page.")

    assert "safety review" in result
    assert len(requests) == 1
    desktop.gui.click.assert_not_called()
    desktop.clipboard.copy.assert_not_called()
    desktop.gui.screenshot.assert_not_called()


async def test_voice_session_delegates_and_returns_result_without_network():
    worker = SimpleNamespace(perform=AsyncMock(return_value="Opened the document."), stop=AsyncMock())
    model = ScriptedRealtimeModel(strict=False)
    runner = create_voice_runner(worker, Settings(), model=model)
    async with await runner.run() as session:
        settings = model.connect_calls[0]["initial_model_settings"]
        assert settings["model_name"] == "gpt-realtime-2.1"
        assert settings["audio"]["input"]["format"]["rate"] == 24000
        assert settings["audio"]["input"]["noise_reduction"] is None
        assert settings["audio"]["input"]["turn_detection"]["threshold"] == 0.75
        assert settings["audio"]["input"]["turn_detection"]["interrupt_response"] is False
        assert settings["audio"]["input"]["turn_detection"]["create_response"] is False
        # Validate the actual GA wire schema, including disabling the SDK's default STT.
        wire = OpenAIRealtimeWebSocketModel()._get_session_config(settings).model_dump()
        assert wire["type"] == "realtime"
        assert wire["model"] == "gpt-realtime-2.1"
        assert wire["audio"]["input"]["transcription"]["model"] == "gpt-transcribe"
        assert wire["audio"]["output"]["voice"] == "marin"
        assert {tool["name"] for tool in wire["tools"]} == {"use_computer", "stop_computer", "exit_agent"}
        await model.emit(RealtimeModelToolCallEvent(
            name="use_computer", call_id="voice_call_1", arguments='{"task":"Open TextEdit"}',
        ))
        async with asyncio.timeout(2):
            async for event in session:
                if event.type == "tool_end":
                    break
        async with asyncio.timeout(2):
            while not any(isinstance(item, RealtimeModelSendToolOutput) for item in model.sent_events):
                await asyncio.sleep(0)
    worker.perform.assert_awaited_once_with("Open TextEdit")
    output = next(item for item in model.sent_events if isinstance(item, RealtimeModelSendToolOutput))
    assert output.output == "Opened the document."


async def test_realtime_stop_tool_can_interrupt_a_running_computer_tool(desktop, monkeypatch):
    started = asyncio.Event()

    async def slow_run(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("main.Runner.run", slow_run)
    worker = ComputerWorker(desktop, Settings())
    model = ScriptedRealtimeModel(strict=False)
    runner = create_voice_runner(worker, Settings(), model=model)
    async with await runner.run() as session:
        await model.emit(RealtimeModelToolCallEvent(
            name="use_computer", call_id="work_1", arguments='{"task":"Open TextEdit"}',
        ))
        async with asyncio.timeout(2):
            await started.wait()
        await model.emit(RealtimeModelToolCallEvent(
            name="stop_computer", call_id="stop_1", arguments="{}",
        ))
        async with asyncio.timeout(2):
            ended = 0
            async for event in session:
                if event.type == "tool_end":
                    ended += 1
                    if ended == 2:
                        break
    assert worker.active is None
    assert desktop._stopped.is_set()


async def test_stop_cancels_worker_and_busy_task_cannot_overlap(desktop, monkeypatch):
    started = asyncio.Event()

    async def slow_run(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("main.Runner.run", slow_run)
    worker = ComputerWorker(desktop, Settings())
    operation = asyncio.create_task(worker.perform("Do a slow task"))
    await started.wait()
    assert "already running" in await worker.perform("A second task")
    assert "stopped" in await worker.stop()
    assert "stopped" in await operation
    assert worker.active is None
    assert desktop._stopped.is_set()


async def test_timeout_stops_computer(desktop, monkeypatch):
    async def slow_run(*args, **kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr("main.Runner.run", slow_run)
    worker = ComputerWorker(desktop, Settings(timeout=0.01))
    assert "timed out" in await worker.perform("A slow task")
    assert worker.active is None
    assert desktop._stopped.is_set()


async def test_outer_cancellation_is_not_swallowed(desktop, monkeypatch):
    started = asyncio.Event()

    async def slow_run(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("main.Runner.run", slow_run)
    worker = ComputerWorker(desktop, Settings())
    task = asyncio.create_task(worker.perform("A slow task"))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert desktop._stopped.is_set()


async def test_interruption_drops_late_audio_but_keeps_the_next_response(monkeypatch):
    class Audio:
        def __init__(self, *args):
            self.tracker = object()
            self.played = []
            self.clears = 0

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def play(self, data, item_id, content_index):
            self.played.append((item_id, data))

        def clear(self):
            self.clears += 1

        def finish(self, *args):
            pass

        async def send_microphone(self, session):
            await asyncio.Event().wait()

    instance = Audio()
    monkeypatch.setattr("mac_audio.MacVoiceAudioIO", lambda *args, **kwargs: instance)
    events = [
        SimpleNamespace(type="audio", item_id="old", content_index=0, audio=SimpleNamespace(data=b"one")),
        SimpleNamespace(type="audio_interrupted", item_id="old", content_index=0),
        SimpleNamespace(type="audio", item_id="old", content_index=0, audio=SimpleNamespace(data=b"late")),
        SimpleNamespace(type="audio", item_id="new", content_index=0, audio=SimpleNamespace(data=b"next")),
        SimpleNamespace(type="audio_end", item_id="new", content_index=0),
    ]

    class Session:
        model = SimpleNamespace(send_event=AsyncMock())
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def __aiter__(self):
            for event in events:
                yield event

    class Runner:
        async def run(self, **kwargs):
            return Session()

    monkeypatch.setattr("main.create_voice_runner", lambda *args, **kwargs: Runner())
    args = SimpleNamespace(push_to_talk=False, input_device=None, output_device=None)
    await run_voice(None, Settings(), args)
    assert instance.clears == 1
    assert instance.played == [("old", b"one"), ("new", b"next")]


async def test_voice_exit_stops_worker_and_closes_audio_and_session(monkeypatch, desktop):
    class Audio:
        def __init__(self):
            self.tracker = object()
            self.closed = False
            self.sender_stopped = False

        def __enter__(self):
            return self

        def __exit__(self, *_):
            self.closed = True

        async def send_microphone(self, session):
            try:
                await asyncio.Event().wait()
            finally:
                self.sender_stopped = True

    audio = Audio()
    monkeypatch.setattr("mac_audio.MacVoiceAudioIO", lambda *args, **kwargs: audio)
    started = asyncio.Event()

    async def slow_run(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("main.Runner.run", slow_run)
    worker = ComputerWorker(desktop, Settings())
    work = asyncio.create_task(worker.perform("A task that is still running"))
    await started.wait()
    model = ScriptedRealtimeModel(strict=False)
    original_create = create_voice_runner
    monkeypatch.setattr(
        "main.create_voice_runner",
        lambda worker, settings, **kwargs: original_create(worker, settings, model=model, **kwargs),
    )
    args = SimpleNamespace(push_to_talk=False, input_device=None, output_device=None)
    task = asyncio.create_task(run_voice(worker, Settings(), args))
    try:
        async with asyncio.timeout(2):
            while not model.connect_calls:
                await asyncio.sleep(0)
            await model.emit(RealtimeModelToolCallEvent(
                name="exit_agent", call_id="exit_1", arguments="{}",
            ))
            await task
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if not work.done():
            work.cancel()
            await asyncio.gather(work, return_exceptions=True)
    assert "stopped" in await work
    assert worker.active is None
    assert desktop._stopped.is_set()
    assert audio.closed
    assert audio.sender_stopped
