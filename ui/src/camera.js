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
      this.worker = new Worker(new URL('./camera-worker.js', import.meta.url));
      this.ready = false; this.busy = false; this.lastAt = 0;
      this.timeout = setTimeout(() => { this.stop(); this.onStatus('error', 'Camera model took too long to load. Try again.'); }, 30000);
      this.worker.onerror = () => { this.stop(); this.onStatus('error', 'Could not start local vision. Check browser support and try again.'); };
      this.worker.onmessage = ({ data }) => {
        if (generation !== this.generation) return;
        if (data.type === 'ready') {
          clearTimeout(this.timeout); this.ready = true;
          this.onStatus('active', 'Camera active · processed locally');
        } else if (data.type === 'signal') {
          this.busy = false;
          this.onSignal({ ...data, age_ms: Math.max(0, performance.now() - data.at) });
        } else if (data.type === 'error') {
          this.stop(); this.onStatus('error', 'Local camera detection failed. You can still use voice and notes.');
        }
      };
      this.worker.postMessage({ type: 'init', origin: location.origin });
      const tick = async at => {
        if (generation !== this.generation) return;
        this.frame = requestAnimationFrame(tick);
        if (!this.ready || this.busy || at - this.lastAt < 66 || this.video.readyState < 2) return;
        this.busy = true; this.lastAt = at;
        try {
          const bitmap = await createImageBitmap(this.video);
          if (generation !== this.generation) { bitmap.close(); return; }
          this.worker.postMessage({ type: 'frame', bitmap, at }, [bitmap]);
        } catch { this.busy = false; }
      };
      this.frame = requestAnimationFrame(tick);
    } catch (error) {
      this.stop();
      this.onStatus('error', error.name === 'NotAllowedError' ? 'Camera permission denied. Allow it in your browser to enable cues.' : 'Camera unavailable. Close other camera apps and try again.');
    } finally { this.starting = false; }
  }
  stop() {
    this.generation++; this.starting = false;
    clearTimeout(this.timeout); cancelAnimationFrame(this.frame);
    this.worker?.terminate(); this.worker = null;
    this.stream?.getTracks().forEach(track => track.stop()); this.stream = null;
    this.video.srcObject = null; this.onStatus('off', 'Camera is off');
  }
}
