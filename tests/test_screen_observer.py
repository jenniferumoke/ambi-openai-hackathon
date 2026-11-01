import asyncio
import io
import json
import os
import platform
from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx2
import pytest
from openai import AsyncOpenAI
from PIL import Image
from pydantic import ValidationError

from observation_hub import ObservationHub
from proactive_controller import TurnContext
from screen_capture import ReadOnlyScreenCapture, ScreenCaptureError, ScreenContextChanged, ScreenFrame, encode_screen_image
from screen_observer import ComputerObservation, ScreenAnalyzer, ScreenObservationSettings, ScreenObserver, run_screen_observation
from test_agent import response


def description():
    return ComputerObservation(visible_activity="Editing Python with a terminal error visible.",
                               task_hypothesis="Possibly debugging a program.", evidence=["An error is visible in the terminal."],
                               possible_blocker="A Python error may need attention.", confidence=0.9,
                               surface="user_task", progress="in_progress", noteworthy=False, notification=None)


def frame(at=None, data=b"synthetic-image", context_id="window-a"):
    return ScreenFrame(monotonic() if at is None else at, data, "Editor", context_id)


async def test_real_sdk_sends_structured_vision_request_with_no_action_tools():
    requests = []

    async def handler(request):
        requests.append(json.loads(request.content))
        output = [{"id": "msg_1", "type": "message", "role": "assistant", "status": "completed",
                   "content": [{"type": "output_text", "text": description().model_dump_json(), "annotations": []}]}]
        return httpx2.Response(200, json=response(output, 1))

    async with AsyncOpenAI(api_key="offline-test-key", max_retries=0,
                           http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))) as client:
        analyzer = ScreenAnalyzer(client, ScreenObservationSettings())
        result = await analyzer.analyze(frame())
    assert result == description()
    assert len(requests) == 1
    body = requests[0]
    assert body["model"] == "gpt-6.1-terra"
    assert body["store"] is False
    assert body["tools"] == []
    assert body["text"]["format"]["type"] == "json_schema"
    assert body["text"]["format"]["strict"] is True
    assert body["input"][0]["content"][1]["image_url"].startswith("data:image/jpeg;base64,")
    assert analyzer.agent.handoffs == []


async def test_observer_agent_compares_recent_task_evidence_and_resets_when_window_changes():
    requests = []

    async def handler(request):
        requests.append(json.loads(request.content))
        output = [{"id": f"msg_{len(requests)}", "type": "message", "role": "assistant", "status": "completed",
                   "content": [{"type": "output_text", "text": description().model_dump_json(), "annotations": []}]}]
        return httpx2.Response(200, json=response(output, len(requests)))

    async with AsyncOpenAI(api_key="offline-test-key", max_retries=0,
                           http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))) as client:
        analyzer = ScreenAnalyzer(client, ScreenObservationSettings())
        await analyzer.analyze(frame(0))
        await analyzer.analyze(frame(25))
        second = json.loads(requests[1]["input"][0]["content"][0]["text"])
        assert len(second["recent_task_history"]) == 1
        prior = second["recent_task_history"][0]
        assert prior["age_seconds"] == 25
        assert prior["evidence"] == description().evidence
        assert "notification" not in prior and "noteworthy" not in prior
        assert analyzer.history_span_seconds == 25
        await analyzer.analyze(frame(30, context_id="other-window"))
        third = json.loads(requests[2]["input"][0]["content"][0]["text"])
        assert third["recent_task_history"] == []
        assert len(analyzer.history) == 1


def test_native_window_metadata_follows_windowserver_instead_of_cached_terminal(monkeypatch):
    import sys

    windows = [[{"pid": 1, "id": 10, "name": "observer", "owner": "Terminal", "layer": 0,
                 "bounds": {"X": 0, "Y": 0, "Width": 800, "Height": 600}}]]
    quartz = SimpleNamespace(
        kCGWindowListOptionOnScreenOnly=1, kCGWindowListExcludeDesktopElements=16, kCGNullWindowID=0,
        kCGWindowOwnerPID="pid", kCGWindowNumber="id", kCGWindowName="name", kCGWindowOwnerName="owner",
        kCGWindowLayer="layer", kCGWindowAlpha="alpha", kCGWindowBounds="bounds", CGMainDisplayID=lambda: 0,
        CGWindowListCopyWindowInfo=lambda *_: windows[0],
        CGDisplayBounds=lambda _: SimpleNamespace(origin=SimpleNamespace(x=0, y=0), size=SimpleNamespace(width=1000, height=800)),
    )
    monkeypatch.setitem(sys.modules, "Quartz", quartz)
    monkeypatch.setattr("screen_capture.platform.system", lambda: "Darwin")
    capture = ReadOnlyScreenCapture()
    first_app, first_id = capture._context()
    windows[0] = [
        {"pid": 2, "id": 20, "name": "offscreen", "owner": "Other Display", "layer": 0,
         "bounds": {"X": -2000, "Y": 0, "Width": 1000, "Height": 800}},
        {"pid": 3, "id": 30, "name": "editor", "owner": "Edge", "layer": 0,
         "bounds": {"X": 0, "Y": 0, "Width": 800, "Height": 600}},
    ]
    second_app, second_id = capture._context()
    assert (first_app, second_app) == ("Terminal", "Edge")
    assert first_id != second_id


