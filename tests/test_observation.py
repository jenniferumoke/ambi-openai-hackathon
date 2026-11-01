import asyncio
import copy
import io
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx2
import pytest
from openai import AsyncOpenAI
from PIL import Image

from camera import CameraError, CameraFrame
from expression_monitor import (
    CUES, EMOTIONS, DecisionsClassifier, ExpressionState, InvalidObservation,
    Observation, ObservationMonitor, ObservationSettings, TemporalFilter, probability, run_observation, terminal_log,
)
from proactive_controller import ShadowController, TurnActivity, TurnContext


def decision_response():
    return {
        "model": "gpt-6-luna",
        "answers": [
            {"type": "predicate", "name": name, "probability": 0.95 if name in ("usable_face", "furrowed_brow") else 0.05}
            for name in ("usable_face", *CUES)
        ] + [{
            "type": "choice", "name": "apparent_emotion", "choice": "confused", "confidence": 0.94,
            "probabilities": [{"value": name, "probability": 0.94 if name == "confused" else 0.01} for name in EMOTIONS],
        }],
        "usage": {"input_tokens": 120, "output_tokens": 0, "total_tokens": 120,
                  "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                  "output_tokens_details": {"reasoning_tokens": 0}},
    }


def observation(at, emotion="confused", face=0.99, confidence=0.95, cues=None):
    return Observation(at, face, cues if cues is not None else {"furrowed_brow": 0.95}, emotion, confidence, confidence)


def stable_state(label="confused", start=0, expiry=10):
    return ExpressionState(label, ("furrowed_brow",), start, expiry)


async def test_real_decisions_sdk_sends_image_and_named_questions_to_correct_endpoint():
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx2.Response(200, json=decision_response())

    jpeg = io.BytesIO()
    Image.new("RGB", (64, 48), "white").save(jpeg, format="JPEG")
    async with AsyncOpenAI(api_key="offline-test-key", max_retries=0,
                           http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))) as client:
        result = await DecisionsClassifier(client).classify(CameraFrame(10, jpeg.getvalue()))

    assert len(requests) == 1
    assert requests[0].url.path == "/v1/decisions"
    body = json.loads(requests[0].content)
    assert body["model"] == "gpt-6-luna"
    assert body["input"][0]["content"][1]["image_url"].startswith("data:image/jpeg;base64,")
    assert {item["name"] for item in body["questions"]} == {"usable_face", *CUES, "apparent_emotion"}
    assert {item["value"] for item in body["questions"][-1]["choices"]} == set(EMOTIONS)
    assert result.emotion == "confused"
    assert result.cues["furrowed_brow"] == 0.95
    assert result.input_tokens == 120
    assert result.captured_at == 10


def invalid_decision(invalid):
    from openai.types.decision import Decision

    payload = copy.deepcopy(decision_response())
    if invalid == "refusal":
        payload["answers"][0] = {"type": "refusal", "name": "usable_face"}
    elif invalid == "missing":
        payload["answers"].pop(0)
    elif invalid == "duplicate":
        payload["answers"].append(payload["answers"][0])
    elif invalid == "nan":
        payload["answers"][0]["probability"] = float("nan")
    elif invalid == "out_of_range":
        payload["answers"][0]["probability"] = 1.5
    elif invalid == "unknown_label":
        payload["answers"][-1]["choice"] = "diagnosis"
    elif invalid == "partial_distribution":
        payload["answers"][-1]["probabilities"].pop()
    elif invalid == "sum_mismatch":
        payload["answers"][-1]["probabilities"][EMOTIONS.index("confused")]["probability"] = 0.91
    elif invalid == "inconsistent_choice":
        payload["answers"][-1]["choice"] = "happy"
    elif invalid == "duplicate_distribution":
        payload["answers"][-1]["probabilities"].append(payload["answers"][-1]["probabilities"][0])
    elif invalid == "unknown_distribution":
        payload["answers"][-1]["probabilities"][0]["value"] = "private-response-data"
    elif invalid == "predicate_type":
        payload["answers"][0] = copy.deepcopy(payload["answers"][-1])
        payload["answers"][0]["name"] = "usable_face"
    elif invalid == "emotion_type":
        payload["answers"][-1] = {"type": "predicate", "name": "apparent_emotion", "probability": 0.9}
    elif invalid == "confidence_nan":
        payload["answers"][-1]["confidence"] = float("nan")
    elif invalid == "distribution_nan":
        payload["answers"][-1]["probabilities"][0]["probability"] = float("nan")
    elif invalid == "unexpected_question":
        payload["answers"][0]["name"] = "private-response-data"
    elif invalid == "unrecognized_refusal":
        payload["answers"][0] = {"type": "refusal", "name": "private-response-data"}
    else:
        raise AssertionError(f"Unknown test case: {invalid}")
    # Actual SDK response objects, without serializing NaN through strict JSON.
    return Decision.model_validate(payload)


