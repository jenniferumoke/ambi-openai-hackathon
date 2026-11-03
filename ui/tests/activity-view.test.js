import test from 'node:test';
import assert from 'node:assert/strict';
import { actionTitle, shouldExpand, goalProgress } from '../src/activity-view.js';

test('activity opens on a new session or task, while manual collapse survives later snapshots', () => {
  assert.equal(shouldExpand({ status: 'idle' }, { status: 'connecting' }), true);
  assert.equal(shouldExpand({ status: 'connected' }, { status: 'connected', phase: 'speaking' }), false);
  assert.equal(shouldExpand({ status: 'idle' }, { status: 'idle', job: { status: 'running' } }), true);
  assert.equal(shouldExpand(null, { status: 'connected' }), true);
  assert.equal(shouldExpand({ status: 'connected' }, { status: 'idle' }), false);
});
test('user-facing steps describe observed actions without inventing intentions', () => {
  assert.equal(actionTitle('screenshot'), 'Reading the screen');
  assert.equal(actionTitle('paste 12 characters'), 'Entering text');
  assert.equal(actionTitle('left click (10, 20)'), 'Clicking a control');
  assert.equal(actionTitle('keypress command+v'), 'Using a keyboard shortcut');
  assert.equal(actionTitle('unknown operation'), 'unknown operation');
});
test('current goal progress stays visible and ignores unrelated old activity', () => {
  const state={job:{id:'current',status:'running',goal_status:'running'},activity:[
    {job_id:'current',status:'running',kind:'review',title:'Checking progress'},
    {job_id:'old',status:'running',kind:'action',title:'screenshot'}]};
  assert.equal(goalProgress(state),'Checking progress');
  state.activity.push({job_id:'current',status:'running',kind:'action',title:'open application'});
  assert.equal(goalProgress(state),'Opening the app');
});
test('checked, paused and stopped goals remain distinct from legacy work', () => {
  assert.equal(goalProgress({job:{status:'completed',goal_status:'achieved'}}),'Goal checked.');
  assert.equal(goalProgress({job:{status:'failed',goal_status:'paused'}}),'Goal paused. Ask Ambi to continue.');
  assert.equal(goalProgress({job:{status:'cancelled',goal_status:'cancelled'}}),'Goal stopped.');
  assert.equal(goalProgress({job:{status:'completed'}}),null);
});
