import asyncio
import json
from datetime import datetime, timedelta, timezone
from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx2
import pytest
from openai import AsyncOpenAI
from starlette.testclient import TestClient

from ambient import Intervention, AmbientClassifier, AmbientLoop, CuePacket, FastCamera
from app_runtime import AppRuntime
from cue_store import CueStore
from memory_store import MemoryStore
from observation_hub import ObservationHub
from server import create_app
from proactive_controller import TurnContext


def packet(sequence=0, cues=None, usable=True, stream_id="one"):
    return CuePacket(stream_id=stream_id, sequence=sequence, usable=usable,
                     cues=cues or [], scores={}, age_ms=0, inference_ms=12, detection_ms=134)


def test_short_cue_is_available_after_expression_relaxes_and_expires():
    hub = ObservationHub()
    camera = FastCamera(hub)
    camera.ingest(packet(cues=["furrowed_brow"]), now=100)
    episode = hub.snapshot(now=100)["camera"]["payload"]["episode"]
    camera.ingest(packet(1), now=100.3)
    data = hub.snapshot(now=100.3)["camera"]["payload"]
    assert data["cues"] == ["furrowed_brow"] and data["current_cues"] == []
    assert data["episode"] == episode
    camera.ingest(packet(2), now=104.1)
    assert hub.snapshot(now=104.1)["camera"]["payload"]["cues"] == []


def test_continuously_held_cue_keeps_one_episode_past_greeting_and_expires_after_release():
    hub = ObservationHub()
    camera = FastCamera(hub)
    camera.ingest(packet(cues=["furrowed_brow"]), now=100)
    key = AmbientLoop.key(hub.snapshot(now=100))
    for sequence in range(1, 21):
        camera.ingest(packet(sequence, ["furrowed_brow"]), now=100 + sequence)
        assert AmbientLoop.key(hub.snapshot(now=100 + sequence)) == key
    camera.ingest(packet(21), now=121)
    assert AmbientLoop.key(hub.snapshot(now=121)) == key
    camera.ingest(packet(22), now=124)
    assert AmbientLoop.key(hub.snapshot(now=124)) is None


@pytest.fixture
def ambient_runtime(tmp_path, monkeypatch):
    now = [100.0]
    monkeypatch.setattr("ambient.monotonic", lambda: now[0])
    monkeypatch.setattr("app_runtime.monotonic", lambda: now[0])
    memory = MemoryStore(tmp_path / "memory.db")
    memory.put(kind="task", title="Prepare pitch")
    runtime = AppRuntime(memory)
    runtime.status, runtime.connected_at = "connected", 90
    runtime.session = SimpleNamespace(model=SimpleNamespace(send_proactive_response=AsyncMock(return_value=True)))
    runtime.context = lambda: TurnContext(user_turn_generation=runtime.activity.user_turn_generation)
    snapshot = runtime.hub.snapshot
    monkeypatch.setattr(runtime.hub, "snapshot", lambda **kwargs: snapshot(now=now[0], **kwargs))
    runtime.camera.ingest(packet(cues=["furrowed_brow"]), now=100)
    yield runtime, now
    memory.close()


async def test_transient_decision_failure_retries_same_cue_after_backoff(ambient_runtime):
    runtime, now = ambient_runtime
    classifier = SimpleNamespace(decide=AsyncMock(side_effect=[TimeoutError(), Intervention(action="offer_task_help", title="Test offer", text="Inspect the failure?", task="Inspect the failure")]))
    loop = AmbientLoop(runtime, classifier)
    await loop.step()
    assert runtime.suggestion is None and loop.last_key is None
    assert runtime.proactive["reason"] == "decision_unavailable"
    await loop.step()
    assert classifier.decide.await_count == 1
    now[0] += 1
    await loop.step()
    assert classifier.decide.await_count == 2
    assert runtime.suggestion is not None


