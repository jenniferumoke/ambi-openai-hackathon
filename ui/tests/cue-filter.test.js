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

const patterns = [
  ['confused_look', { browOuterUpLeft: .9, browOuterUpRight: .1, eyeSquintLeft: .8, eyeSquintRight: .8 }, 300],
  ['concentrating_look', { browDownLeft: .8, browDownRight: .8, eyeSquintLeft: .8, eyeSquintRight: .8 }, 500],
  ['irritated_look', { browDownLeft: .8, browDownRight: .8, mouthPressLeft: .8, mouthPressRight: .8 }, 300],
  ['tired_look', { jawOpen: .9, eyeSquintLeft: .8, eyeSquintRight: .8 }, 650],
  ['sleepy_look', { eyeBlinkLeft: .9, eyeBlinkRight: .9 }, 700],
];
for (const [cue, scores, holdMs] of patterns) {
  test(`${cue} requires its visible pattern to persist`, () => {
    const filter = new CueFilter();
    let result;
    for (let at = 0; at < holdMs; at += 67) result = filter.update(scores, at);
    assert.equal(result.cues.includes(cue), false);
    for (let at = Math.ceil(holdMs / 67) * 67; at <= 1000; at += 67) result = filter.update(scores, at);
    assert.equal(result.cues.includes(cue), true);
    assert.deepEqual(filter.update({}, 1067).cues, []);
  });
}

test('isolated brow, mouth, or one closed eye does not claim a composite look', () => {
  const filter = new CueFilter();
  const scores = { browDownLeft: .9, browDownRight: .9, jawOpen: .9, eyeBlinkLeft: .9 };
  let result;
  for (let at = 0; at <= 1000; at += 67) result = filter.update(scores, at);
  for (const cue of ['confused_look', 'concentrating_look', 'irritated_look', 'tired_look', 'sleepy_look']) {
    assert.equal(result.cues.includes(cue), false);
  }
});

test('a missing face or long frame gap clears sustained look evidence', () => {
  const filter = new CueFilter();
  const closed = { eyeBlinkLeft: .9, eyeBlinkRight: .9 };
  for (let at = 0; at <= 402; at += 67) filter.update(closed, at);
  assert.equal(filter.update(closed, 469, 0).usable, false);
  assert.deepEqual(filter.update(closed, 536).cues, []);
  assert.deepEqual(filter.update(closed, 1200).cues, []);
});
