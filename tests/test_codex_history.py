import asyncio
from pathlib import Path
import json
import pytest
from starlette.testclient import TestClient
from codex_bridge import CodexBridge
from app_runtime import AppRuntime
from memory_store import MemoryStore
from server import create_app


def test_history_survives_restart_and_never_resumes_work(tmp_path):
    path = tmp_path / 'memory.sqlite3'
    memory = MemoryStore(path)
    runtime = AppRuntime(memory)
    runtime.transcript.append({'id': 'hello', 'role': 'user', 'text': 'A saved message'})
    runtime.emit('job_started', task='A task in progress')
    runtime.snapshot()
    memory.close()
    memory = MemoryStore(path)
    restored = AppRuntime(memory)
    assert restored.snapshot()['transcript'][0]['text'] == 'A saved message'
    assert restored.activity_log[0]['status'] == 'cancelled'
    assert restored.job is None
    assert restored.codex.process is None
    assert restored.computer_enabled is False
    memory.close()


async def test_approval_is_scoped_and_never_accepted_automatically():
    bridge = CodexBridge(lambda *args: None)
    sent = []
    async def capture(value): sent.append(value)
    bridge._write = capture
    bridge.thread_id, bridge.turn_id = 'thread-a', 'turn-a'
    request = {'threadId': 'thread-a', 'turnId': 'turn-a', 'command': 'echo test', 'cwd': '/tmp'}
    await bridge._approval(7, 'item/commandExecution/requestApproval', request)
    assert sent == []
    identity = bridge.state['pending'][0]['id']
    await bridge.approve(identity, 'decline')
    assert sent == [{'id': 7, 'result': {'decision': 'decline'}}]
    with pytest.raises(ValueError, match='expired'):
        await bridge.approve(identity, 'accept')
    await bridge._approval(8, 'item/fileChange/requestApproval', {**request, 'turnId': 'stale'})
    assert 'error' in sent[-1]
    await bridge._approval(9, 'item/permissions/requestApproval', request)
    assert 'error' in sent[-1]  # Unknown grants fail closed.


async def test_immediate_completion_does_not_leave_a_running_job(tmp_path):
    memory = MemoryStore(tmp_path / 'db')
    runtime = AppRuntime(memory)
    async def start(*args, **kwargs):
        runtime._codex_event('turn_completed', {'turn': {'status': 'completed'}})
        return 'thread-fixture'
    runtime.codex.start = start
    await runtime.send_codex('Explain the fixture')
    assert runtime.job['status'] == 'completed'
    assert runtime.snapshot()['transcript'][0]['role'] == 'user'
    memory.close()


def test_task_routes_require_authentication_and_validate_grants(tmp_path):
    with TestClient(create_app(db_path=tmp_path / 'db', seed=False)) as client:
        assert client.post('/api/codex-connect', json={}).status_code == 403
        bootstrap = client.get('/api/bootstrap').json()
        headers = {'X-Ambi-Token': bootstrap['token']}
        assert bootstrap['state']['codex']['status'] == 'disconnected'
        assert client.post('/api/codex-approval', headers=headers, json={'id': 'expired', 'decision': 'accept'}).status_code == 400
        assert client.post('/api/workspace', headers=headers, json={'path': '/does-not-exist-ambi'}).status_code == 400
        assert client.post('/api/codex-model', headers=headers, json={'model': 'not-listed'}).status_code == 400
        assert client.post('/api/computer-access', headers=headers, json={'enabled': False}).status_code == 200


async def test_stop_during_connection_marks_task_cancelled(tmp_path):
    memory = MemoryStore(tmp_path / 'cancel.db')
    runtime = AppRuntime(memory)
    runtime.emit('job_started', task='Connecting task')
    runtime.job.update(engine='codex', client_id='owned-client')
    runtime.codex.state['status'] = 'connecting'
    closed = []
    async def close(): closed.append(True)
    runtime.codex.close = close
    await runtime.stop_work()
    assert closed == [True]
    assert runtime.job['status'] == 'cancelled'
    memory.close()


def test_quit_cancellation_cannot_cancel_a_different_clients_task(tmp_path):
    with TestClient(create_app(db_path=tmp_path / 'scope.db', seed=False)) as client:
        runtime = client.app.state.runtime
        runtime.emit('job_started', task='Other client task')
        runtime.job.update(engine='codex', client_id='other-client')
        headers = {'X-Ambi-Token': client.get('/api/bootstrap').json()['token']}
        response = client.post('/api/stop-task', headers=headers, json={'client_id': 'my-client'})
        assert response.status_code == 200
        assert runtime.job['status'] == 'running'


async def test_network_and_patch_approval_details_remain_transient():
    bridge = CodexBridge(lambda *args: None)
    bridge.thread_id, bridge.turn_id = 't', 'v'
    async def capture(value): pass
    bridge._write = capture
    bridge.items['patch'] = {'changes': [{'path': '/work/example.txt', 'diff': '+hello'}]}
    await bridge._approval(9, 'item/fileChange/requestApproval', {
        'threadId': 't', 'turnId': 'v', 'itemId': 'patch', 'grantRoot': '/work',
        'availableDecisions': ['decline', 'cancel']})
    request = bridge.state['pending'][0]
    assert request['changes'][0]['diff'] == '+hello'
    assert request['grant_root'] == '/work'
    with pytest.raises(ValueError, match='one-time'):
        await bridge.approve(request['id'], 'accept')


def test_older_history_is_paginated_without_silent_eviction(tmp_path):
    memory = MemoryStore(tmp_path / 'archive.db')
    runtime = AppRuntime(memory)
    for index in range(245):
        runtime.transcript.append({'id': str(index), 'role': 'user', 'text': f'Message {index}'})
        runtime.save_history()
    snapshot = runtime.snapshot()
    assert len(snapshot['transcript']) == 40
    page = runtime.history_store.messages(before=snapshot['history_cursor'])
    assert page['messages'][-1]['text'] == 'Message 204'
    assert page['has_more']
    count = memory.db.execute("SELECT COUNT(*) FROM companion_history WHERE kind='message'").fetchone()[0]
    assert count == 245
    memory.close()


async def test_missing_executable_reports_recoverable_connection_error():
    bridge = CodexBridge(lambda *args: None, executable='/ambi/nonexistent/codex')
    with pytest.raises(ValueError, match='could not start'):
        await bridge.connect()
    assert bridge.state['status'] == 'disconnected'
    assert bridge.process is None


async def test_interrupt_before_turn_id_closes_owned_connection():
    bridge = CodexBridge(lambda *args: None)
    bridge.state['status'] = 'running'
    closed = []
    async def close(): closed.append(True)
    bridge.close = close
    await bridge.interrupt()
    assert closed == [True]