async def test_busy_voice_retries_cached_decision_without_consuming_offer_or_cooldown(ambient_runtime):
    runtime, _ = ambient_runtime
    classifier = SimpleNamespace(decide=AsyncMock(return_value=Intervention(action="offer_task_help", title="Test offer", text="Inspect the failure?", task="Inspect the failure")))
    runtime.session.model.send_proactive_response.side_effect = [False, True]
    loop = AmbientLoop(runtime, classifier)
    await loop.step()
    assert runtime.suggestion is None and loop.last_key is None
    assert loop.last_offer == float("-inf")
    assert runtime.proactive["reason"] == "voice_busy"
    await loop.step()
    classifier.decide.assert_awaited_once()
    assert runtime.suggestion is not None
    await loop.step()
    assert runtime.session.model.send_proactive_response.await_count == 2


@pytest.mark.parametrize("change", ["neutral", "face_lost", "user", "worker", "focus"])
async def test_normal_offer_rechecks_context_at_socket_send(ambient_runtime, change):
    runtime, _ = ambient_runtime
    async def send(_, send_if):
        if change == "neutral":
            runtime.camera.ingest(packet(1, ["neutral"]), now=100.1)
        elif change == "face_lost":
            runtime.camera.ingest(packet(1, usable=False), now=100.1)
        elif change == "user":
            runtime.activity.confirmed_speech()
        elif change == "worker":
            runtime.context = lambda: TurnContext(computer_generation=1)
        else:
            runtime.focus = True
        return send_if()
    runtime.session.model.send_proactive_response.side_effect = send
    loop = AmbientLoop(runtime, SimpleNamespace(decide=AsyncMock(return_value=Intervention(action="offer_task_help", title="Test offer", text="Inspect the failure?", task="Inspect the failure"))))
    await loop.step()
    assert runtime.suggestion is None and loop.last_offer == float("-inf")


async def test_a_declined_decision_is_not_repeated_for_every_frame(ambient_runtime):
    runtime, now = ambient_runtime
    classifier = SimpleNamespace(decide=AsyncMock(return_value=Intervention(action="none", title="", text="", task=None)))
    loop = AmbientLoop(runtime, classifier)
    await loop.step()
    for sequence in range(1, 7):
        now[0] += 1
        runtime.camera.ingest(packet(sequence, ["furrowed_brow"]), now=now[0])
    await loop.step()
    classifier.decide.assert_awaited_once()
    assert runtime.suggestion is None


@pytest.mark.parametrize("observe_screen,reason", [
    (True, "screen_permission_missing"), (False, "screen_observation_off"),
])
async def test_runtime_preserves_permission_reason_and_safe_voice_error(ambient_runtime, monkeypatch, observe_screen, reason):
    from main import RealtimeSessionError
    runtime, _ = ambient_runtime
    monkeypatch.setattr(runtime, "permissions", lambda: {"Accessibility": False, "Screen Recording": False})
    monkeypatch.setattr("app_runtime.run_voice", AsyncMock(side_effect=RealtimeSessionError({
        "code": "session_expired", "message": "private-provider-body",
    })))
    await runtime._run(observe_screen)
    snapshot = runtime.snapshot()
    assert snapshot["status"] == "error"
    assert snapshot["observations"]["computer"] == {"status": "disabled", "reason": reason}
    event = next(event for event in snapshot["events"] if event["type"] == "session_error")
    assert event["code"] == "session_expired" and event["location"]
    assert "private-provider-body" not in json.dumps(snapshot)


def test_camera_gap_starts_a_new_episode_instead_of_resurrecting_an_old_one():
    hub = ObservationHub()
    camera = FastCamera(hub)
    camera.ingest(packet(cues=["smiling"]), now=100)
    old_key = AmbientLoop.key(hub.snapshot(now=100))
    camera.ingest(packet(1, ["smiling"]), now=103)
    assert AmbientLoop.key(hub.snapshot(now=103)) != old_key


def test_missing_face_and_out_of_order_packet_do_not_restore_a_cue():
    hub = ObservationHub()
    camera = FastCamera(hub)
    camera.ingest(packet(2, ["smiling"]), now=100)
    assert not camera.ingest(packet(1, ["frowning"]), now=100.1)
    camera.ingest(packet(3, usable=False), now=100.2)
    assert hub.snapshot(now=100.2)["camera"]["status"] == "unavailable"
    camera.ingest(packet(4), now=100.3)
    assert hub.snapshot(now=100.3)["camera"]["payload"]["cues"] == []


