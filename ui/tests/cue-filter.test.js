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
  ['confused_look', { browOuterUpLeft: .9, browOuterUpRight: .1, eyeSquintLeft: .8, eyeSquintRight: .8 }, 350],
  ['concentrating_look', { browDownLeft: .8, browDownRight: .8, eyeSquintLeft: .8, eyeSquintRight: .8 }, 500],
  ['irritated_look', { browDownLeft: .8, browDownRight: .8, mouthPressLeft: .8, mouthPressRight: .8 }, 300],
  ['tired_look', { jawOpen: .9, eyeSquintLeft: .8, eyeSquintRight: .8 }, 700],
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

test('a moderate mouth opening and one closed eye do not claim a composite look', () => {
  const filter = new CueFilter();
  const scores = { browDownLeft: .9, browDownRight: .9, jawOpen: .6, eyeBlinkLeft: .9 };
  let result;
  for (let at = 0; at <= 2000; at += 67) result = filter.update(scores, at);
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

function hold(filter, scores, start, duration, step = 50) {
  let result;
  for (let at = start; at <= start + duration; at += step) result = filter.update(scores, at);
  return result;
}

test('an open-eyed yawn becomes tired after a longer sustained opening', () => {
  const filter = new CueFilter();
  assert.deepEqual(hold(filter, { jawOpen: .85 }, 0, 1150).cues, []);
  const result = filter.update({ jawOpen: .85 }, 1200);
  assert.deepEqual(result.cues, ['tired_look']);
  assert.equal(result.detection_ms, 1200);
  assert.deepEqual(filter.update({}, 1250).cues, []);
});

test('a yawn with modest bilateral eye narrowing uses the faster path', () => {
  const filter = new CueFilter();
  const yawn = { jawOpen: .65, eyeSquintLeft: .32, eyeBlinkRight: .35 };
  assert.deepEqual(hold(filter, yawn, 0, 650).cues, []);
  const result = filter.update(yawn, 700);
  assert.deepEqual(result.cues, ['tired_look']);
  assert.equal(result.detection_ms, 700);
});

test('a developing yawn tolerates small jaw fluctuations and then clears on recovery', () => {
  const filter = new CueFilter();
  hold(filter, {}, 0, 200);
  hold(filter, { jawOpen: .5 }, 250, 150);
  let result;
  for (let at = 450; at <= 1750; at += 50) {
    result = filter.update({ jawOpen: at % 200 === 0 ? .69 : .82 }, at);
  }
  assert.deepEqual(result.cues, ['tired_look']);
  assert.deepEqual(filter.update({ jawOpen: .1 }, 1800).cues, []);
});

test('changing yawn patterns does not borrow the shorter hold time', () => {
  const filter = new CueFilter();
  hold(filter, { jawOpen: .65, eyeSquintLeft: .4, eyeSquintRight: .4 }, 0, 600);
  assert.deepEqual(hold(filter, { jawOpen: .85 }, 650, 1150).cues, []);
  assert.deepEqual(filter.update({ jawOpen: .85 }, 1850).cues, ['tired_look']);
});

test('a confirmed yawn stays tired as the eyes reopen, preserving initial detection time', () => {
  const filter = new CueFilter();
  const yawn = { jawOpen: .85, eyeBlinkLeft: .8, eyeBlinkRight: .8 };
  const initial = hold(filter, yawn, 0, 750);
  assert.deepEqual(initial.cues, ['tired_look']);
  for (let at = 800; at <= 1600; at += 50) {
    const result = filter.update({ jawOpen: .85 }, at);
    assert.deepEqual(result.cues, ['tired_look']);
    assert.equal(result.detection_ms, initial.detection_ms);
  }
  assert.deepEqual(filter.update({}, 1650).cues, []);
  const bothPaths = hold(new CueFilter(), yawn, 0, 1600);
  assert.equal(bothPaths.detection_ms, 700);
});

test('yawn-related brow tension and eye closure produce tired, not competing labels', () => {
  const filter = new CueFilter();
  const yawn = {
    jawOpen: .85, eyeBlinkLeft: .9, eyeBlinkRight: .9,
    eyeSquintLeft: .8, eyeSquintRight: .8,
    browDownLeft: .8, browDownRight: .8, browInnerUp: .5,
    mouthPressLeft: .6, mouthPressRight: .6, mouthFrownLeft: .5, mouthFrownRight: .5,
  };
  assert.deepEqual(hold(filter, yawn, 0, 1600).cues, ['tired_look']);
});

test('repeated speech-like mouth openings and brief blinks do not accumulate into tired or sleepy', () => {
  const filter = new CueFilter();
  for (let at = 0; at <= 5000; at += 50) {
    const open = at % 500 < 300;
    const blink = at % 1200 < 150 ? .95 : .05;
    const result = filter.update({ jawOpen: open ? .85 : .15, eyeBlinkLeft: blink, eyeBlinkRight: blink }, at);
    assert.deepEqual(result.cues, [], `unexpected cue at ${at} ms`);
  }
});

test('laughing and a wide-eyed open mouth are not yawns', () => {
  for (const expression of [
    { ...smile, jawOpen: .9, eyeSquintLeft: .8, eyeSquintRight: .8, eyeBlinkLeft: .85, eyeBlinkRight: .85 },
    { jawOpen: .9, eyeWideLeft: .8, eyeWideRight: .8, browInnerUp: .9 },
  ]) {
    const result = hold(new CueFilter(), expression, 0, 2000);
    assert.equal(result.cues.includes('tired_look'), false);
    assert.equal(result.cues.includes('sleepy_look'), false);
  }
});

test('moderate bilateral brow lowering is a furrow, without inventing a composite look', () => {
  const result = hold(new CueFilter(), { browDownLeft: .32, browDownRight: .36 }, 0, 1200);
  assert.deepEqual(result.cues, ['furrowed_brow']);
});

test('an isolated brow, eyebrow raise, squint, or wink is insufficient for a composite look', () => {
  for (const expression of [
    { browDownLeft: .95 }, { browOuterUpLeft: .9 },
    { browOuterUpLeft: .9, browOuterUpRight: .9, browInnerUp: .9 },
    { eyeSquintLeft: .8, eyeSquintRight: .8 }, { eyeBlinkLeft: .95 },
  ]) assert.deepEqual(hold(new CueFilter(), expression, 0, 2000).cues, []);
});

test('confused look supports mixed inner brow movement and corroborated brow asymmetry', () => {
  for (const expression of [
    { browDownLeft: .35, browDownRight: .4, browInnerUp: .45 },
    { browDownLeft: .7, browDownRight: .1, mouthPressLeft: .32, mouthPressRight: .35 },
    { browOuterUpLeft: .6, browOuterUpRight: .2, eyeSquintLeft: .3, eyeSquintRight: .35 },
  ]) {
    const filter = new CueFilter();
    assert.equal(hold(filter, expression, 0, 300).cues.includes('confused_look'), false);
    const result = filter.update(expression, 350);
    assert.equal(result.cues.includes('confused_look'), true);
    assert.equal(result.cues.includes('concentrating_look'), false);
  }
});

test('specific confused and irritated patterns take precedence over concentrating', () => {
  for (const [cue, extra] of [
    ['confused_look', { browInnerUp: .5 }],
    ['irritated_look', { mouthPressLeft: .7, mouthPressRight: .7 }],
  ]) {
    const filter = new CueFilter();
    const concentrating = { browDownLeft: .6, browDownRight: .6, eyeSquintLeft: .7, eyeSquintRight: .7 };
    assert.equal(hold(filter, concentrating, 0, 600).cues.includes('concentrating_look'), true);
    const result = hold(filter, { ...concentrating, ...extra }, 650, 600);
    assert.equal(result.cues.includes(cue), true);
    assert.equal(result.cues.includes('concentrating_look'), false);
  }
});

test('brief threshold jitter preserves a candidate but prolonged weak evidence resets it', () => {
  const closed = { eyeBlinkLeft: .8, eyeBlinkRight: .8 };
  const dip = { eyeBlinkLeft: .65, eyeBlinkRight: .65 };
  const filter = new CueFilter();
  hold(filter, closed, 0, 300);
  filter.update(dip, 350);
  assert.deepEqual(hold(filter, closed, 400, 300).cues, ['sleepy_look']);
  const held = filter.update(dip, 750);
  assert.deepEqual(held.cues, ['sleepy_look']);
  assert.equal(held.detection_ms, 700);
  filter.reset();
  hold(filter, closed, 0, 300);
  hold(filter, dip, 350, 200);
  assert.deepEqual(hold(filter, closed, 600, 650).cues, []);
  assert.deepEqual(filter.update(closed, 1300).cues, ['sleepy_look']);
});

test('separated positive frames cannot activate a short cue', () => {
  const filter = new CueFilter();
  for (let at = 0; at <= 1000; at += 50) {
    assert.deepEqual(filter.update(at % 100 === 0 ? smile : {}, at).cues, []);
  }
});

for (const step of [33, 67, 100, 200]) {
  test(`yawn timing works with ${step} ms between frames`, () => {
    const filter = new CueFilter();
    for (let at = 0; at <= 1400; at += step) {
      const result = filter.update({ jawOpen: .85 }, at);
      assert.equal(result.cues.includes('tired_look'), at >= 1200);
    }
  });
}

test('face loss, multiple faces, explicit reset, and frame gaps clear yawn evidence', () => {
  for (const reset of ['missing', 'multiple', 'reset', 'gap']) {
    const filter = new CueFilter();
    const yawn = { jawOpen: .85 };
    assert.deepEqual(hold(filter, yawn, 0, 1300).cues, ['tired_look']);
    if (reset === 'reset') filter.reset();
    else if (reset !== 'gap') {
      assert.deepEqual(filter.update(yawn, 1350, reset === 'missing' ? 0 : 2),
        { cues: [], scores: {}, usable: false, detection_ms: 0 });
    }
    const start = reset === 'gap' ? 2000 : 1400;
    assert.deepEqual(hold(filter, yawn, start, 1150).cues, []);
    assert.deepEqual(filter.update(yawn, start + 1200).cues, ['tired_look']);
  }
});

test('output keeps the nine public cue names and finite scores; invalid values cannot create cues', () => {
  const invalid = { jawOpen: Infinity, eyeBlinkLeft: NaN, eyeBlinkRight: .9, browDownLeft: '1', browDownRight: 1 };
  const result = hold(new CueFilter(), invalid, 0, 2000);
  assert.deepEqual(result.cues, []);
  assert.deepEqual(Object.keys(result.scores).sort(), [
    'smiling', 'frowning', 'furrowed_brow', 'tense_expression', 'confused_look',
    'concentrating_look', 'irritated_look', 'tired_look', 'sleepy_look',
  ].sort());
  assert.ok(Object.values(result.scores).every(score => Number.isFinite(score) && score >= 0 && score <= 1));
});