@pytest.mark.parametrize("invalid,reason,question,field", [
    ("refusal", "refused_answer", "usable_face", None),
    ("missing", "answer_names_mismatch", None, "answers"),
    ("duplicate", "duplicate_answer", "usable_face", None),
    ("nan", "non_finite_probability", "usable_face", "probability"),
    ("out_of_range", "probability_out_of_range", "usable_face", "probability"),
    ("unknown_label", "invalid_emotion_choice", "apparent_emotion", "choice"),
    ("partial_distribution", "incomplete_distribution", "apparent_emotion", "probabilities"),
    ("sum_mismatch", "distribution_sum_mismatch", "apparent_emotion", "probabilities"),
    ("inconsistent_choice", "inconsistent_emotion_choice", "apparent_emotion", "choice"),
    ("duplicate_distribution", "duplicate_distribution_label", "apparent_emotion", "probabilities"),
    ("unknown_distribution", "unknown_distribution_label", "apparent_emotion", "probabilities"),
    ("predicate_type", "unexpected_answer_type", "usable_face", "type"),
    ("emotion_type", "unexpected_answer_type", "apparent_emotion", "type"),
    ("confidence_nan", "non_finite_probability", "apparent_emotion", "confidence"),
    ("distribution_nan", "non_finite_probability", "apparent_emotion", "probabilities"),
    ("unexpected_question", "answer_names_mismatch", None, "answers"),
    ("unrecognized_refusal", "refused_answer", "unrecognized", None),
])
async def test_invalid_or_refused_decisions_explain_why_the_observation_was_rejected(invalid, reason, question, field):
    client = SimpleNamespace(decisions=SimpleNamespace(create=AsyncMock(return_value=invalid_decision(invalid))))
    with pytest.raises(InvalidObservation) as raised:
        await DecisionsClassifier(client).classify(CameraFrame(1, b"test-image"))
    details = raised.value.diagnostics()
    assert details["reason"] == reason
    assert details.get("question") == question
    assert details.get("field") == field
    assert details["message"]
    encoded = json.dumps(details, allow_nan=False)
    assert "private-response-data" not in encoded
    assert "test-image" not in encoded
    if invalid == "sum_mismatch":
        assert details["probability_sum"] == 0.97
        assert details["expected_sum"] == 1.0
        assert details["tolerance"] == 0.02
    elif invalid == "missing":
        assert details["missing_questions"] == ["usable_face"]
        assert details["unexpected_answer_count"] == 0
    elif invalid == "unexpected_question":
        assert details["missing_questions"] == ["usable_face"]
        assert details["unexpected_answer_count"] == 1
    elif invalid == "partial_distribution":
        assert details["missing_labels"] == ["uncertain"]
    elif invalid == "predicate_type":
        assert (details["expected_type"], details["received_type"]) == ("predicate", "choice")
    elif invalid == "emotion_type":
        assert (details["expected_type"], details["received_type"]) == ("choice", "predicate")


@pytest.mark.parametrize("value,reason", [
    ("private-response-data", "invalid_probability_type"),
    (True, "invalid_probability_type"),
    (None, "invalid_probability_type"),
    (float("inf"), "non_finite_probability"),
    (-0.1, "probability_out_of_range"),
])
def test_invalid_probability_diagnostics_include_field_without_echoing_untrusted_values(value, reason):
    with pytest.raises(InvalidObservation) as raised:
        probability(value, question="apparent_emotion", field="confidence")
    details = raised.value.diagnostics()
    assert details["reason"] == reason
    assert details["field"] == "confidence"
    assert "private-response-data" not in json.dumps(details, allow_nan=False)


async def test_diagnostics_preserve_existing_distribution_tolerance_and_detection_threshold():
    from openai.types.decision import Decision

    payload = decision_response()
    payload["answers"][-1]["probabilities"][0]["probability"] = 0.0  # Sum 0.99 remains within tolerance.
    client = SimpleNamespace(decisions=SimpleNamespace(create=AsyncMock(return_value=Decision.model_validate(payload))))
    result = await DecisionsClassifier(client).classify(CameraFrame(1, b"image"))
    assert result.emotion == "confused"
    assert ObservationSettings().threshold == 0.8


