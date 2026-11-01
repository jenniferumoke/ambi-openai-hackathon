"""Late spoken-interruption cancellations must not end a healthy session."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from agents.realtime.model_inputs import RealtimeModelSendRawMessage

from main import RealtimeSessionError, handle_realtime_events
from voice_realtime import SpeechConfirmedRealtimeModel


@pytest.mark.parametrize("as_object", [False, True])
async def test_finished_reply_cancellation_is_logged_and_next_reply_still_plays(as_object, capsys):
    error = {"code": "response_cancel_not_active", "message": "private-provider-payload"}
    if as_object:
        error = SimpleNamespace(**error)
    async def events():
        yield SimpleNamespace(type="error", error=error)
        yield SimpleNamespace(type="audio", item_id="next", content_index=0,
                              audio=SimpleNamespace(data=b"\x01\x00"))
        yield SimpleNamespace(type="audio_end", item_id="next", content_index=0)
    audio = SimpleNamespace(play=Mock(), finish=Mock(), clear=Mock())
    log = Mock()
    await handle_realtime_events(events(), audio, log=log)
    audio.play.assert_called_once_with(b"\x01\x00", "next", 0)
    audio.finish.assert_called_once_with("next", 0)
    audio.clear.assert_not_called()
    assert log.call_args.args == ("realtime_warning",)
    assert log.call_args.kwargs["code"] == "response_cancel_not_active"
    assert "private-provider-payload" not in str(log.call_args)
    assert "private-provider-payload" not in capsys.readouterr().out


@pytest.mark.parametrize("code", ["invalid_api_key", "insufficient_quota", "server_error", "unknown"])
async def test_other_errors_are_not_silenced(code):
    async def events():
        yield SimpleNamespace(type="error", error={"code": code, "message": "private-provider-payload"})
    with pytest.raises(RealtimeSessionError) as failure:
        await handle_realtime_events(events(), SimpleNamespace())
    assert "private-provider-payload" not in str(failure.value)


async def test_late_cancel_targets_original_reply_and_cannot_release_a_newer_turn():
    model = SpeechConfirmedRealtimeModel()
    sent = []
    async def send(payload):
        sent.append(json.loads(payload))
    model._websocket = SimpleNamespace(send=send)
    model._emit_event = AsyncMock()
    await model._mark_response_created("old-response")
    await model._cancel_response()
    assert sent == [{"type": "response.cancel", "response_id": "old-response"}]
    await model._mark_response_done("old-response")
    await model._mark_response_created("new-response")
    await model._handle_ws_event({"type": "error", "event_id": "late-cancel", "error": {
        "type": "invalid_request_error", "code": "response_cancel_not_active",
        "message": "Cancellation failed: no active response found", "event_id": None,
    }})
    assert model._ongoing_response
    assert model._response_create_sequencer.ongoing_response_id == "new-response"
    # Only its own completion releases the sequencer for the next user reply.
    await model._mark_response_done("new-response")
    await model.send_event(RealtimeModelSendRawMessage(message={"type": "response.create"}))
    import asyncio
    async with asyncio.timeout(1):
        while not any(event["type"] == "response.create" for event in sent):
            await asyncio.sleep(0)
    await model._cancel_response_create_tasks()
