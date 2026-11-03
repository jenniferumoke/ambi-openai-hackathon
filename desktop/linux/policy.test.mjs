import test from 'node:test';
import assert from 'node:assert/strict';
import {allowedPage, idle, frameActive, launchEnvironment, linuxSession} from './policy.mjs';
test('only the exact local companion page may use native bridge', () => {
  assert.equal(allowedPage('http://127.0.0.1:8767/companion.html'), true);
  for (const url of ['http://localhost:8767/companion.html','https://127.0.0.1:8767/companion.html','http://127.0.0.1:8765/companion.html','http://user@127.0.0.1:8767/companion.html','http://127.0.0.1:8767/other','http://127.0.0.1:8767/companion.html?next=other','http://127.0.0.1:8767/companion.html#other','file:///companion.html','invalid']) assert.equal(allowedPage(url),false,url);
});
test('key changes require an observed idle backend and no running task', () => {
  assert.equal(idle({status:'idle'}),true);
  for (const state of [null,{status:'connected'},{status:'idle',job:{status:'running'}}]) assert.equal(idle(state),false);
});
test('frame follows real running state and clears on disconnect', () => {
  assert.equal(frameActive({job:{status:'running'}}),true);
  for(const state of [null,{job:{status:'completed'}},{job:{status:'cancelled'}},{job:{status:'failed'}}]) assert.equal(frameActive(state),false);
});
test('native launch never inherits a key or dotenv, optional explicit key remains in process environment only', () => {
  const original={OPENAI_API_KEY:'test-inherited',PATH:'/usr/bin'};
  assert.equal(launchEnvironment(original,'/private').OPENAI_API_KEY,undefined);
  assert.equal(original.OPENAI_API_KEY,'test-inherited');
  const env=launchEnvironment(original,'/private','test-explicit');
  assert.equal(env.OPENAI_API_KEY,'test-explicit'); assert.equal(env.AMBI_NATIVE_HOST,'1'); assert.equal(env.AMBI_DATA_DIR,'/private');
});
test('Wayland, XWayland and headless sessions fail closed', () => {
  assert.equal(linuxSession({DISPLAY:':0',XDG_SESSION_TYPE:'x11'}),true);
  for(const env of [{},{DISPLAY:':0',XDG_SESSION_TYPE:'wayland'},{DISPLAY:':0',WAYLAND_DISPLAY:'wayland-0'}]) assert.equal(linuxSession(env),false);
});