@pytest.mark.parametrize("invalid,reason", [
    ("sum_mismatch", "distribution_sum_mismatch"),
    ("unrecognized_refusal", "refused_answer"),
    ("unexpected_question", "answer_names_mismatch"),
])
async def test_terminal_logs_rejection_diagnostics_and_sequence_without_raw_data(capsys, invalid, reason):
    from time import monotonic

    rejected = asyncio.Event()

    def log(event, **fields):
        terminal_log(event, **fields)
        if event == "classification_unavailable":
            rejected.set()

    client = SimpleNamespace(decisions=SimpleNamespace(create=AsyncMock(return_value=invalid_decision(invalid))))
    monitor = ObservationMonitor(
        SimpleNamespace(capture=AsyncMock(side_effect=lambda: CameraFrame(monotonic(), b"private-image-data"))),
        DecisionsClassifier(client), ObservationSettings(), log=log,
    )
    monitor.filter.state = stable_state(expiry=monotonic() + 20)
    task = asyncio.create_task(monitor.run())
    try:
        async with asyncio.timeout(2):
            await rejected.wait()
        assert monitor.filter.state is None
        output = capsys.readouterr().out
        line = next(line for line in output.splitlines() if "classification_unavailable" in line)
        fields = json.loads(line.split("classification_unavailable ", 1)[1])
        assert fields["sequence"] == 1
        assert fields["error"] == "InvalidObservation"
        assert fields["reason"] == reason
        assert fields["http_status"] is None
        assert fields["latency_ms"] >= 0
        assert "private-image-data" not in output
        assert "private-response-data" not in output
        assert "data:image/" not in output
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_temporal_filter_requires_persistence_rejects_stale_and_clears_on_missing_face():
    state = TemporalFilter(ObservationSettings())
    assert state.observe(observation(0), 0) is None
    assert state.observe(observation(2, emotion="neutral"), 2) is None
    assert state.observe(observation(4), 4) is None
    stable = state.observe(observation(6), 6)
    assert stable.label == "confused"
    assert stable.started_at == 0
    # Neither an old response nor an out-of-order response refreshes the state.
    assert state.observe(observation(5), 7) == stable
    assert state.observe(observation(7), 20) is None
    for at in (21, 23, 25):
        state.observe(observation(at), at)
    assert state.current(25).label == "confused"
    assert state.observe(observation(26, face=0.1), 26) is None
    assert not state.samples


@pytest.mark.parametrize("kwargs", [{"confidence": 0.6}, {"emotion": "uncertain"}, {"cues": {}}])
def test_ambiguous_or_unsupported_emotion_does_not_stabilize(kwargs):
    state = TemporalFilter(ObservationSettings())
    for at in (0, 2, 4, 6, 8):
        assert state.observe(observation(at, **kwargs), at) is None


def test_controller_defers_rechecks_and_never_repeats_an_episode():
    controller = ShadowController(cooldown=60)
    state = stable_state()
    for field, expected in [
        ("user_speaking", "user_speaking"), ("response_active", "response_in_progress"),
        ("audio_playing", "speaker_audio_playing"), ("computer_busy", "computer_task_running"),
    ]:
        decision = controller.evaluate(state, 4, TurnContext(**{field: True}))
        assert (decision.action, decision.reason) == ("defer", expected)
    proposed = controller.evaluate(state, 5)
    assert proposed.action == "would_check_in"
    assert proposed.proposed_text == "Would a walkthrough help?"
    assert controller.evaluate(stable_state(expiry=200), 70).reason == "already_proposed_for_this_episode"
    new_episode = stable_state(start=10, expiry=100)
    assert controller.evaluate(new_episode, 20).reason == "cooldown"
    assert controller.evaluate(new_episode, 65).action == "would_check_in"


def test_deferred_expired_observation_is_discarded_and_positive_expression_needs_no_check_in():
    controller = ShadowController()
    state = stable_state()
    assert controller.evaluate(state, 9, TurnContext(user_speaking=True)).action == "defer"
    assert controller.evaluate(state, 10).action == "ignore"
    assert controller.evaluate(stable_state(label="happy"), 1).reason == "no_check_in_needed"


def test_turn_activity_tracks_raw_vad_and_generation_without_sending_anything():
    activity = TurnActivity()

    def emit(kind):
        activity.on_event(SimpleNamespace(type="raw_model_event", data=SimpleNamespace(
            type="raw_server_event", data={"type": kind},
        )))

    emit("input_audio_buffer.speech_started")
    assert activity.user_speaking
    emit("input_audio_buffer.speech_stopped")
    assert not activity.user_speaking and activity.response_active
    emit("response.done")
    assert not activity.response_active


