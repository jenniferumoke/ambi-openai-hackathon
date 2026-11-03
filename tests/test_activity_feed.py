import asyncio

import pytest

from app_runtime import AppRuntime
from memory_store import MemoryStore


def test_activity_survives_diagnostic_buffer_and_preserves_worker_uncertainty(tmp_path):
    memory = MemoryStore(tmp_path / 'memory.db')
    try:
        runtime = AppRuntime(memory)
        runtime.emit('job_started', task='Inspect a sample')
        runtime.emit('computer_step_started', step_id='read', label='screenshot')
        runtime.emit('computer_step_finished', step_id='read', status='completed', detail='Operation returned.')
        runtime.emit('job_finished', status='completed', result='Please confirm before editing.')
        for _ in range(60):
            runtime.emit('proactive_status', status='waiting', reason='no_relevant_context')
        rows = runtime.snapshot()['activity']
        assert rows[0]['status'] == 'returned'
        assert rows[0]['detail'] == 'Please confirm before editing.'
        assert rows[1]['status'] == 'completed'
        assert rows[1]['job_id'] == rows[0]['id']
        assert len(runtime.events) == 40
        assert len(rows) == 2
        for i in range(250):
            runtime.emit('computer_step_started', step_id=str(i), label='screenshot')
        assert len(runtime.snapshot()['activity']) == 200
    finally:
        memory.close()


async def test_desktop_feed_does_not_include_typed_text_or_screenshot_pixels(desktop):
    events = []
    desktop.emit = lambda event, **fields: events.append((event, fields))
    await desktop.type('private sample text')
    assert events[0][0] == 'computer_step_started'
    assert events[1][1]['status'] == 'completed'
    assert 'private sample text' not in str(events)
    events.clear()
    desktop.gui.screenshot.side_effect = RuntimeError('private provider detail')
    with pytest.raises(RuntimeError):
        await desktop.screenshot()
    assert events[1][1]['status'] == 'failed'
    assert 'private provider detail' not in str(events)


async def test_cancelled_desktop_action_is_not_reported_complete(desktop):
    events = []
    desktop.emit = lambda event, **fields: events.append((event, fields))
    async def cancelled(operation):
        raise asyncio.CancelledError()
    from unittest.mock import patch
    with patch('desktop.asyncio.to_thread', cancelled):
        with pytest.raises(asyncio.CancelledError):
            await desktop.screenshot()
    assert [fields.get('status') for _, fields in events] == [None, 'cancelled']


def test_goal_review_activity_stays_running_until_checked_and_distinguishes_completion(tmp_path):
    memory=MemoryStore(tmp_path/'review.db')
    try:
        runtime=AppRuntime(memory)
        runtime.emit('job_started',task='Save synthetic test note')
        runtime.emit('goal_checkpoint',goal_id='goal',status='running',round=1)
        runtime.emit('goal_review_started',goal_id='goal',round=1)
        assert runtime.activity_log[-1]['status']=='running'
        runtime.emit('goal_review',goal_id='goal',round=1,decision='achieved',summary='Saved text matched read-back.')
        assert runtime.activity_log[-1]['status']=='completed'
        assert runtime.activity_log[-1]['detail']=='Saved text matched read-back.'
        runtime.emit('job_finished',status='completed',result='Text checked.',reviewed=True)
        assert runtime.activity_log[0]['status']=='checked'
        assert runtime.job['goal_id']=='goal' and runtime.job['review_round']==1
    finally:memory.close()