def test_all_look_cues_reach_model_evaluation():
    from ambient import AmbientLoop

    cues = ["confused_look", "concentrating_look", "irritated_look", "tired_look", "sleepy_look"]
    hub = ObservationHub()
    camera = FastCamera(hub)
    camera.ingest(packet(cues=cues), now=100)
    snapshot = hub.snapshot(now=100)
    assert set(snapshot["camera"]["payload"]["cues"]) == set(cues)
    assert AmbientLoop.key(snapshot) is not None
    camera.ingest(packet(1, cues=["furrowed_brow", "confused_look"]), now=100.1)
    assert AmbientLoop.key(hub.snapshot(now=100.1)) is not None


def test_neutral_replaces_recent_expression_without_a_proactive_episode():
    hub = ObservationHub()
    camera = FastCamera(hub)
    camera.ingest(packet(cues=["furrowed_brow"]), now=100)
    assert AmbientLoop.key(hub.snapshot(now=100)) is not None
    camera.ingest(packet(1, cues=["neutral"]), now=100.7)
    snapshot = hub.snapshot(now=100.7)
    payload = snapshot["camera"]["payload"]
    assert payload["cues"] == payload["current_cues"] == ["neutral"]
    assert payload["episode"] is None
    assert AmbientLoop.key(snapshot) is None


async def test_model_generates_offer_from_context_without_images(tmp_path):
    decision = Intervention(action="offer_task_help", title="Inspect the error?", text="Shall I examine the failing case?", task="Inspect the failing test")
    parse = AsyncMock(return_value=SimpleNamespace(output_parsed=decision))
    client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    store = MemoryStore(tmp_path / "db")
    try:
        store.put(kind="task", title="Prepare pitch")
        assert await AmbientClassifier(client).decide({"camera": "confused_look"}, store) == decision
        request = parse.call_args.kwargs
        assert "Prepare pitch" in request["input"]
        assert "input_image" not in request["input"]
        assert request["store"] is False
    finally:
        store.close()



async def test_late_decision_cannot_speak_after_user_starts(tmp_path):
    memory = MemoryStore(tmp_path / "db")
    runtime = AppRuntime(memory)
    runtime.status = "connected"
    runtime.connected_at = monotonic() - 10
    runtime.camera.ingest(packet(cues=["furrowed_brow"]))
    runtime.memory.put(kind="task", title="Prepare pitch")
    runtime.session = SimpleNamespace(model=SimpleNamespace(send_proactive_response=AsyncMock()))
    called = asyncio.Event()
    async def decide(*_):
        runtime.activity.confirmed_speech()
        called.set()
        return "offer_task_help"
    task = asyncio.create_task(AmbientLoop(runtime, SimpleNamespace(decide=decide)).run())
    try:
        async with asyncio.timeout(1):
            await called.wait()
        assert runtime.suggestion is None
        runtime.session.model.send_proactive_response.assert_not_awaited()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        memory.close()


def test_local_api_requires_token_and_keeps_memory_across_restart(tmp_path):
    path = tmp_path / "db"
    app = create_app(db_path=path, seed=False)
    with TestClient(app) as client:
        boot = client.get('/api/bootstrap').json()
        assert 'api_configured' in boot and 'OPENAI_API_KEY' not in json.dumps(boot)
        assert client.post('/api/memory', json={}).status_code == 403
        headers = {'X-Ambi-Token': boot['token']}
        assert boot['state']['observations']['computer']['status'] == 'disabled'
        assert boot['state']['proactive'] == {'status': 'paused', 'reason': 'session_not_connected'}
        assert client.get('/api/state', headers=headers).json()['proactive'] == boot['state']['proactive']
        assert client.post('/api/memory', headers=headers,
                           json={'kind': 'note', 'title': []}).status_code == 400
        assert client.post('/api/memory', headers={**headers, 'Origin': 'https://evil.invalid'}, json={}).status_code == 403
        assert client.get('/api/bootstrap', headers={'Origin': 'https://evil.invalid'}).status_code == 403
        response = client.post('/api/memory', headers=headers,
                               json={'kind': 'task', 'title': 'Demo brief', 'source': 'My notes', 'body': 'Use three slides.'})
        assert response.status_code == 200
        stored = client.get('/api/state', headers=headers).json()['memories'][0]
        assert client.post('/api/memory-complete', headers=headers, json={'id': stored['id']}).status_code == 200
    with TestClient(create_app(db_path=path, seed=False)) as client:
        token = client.get('/api/bootstrap').json()['token']
        assert client.get('/api/state', headers={'X-Ambi-Token': token}).json()['memories'][0]['status'] == 'done'


