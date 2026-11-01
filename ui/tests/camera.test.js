import test from 'node:test';
import assert from 'node:assert/strict';
import { Camera } from '../src/camera.js';

function setup(t) {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const workers = [], frames = [], signals = [], tracks = [];
  const video = { readyState: 2, currentTime: 1, srcObject: null, play: async () => {} };
  const globals = {
    navigator: { mediaDevices: { getUserMedia: async () => {
      const track = { stopped: false, stop() { this.stopped = true; } };
      tracks.push(track);
      return { getTracks: () => [track] };
    } } },
    location: { origin: 'http://127.0.0.1:8765' },
    createImageBitmap: async () => ({ close() {} }),
    requestAnimationFrame() { throw Error('Camera must not rely on animation callbacks'); },
    Worker: class {
      constructor() { workers.push(this); }
      terminate() { this.terminated = true; }
      postMessage(data) {
        if (data.type === 'init') this.onmessage({ data: { type: 'ready' } });
        if (data.type === 'frame') {
          frames.push(data);
          this.onmessage({ data: { type: 'signal', at: data.at, usable: true, cues: [], scores: {} } });
        }
      }
    },
  };
  for (const [name, value] of Object.entries(globals)) {
    const descriptor = Object.getOwnPropertyDescriptor(globalThis, name);
    Object.defineProperty(globalThis, name, { configurable: true, writable: true, value });
    t.after(() => descriptor ? Object.defineProperty(globalThis, name, descriptor) : delete globalThis[name]);
  }
  const camera = new Camera(video, signal => signals.push(signal), () => {});
  t.after(() => camera.stop());
  return { camera, video, workers, frames, signals, tracks };
}

test('camera samples without animation frames and never counts a frozen video frame twice', async t => {
  const { camera, video, frames, signals } = setup(t);
  await camera.start();
  t.mock.timers.tick(1);
  await Promise.resolve();
  assert.equal(frames.length, 1);
  t.mock.timers.tick(670);
  await Promise.resolve();
  assert.equal(frames.length, 1);
  video.currentTime = 2;
  t.mock.timers.tick(67);
  await Promise.resolve();
  assert.equal(frames.length, 2);
  assert.equal(signals.length, 2);
  camera.stop();
  video.currentTime = 3;
  t.mock.timers.tick(1000);
  await Promise.resolve();
  assert.equal(frames.length, 2);
});

test('a delayed video start cannot resurrect a stopped camera or replace its new worker', async t => {
  const { camera, video, workers, tracks } = setup(t);
  let finishPlay;
  video.play = () => new Promise(resolve => { finishPlay = resolve; });
  const oldStart = camera.start();
  await Promise.resolve();
  camera.stop();
  video.play = async () => {};
  await camera.start();
  finishPlay();
  await oldStart;
  assert.equal(workers.length, 1);
  assert.equal(camera.worker, workers[0]);
  assert.equal(workers[0].terminated, undefined);
  assert.equal(tracks[0].stopped, true);
  assert.equal(tracks[1].stopped, false);
});
