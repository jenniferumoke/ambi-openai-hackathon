// Blendshape scores describe visible geometry, never probabilities of feelings.
const CONFIG = {
  smiling: { threshold: .45, holdMs: 0 },
  frowning: { threshold: .35, holdMs: 0 },
  furrowed_brow: { threshold: .4, holdMs: 0 },
  tense_expression: { threshold: .45, holdMs: 0 },
  confused_look: { threshold: .35, holdMs: 300 },
  concentrating_look: { threshold: .35, holdMs: 500 },
  irritated_look: { threshold: .4, holdMs: 300 },
  tired_look: { threshold: .5, holdMs: 650 },
  sleepy_look: { threshold: .7, holdMs: 700 },
};

export class CueFilter {
  constructor() { this.reset(); }
  reset() { this.samples = []; this.active = new Set(); this.started = {}; this.latencies = {}; this.lastAt = -Infinity; }
  update(scores, at, faceCount = 1) {
    if (!Number.isFinite(at) || at <= this.lastAt) return null;
    if (at - this.lastAt > 500) this.reset();
    this.lastAt = at;
    if (faceCount !== 1) {
      this.samples = []; this.active.clear(); this.started = {}; this.latencies = {};
      return { cues: [], scores: {}, usable: false, detection_ms: 0 };
    }
    const val = name => Math.max(0, Math.min(1, Number(scores[name]) || 0));
    const average = (a, b) => (val(a) + val(b)) / 2;
    const smile = average('mouthSmileLeft', 'mouthSmileRight');
    const frown = average('mouthFrownLeft', 'mouthFrownRight');
    const browDown = average('browDownLeft', 'browDownRight');
    const mouthPress = average('mouthPressLeft', 'mouthPressRight');
    const squint = average('eyeSquintLeft', 'eyeSquintRight');
    const blink = Math.min(val('eyeBlinkLeft'), val('eyeBlinkRight'));
    const outerBrowDifference = Math.abs(val('browOuterUpLeft') - val('browOuterUpRight'));
    const sneer = average('noseSneerLeft', 'noseSneerRight');
    const cues = {
      smiling: smile,
      frowning: frown,
      furrowed_brow: browDown,
      tense_expression: mouthPress,
      // Composite labels are shorthand for these visible patterns, not states of mind.
      confused_look: Math.min(outerBrowDifference, squint),
      concentrating_look: Math.min(browDown, squint),
      irritated_look: Math.min(browDown, Math.max(mouthPress, sneer)),
      tired_look: Math.min(val('jawOpen'), Math.max(squint, blink)),
      sleepy_look: blink,
    };
    this.samples.push({ at, cues });
    this.samples = this.samples.filter(sample => at - sample.at <= 350).slice(-5);
    let latency = 0;
    for (const [cue, strength] of Object.entries(cues)) {
      const { threshold, holdMs } = CONFIG[cue];
      if (strength >= threshold) {
        this.started[cue] ??= at;
        const supporting = this.samples.filter(sample => sample.cues[cue] >= threshold);
        if (supporting.length >= 3 && at - this.started[cue] >= holdMs) {
          if (!this.active.has(cue)) this.latencies[cue] = at - this.started[cue];
          this.active.add(cue);
          latency = Math.max(latency, this.latencies[cue]);
        }
      } else {
        delete this.started[cue];
        if (strength < threshold * .65) {
          this.active.delete(cue); delete this.latencies[cue];
        }
      }
    }
    return { cues: [...this.active], scores: cues, usable: true, detection_ms: Math.round(latency) };
  }
}
