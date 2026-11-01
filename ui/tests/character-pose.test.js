import test from 'node:test';
import assert from 'node:assert/strict';
import { createPoseController } from '../src/character-pose.js';
const state = (extra = {}) => ({ status: 'connected', phase: 'ready', ...extra });
test('connection and phase priorities, including suggestions', () => {
 const c = createPoseController();
 for (const [s,p] of [[{status:'connecting'},'thinking'],[{status:'error'},'recovering'],[{status:'idle'},'waiting'],[{status:'stopping'},'waiting'],[{phase:'listening'},'listening'],[{phase:'speaking'},'speaking'],[{phase:'working'},'working'],[{phase:'ready'},'listening'],[{suggestion:{id:'s'}},'needsYou']]) assert.equal(c.update(state(s)),p);
 c.dispose();
});
test('new completion lasts three seconds, expires without a server event, and never retriggers', () => {
 let time=0, callback, notified=0;
 const c=createPoseController({now:()=>time,schedule:(fn,ms)=>{assert.equal(ms,3000);callback=fn;},cancel:()=>{},changed:()=>notified++});
 const completed=state({job:{id:'a',status:'completed'}});
 assert.equal(c.update(completed),'listening');
 c.update(state({job:{id:'b',status:'running'}}));
 const next=state({job:{id:'b',status:'completed'}});
 assert.equal(c.update(next),'success');
 time=2999; assert.equal(c.update(next),'success');
 time=3000; callback(); assert.equal(notified,1);
 assert.equal(c.update(next),'listening');
 assert.equal(c.update({...next,suggestion:{id:'s'}}),'needsYou');
});
test('errors and disconnection take priority over a success pulse', () => {
 const c=createPoseController();
 c.update(state({job:{id:'a',status:'running'}}));
 const job={id:'a',status:'completed'};
 assert.equal(c.update(state({job})),'success');
 assert.equal(c.update(state({job,status:'error'})),'recovering');
 assert.equal(c.update(state({job,status:'idle'})),'waiting');
 assert.equal(c.update(state({job})),'listening');
 c.dispose();
});
