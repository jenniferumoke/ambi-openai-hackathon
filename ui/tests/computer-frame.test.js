import test from 'node:test';
import assert from 'node:assert/strict';
import { computerTaskActive, createComputerFrame } from '../src/computer-frame.js';

test('native Mac preview delegates to the display overlay without an app frame', () => {
  const messages = [], root = { dataset: {} }, banner = {};
  globalThis.window = { webkit: { messageHandlers: { ambi: { postMessage: value => messages.push(value) } } } };
  try {
    const frame = createComputerFrame({ root, banner, label: {},
      action: { addEventListener() {} }, stop() {} });
    frame.preview();
    assert.deepEqual(messages.at(-1), { type: 'frame-preview', enabled: true });
    assert.equal(root.dataset.computerFrame, 'idle');
    assert.equal(banner.hidden, true);
    frame.update({ job: { status: 'running' } }, true);
    assert.deepEqual(messages.at(-1), { type: 'frame-preview', enabled: false });
  } finally { delete globalThis.window; }
});

test('only a connected running task shows a live frame', () => {
  assert.equal(computerTaskActive({ job: { status: 'running' } }, true), true);
  for (const status of ['completed', 'cancelled', 'failed', undefined]) {
    assert.equal(computerTaskActive({ job: { status } }, true), false);
  }
  assert.equal(computerTaskActive({ job: { status: 'running' } }, false), false);
  assert.equal(computerTaskActive({ status: 'connected', phase: 'listening' }, true), false);
});

test('preview cannot stop a task; disconnect and completion remove live indication', () => {
  const root = { dataset: {} }, banner = {}, label = {};
  let click, stops = 0;
  const action = { addEventListener: (_, handler) => { click = handler; } };
  const frame = createComputerFrame({ root, banner, label, action, stop: () => { stops++; } });
  frame.preview();
  assert.equal(root.dataset.computerFrame, 'preview');
  assert.match(label.textContent, /preview/);
  click();
  assert.equal(stops, 0);
  assert.equal(banner.hidden, true);
  frame.update({ job: { status: 'running' } }, true);
  click();
  assert.equal(stops, 1);
  assert.equal(root.dataset.computerFrame, 'active'); // Await backend acknowledgement.
  frame.update({ job: { status: 'running' } }, false);
  assert.equal(banner.hidden, true);
  frame.update({ job: { status: 'completed' } }, true);
  assert.equal(banner.hidden, true);
});