def test_camera_payload_validation_and_focus(tmp_path):
    with TestClient(create_app(db_path=tmp_path/'db', seed=False)) as client:
        headers = {'X-Ambi-Token': client.get('/api/bootstrap').json()['token']}
        data = packet(cues=['smiling']).model_dump()
        assert client.post('/api/camera', headers=headers, json=data).status_code == 200
        state = client.get('/api/state', headers=headers).json()
        assert state['camera']['cues'] == ['smiling']
        assert client.post('/api/camera', headers=headers, json={**data, 'age_ms': 8000}).status_code == 400
        assert client.post('/api/focus', headers=headers, json={'enabled': True}).status_code == 200
        assert client.get('/api/state', headers=headers).json()['focus'] is True
        assert client.post('/api/accept', headers=headers, json={'id': 'expired'}).status_code == 400
        assert client.post('/api/camera-off', headers=headers, json={}).status_code == 200
        assert client.get('/api/state', headers=headers).json()['camera'] is None


def test_ellis_demo_uses_existing_cue_and_accept_contract_without_automatic_actions(tmp_path):
    from eval.test.demo import create_demo_app

    app = create_demo_app(root=tmp_path / "demo", auto_start=False)
    with TestClient(app) as client:
        r = app.state.runtime
        r.status, r.connected_at = "connected", monotonic() - 10
        r.session = SimpleNamespace(model=SimpleNamespace(send_context_response=AsyncMock(return_value=True)),
                                    send_message=AsyncMock(), interrupt=AsyncMock())
        r.audio = SimpleNamespace(clear=lambda: None)
        headers = {'X-Ambi-Token': client.get('/api/bootstrap').json()['token']}
        assert client.post('/api/camera', headers=headers, json=packet(cues=['smiling']).model_dump()).status_code == 200
        # Cue receipt alone never manufactures a scripted suggestion.
        assert client.get('/api/state', headers=headers).json()['suggestion'] is None
        r.suggestion = {'id': 'model-offer', 'title': 'Inspect the failing test?',
                        'text': 'Can I inspect the failing test?', 'task': 'Inspect PairMatch',
                        'action': 'offer_task_help', 'expires_at': monotonic() + 30}
        suggestion = client.get('/api/state', headers=headers).json()['suggestion']
        assert suggestion['title'] == 'Inspect the failing test?'
        r.session.send_message.assert_not_awaited()
        assert client.post('/api/accept', headers=headers, json={'id': 'wrong'}).status_code == 400
        assert client.post('/api/accept', headers=headers, json={'id': suggestion['id']}).status_code == 200
        r.session.send_message.assert_awaited_once_with(suggestion['task'])
        assert client.get('/api/state', headers=headers).json()['suggestion'] is None
        assert client.post('/api/accept', headers=headers, json={'id': suggestion['id']}).status_code == 400
        assert client.get('/api/cues', headers=headers).json()['schema_version'] == 2
        r.suggestion = {**suggestion, 'expires_at': monotonic() - 1}
        assert client.post('/api/accept', headers=headers, json={'id': suggestion['id']}).status_code == 400
        r.suggestion = {**suggestion, 'expires_at': monotonic() + 10}
        assert client.post('/api/dismiss', headers=headers, json={'id': suggestion['id']}).status_code == 200
        assert r.suggestion is None
        assert r.session.send_message.await_count == 1