async def test_timeout_clears_previous_state_and_cancellation_releases_monitor_tasks():
    blocked = asyncio.Event()

    async def classify(frame):
        await blocked.wait()

    import time
    camera = SimpleNamespace(capture=AsyncMock(side_effect=lambda: CameraFrame(time.monotonic(), b"private-frame")))
    settings = ObservationSettings(interval=0.5, ttl=2, request_timeout=0.1)
    logs = []
    unavailable = asyncio.Event()

    def log(event, **fields):
        logs.append((event, fields))
        if event == "classification_unavailable":
            unavailable.set()

    monitor = ObservationMonitor(camera, SimpleNamespace(classify=classify), settings, log=log)
    monitor.filter.state = stable_state(expiry=time.monotonic() + 10)
    task = asyncio.create_task(monitor.run())
    try:
        async with asyncio.timeout(2):
            await unavailable.wait()
        assert monitor.filter.state is None
        assert camera.capture.await_count == 1
        assert "private-frame" not in str(logs)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_supervisor_closes_camera_and_logs_no_api_body_on_access_failure(monkeypatch):
    closed = asyncio.Event()

    class Camera:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            closed.set()

        async def capture(self):
            import time
            return CameraFrame(time.monotonic(), b"private-frame")

    monkeypatch.setattr("expression_monitor.MacCamera", lambda _: Camera())
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx2.Response(403, json={"error": {"message": "private-frame secret-api-key", "type": "forbidden"}})

    client = AsyncOpenAI(api_key="offline-test-key", max_retries=0,
                         http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))
    monkeypatch.setattr("expression_monitor.AsyncOpenAI", lambda **_: client)
    logs = []
    await run_observation(ObservationSettings(), log=lambda event, **fields: logs.append((event, fields)))
    assert closed.is_set()
    assert len(requests) == 1
    assert any(event == "disabled" for event, _ in logs)
    assert logs[-1][0] == "stopped"
    assert "private-frame" not in str(logs) and "secret-api-key" not in str(logs)


async def test_camera_start_failure_is_contained(monkeypatch):
    class Denied:
        async def __aenter__(self):
            raise CameraError("Camera access denied.")

        async def __aexit__(self, *_):
            pass

    monkeypatch.setattr("expression_monitor.MacCamera", lambda _: Denied())
    logs = []
    await run_observation(ObservationSettings(), log=lambda event, **fields: logs.append((event, fields)))
    assert [event for event, _ in logs] == ["starting", "disabled", "stopped"]


@pytest.mark.parametrize("kwargs", [{"interval": 0}, {"threshold": float("nan")}, {"ttl": 1}, {"ttl": 4}, {"request_timeout": 0}])
def test_invalid_observation_settings_are_rejected(kwargs):
    with pytest.raises(ValueError):
        ObservationSettings(**kwargs)


@pytest.mark.parametrize("unusable", ["face", "expired"])
async def test_unusable_frame_clears_state_and_does_not_publish_an_emotion(monkeypatch, unusable):
    now = [0.0]
    monkeypatch.setattr("expression_monitor.monotonic", lambda: now[0])
    logged = asyncio.Event()
    logs = []

    def log(event, **fields):
        logs.append((event, fields))
        if event in ("sample", "sample_discarded"):
            logged.set()

    async def classify(frame):
        now[0] = 12 if unusable == "expired" else 1
        return observation(frame.captured_at, face=0.1 if unusable == "face" else 0.99)

    monitor = ObservationMonitor(
        SimpleNamespace(capture=AsyncMock(return_value=CameraFrame(0, b"private-image"))),
        SimpleNamespace(classify=classify), ObservationSettings(), log=log,
    )
    monitor.filter.state = stable_state(expiry=20)
    task = asyncio.create_task(monitor.run())
    try:
        async with asyncio.timeout(2):
            await logged.wait()
        assert monitor.filter.state is None
        if unusable == "face":
            fields = next(fields for event, fields in logs if event == "sample")
            assert fields["possible_emotion"] == "unavailable"
            assert fields["cues"] == {}
        else:
            assert any(event == "sample_discarded" for event, _ in logs)
            assert not any(event == "sample" for event, _ in logs)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_transient_classifier_failure_retries_and_recovers():
    from time import monotonic

    recovered = asyncio.Event()
    logs = []
    attempts = 0

    async def classify(frame):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("private request data must not be logged")
        return observation(frame.captured_at)

    def log(event, **fields):
        logs.append((event, fields))
        if event == "sample":
            recovered.set()

    monitor = ObservationMonitor(
        SimpleNamespace(capture=AsyncMock(side_effect=lambda: CameraFrame(monotonic(), b"image"))),
        SimpleNamespace(classify=classify), ObservationSettings(interval=0.5, ttl=2), log=log,
    )
    task = asyncio.create_task(monitor.run())
    try:
        async with asyncio.timeout(3):
            await recovered.wait()
        assert attempts == 2
        assert monitor.requests == 2
        assert len(monitor.filter.samples) == 1
        assert "private request data" not in str(logs)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
