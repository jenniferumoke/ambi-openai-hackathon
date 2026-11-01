import test from 'node:test';
import assert from 'node:assert/strict';
import { CueFilter } from '../src/cue-filter.js';
const smile = { mouthSmileLeft: .8, mouthSmileRight: .9 };
test('brief expression is detected in 134 ms and resets on neutral', () => {
  const filter = new CueFilter();
  filter.update({}, 0);
  assert.deepEqual(filter.update(smile, 66).cues, []);
  assert.deepEqual(filter.update(smile, 133).cues, []);
  const result = filter.update(smile, 200);
  assert.deepEqual(result.cues, ['smiling']);
  assert.equal(result.detection_ms, 134);
  assert.deepEqual(filter.update({}, 267).cues, []);
});
test('one noisy frame, missing face, and a second face cannot become a stable cue', () => {
  const filter = new CueFilter();
  filter.update(smile, 0); filter.update({}, 67);
  assert.deepEqual(filter.update({}, 134).cues, []);
  filter.update(smile, 201); filter.update(smile, 268);
  assert.equal(filter.update(smile, 335, 2).usable, false);
  assert.deepEqual(filter.update(smile, 402).cues, []);
  assert.equal(filter.update(smile, 469, 0).usable, false);
});
test('old frames and long gaps cannot accumulate evidence', () => {
  const filter = new CueFilter();
  filter.update(smile, 100); filter.update(smile, 167);
  assert.equal(filter.update(smile, 150), null);
  assert.deepEqual(filter.update(smile, 1000).cues, []);
});
