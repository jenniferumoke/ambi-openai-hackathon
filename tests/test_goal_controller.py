import asyncio
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from goal_controller import CheckedReview, ExecutionReport, GoalController, GoalJournal, GoalReview
from goal_verifier import verify_saved_text


def review(status='achieved', *, step='', strategy='none', approval=False, fresh=True, contradict=False):
    return CheckedReview(GoalReview(status=status, summary='Observed test result.', evidence_ids=['fresh'],
        strategy=strategy, next_step=step, requires_approval=approval), {'fresh'} if fresh else set(),
        ('Saved value is wrong.',) if contradict else ())


@pytest.fixture
def journal():
    db=sqlite3.connect(':memory:')
    yield GoalJournal(db)
    db.close()


async def test_incomplete_result_selects_alternative_then_checks_completion(journal):
    execute=AsyncMock(side_effect=[ExecutionReport('Button unavailable.'),ExecutionReport('Saved via standard form.')])
    check=AsyncMock(side_effect=[review('continue',step='Use the standard save form.',strategy='alternative_ui'),review()])
    events=[]
    outcome=await GoalController(journal=journal,emit=lambda event,**data:events.append(event)).run('Save test note.',execute,check)
    assert outcome.status=='achieved' and execute.await_count==2 and check.await_count==2
    assert execute.await_args_list[1].args[:2]==('Save test note.','Use the standard save form.')
    assert journal.get(outcome.goal_id)['status']=='achieved'
    assert events.count('goal_review')==2 and events.count('goal_next_step')==1


@pytest.mark.parametrize('checked',[review(fresh=False),review(contradict=True),review(approval=True)])
async def test_unsupported_success_or_approval_cannot_complete_or_continue(journal,checked):
    execute=AsyncMock(return_value=ExecutionReport('Executor claims done.'))
    outcome=await GoalController(journal=journal).run('Test goal',execute,AsyncMock(return_value=checked))
    assert outcome.status=='paused' and execute.await_count==1


async def test_safety_boundary_never_enters_automatic_recovery(journal):
    check=AsyncMock()
    outcome=await GoalController(journal=journal).run('Test goal',
        AsyncMock(return_value=ExecutionReport('Safety approval required.','DesktopStopped',False)),check)
    assert outcome.status=='paused'
    check.assert_not_awaited()


async def test_repeat_guard_prevents_infinite_alternatives(journal):
    execute=AsyncMock(return_value=ExecutionReport('Still incomplete.'))
    outcome=await GoalController(journal=journal,max_rounds=10).run('Test goal',execute,
        AsyncMock(return_value=review('continue',step='Try the same button.',strategy='alternative_ui')))
    assert outcome.status=='paused' and execute.await_count==3
    assert 'repeated' in outcome.summary


async def test_repeated_step_with_new_checked_progress_can_continue(journal):
    decisions=[]
    for count in range(4):
        checked=review('continue',step='Process the next item.',strategy='continue_steps')
        checked.review.summary=f'Fresh evidence shows {count+1} items completed.'
        decisions.append(checked)
    decisions.append(review())
    execute=AsyncMock(return_value=ExecutionReport('Next item returned.'))
    outcome=await GoalController(journal=journal,max_rounds=6).run('Process five test items.',execute,
        AsyncMock(side_effect=decisions))
    assert outcome.status=='achieved' and execute.await_count==5


async def test_stop_during_review_is_sticky_and_checkpointed(journal):
    started=asyncio.Event()
    async def check(*_):
        started.set()
        await asyncio.Event().wait()
    execute=AsyncMock(return_value=ExecutionReport('First step finished.'))
    task=asyncio.create_task(GoalController(journal=journal).run('Test goal',execute,check))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):await task
    row=journal.db.execute('SELECT status FROM companion_goals').fetchone()
    assert row[0]=='cancelled' and execute.await_count==1


async def test_budget_pauses_with_a_resume_checkpoint(journal):
    async def slow(*_):await asyncio.Event().wait()
    outcome=await GoalController(journal=journal,timeout=.01).run('Test goal',slow,AsyncMock())
    assert outcome.status=='paused' and journal.get(outcome.goal_id)['task']=='Test goal'


async def test_resume_checks_fresh_state_before_replaying_any_action(journal):
    journal.save('saved','paused',task='Original goal',plan='Old unverified step',summary='Prior progress')
    execute=AsyncMock()
    outcome=await GoalController(journal=journal).run('resume',execute,AsyncMock(return_value=review()),resume_goal_id='saved')
    assert outcome.status=='achieved' and outcome.goal_id=='saved'
    execute.assert_not_awaited()