def test_camera_cue_history_is_persisted_and_current_state_stays_fresh(tmp_path):
    path = tmp_path / 'db'
    cue_path = tmp_path / 'cues.sqlite3'
    with TestClient(create_app(db_path=path, cue_db_path=cue_path, seed=False)) as client:
        token = client.get('/api/bootstrap').json()['token']
        headers = {'X-Ambi-Token': token}
        data = packet(cues=['confused_look', 'sleepy_look']).model_dump()
        data['scores'] = {'confused_look': .8, 'sleepy_look': .9}
        first = client.post('/api/camera', headers=headers, json=data).json()
        assert first['accepted'] and first['stored'] and isinstance(first['event_id'], int)
        repeated = client.post('/api/camera', headers=headers,
                               json={**data, 'sequence': 1, 'scores': {'confused_look': .7}}).json()
        assert repeated == {'ok': True, 'accepted': True, 'stored': False, 'event_id': None}
        duplicate = client.post('/api/camera', headers=headers, json={**data, 'sequence': 1}).json()
        assert not duplicate['accepted'] and not duplicate['stored']
        assert client.post('/api/camera', headers=headers, json={**data, 'sequence': 2, 'cues': [], 'scores': {}}).json()['stored']
        assert client.post('/api/camera', headers=headers, json={**data, 'sequence': 3, 'cues': ['not_a_cue']}).status_code == 400
        state = client.get('/api/cues', headers=headers).json()
        assert state['schema_version'] == 2
        assert state['current']['cues'] == []
        assert len(state['events']) == 2
        assert state['events'][1]['cues'] == ['confused_look', 'sleepy_look']
        assert state['events'][1]['scores'] == {'confused_look': .8, 'sleepy_look': .9}
        assert client.get('/api/cues?limit=1', headers=headers).json()['events'][0]['sequence'] == 2
        assert client.get('/api/cues?limit=101', headers=headers).status_code == 400
        assert client.get('/api/cues').status_code == 403
        client.post('/api/camera-off', headers=headers, json={})
        assert client.get('/api/cues', headers=headers).json()['current'] is None
    with TestClient(create_app(db_path=path, cue_db_path=cue_path, seed=False)) as client:
        headers = {'X-Ambi-Token': client.get('/api/bootstrap').json()['token']}
        state = client.get('/api/cues', headers=headers).json()
        assert state['current'] is None and len(state['events']) == 2


def test_neutral_round_trips_through_state_websocket_and_durable_history(tmp_path):
    path = tmp_path / 'db'
    cue_path = tmp_path / 'cues.sqlite3'
    with TestClient(create_app(db_path=path, cue_db_path=cue_path, seed=False)) as client:
        token = client.get('/api/bootstrap').json()['token']
        headers = {'X-Ambi-Token': token}
        data = {**packet(cues=['neutral']).model_dump(), 'scores': {'neutral': .92}, 'detection_ms': 600}
        first = client.post('/api/camera', headers=headers, json=data).json()
        assert first['accepted'] and first['stored']
        repeated = client.post('/api/camera', headers=headers, json={**data, 'sequence': 1}).json()
        assert repeated['accepted'] and not repeated['stored']
        camera = client.get('/api/state', headers=headers).json()['camera']
        assert camera['cues'] == ['neutral'] and camera['scores'] == {'neutral': .92}
        with client.websocket_connect('/ws', subprotocols=['ambi', token],
                                      headers={'Origin': 'http://127.0.0.1:8765'}) as ws:
            assert ws.receive_json()['camera']['cues'] == ['neutral']
        # Existing clients may still send [] for an unclassified frame.
        assert client.post('/api/camera', headers=headers, json=packet(2).model_dump()).json()['stored']
        history = client.get('/api/cues', headers=headers).json()
        assert history['schema_version'] == 2
        assert history['current']['cues'] == []
        assert [event['cues'] for event in history['events']] == [[], ['neutral']]
    with TestClient(create_app(db_path=path, cue_db_path=cue_path, seed=False)) as client:
        headers = {'X-Ambi-Token': client.get('/api/bootstrap').json()['token']}
        history = client.get('/api/cues', headers=headers).json()
        assert history['current'] is None
        assert history['events'][1]['cues'] == ['neutral']
        assert history['events'][1]['scores'] == {'neutral': .92}


