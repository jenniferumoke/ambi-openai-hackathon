import { mkdir, cp, access, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
const root = fileURLToPath(new URL('../', import.meta.url));
await mkdir(root + 'public/vision', { recursive: true });
await cp(root + 'node_modules/@mediapipe/tasks-vision/wasm', root + 'public/vision/wasm', { recursive: true });
await mkdir(root + 'public/models', { recursive: true });
const model = root + 'public/models/face_landmarker.task';
try { await access(model); } catch {
  const url = 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task';
  const response = await fetch(url, { signal: AbortSignal.timeout(60000) });
  if (!response.ok) throw new Error(`Model download failed: ${response.status}`);
  const data = new Uint8Array(await response.arrayBuffer());
  if (data.length < 1000000) throw new Error('Incomplete face model');
  await writeFile(model, data);
}
console.log('Local vision assets ready. Camera frames stay on this device.');
