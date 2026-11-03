// A running task is observable; a successful OS action is a separate claim.
export function computerTaskActive(state, connected) {
  return connected === true && state?.job?.status === 'running';
}

export function createComputerFrame({ root, banner, label, action, stop }) {
  const native = globalThis.window?.webkit?.messageHandlers?.ambi;
  let active = false, preview = false;
  function render() {
    if (native) {
      root.dataset.computerFrame = 'idle';
      banner.hidden = true;
      native.postMessage({ type: 'frame-preview', enabled: preview && !active });
      return;
    }
    root.dataset.computerFrame = active ? 'active' : preview ? 'preview' : 'idle';
    banner.hidden = !active && !preview;
    label.textContent = active ? 'Ambi is working' : 'Computer-use frame preview';
    action.textContent = active ? 'Stop task' : 'Close preview';
  }
  action.addEventListener('click', () => {
    if (active) stop();
    else { preview = false; render(); }
  });
  render();
  return {
    update(state, connected) {
      active = computerTaskActive(state, connected);
      preview = false;
      render();
    },
    preview() { preview = true; render(); },
  };
}
