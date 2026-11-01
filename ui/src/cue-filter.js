// Blendshape scores describe visible geometry, never probabilities of feelings.
// These are heuristic operating points, not a trained emotion classifier.
const CONFIG = {
  smiling: { threshold: .45, holdMs: 0 },
  frowning: { threshold: .35, holdMs: 0 },
  furrowed_brow: { threshold: .28, holdMs: 0 },
  tense_expression: { threshold: .45, holdMs: 0 },
  confused_look: { threshold: .25, holdMs: 350 },
  concentrating_look: { threshold: .3, holdMs: 500 },
  irritated_look: { threshold: .4, holdMs: 300 },
  tired_look: { threshold: .55, holdMs: 700 },
  // An open-eyed yawn needs a wider, longer mouth opening than the eye-assisted
  // path. Separate timers prevent switching paths from borrowing a shorter hold.
  wide_yawn: { cue: 'tired_look', threshold: .72, holdMs: 1200 },
  sleepy_look: { threshold: .7, holdMs: 700 },
};
const MAX_FRAME_GAP_MS = 500;
const MAX_THRESHOLD_DIP_MS = 150;

function patternStrengths(scores, confirmedYawn) {
  const val = name => Number.isFinite(scores[name]) ? Math.max(0, Math.min(1, scores[name])) : 0;
  const average = (a, b) => (val(a) + val(b)) / 2;
  const both = (a, b) => Math.min(val(a), val(b));
  const smile = average('mouthSmileLeft', 'mouthSmileRight');
  const frown = average('mouthFrownLeft', 'mouthFrownRight');
  // Require support on both sides: a single lowered brow is asymmetry, not a
  // bilateral furrow. A lower entry point still catches moderate real furrows.
  const browDown = both('browDownLeft', 'browDownRight');
  const mouthPress = average('mouthPressLeft', 'mouthPressRight');
  const squint = both('eyeSquintLeft', 'eyeSquintRight');
  const blink = both('eyeBlinkLeft', 'eyeBlinkRight');
  const narrowedEyes = Math.min(
    Math.max(val('eyeSquintLeft'), val('eyeBlinkLeft')),
    Math.max(val('eyeSquintRight'), val('eyeBlinkRight')),
  );
  const browDifference = Math.max(
    Math.abs(val('browOuterUpLeft') - val('browOuterUpRight')),
    Math.abs(val('browDownLeft') - val('browDownRight')),
  );
  const sneer = average('noseSneerLeft', 'noseSneerRight');
  const jaw = val('jawOpen');
  const smiling = smile >= CONFIG.smiling.threshold;
  const wideEyes = average('eyeWideLeft', 'eyeWideRight') >= .45;
  const canYawn = !smiling && !wideEyes;
  // Once a yawn is confirmed, reopening the eyes should not interrupt it while
  // the jaw remains open. This continuation cannot shorten initial detection.
  const yawn = canYawn ? (confirmedYawn && jaw >= CONFIG.tired_look.threshold
    ? jaw : Math.min(jaw, narrowedEyes * 2)) : 0;
  const wideYawn = canYawn ? jaw : 0;
  const yawnPosture = yawn >= CONFIG.tired_look.threshold || wideYawn >= CONFIG.wide_yawn.threshold;
  const quietMouth = jaw < .35 && !smiling;
  // Uneven brows with a second cue, or inner-brow lift together with lowering.
  // A symmetric eyebrow raise, plain furrow, or isolated squint is insufficient.
  const confused = quietMouth ? Math.max(
    Math.min(browDifference, Math.max(squint, mouthPress, frown)),
    Math.min(val('browInnerUp'), browDown),
  ) : 0;
  const irritated = quietMouth ? Math.min(browDown, Math.max(mouthPress, sneer), 1 - blink) : 0;
  const concentrating = quietMouth
    && confused < CONFIG.confused_look.threshold && irritated < CONFIG.irritated_look.threshold
    ? Math.min(browDown, squint, 1 - blink) : 0;
  return {
    smiling: smile,
    frowning: smiling || yawnPosture ? 0 : frown,
    furrowed_brow: yawnPosture ? 0 : browDown,
    tense_expression: yawnPosture ? 0 : mouthPress,
    confused_look: confused,
    concentrating_look: concentrating,
    irritated_look: irritated,
    tired_look: yawn,
    wide_yawn: wideYawn,
    // Closed eyes during yawning or laughing should not add a second label.
    sleepy_look: quietMouth ? blink : 0,
  };
}

export class CueFilter {
  constructor() { this.reset(); }
  reset() { this.evidence = {}; this.lastAt = -Infinity; }
  update(scores, at, faceCount = 1) {
    if (!Number.isFinite(at) || at <= this.lastAt) return null;
    if (at - this.lastAt > MAX_FRAME_GAP_MS) this.reset();
    this.lastAt = at;
    if (faceCount !== 1) {
      this.evidence = {};
      return { cues: [], scores: {}, usable: false, detection_ms: 0 };
    }
    const strengths = patternStrengths(scores,
      this.evidence.tired_look?.active || this.evidence.wide_yawn?.active);
    const active = new Map();
    const cueScores = {};
    for (const [pattern, { cue = pattern, threshold, holdMs }] of Object.entries(CONFIG)) {
      const strength = strengths[pattern];
      cueScores[cue] = Math.max(cueScores[cue] ?? 0, strength);
      let evidence = this.evidence[pattern];
      // Neutral frames immediately break continuity. Brief near-threshold dips
      // preserve a candidate, but never turn weak evidence into an activation.
      if (strength < threshold * .65) {
        delete this.evidence[pattern];
        continue;
      }
      if (strength >= threshold) {
        evidence ??= this.evidence[pattern] = { started: at, frames: 0, active: false };
        evidence.frames++;
        evidence.lastStrong = at;
        if (!evidence.active && evidence.frames >= 3 && at - evidence.started >= holdMs) {
          evidence.active = true;
          evidence.latency = at - evidence.started;
        }
      } else if (evidence && !evidence.active && at - evidence.lastStrong > MAX_THRESHOLD_DIP_MS) {
        delete this.evidence[pattern];
        continue;
      }
      if (evidence?.active) {
        const first = active.get(cue);
        // Multiple paths for the same public cue retain the first detection.
        if (!first || evidence.started + evidence.latency < first.started + first.latency) {
          active.set(cue, evidence);
        }
      }
    }
    const latency = Math.max(0, ...[...active.values()].map(evidence => evidence.latency));
    return { cues: [...active.keys()], scores: cueScores, usable: true, detection_ms: Math.round(latency) };
  }
}
