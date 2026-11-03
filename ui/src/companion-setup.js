import { Rive, Layout, Fit, Alignment } from '@rive-app/canvas';
import { COLORS, normalizeSettings, colorFilter } from './companion-settings.js';

export function createSetup({ getSettings, save, onOpen, onClose }) {
  const dialog = document.querySelector('#setup-dialog');
  const name = document.querySelector('#setup-name');
  const previewCanvas = document.querySelector('#setup-preview');
  const tileCanvas = document.querySelector('#setup-character');
  let draft, previews = [], invoker;
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
  function render() {
    document.querySelector('#setup-preview-name').textContent = draft.displayName;
    const stage = document.querySelector('#setup-stage');
    stage.dataset.background = draft.background;
    stage.style.setProperty('--preview-scale', draft.scale);
    for (const canvas of [previewCanvas, tileCanvas]) canvas.style.filter = colorFilter(draft.color);
    for (const rive of previews) {
      const pose = rive.viewModelInstance?.enum('pose'); if (pose) pose.value = 'waiting';
      const play = rive.viewModelInstance?.boolean('play'); if (play) play.value = draft.animated && !reducedMotion.matches;
      rive.startRendering();
    }
    dialog.querySelectorAll('[data-color]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.color === draft.color)));
    dialog.querySelectorAll('[data-background]').forEach(button => { if (button.tagName === 'BUTTON') button.setAttribute('aria-pressed', String(button.dataset.background === draft.background)); });
    dialog.querySelectorAll('[data-animated]').forEach(button => button.setAttribute('aria-pressed', String((button.dataset.animated === 'true') === draft.animated)));
    document.querySelector('#setup-color-name').textContent = COLORS.find(color => color.id === draft.color).name;
  }
  function initializePreviews() {
    previews = [previewCanvas, tileCanvas].map(canvas => {
      const rive = new Rive({ src: '/ambi-companion.riv', canvas, artboard: 'Ambi', stateMachine: 'Ambi Controller',
        autoplay: true, autoBind: true, layout: new Layout({ fit: Fit.Contain, alignment: Alignment.Center }),
        onLoad: () => { rive.resizeDrawingSurfaceToCanvas(); if (dialog.open) render(); },
        onLoadError: () => { document.querySelector('#setup-error').textContent = 'The character preview could not load. Close setup and reload Ambi to try again.'; },
      });
      return rive;
    });
  }
  const colors = document.querySelector('#setup-colors');
  for (const color of COLORS) {
    const button = document.createElement('button'); button.type = 'button';
    button.dataset.color = color.id; button.style.setProperty('--swatch', color.hex);
    button.setAttribute('aria-label', color.name); button.title = color.name;
    button.addEventListener('click', () => { draft.color = color.id; render(); }); colors.append(button);
  }
  name.addEventListener('input', () => { draft.displayName = name.value.trim().slice(0, 24) || 'Ambi'; render(); });
  document.querySelector('#setup-size').addEventListener('input', event => {
    draft.scale = Number(event.target.value); render();
  });
  dialog.querySelectorAll('button[data-background]').forEach(button => button.addEventListener('click', () => { draft.background = button.dataset.background; render(); }));
  dialog.querySelectorAll('button[data-animated]').forEach(button => button.addEventListener('click', () => { draft.animated = button.dataset.animated === 'true'; render(); }));
  document.querySelector('#setup-close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => { for (const rive of previews) rive.cleanup(); previews = []; onClose(); invoker?.focus?.(); });
  document.querySelector('#setup-save').addEventListener('click', () => {
    const normalized = normalizeSettings(draft);
    try { save(normalized); dialog.close(); }
    catch { document.querySelector('#setup-error').textContent = 'Your choices could not be saved. Please try again.'; }
  });
  const resize = new ResizeObserver(() => { for (const rive of previews) rive.resizeDrawingSurfaceToCanvas(); });
  resize.observe(previewCanvas); resize.observe(tileCanvas);
  const onMotion = () => { if (dialog.open) render(); };
  reducedMotion.addEventListener('change', onMotion);
  window.addEventListener('pagehide', () => { resize.disconnect(); reducedMotion.removeEventListener('change', onMotion); for (const rive of previews) rive.cleanup(); });
  return {
    open() {
      if (dialog.open) return;
      invoker = document.activeElement; draft = normalizeSettings(getSettings());
      name.value = draft.displayName; document.querySelector('#setup-size').value = draft.scale;
      document.querySelector('#setup-error').textContent = '';
      onOpen(); dialog.showModal(); render(); initializePreviews();
    },
  };
}
