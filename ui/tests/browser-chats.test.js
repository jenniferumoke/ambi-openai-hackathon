import test from 'node:test';
import assert from 'node:assert/strict';
import { BROWSER_CHATS, chatHandoff } from '../src/browser-chats.js';
test('handoff uses only the three fixed HTTPS destinations and keeps draft out of URL',()=>{
 for(const id of ['chatgpt','claude','gemini']) {
  const h=chatHandoff(id,' Private draft & token? ');
  assert.equal(h.draft,'Private draft & token?'); assert.equal(h.url,BROWSER_CHATS[id].url);
  const url=new URL(h.url); assert.equal(url.protocol,'https:');assert.equal(url.search,'');assert.equal(url.hash,'');
 }
});
test('unknown destinations and invalid drafts fail closed',()=>{
 for(const id of ['__proto__','constructor','https://evil.test/','javascript:alert(1)'])assert.throws(()=>chatHandoff(id));
 for(const draft of [null,{},'x'.repeat(4001)])assert.throws(()=>chatHandoff('chatgpt',draft));
 assert.equal(chatHandoff('claude').draft,'');
});