@pytest.mark.parametrize("field,value", [("confidence", float("nan")), ("confidence", 1.1),
                                         ("visible_activity", "x" * 241), ("evidence", ["x"] * 5),
                                         ("evidence", ["x" * 161])])
def test_invalid_screen_descriptions_are_rejected(field, value):
    data = description().model_dump()
    data[field] = value
    with pytest.raises(ValidationError):
        ComputerObservation.model_validate(data)


async def test_observer_skips_identical_frames_only_until_cached_result_expires(monkeypatch):
    now = [0.0]
    monkeypatch.setattr("screen_observer.monotonic", lambda: now[0])
    hub = ObservationHub(["computer"])
    samples = 0
    refreshed = asyncio.Event()
    analyzer = SimpleNamespace(analyze=AsyncMock(return_value=description()))
    capture = SimpleNamespace(capture=AsyncMock(side_effect=lambda: frame(now[0])),
                              context_id=AsyncMock(return_value="window-a"))

    def log(event, **fields):
        nonlocal samples
        if event == "screen_sample":
            samples += 1
            if samples == 2:
                refreshed.set()
        if event == "screen_unchanged":
            now[0] = 3

    observer = ScreenObserver(capture, analyzer, ScreenObservationSettings(interval=0.5, ttl=2), hub, log=log)
    task = asyncio.create_task(observer.run())
    try:
        async with asyncio.timeout(3):
            await refreshed.wait()
        assert analyzer.analyze.await_count == 2
        assert observer.skipped == 1
        assert hub.snapshot(now=3)["computer"]["observed_at"] == 3
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_identical_new_capture_refreshes_pair_alignment_without_a_model_call(monkeypatch):
    now = [100.0]
    monkeypatch.setattr("screen_observer.monotonic", lambda: now[0])
    hub = ObservationHub()
    refreshed = asyncio.Event()
    analyzer = SimpleNamespace(analyze=AsyncMock(return_value=description()))
    capture = SimpleNamespace(capture=AsyncMock(side_effect=lambda: frame(now[0])),
                              context_id=AsyncMock(return_value="window-a"))

    def log(event, **_):
        if event == "screen_sample":
            now[0] = 110
            hub.publish("camera", observed_at=110, expires_at=112, payload={}, now=110)
        elif event == "screen_unchanged":
            refreshed.set()

    observer = ScreenObserver(capture, analyzer, ScreenObservationSettings(interval=.5), hub, log=log)
    task = asyncio.create_task(observer.run())
    try:
        async with asyncio.timeout(2):
            await refreshed.wait()
        snapshot = hub.snapshot(now=110)
        assert snapshot["pair"]["aligned"]
        assert snapshot["computer"]["observed_at"] == 110
        assert snapshot["computer"]["expires_at"] == 130
        assert observer._valid_until == 120  # Periodic reanalysis is still bounded.
        analyzer.analyze.assert_awaited_once()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_changed_screen_clears_old_blocker_before_waiting_for_analysis():
    hub = ObservationHub()
    checked = asyncio.Event()
    samples = 0
    async def capture():
        nonlocal samples
        samples += 1
        return frame(data=f"pixels-{samples}".encode())
    async def analyze(_):
        if samples == 2:
            snapshot = hub.snapshot()["computer"]
            assert snapshot["status"] == "unavailable"
            assert snapshot["reason"] == "screen_changed"
            assert "payload" not in snapshot
            checked.set()
        return description()
    observer = ScreenObserver(SimpleNamespace(capture=capture, context_id=AsyncMock(return_value="window-a")),
                              SimpleNamespace(analyze=analyze), ScreenObservationSettings(interval=.5), hub,
                              log=lambda *args, **kwargs: None)
    task = asyncio.create_task(observer.run())
    try:
        async with asyncio.timeout(2):
            await checked.wait()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("change", ["window", "worker", "expired"])
