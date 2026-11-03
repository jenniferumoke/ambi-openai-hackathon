import test from 'node:test';
import assert from 'node:assert/strict';
import { voicePresentation } from '../src/voice-presentation.js';
import { createPoseController } from '../src/character-pose.js';
test('startup remains idle and unavailable voice has a setup recovery',()=>{
 const ready=voicePresentation({status:'idle'},true,true);
 assert.equal(ready.phase,'idle'); assert.equal(ready.button,'Talk with Ambi');
 assert.match(ready.hint,/microphone stays off/);
 assert.match(voicePresentation({status:'idle'},true,false).hint,/Set up/);
 assert.equal(voicePresentation({status:'connected'},false,true).disabled,true);
});
test('voice differentiates listening, muted, speaking, working and approval',()=>{
 const s={status:'connected',phase:'listening',microphone_enabled:true};
 assert.equal(voicePresentation(s,true,true).phase,'listening');
 assert.equal(voicePresentation({...s,microphone_enabled:false},true,true).phase,'muted');
 assert.equal(voicePresentation({...s,phase:'speaking'},true,true).phase,'speaking');
 assert.equal(voicePresentation({...s,job:{status:'running'}},true,true).phase,'working');
 assert.equal(voicePresentation({...s,job:{status:'running'},codex:{pending:[{id:'a'}]}},true,true).phase,'attention');
 assert.equal(voicePresentation({...s,status:'stopping'},true,true).disabled,true);
});
test('Codex work animates even with voice idle and pauses for permission',()=>{
 let time=0;
 const c=createPoseController({now:()=>time,schedule:()=>0,cancel:()=>{}});
 const s={status:'idle',job:{id:'task',engine:'codex',status:'running'}};
 assert.equal(c.update(s),'working');
 assert.equal(c.update({...s,codex:{status:'approval-required'}}),'needsYou');
 assert.equal(c.update({...s,job:{...s.job,status:'completed'}}),'success');
 time=3000;
 assert.equal(c.update({...s,job:{...s.job,status:'completed'}}),'waiting');
 assert.equal(c.update({...s,status:'error'}),'recovering');
 c.dispose();
});

test('muting stops the listening pose without interrupting the speaking pose',()=>{
 const c=createPoseController();
 assert.equal(c.update({status:'connected',phase:'listening',microphone_enabled:false}),'waiting');
 assert.equal(c.update({status:'connected',phase:'speaking',microphone_enabled:false}),'speaking');
 c.dispose();
});
