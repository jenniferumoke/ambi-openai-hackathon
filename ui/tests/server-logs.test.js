import test from 'node:test';
import assert from 'node:assert/strict';
import { createServerLog } from '../src/server-logs.js';

test('rolling snapshots retain errors without duplicating events', () => {
  const logs = createServerLog();
  const connected = { id: 'a', type: 'connected', at: 20000 };
  const error = { id: 'b', type: 'session_error', at: 20002.5, message: 'Session stopped (RuntimeError).' };
  logs.update([connected, error]);
  const text = logs.update([error, { id: 'c', type: 'session_stopped', at: 20003 }]);
  assert.equal(text.match(/session_error/g).length, 1);
  assert.match(text, /connected/);
  assert.match(text, /\[\+2\.500s\] session_error/);
  assert.match(text, /Session stopped \(RuntimeError\)/);
  assert.equal(logs.update([]), text);
});

test('log retention is bounded and a server restart resets the elapsed clock', () => {
  const logs = createServerLog(2);
  const text = logs.update([0, 1, 2].map(i => ({ id: String(i), type: `event_${i}`, at: 100 + i })));
  assert.doesNotMatch(text, /event_0/);
  assert.match(text, /event_2/);
  logs.reset();
  assert.equal(logs.update([{ id: 'new', type: 'connected', at: 5 }]), '[+0.000s] connected');
});

test('only diagnostic fields are displayed and absent timestamps stay unknown', () => {
  const logs = createServerLog();
  const text = logs.update([null, {}, { id: 'a', type: 'audio_fallback', reason: 'voice_processing_start_failed',
    token: 'private-token', request: { body: 'private-request' }, task: 'private task text' }]);
  assert.match(text, /\[—\] audio_fallback/);
  assert.match(text, /voice_processing_start_failed/);
  assert.doesNotMatch(text, /private/);
});

test('clearing hides repeated snapshot events but allows new events through', () => {
  const logs = createServerLog();
  const old = { id: 'old', type: 'connected', at: 100 };
  const recent = { id: 'recent', type: 'session_stopped', at: 110 };
  logs.update([old, recent]);
  logs.clear([recent]);
  assert.equal(logs.update([recent]), '');
  assert.equal(logs.update([recent]), '');
  const fresh = { id: 'fresh', type: 'connected', at: 120 };
  assert.equal(logs.update([recent, fresh]), '[+0.000s] connected');
  logs.clear([recent, fresh]);
  assert.equal(logs.update([recent, fresh]), '');
  logs.reset();
  assert.equal(logs.update([recent]), '[+0.000s] session_stopped');
});
