export const BASE = 'http://127.0.0.1:8767';
export function allowedPage(value) {
  try { const u = new URL(value); return u.origin === BASE && !u.username && !u.password && u.pathname === '/companion.html' && !u.search && !u.hash; }
  catch { return false; }
}
export function idle(snapshot) {
  return snapshot?.status === 'idle' && snapshot?.job?.status !== 'running';
}
export function frameActive(snapshot) { return snapshot?.job?.status === 'running'; }
export function launchEnvironment(source, dataDir, key = '') {
  const env = { ...source, AMBI_NATIVE_HOST: '1', AMBI_DATA_DIR: dataDir };
  delete env.OPENAI_API_KEY;
  if (key) env.OPENAI_API_KEY = key;
  return env;
}
export function linuxSession(env) {
  return Boolean(env.DISPLAY) && !env.WAYLAND_DISPLAY && (env.XDG_SESSION_TYPE || 'x11').toLowerCase() === 'x11';
}
