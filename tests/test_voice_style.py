"""Offline delivery selection, real transport payloads, and PCM playback checks."""
import asyncio
import json
import struct
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agents.realtime.model_events import RealtimeModelAudioEvent
from agents.realtime.model_inputs import RealtimeModelSendRawMessage
from openai.types.realtime import ResponseCreateEvent, SessionUpdateEvent

from main import Settings, VOICE_INSTRUCTIONS, create_voice_runner
from proactive_realtime import PROACTIVE_INSTRUCTIONS, ProactiveRealtimeModel
from voice_realtime import SpeechConfirmedRealtimeModel
from voice_style import STYLES, soften_pcm16, style_for_camera


def camera(cues, **changes):
    return {"usable": True, "received_at": 100, "cues": cues, **changes}


@pytest.mark.parametrize('cues,style', [
    (["smiling"], "playful"), (["tired_look"], "soothing"), (["sleepy_look"], "soothing"),
    (["smiling", "tired_look"], "soothing"), (["confused_look"], "supportive"),
    (["furrowed_brow", "smiling"], "supportive"), (["irritated_look"], "supportive"),
    (["neutral"], "balanced"), (["concentrating_look"], "balanced"), ([], "balanced"),
])
def test_current_stable_cues_select_delivery(cues, style):
    assert style_for_camera(camera(cues), now=100.5).name == style


@pytest.mark.parametrize('latest', [
    None, camera(["tired_look"], usable=False), camera(["smiling"], received_at=98),
    camera(["smiling"], received_at=101), camera(["smiling"], received_at=float('nan')),
    camera(["smiling"], received_at=None), camera([], scores={"smiling": .99}),
])
def test_missing_expired_or_unclassified_camera_uses_default_delivery(latest):
    assert style_for_camera(latest, now=100).name == 'balanced'


class Socket:
    def __init__(self):
        self.messages = []

    async def send(self, message):
        self.messages.append(json.loads(message))


def configured_model(model_class=ProactiveRealtimeModel):
    model = model_class()
    latest = [camera(["smiling"])]
    model.configure_voice_style(lambda: style_for_camera(latest[0], now=100.5), VOICE_INSTRUCTIONS)
    model._websocket = Socket()
    return model, latest


async def test_regular_response_preserves_full_instructions_and_tool_settings():
    model, latest = configured_model(SpeechConfirmedRealtimeModel)
    request = ResponseCreateEvent(type='response.create', event_id='user-turn')
    await model._send_raw_message(request)
    sent = model._websocket.messages[-1]
    assert sent['event_id'] == 'user-turn'
    assert sent['response']['instructions'].startswith(VOICE_INSTRUCTIONS)
    assert 'playful, fun' in sent['response']['instructions']
    assert "explicit tone preferences" in sent['response']['instructions']
    assert sent['response']['metadata']['ambi_voice_style'] == 'playful'
    assert 'tools' not in sent['response']  # Inherit the session's approved tools.
    assert request.response is None  # No mutation/repeated prompt suffixes.
    latest[0] = camera(["neutral"])
    assert len(model._websocket.messages) == 1  # Cue changes never start speech.
    await model._send_raw_message(request)
    assert model._websocket.messages[-1]['response']['metadata']['ambi_voice_style'] == 'balanced'


async def test_session_instruction_updates_are_preserved_on_later_turns():
    model, _ = configured_model()
    await model._send_raw_message(SessionUpdateEvent.model_validate({
        'type': 'session.update', 'session': {'type': 'realtime', 'instructions': 'Updated task and permission rules.'},
    }))
    await model._send_raw_message(ResponseCreateEvent(type='response.create'))
    assert model._websocket.messages[-1]['response']['instructions'].startswith('Updated task and permission rules.')


async def test_proactive_delivery_preserves_no_tools_and_only_uses_allowlisted_style_text():
    model, latest = configured_model()
    latest[0] = camera(["tired_look"], instructions='INJECTED INSTRUCTION')
    assert await model.send_proactive_response('untrusted context', lambda: True)
    response = model._websocket.messages[-1]['response']
    assert response['instructions'].startswith(PROACTIVE_INSTRUCTIONS)
    assert 'calm, soothing' in response['instructions']
    assert 'INJECTED INSTRUCTION' not in response['instructions']
    assert response['tools'] == [] and response['tool_choice'] == 'none'
    assert response['metadata'] == {'kind': 'proactive_observation', 'ambi_voice_style': 'soothing'}