async def test_inflight_analysis_is_discarded_when_its_context_or_freshness_changes(monkeypatch, change):
    now = [0.0]
    generation = [0]
    monkeypatch.setattr("screen_observer.monotonic", lambda: now[0])
    hub = ObservationHub(["computer"])
    discarded = asyncio.Event()

    async def analyze(_):
        if change == "worker":
            generation[0] = 1  # A task started and finished while analysis was in flight.
        if change == "expired":
            now[0] = 30
        return description()

    capture = SimpleNamespace(capture=AsyncMock(return_value=frame(0)),
                              context_id=AsyncMock(return_value="window-b" if change == "window" else "window-a"))
    observer = ScreenObserver(capture, SimpleNamespace(analyze=analyze), ScreenObservationSettings(), hub,
                              context=lambda: TurnContext(computer_generation=generation[0]),
                              log=lambda event, **_: discarded.set() if event == "screen_discarded" else None)
    task = asyncio.create_task(observer.run())
    try:
        async with asyncio.timeout(1):
            await discarded.wait()
        assert hub.snapshot(now=now[0])["computer"]["status"] == "unavailable"
        assert "payload" not in hub.snapshot(now=now[0])["computer"]
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_computer_worker_pauses_capture_and_resuming_reanalyzes_even_identical_frame():
    busy = [True]
    sampled = asyncio.Event()
    capture = SimpleNamespace(capture=AsyncMock(side_effect=lambda: frame()), context_id=AsyncMock(return_value="window-a"))
    analyzer = SimpleNamespace(analyze=AsyncMock(return_value=description()))
    hub = ObservationHub(["computer"])

    def log(event, **_):
        if event == "screen_paused":
            capture.capture.assert_not_awaited()
            busy[0] = False
        elif event == "screen_sample":
            sampled.set()

    observer = ScreenObserver(capture, analyzer, ScreenObservationSettings(interval=0.5, ttl=2), hub,
                              context=lambda: TurnContext(computer_busy=busy[0]), log=log)
    observer._last_fingerprint = frame().fingerprint
    observer._last_generation = 0
    observer._valid_until = monotonic() + 20
    task = asyncio.create_task(observer.run())
    try:
        async with asyncio.timeout(2):
            await sampled.wait()
        analyzer.analyze.assert_awaited_once()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_short_worker_task_between_samples_invalidates_the_cached_interpretation():
    generation = [0]
    samples = 0
    refreshed = asyncio.Event()
    capture = SimpleNamespace(capture=AsyncMock(side_effect=lambda: frame()), context_id=AsyncMock(return_value="window-a"))
    analyzer = SimpleNamespace(analyze=AsyncMock(return_value=description()))

    def log(event, **_):
        nonlocal samples
        if event == "screen_sample":
            samples += 1
            generation[0] = 1
            if samples == 2:
                refreshed.set()

    observer = ScreenObserver(capture, analyzer, ScreenObservationSettings(interval=0.5, ttl=2), ObservationHub(["computer"]),
                              context=lambda: TurnContext(computer_generation=generation[0]), log=log)
    task = asyncio.create_task(observer.run())
    try:
        async with asyncio.timeout(2):
            await refreshed.wait()
        assert analyzer.analyze.await_count == 2
        assert observer.skipped == 0
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_screen_analysis_timeout_clears_context_and_cancels_the_request():
    cancelled = asyncio.Event()
    unavailable = asyncio.Event()
    hub = ObservationHub(["computer"])
    hub.publish("computer", observed_at=monotonic(), expires_at=monotonic() + 20, payload={"old": True})

    async def analyze(_):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    observer = ScreenObserver(
        SimpleNamespace(capture=AsyncMock(side_effect=lambda: frame()), context_id=AsyncMock()),
        SimpleNamespace(analyze=analyze), ScreenObservationSettings(interval=0.5, ttl=2, request_timeout=0.1), hub,
        log=lambda event, **_: unavailable.set() if event == "screen_analysis_unavailable" else None,
    )
    task = asyncio.create_task(observer.run())
    try:
        async with asyncio.timeout(2):
            await unavailable.wait()
        assert cancelled.is_set()
        assert hub.snapshot()["computer"]["status"] == "unavailable"
        assert observer.requests == 1
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_access_failure_closes_capture_clears_hub_and_does_not_log_api_body(monkeypatch):
    closed = asyncio.Event()

    class Capture:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            closed.set()

        async def capture(self):
            return frame()

    async def handler(request):
        return httpx2.Response(403, json={"error": {"message": "private-request-body secret-token", "type": "forbidden"}})

    client = AsyncOpenAI(api_key="offline-test-key", max_retries=0,
                         http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))
    monkeypatch.setattr("screen_observer.AsyncOpenAI", lambda **_: client)
    monkeypatch.setattr("screen_observer.ReadOnlyScreenCapture", Capture)
    hub = ObservationHub(["computer"])
    logs = []
    await run_screen_observation(ScreenObservationSettings(), hub, log=lambda event, **fields: logs.append((event, fields)))
    assert closed.is_set()
    assert hub.snapshot()["computer"]["status"] == "disabled"
    assert logs[-1][0] == "screen_stopped"
    assert "private-request-body" not in str(logs) and "secret-token" not in str(logs)


