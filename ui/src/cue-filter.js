// Blendshape scores are expression geometry, never probabilities of feelings.
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
    const cues = {
      smiling: average('mouthSmileLeft', 'mouthSmileRight'),
      frowning: average('mouthFrownLeft', 'mouthFrownRight'),
      furrowed_brow: average('browDownLeft', 'browDownRight'),
      tense_expression: average('mouthPressLeft', 'mouthPressRight'),
    };
    const thresholds = { smiling: .45, frowning: .35, furrowed_brow: .4, tense_expression: .45 };
    this.samples.push({ at, cues });
    this.samples = this.samples.filter(sample => at - sample.at <= 350).slice(-5);
    let latency = 0;
    for (const [cue, strength] of Object.entries(cues)) {
      if (strength >= thresholds[cue]) {
        this.started[cue] ??= at;
        const supporting = this.samples.filter(sample => sample.cues[cue] >= thresholds[cue]);
        if (supporting.length >= 3) {
          if (!this.active.has(cue)) this.latencies[cue] = at - this.started[cue];
          this.active.add(cue);
          latency = Math.max(latency, this.latencies[cue]);
        }
      } else if (strength < thresholds[cue] * .65) {
        this.active.delete(cue); delete this.started[cue]; delete this.latencies[cue];
      }
    }
    return { cues: [...this.active], scores: cues, usable: true, detection_ms: Math.round(latency) };
  }
}
