"""Replay the failure modes from the Oct 31 live run without hardware/network."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx2
import pytest
from openai import AsyncOpenAI

from camera import CameraFrame
from expression_monitor import DecisionsClassifier, ObservationMonitor, ObservationSettings
from observation_hub import ObservationHub
from proactive_controller import TurnActivity, TurnContext
from proactive_voice import NotificationPolicy
from screen_observer import ScreenAnalyzer, ScreenObservationSettings
from test_agent import response
from test_observation import decision_response
from test_screen_observer import description, frame
from voice_input import SpeechGate
from voice_realtime import SpeechConfirmedRealtimeModel
from proactive_realtime import ProactiveRealtimeModel


async def test_rejected_audio_delete_uses_real_sdk_wire_format():
    from agents.realtime.openai_realtime import OpenAIRealtimeWebSocketModel
    model = OpenAIRealtimeWebSocketModel()
    sent = []

    async def send(payload):
        sent.append(json.loads(payload))

    model._websocket = SimpleNamespace(send=send)
    gate = SpeechGate(TurnActivity(confirmed_input_only=True), log=lambda *args, **kwargs: None)
    await gate.on_event({"type": "conversation.item.input_audio_transcription.completed", "item_id": "noise", "transcript": ""},
                        SimpleNamespace(model=model), SimpleNamespace(clear=Mock()))
    assert sent == [{"type": "conversation.item.delete", "item_id": "noise"}]


@pytest.mark.parametrize("model_type", [SpeechConfirmedRealtimeModel, ProactiveRealtimeModel])
async def test_real_sdk_does_not_interrupt_playback_until_speech_is_confirmed(model_type):
    from agents.realtime import RealtimeModelSendInterrupt
    model = model_type()
    sent = []

    async def send(payload):
        sent.append(json.loads(payload))

    model._websocket = SimpleNamespace(send=send)
    model._emit_event = AsyncMock()
    model._ongoing_response = True
    model._audio_state_tracker.on_audio_delta("reply", 0, bytes(48000), response_id="response")
    model._playback_tracker = SimpleNamespace(
        get_state=lambda: {"current_item_id": "reply", "current_item_content_index": 0, "elapsed_ms": 200},
        on_interrupted=Mock(),
    )
    vad = {"type": "input_audio_buffer.speech_started", "event_id": "vad", "item_id": "tap", "audio_start_ms": 1000}
    await model._handle_ws_event(vad)
    assert not sent
    assert [call.args[0].type for call in model._emit_event.await_args_list] == ["raw_server_event"]
    assert model._audio_state_tracker.get_last_audio_item() == ("reply", 0)
    model._playback_tracker.on_interrupted.assert_not_called()
    # SpeechGate invokes this only after recognizing an actual spoken turn.
    await model.send_event(RealtimeModelSendInterrupt())
    assert {event["type"] for event in sent} == {"conversation.item.truncate", "response.cancel"}
    assert any(call.args[0].type == "audio_interrupted" for call in model._emit_event.await_args_list)
    model._playback_tracker.on_interrupted.assert_called_once()


@pytest.mark.parametrize("transcript,logprobs", [
    ("", []), ("...", []), ("[keyboard tapping]", []), ("(background noise)", []),
    ("Hello", [{"logprob": -3.2}]),
])
async def test_noise_does_not_speak_interrupt_or_invalidate_observations(transcript, logprobs):
    activity = TurnActivity(confirmed_input_only=True)
    session = SimpleNamespace(model=SimpleNamespace(send_event=AsyncMock()), interrupt=AsyncMock())
    audio = SimpleNamespace(clear=Mock())
    gate = SpeechGate(activity, log=lambda *args, **kwargs: None)
    for kind in ("speech_started", "speech_stopped"):
        await gate.on_event({"type": "input_audio_buffer." + kind, "item_id": "tap"}, session, audio)
    assert activity.user_speaking and activity.user_turn_generation == 0
    await gate.on_event({"type": "conversation.item.input_audio_transcription.completed", "item_id": "tap",
                         "transcript": transcript, "logprobs": logprobs}, session, audio)
    assert not activity.user_speaking and not activity.response_active
    assert activity.last_user_activity == 0 and activity.user_turn_generation == 0
    session.interrupt.assert_not_awaited()
    audio.clear.assert_not_called()
    assert [call.args[0].message["type"] for call in session.model.send_event.await_args_list] == ["conversation.item.delete"]


@pytest.mark.parametrize("words", ["Stop", "Yes", "Bye", "Inspect the Python error"])
async def test_short_valid_commands_create_one_response_and_can_interrupt(words):
    activity = TurnActivity(confirmed_input_only=True)
    session = SimpleNamespace(model=SimpleNamespace(send_event=AsyncMock()), interrupt=AsyncMock())
    audio = SimpleNamespace(clear=Mock())
    gate = SpeechGate(activity, log=lambda *args, **kwargs: None)
    raw = {"type": "conversation.item.input_audio_transcription.completed", "item_id": "speech", "transcript": words,
           "logprobs": [{"logprob": -0.1}]}
    await gate.on_event(raw, session, audio)
    await gate.on_event(raw, session, audio)  # Duplicate delivery must not greet/respond twice.
    session.interrupt.assert_awaited_once()
    assert activity.user_turn_generation == 1 and activity.last_user_activity > 0
    assert session.model.send_event.await_args.args[0].message == {"type": "response.create"}
    session.model.send_event.assert_awaited_once()


@pytest.mark.parametrize("second_transcript,accepted_count", [("Inspect the error", 2), ("", 1)])
async def test_reply_waits_for_a_subsequent_pending_utterance(second_transcript, accepted_count):
    activity = TurnActivity(confirmed_input_only=True)
    session = SimpleNamespace(model=SimpleNamespace(send_event=AsyncMock()), interrupt=AsyncMock())
    audio = SimpleNamespace(clear=Mock())
    gate = SpeechGate(activity, log=lambda *args, **kwargs: None)
    await gate.on_event({"type": "input_audio_buffer.speech_stopped", "item_id": "first"}, session, audio)
    await gate.on_event({"type": "input_audio_buffer.speech_started", "item_id": "second"}, session, audio)
    await gate.on_event({"type": "conversation.item.input_audio_transcription.completed", "item_id": "first",
                         "transcript": "Yes"}, session, audio)
    session.interrupt.assert_not_awaited()
    assert activity.user_speaking
    await gate.on_event({"type": "conversation.item.input_audio_transcription.completed", "item_id": "second",
                         "transcript": second_transcript}, session, audio)
    assert not activity.user_speaking and activity.user_turn_generation == accepted_count
    assert [call.args[0].message["type"] for call in session.model.send_event.await_args_list].count("response.create") == 1
    session.interrupt.assert_awaited_once()


async def test_missing_transcription_expires_without_blocking_proactive_voice(monkeypatch):
    now = [100]
    monkeypatch.setattr("voice_input.monotonic", lambda: now[0])
    activity = TurnActivity(confirmed_input_only=True)
    session = SimpleNamespace(model=SimpleNamespace(send_event=AsyncMock()), interrupt=AsyncMock())
    audio = SimpleNamespace(clear=Mock())
    gate = SpeechGate(activity, log=lambda *args, **kwargs: None)
    await gate.on_event({"type": "input_audio_buffer.speech_stopped", "item_id": "noise"}, session, audio)
    now[0] = 113
    task = asyncio.create_task(gate.maintain(session, audio))
    try:
        async with asyncio.timeout(1):
            while activity.user_speaking:
                await asyncio.sleep(0)
        assert activity.user_turn_generation == 0
        # A late transcript cannot resurrect a discarded turn.
        await gate.on_event({"type": "conversation.item.input_audio_transcription.completed", "item_id": "noise",
                             "transcript": "Hello"}, session, audio)
        session.interrupt.assert_not_awaited()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_frowning_refusal_does_not_erase_independently_answered_brow_cues():
    async def handler(request):
        payload = decision_response()
        payload["answers"] = [{"type": "refusal", "name": "frowning"} if item["name"] == "frowning" else item
                              for item in payload["answers"]]
        return httpx2.Response(200, json=payload)

    hub = ObservationHub()
    monitor = ObservationMonitor(None, None, ObservationSettings(), hub=hub)
    async with AsyncOpenAI(api_key="offline", max_retries=0,
                           http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))) as client:
        classifier = DecisionsClassifier(client)
        for at in (100, 102, 104):
            result = await classifier.classify(CameraFrame(at, b"synthetic"))
            assert "frowning" not in result.cues and result.unavailable_questions == ("frowning",)
            monitor.cue_filter.forget(result.unavailable_questions)
            monitor.cue_filter.observe(result, at)
            monitor._publish_camera(at)
            if at < 104:
                assert hub.snapshot(now=at)["camera"]["status"] != "available"
    payload = hub.snapshot(now=104)["camera"]["payload"]
    assert payload["cues"] == ["furrowed_brow"]
    assert monitor.settings.threshold == 0.8 and monitor.settings.ttl == 10
    assert hub.snapshot(now=114)["camera"]["status"] == "unavailable"


@pytest.mark.parametrize("failure", ["The test returned None instead of the expected pair of indices.",
                                    "The test call cannot run because brackets do not match."])
async def test_task_failure_can_offer_help_without_camera_and_survives_model_latency(failure):
    async def handler(request):
        observation = description().model_copy(update={
            "task_goal": "Find two indices whose values add to the target.",
            "expected_result": "A matching pair of indices.", "actual_result": "None",
            "task_failure": failure, "noteworthy": False, "progress": "in_progress",
        })
        return httpx2.Response(200, json=response([{
            "id": "msg_1", "type": "message", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": observation.model_dump_json(), "annotations": []}],
        }], 1))

    async with AsyncOpenAI(api_key="offline", max_retries=0,
                           http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))) as client:
        result = await ScreenAnalyzer(client, ScreenObservationSettings()).analyze(frame(100))
    assert result.noteworthy and result.progress == "blocked"
    hub = ObservationHub(["computer"])
    hub.publish("computer", observed_at=100, expires_at=120, payload=result.model_dump(), now=109.3)
    policy = NotificationPolicy()
    assert policy.candidate(hub.snapshot(now=111), TurnContext(), 111) is not None
    assert policy.candidate(hub.snapshot(now=119), TurnContext(), 119) is not None
    assert policy.candidate(hub.snapshot(now=120), TurnContext(), 120) is None
