import { Rive, Layout, Fit, Alignment, RuntimeLoader } from '@rive-app/canvas';
import wasmUrl from '@rive-app/canvas/rive_fallback.wasm?url';
import { createPoseController } from './character-pose.js';

RuntimeLoader.setWasmUrl(wasmUrl);
const canvas = document.querySelector('#ambi');
const motion = matchMedia('(prefers-reduced-motion: reduce)');
let latest, desiredPose = 'waiting', currentPose;
const poses = createPoseController({ changed: () => { if (latest) renderCharacter(latest); } });
const rive = new Rive({
  src: '/ambi.riv', canvas, artboard: 'Ambi', stateMachine: 'Ambi Controller',
  autoplay: true, autoBind: true,
  layout: new Layout({ fit: Fit.Contain, alignment: Alignment.Center }),
  onLoad() { rive.resizeDrawingSurfaceToCanvas(); applyPose(); applyMotion(); },
  onLoadError() {
    const title = document.querySelector('#hero-title');
    title.textContent = 'Ambi couldn’t load. Please reload.';
    title.classList.remove('sr-only');
  },
});
function applyPose() {
  const pose = rive.viewModelInstance?.enum('pose');
  if (!pose || currentPose === desiredPose) return;
  pose.value = desiredPose;
  currentPose = desiredPose;
  canvas.dataset.pose = currentPose;
  canvas.setAttribute('aria-label', `Ambi ${currentPose}`);
}
function applyMotion() {
  const play = rive.viewModelInstance?.boolean('play');
  if (play) { play.value = !motion.matches; canvas.dataset.play = String(play.value); }
}
export function renderCharacter(state) {
  latest = state;
  desiredPose = poses.update(state);
  applyPose();
}
const resize = new ResizeObserver(() => rive.resizeDrawingSurfaceToCanvas());
resize.observe(canvas);
motion.addEventListener('change', applyMotion);
document.addEventListener('keydown', event => {
  if (event.code !== 'Space' || event.repeat || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
  if (event.target.closest('input, textarea, select, [contenteditable="true"], button:not(#start), a')) return;
  event.preventDefault();
  document.querySelector('#start').click();
});
window.addEventListener('pagehide', () => {
  poses.dispose(); resize.disconnect(); motion.removeEventListener('change', applyMotion); rive.cleanup();
});