@pytest.mark.parametrize("changed", [False, True])
async def test_native_capture_uses_no_worker_lifecycle_and_detects_window_changes(monkeypatch, changed):
    import sys

    monkeypatch.setattr("screen_capture.platform.system", lambda: "Darwin")
    quartz = SimpleNamespace(CGPreflightScreenCaptureAccess=lambda: True, CGMainDisplayID=lambda: 0,
                             CGDisplayCreateImage=Mock(return_value=object()))
    monkeypatch.setitem(sys.modules, "Quartz", quartz)
    monkeypatch.setattr("screen_capture.encode_screen_image", lambda _: b"image")
    capture = ReadOnlyScreenCapture()
    monkeypatch.setattr(capture, "_context", Mock(side_effect=[("Editor", "a"), ("Editor", "b" if changed else "a")]))
    async with capture:
        if changed:
            with pytest.raises(ScreenContextChanged):
                await capture.capture()
        else:
            result = await capture.capture()
            assert (result.application, result.context_id) == ("Editor", "a")
    quartz.CGDisplayCreateImage.assert_called_once_with(0)
    assert capture._closed.is_set()


async def test_screen_permission_denial_never_attempts_capture(monkeypatch):
    import sys

    monkeypatch.setattr("screen_capture.platform.system", lambda: "Darwin")
    quartz = SimpleNamespace(CGPreflightScreenCaptureAccess=lambda: False, CGDisplayCreateImage=Mock())
    monkeypatch.setitem(sys.modules, "Quartz", quartz)
    async with ReadOnlyScreenCapture() as capture:
        with pytest.raises(ScreenCaptureError, match="Screen Recording"):
            await capture.capture()
    quartz.CGDisplayCreateImage.assert_not_called()


@pytest.mark.skipif(platform.system() != "Darwin", reason="Uses native image encoding; does not capture the screen")
def test_native_in_memory_encoding_with_synthetic_image():
    import Quartz as q

    width, height = 2000, 1000
    rgba = Image.new("RGBA", (width, height), "white").tobytes()
    provider = q.CGDataProviderCreateWithData(None, rgba, len(rgba), None)
    native = q.CGImageCreate(width, height, 8, 32, width * 4, q.CGColorSpaceCreateDeviceRGB(),
                            q.kCGImageAlphaLast, provider, None, False, q.kCGRenderingIntentDefault)
    data = encode_screen_image(native)
    with Image.open(io.BytesIO(data)) as image:
        assert image.format == "JPEG"
        assert image.size == (1600, 800)
        assert not image.getexif()


@pytest.mark.skipif(platform.system() != "Darwin", reason="Uses native window metadata; does not capture the screen")
async def test_native_window_identity_can_be_read_off_the_audio_event_loop():
    async with ReadOnlyScreenCapture() as capture:
        async with asyncio.timeout(3):
            identity = await capture.context_id()
        assert identity == "unknown" or len(identity) == 20


@pytest.mark.skipif(platform.system() != "Darwin" or os.getenv("RUN_SCREEN_TESTS") != "1",
                    reason="Opt-in local screen test; set RUN_SCREEN_TESTS=1 (no upload or recording)")
async def test_live_screen_capture_is_local_and_read_only():
    import Quartz as q

    if not q.CGPreflightScreenCaptureAccess():
        pytest.skip("Grant Screen Recording to the launching terminal, then restart it.")
    async with ReadOnlyScreenCapture() as capture:
        result = await capture.capture()
        with Image.open(io.BytesIO(result.jpeg)) as image:
            assert max(image.size) <= 1600
