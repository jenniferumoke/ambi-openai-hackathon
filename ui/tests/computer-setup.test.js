import test from 'node:test';
import assert from 'node:assert/strict';
import { computerSetup } from '../src/computer-setup.js';
const idle={platform:'darwin',status:'idle',permissions:{Accessibility:false,'Screen Recording':false},computer_enabled:false};
test('missing permission leads to setup without enabling computer access',()=>{
 const before=JSON.stringify(idle),s=computerSetup(idle,true);
 assert.equal(s.button,'Set up computer use');assert.equal(s.blocked,false);assert.equal(s.ready,false);
 assert.deepEqual(s.missing,['Accessibility','Screen Recording']);assert.equal(JSON.stringify(idle),before);
});
test('only a nonempty all-true permission snapshot is ready',()=>{
 assert.equal(computerSetup({...idle,permissions:{}},true).ready,false);
 assert.equal(computerSetup({...idle,permissions:{Accessibility:'yes'}},true).ready,false);
 const ready=computerSetup({...idle,permissions:{Accessibility:true,'Screen Recording':true}},true);
 assert.equal(ready.ready,true);assert.match(ready.button,/Enable/);
});
test('live voice, jobs, disconnection and unknown status block setup',()=>{
 for(const status of ['connected','connecting','stopping','unknown'])assert.equal(computerSetup({...idle,status},true).blocked,true);
 assert.equal(computerSetup({...idle,job:{status:'running'}},true).blocked,true);
 assert.equal(computerSetup(idle,false).blocked,true);
});
test('Windows uses interactive desktop readiness rather than Mac privacy settings',()=>{
 const s=computerSetup({platform:'win32',status:'idle',permissions:{'Interactive desktop':true},computer_enabled:false},true);
 assert.equal(s.mac,false);assert.equal(s.ready,true);
 assert.match(computerSetup({...idle,computer_enabled:true},true).button,/Disable/);
});

test('a failed session can reconnect but cannot enable control until idle',()=>{
 const s=computerSetup({...idle,status:'error',permissions:{Accessibility:true,'Screen Recording':true}},true);
 assert.equal(s.blocked,false);assert.equal(s.enableAllowed,false);assert.match(s.button,/Reconnect/);
});

test('partial Mac and unsupported platform snapshots never enable the driver',()=>{
 const partial=computerSetup({...idle,permissions:{Accessibility:true}},true);
 assert.equal(partial.ready,false);assert.deepEqual(partial.missing,['Screen Recording']);
 assert.equal(computerSetup({...idle,platform:'unknown',permissions:{ok:true}},true).ready,false);
});

test('Linux requires every X11 prerequisite and gives platform-specific guidance',()=>{
 const state={platform:'linux',status:'idle',permissions:{'X11 session':true,'Screenshot utility':true,'Clipboard utility':true},computer_enabled:false};
 const ready=computerSetup(state,true);assert.equal(ready.ready,true);assert.equal(ready.enableAllowed,true);assert.equal(ready.mac,false);assert.equal(ready.linux,true);
 const blocked=computerSetup({...state,permissions:{...state.permissions,'X11 session':false}},true);
 assert.equal(blocked.enableAllowed,false);assert.match(blocked.message,/Wayland/);
 assert.equal(computerSetup({...state,permissions:{}},true).ready,false);
});