@pytest.mark.parametrize('kind', ['startup', 'demo_suggestion'])
async def test_special_turns_keep_their_own_prompt_and_receive_delivery(kind):
    model, _ = configured_model()
    assert await model.send_context_response('context', lambda: True, instructions='Say only the offered question.', kind=kind)
    response = model._websocket.messages[-1]['response']
    assert response['instructions'].startswith('Say only the offered question.')
    assert response['metadata'] == {'kind': kind, 'ambi_voice_style': 'playful'}
    assert response['tools'] == [] and response['tool_choice'] == 'none'


async def test_queued_user_turn_selects_fresh_style_at_send_time(monkeypatch):
    model, latest = configured_model()
    waiting, release = asyncio.Event(), asyncio.Event()
    original = model._response_create_sequencer.wait_for_response_create_slot

    async def wait(*args, **kwargs):
        waiting.set()
        await release.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(model._response_create_sequencer, 'wait_for_response_create_slot', wait)
    await model.send_event(RealtimeModelSendRawMessage(message={'type': 'response.create'}))
    async with asyncio.timeout(2):
        await waiting.wait()
        latest[0] = None  # Camera switched off while waiting for the prior reply.
        release.set()
        while not model._websocket.messages:
            await asyncio.sleep(0)
    assert model._websocket.messages[-1]['response']['metadata']['ambi_voice_style'] == 'balanced'
    await model._cancel_response_create_tasks()


async def test_cancelled_conditional_send_does_not_emit_a_style_or_a_response():
    model, _ = configured_model()
    assert not await model.send_context_response('context', lambda: False)
    assert model._websocket.messages == []
    assert model._voice_response_styles == {}


async def created(model, response_id, style):
    await model._handle_ws_event({
        'type': 'response.created', 'event_id': 'created-' + response_id,
        'response': {'id': response_id, 'object': 'realtime.response', 'status': 'in_progress',
                     'output': [], 'metadata': {'ambi_voice_style': style}},
    })


async def test_quieter_samples_are_fixed_per_response_and_do_not_change_duration():
    model, latest = configured_model()
    emitted = []
    async def on_event(event):
        if event.type == 'audio':
            emitted.append(event)
    model.add_listener(SimpleNamespace(on_event=on_event))
    await created(model, 'calm-reply', 'soothing')
    data = struct.pack('<5h', -32768, -10000, 0, 10000, 32767)
    audio = RealtimeModelAudioEvent(data=data, response_id='calm-reply', item_id='item-1', content_index=0)
    await model._emit_event(audio)
    latest[0] = camera(["smiling"])
    await model._emit_event(audio)
    for event in emitted:
        assert struct.unpack('<5h', event.data) == tuple(round(value * .78) for value in (-32768, -10000, 0, 10000, 32767))
        assert len(event.data) == len(data)
        assert event.item_id == 'item-1' and event.content_index == 0
    assert audio.data == data
    await created(model, 'upbeat-reply', 'playful')
    await model._emit_event(RealtimeModelAudioEvent(data=data, response_id='upbeat-reply', item_id='item-2', content_index=0))
    assert emitted[-1].data == data
    model._reset_connection_state()
    assert model._voice_response_styles == {}


def test_pcm_attenuation_preserves_silence_and_rejects_invalid_gain_or_alignment():
    assert soften_pcm16(bytes(480), .78) == bytes(480)
    assert soften_pcm16(b'unchanged', 1) == b'unchanged'
    for gain in (-1, 2, float('nan')):
        with pytest.raises(ValueError):
            soften_pcm16(b'\x00\x00', gain)
    with pytest.raises(ValueError, match='aligned'):
        soften_pcm16(b'\x01', .78)


async def test_runner_wires_delivery_without_losing_saved_context_or_tool_permissions(tmp_path):
    from memory_store import MemoryStore
    memory = MemoryStore(tmp_path / 'memory.db')
    memory.put(kind='task', title='Prepare the demo')
    try:
        model = ProactiveRealtimeModel()
        create_voice_runner(SimpleNamespace(perform=AsyncMock(), stop=AsyncMock()), Settings(),
                            model=model, memory=memory, voice_style=lambda: STYLES['soothing'])
        model._websocket = Socket()
        await model._send_raw_message(ResponseCreateEvent(type='response.create'))
        instructions = model._websocket.messages[-1]['response']['instructions']
        assert 'Prepare the demo' in instructions
        assert 'wait for the user\'s request or approval' in instructions
        assert 'calm, soothing' in instructions
    finally:
        memory.close()
