import { FaceLandmarker, FilesetResolver } from '@mediapipe/tasks-vision';
import { CueFilter } from './cue-filter.js';
let landmarker;
const filter = new CueFilter();
self.onmessage = async ({ data }) => {
  if (data.type === 'init') {
    try {
      const files = await FilesetResolver.forVisionTasks(data.origin + '/vision/wasm');
      landmarker = await FaceLandmarker.createFromOptions(files, {
        baseOptions: { modelAssetPath: data.origin + '/models/face_landmarker.task', delegate: 'CPU' },
        runningMode: 'VIDEO', numFaces: 2, outputFaceBlendshapes: true,
        minFaceDetectionConfidence: .6, minFacePresenceConfidence: .6, minTrackingConfidence: .6,
      });
      self.postMessage({ type: 'ready' });
    } catch (error) { self.postMessage({ type: 'error', message: String(error.message || error) }); }
  } else if (data.type === 'frame') {
    const started = performance.now();
    try {
      const result = landmarker.detectForVideo(data.bitmap, data.at);
      const scores = Object.fromEntries((result.faceBlendshapes[0]?.categories || []).map(c => [c.categoryName, c.score]));
      const signal = filter.update(scores, data.at, result.faceLandmarks.length);
      self.postMessage({ type: 'signal', ...signal, at: data.at,
        inference_ms: Math.round(performance.now() - started), face_count: result.faceLandmarks.length });
    } catch (error) { self.postMessage({ type: 'error', message: String(error.message || error) }); }
    finally { data.bitmap.close(); }
  } else if (data.type === 'reset') filter.reset();
};