async def test_explicit_resume_of_stopped_goal_rechecks_and_keeps_round_ids_unique(journal):
    journal.save('stopped','cancelled',task='Original goal',plan='Old step',round=3)
    execute=AsyncMock()
    assert journal.latest_resumable()['status']=='cancelled'
    outcome=await GoalController(journal=journal).run('explicit resume',execute,AsyncMock(return_value=review()),resume_goal_id='stopped')
    assert outcome.status=='achieved' and journal.get('stopped')['round']==4
    execute.assert_not_awaited()


def test_restart_pauses_running_goal_without_auto_replay(journal):
    journal.save('saved','running',task='Original goal',plan='Pending step')
    reopened=GoalJournal(journal.db)
    assert reopened.latest_paused()['id']=='saved'
    assert reopened.get('saved')['task']=='Original goal'


def test_saved_file_readback_is_explicit_and_does_not_return_contents(tmp_path):
    path=tmp_path/'owned.txt';path.write_text('Synthetic expected line.\n')
    task=f'Save Synthetic expected line. at {path}'
    result=verify_saved_text(str(path),'Synthetic expected line.',task=task,root=tmp_path)
    assert result['matches'] is True and 'text' not in result
    with pytest.raises(ValueError):verify_saved_text(str(path),'different',task=task,root=tmp_path)


def test_file_verifier_rejects_symlink_escape(tmp_path):
    root=tmp_path/'allowed';root.mkdir()
    private=tmp_path/'outside.txt';private.write_text('Synthetic outside text.')
    link=root/'link.txt';link.symlink_to(private)
    with pytest.raises(ValueError,match='confined'):
        verify_saved_text(str(link),'Synthetic outside text.',task=f'Read {link}: Synthetic outside text.',root=root)


async def test_real_sdk_review_uses_fresh_file_tool_and_structured_output(tmp_path):
    import httpx2
    from agents.models.openai_responses import OpenAIResponsesModel
    from openai import AsyncOpenAI
    from test_agent import response
    from goal_verifier import review_goal
    path=tmp_path/'owned.txt';path.write_text('Synthetic checked line.\n')
    requests=[]
    async def handler(request):
        body=json.loads(request.content);requests.append(body)
        if len(requests)==1:
            output=[{'type':'function_call','id':'fc1','call_id':'check-file','name':'check_saved_text',
                     'arguments':json.dumps({'path':str(path),'expected_text':'Synthetic checked line.'})}]
        else:
            tool=next(item for item in body['input'] if item.get('type')=='function_call_output')
            evidence=json.loads(tool['output'])['evidence_id']
            decision=GoalReview(status='achieved',summary='Saved text matched fresh read-back.',
                evidence_ids=[evidence],strategy='none',next_step='',requires_approval=False)
            output=[{'type':'message','id':'m1','role':'assistant','status':'completed','content':[
                {'type':'output_text','text':decision.model_dump_json(),'annotations':[]}]}]
        return httpx2.Response(200,json=response(output,len(requests)))
    async with AsyncOpenAI(api_key='offline-test-key',max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))) as client:
        computer=SimpleNamespace(environment='mac',screenshot=AsyncMock())
        checked=await review_goal(computer,OpenAIResponsesModel('gpt-6.1-terra',client),
            f'Save Synthetic checked line. at {path}',ExecutionReport('Executor says saved.'),root=tmp_path)
    assert checked.review.status=='achieved' and checked.observed_ids
    assert set(checked.review.evidence_ids).issubset(checked.observed_ids)
    computer.screenshot.assert_not_awaited()
    assert requests[0]['store'] is False
    assert {tool['name'] for tool in requests[0]['tools']}=={'inspect_screen','inspect_application','check_saved_text'}


async def test_worker_stop_cancels_review_and_does_not_start_another_attempt(desktop,monkeypatch,tmp_path):
    import main
    from memory_store import MemoryStore
    started=asyncio.Event()
    async def slow_review(*args,**kwargs):
        started.set()
        await asyncio.Event().wait()
    execute=AsyncMock(return_value=SimpleNamespace(final_output='Executor returned.'))
    monkeypatch.setattr(main.Runner,'run',execute)
    monkeypatch.setattr('goal_verifier.review_goal',slow_review)
    memory=MemoryStore(tmp_path/'worker.db')
    try:
        worker=main.ComputerWorker(desktop,main.Settings(),review=True,memory=memory,verification_root=tmp_path)
        operation=asyncio.create_task(worker.perform('Synthetic goal'))
        await started.wait()
        await worker.stop()
        assert 'stopped' in (await operation).lower()
        assert execute.await_count==1 and desktop._stopped.is_set()
        assert memory.db.execute('SELECT status FROM companion_goals').fetchone()[0]=='cancelled'
    finally:memory.close()
