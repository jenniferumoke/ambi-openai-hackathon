export class Camera {
  constructor(video, onSignal, onStatus) {
    Object.assign(this, { video, onSignal, onStatus, generation: 0 });
  }
  async start() {
    if (this.stream || this.starting) return;
    this.starting = true;
    const generation = ++this.generation;
    this.onStatus('loading', 'Opening camera…');
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480, frameRate: 15 }, audio: false });
      if (generation !== this.generation) { stream.getTracks().forEach(t => t.stop()); return; }
      this.stream = stream; this.video.srcObject = stream;
      await this.video.play();
      if (generation !== this.generation) return;
      this.worker = new Worker(new URL('./camera-worker.js', import.meta.url));
      this.ready = false; this.busy = false;
      this.timeout = setTimeout(() => { this.stop(); this.onStatus('error', 'Camera model took too long to load. Try again.'); }, 30000);
      this.worker.onerror = () => {
        if (generation !== this.generation) return;
        this.stop(); this.onStatus('error', 'Could not start local vision. Check browser support and try again.');
      };
      this.worker.onmessage = ({ data }) => {
        if (generation !== this.generation) return;
        if (data.type === 'ready') {
          clearTimeout(this.timeout); this.ready = true;
          this.onStatus('active', 'Camera active · processed locally');
        } else if (data.type === 'signal') {
          this.busy = false;
          const age = Math.max(0, performance.now() - data.at);
          if (age <= 1500) this.onSignal({ ...data, age_ms: age });
        } else if (data.type === 'error') {
          this.stop(); this.onStatus('error', 'Local camera detection failed. You can still use voice and notes.');
        }
      };
      this.worker.postMessage({ type: 'init', origin: location.origin });
      let lastVideoTime = -1;
      const tick = async () => {
        if (generation !== this.generation) return;
        // Animation callbacks stop in background tabs. A bounded timer keeps
        // sampling when the browser permits it while the user works elsewhere.
        this.frame = setTimeout(tick, 67);
        if (!this.ready || this.busy || this.video.readyState < 2 || this.video.currentTime === lastVideoTime) return;
        const at = performance.now();
        lastVideoTime = this.video.currentTime;
        this.busy = true;
        try {
          const bitmap = await createImageBitmap(this.video);
          if (generation !== this.generation) { bitmap.close(); return; }
          this.worker.postMessage({ type: 'frame', bitmap, at }, [bitmap]);
        } catch { this.busy = false; }
      };
      this.frame = setTimeout(tick, 0);
    } catch (error) {
      if (generation !== this.generation) return;
      this.stop();
      this.onStatus('error', error.name === 'NotAllowedError' ? 'Camera permission denied. Allow it in your browser to enable cues.' : 'Camera unavailable. Close other camera apps and try again.');
    } finally { if (generation === this.generation) this.starting = false; }
  }
  stop() {
    this.generation++; this.starting = false;
    clearTimeout(this.timeout); clearTimeout(this.frame);
    this.worker?.terminate(); this.worker = null;
    this.stream?.getTracks().forEach(track => track.stop()); this.stream = null;
    this.video.srcObject = null; this.onStatus('off', 'Camera is off');
  }
}