@pytest.mark.parametrize('changes', [
    {'cues': ['neutral', 'smiling']},
    {'cues': ['neutral', 'tired_look']},
    {'usable': False},
    {'scores': {'neutral': 1.1}},
])
def test_neutral_packet_validation(tmp_path, changes):
    with TestClient(create_app(db_path=tmp_path / 'db', seed=False)) as client:
        headers = {'X-Ambi-Token': client.get('/api/bootstrap').json()['token']}
        data = {**packet(cues=['neutral']).model_dump(), 'scores': {'neutral': .9}, **changes}
        assert client.post('/api/camera', headers=headers, json=data).status_code == 400
        assert client.get('/api/cues', headers=headers).json()['events'] == []


def test_cue_journal_is_bounded_by_age_and_event_count(tmp_path):
    store = CueStore(tmp_path / 'cues.sqlite3', max_events=2)
    now = datetime.now(timezone.utc)
    try:
        store.record(packet(0, ['smiling']), now=now)
        store.record(packet(1), now=now + timedelta(seconds=1))
        store.record(packet(2, ['frowning']), now=now + timedelta(seconds=2))
        assert [event['sequence'] for event in store.list()] == [2, 1]
        store.record(packet(3), now=now + timedelta(hours=24, seconds=3))
        assert [event['sequence'] for event in store.list()] == [3]
    finally:
        store.close()


def test_other_frontend_can_use_configured_origin_and_cue_api(tmp_path, monkeypatch):
    monkeypatch.setenv('AMBI_FRONTEND_ORIGINS', 'http://localhost:3000')
    with TestClient(create_app(db_path=tmp_path / 'db', seed=False)) as client:
        origin = {'Origin': 'http://localhost:3000'}
        preflight = client.options('/api/cues', headers={**origin, 'Access-Control-Request-Method': 'GET',
                                                       'Access-Control-Request-Headers': 'x-ambi-token'})
        assert preflight.status_code == 200
        assert preflight.headers['access-control-allow-origin'] == 'http://localhost:3000'
        boot = client.get('/api/bootstrap', headers=origin)
        assert boot.headers['access-control-allow-origin'] == 'http://localhost:3000'
        result = client.get('/api/cues', headers={**origin, 'X-Ambi-Token': boot.json()['token']})
        assert result.status_code == 200 and result.json()['events'] == []
        assert client.get('/api/bootstrap', headers={'Origin': 'https://other.example'}).status_code == 403


def test_websocket_requires_local_origin_and_token(tmp_path):
    from starlette.websockets import WebSocketDisconnect
    with TestClient(create_app(db_path=tmp_path/'db', seed=False)) as client:
        token = client.get('/api/bootstrap').json()['token']
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/ws', subprotocols=['ambi', token], headers={'Origin': 'https://evil.invalid'}):
                pass
        with client.websocket_connect('/ws', subprotocols=['ambi', token], headers={'Origin': 'http://127.0.0.1:8765'}) as ws:
            state = ws.receive_json()
            assert state['status'] == 'idle'
            assert state['proactive'] == {'status': 'paused', 'reason': 'session_not_connected'}


@pytest.mark.parametrize("cue", ["confused_look", "concentrating_look", "irritated_look", "tired_look", "sleepy_look"])
async def test_composite_cue_uses_model_wording_without_running_tools(ambient_runtime, cue):
    runtime, now = ambient_runtime
    runtime.camera.ingest(packet(1, [cue]), now=100)
    choice = Intervention(action="offer_task_help", title="Model title", text="A context-specific offer?", task="Inspect only")
    classifier = SimpleNamespace(decide=AsyncMock(return_value=choice))
    await AmbientLoop(runtime, classifier).step()
    classifier.decide.assert_awaited_once()
    assert runtime.suggestion['text'] == choice.text
    assert runtime.suggestion['task'] == choice.task
