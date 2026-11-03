// Readiness presentation only. This never requests permissions or enables input.
export function computerSetup(state = {}, connected = false) {
  const permissions = state.permissions || {};
  const required = state.platform === 'darwin' ? ['Accessibility', 'Screen Recording'] : state.platform === 'win32' ? ['Interactive desktop'] : state.platform === 'linux' ? ['X11 session', 'Screenshot utility', 'Clipboard utility'] : [];
  const names = [...new Set([...required, ...Object.keys(permissions)])];
  const entries = names.map(name => [name, permissions[name] === true]);
  const missing = entries.filter(([, ready]) => !ready).map(([name]) => name);
  const active = state.job?.status === 'running' || ['connected', 'connecting', 'stopping'].includes(state.status);
  const ready = connected && required.length > 0 && missing.length === 0;
  const blocked = !connected || active || !['idle', 'error'].includes(state.status);
  const enableAllowed = ready && !blocked && state.status === 'idle';
  return { ready, missing, checks: entries, blocked, active, enableAllowed, mac: state.platform === 'darwin', linux: state.platform === 'linux',
    button: state.status === 'error' ? 'Reconnect computer driver' : state.computer_enabled ? 'Disable computer control' : ready ? 'Enable computer control for this run' : 'Set up computer use',
    message: !connected ? 'Reconnect to Ambi before setting up computer use.'
      : active ? 'End the conversation and stop active tasks before changing computer access.'
      : state.status === 'error' ? 'Reconnect the local service to recover, then check computer access again.'
      : required.length === 0 ? 'No supported computer driver is reported for this platform.'
      : missing.length ? (state.platform === 'darwin' ? 'Approve the missing access in system settings, then return here. Ambi checks again automatically.' : state.platform === 'linux' ? 'This preview needs an X11 session, scrot and xclip or xsel. Wayland control is unavailable. Review the Linux setup guide; no system policy is changed.' : 'Return to an unlocked Windows desktop in your normal user session, then check again.')
      : state.computer_enabled ? 'Computer control is enabled for this run. Stop remains available during tasks.'
      : 'Permissions are ready. Enable computer control for this run, then start a new voice conversation.' };
}
