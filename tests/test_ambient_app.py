import asyncio
import json
from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx2
import pytest
from openai import AsyncOpenAI
from starlette.testclient import TestClient

from ambient import AmbientClassifier, AmbientLoop, CuePacket, FastCamera
from app_runtime import AppRuntime
from memory_store import MemoryStore
from observation_hub import ObservationHub
from server import create_app


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


def test_missing_face_and_out_of_order_packet_do_not_restore_a_cue():
    hub = ObservationHub()
    camera = FastCamera(hub)
    camera.ingest(packet(2, ["smiling"]), now=100)
    assert not camera.ingest(packet(1, ["frowning"]), now=100.1)
    camera.ingest(packet(3, usable=False), now=100.2)
    assert hub.snapshot(now=100.2)["camera"]["status"] == "unavailable"
    camera.ingest(packet(4), now=100.3)
    assert hub.snapshot(now=100.3)["camera"]["payload"]["cues"] == []


async def test_decisions_request_uses_context_and_no_camera_image(tmp_path):
    requests = []
    async def handler(request):
        requests.append(json.loads(request.content))
        return httpx2.Response(200, json={"model": "gpt-6-luna", "answers": [{
            "type": "choice", "name": "intervention", "choice": "offer_task_help", "confidence": .9,
            "probabilities": [{"value": "none", "probability": .05},
                              {"value": "offer_task_help", "probability": .9},
                              {"value": "acknowledge_progress", "probability": .05}],
        }], "usage": {"input_tokens": 10, "output_tokens": 0, "total_tokens": 10}})
    store = MemoryStore(tmp_path / "db")
    store.put(kind="task", title="Prepare pitch")
    async with AsyncOpenAI(api_key="offline", http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))) as client:
        assert await AmbientClassifier(client).decide({"camera": "furrowed_brow"}, store) == "offer_task_help"
    assert requests[0]["model"] == "gpt-6-luna"
    assert "Prepare pitch" in requests[0]["input"] and "input_image" not in json.dumps(requests)
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


def test_websocket_requires_local_origin_and_token(tmp_path):
    from starlette.websockets import WebSocketDisconnect
    with TestClient(create_app(db_path=tmp_path/'db', seed=False)) as client:
        token = client.get('/api/bootstrap').json()['token']
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/ws', subprotocols=['ambi', token], headers={'Origin': 'https://evil.invalid'}):
                pass
        with client.websocket_connect('/ws', subprotocols=['ambi', token], headers={'Origin': 'http://127.0.0.1:8765'}) as ws:
            assert ws.receive_json()['status'] == 'idle'
