import { Rive, Layout, Fit, Alignment, RuntimeLoader } from '@rive-app/canvas';
import wasmUrl from '@rive-app/canvas/rive_fallback.wasm?url';
import { createPoseController } from './character-pose.js';

RuntimeLoader.setWasmUrl(wasmUrl);
const canvas = document.querySelector('#ambi');
const companionSurface = canvas.dataset.source === '/ambi-companion.riv';
// Keep the companion's backing surface stable as its CSS layout moves/resizes.
// Reallocating this canvas during WKWebView layout can discard its rendered art.
if (companionSurface) { canvas.width = 1360; canvas.height = 960; }
const motion = matchMedia('(prefers-reduced-motion: reduce)');
let latest, desiredPose = 'waiting', currentPose;
let animationEnabled = true, displayName = 'Ambi';
const poses = createPoseController({ changed: () => { if (latest) renderCharacter(latest); } });
const rive = new Rive({
  src: canvas.dataset.source || '/ambi.riv', canvas, artboard: 'Ambi', stateMachine: 'Ambi Controller',
  autoplay: true, autoBind: true,
  layout: new Layout({ fit: Fit.Contain, alignment: Alignment.Center }),
  onLoad() { resizeSurface(); applyPose(); applyMotion(); },
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
  canvas.setAttribute('aria-label', `${displayName} ${currentPose}`);
}
function applyMotion() {
  const play = rive.viewModelInstance?.boolean('play');
  if (play) { play.value = animationEnabled && !motion.matches; canvas.dataset.play = String(play.value); }
  rive.startRendering();
}
export function customizeCharacter(settings, filter) {
  animationEnabled = settings.animated;
  displayName = settings.displayName;
  canvas.style.filter = filter;
  canvas.setAttribute('aria-label', `${displayName} ${currentPose || 'waiting'}`);
  applyMotion();
}
export function renderCharacter(state) {
  latest = state;
  desiredPose = poses.update(state);
  applyPose();
}
function resizeSurface() {
  if (companionSurface) rive.resizeToCanvas();
  else rive.resizeDrawingSurfaceToCanvas();
  rive.startRendering();
}
const resize = new ResizeObserver(resizeSurface);
resize.observe(canvas);
motion.addEventListener('change', applyMotion);
document.addEventListener('keydown', event => {
  if (document.querySelector('dialog[open], #connection-dialog:not([hidden])')) return;
  if (event.code !== 'Space' || event.repeat || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
  if (event.target.closest('input, textarea, select, [contenteditable="true"], button:not(#start), a')) return;
  event.preventDefault();
  document.querySelector('#start').click();
});
window.addEventListener('pagehide', () => {
  poses.dispose(); resize.disconnect(); motion.removeEventListener('change', applyMotion); rive.cleanup();
});
