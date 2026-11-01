import test from 'node:test';
import assert from 'node:assert/strict';
import { proactiveStatus, screenStatus } from '../src/observation-status.js';

test('visible cues do not disguise a stopped or focused voice session', () => {
  assert.match(proactiveStatus({ status: 'error', proactive: { reason: 'offer_sent' } }), /stopped/);
  assert.match(proactiveStatus({ status: 'idle' }), /Start a voice session/);
  assert.match(proactiveStatus({ status: 'connected', proactive: { reason: 'focus_mode' } }), /Focus mode/);
  assert.match(proactiveStatus({ status: 'connected', proactive: { reason: 'already_offered' } }), /already made/);
});

test('missing permission, slow analysis and unknown observer payloads remain distinguishable', () => {
  assert.match(screenStatus({ status: 'disabled', reason: 'screen_permission_missing' }), /permission/);
  assert.match(screenStatus({ status: 'unavailable', reason: 'analysis_unavailable' }), /retrying/);
  assert.match(screenStatus({ status: 'unavailable', reason: 'screen_changed' }), /refreshing/);
  assert.match(screenStatus({ status: 'available' }), /primary display/);
  assert.equal(screenStatus({ status: 'future-status', payload: null }), 'Screen context off');
});
