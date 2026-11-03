import { app, BrowserWindow, Menu, ipcMain, dialog, screen } from 'electron';
import { spawn, spawnSync } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
import fs from 'node:fs/promises';
import net from 'node:net';
import { BASE, allowedPage, idle, frameActive, launchEnvironment, linuxSession } from './policy.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '../..');
const python = path.join(root, '.venv/bin/python');
const local = name => pathToFileURL(path.join(here, name)).href;
const preferences = {contextIsolation: true, nodeIntegration: false, sandbox: true, preload: path.join(here, 'preload.cjs')};
let main, keyWindow, frame, stopWindow, child, token, snapshot, poll, launchKey = '', quitting = false;

function secure(win, allowed) {
  win.webContents.setWindowOpenHandler(() => ({action: 'deny'}));
  win.webContents.on('will-navigate', (event, url) => { if (!allowed(url)) event.preventDefault(); });
  win.webContents.session.setPermissionRequestHandler((_contents, _permission, done) => done(false));
}
async function post(action, value = {}) {
  const response = await fetch(`${BASE}/api/${action}`, {method: 'POST', signal: AbortSignal.timeout(5000),
    headers: {'Content-Type': 'application/json', 'X-Ambi-Token': token}, body: JSON.stringify(value)});
  if (!response.ok) throw new Error('Ambi action did not complete.');
}
function updateFrame(active) {
  for (const win of [frame, stopWindow]) {
    if (!win || win.isDestroyed()) continue;
    if (active) { if (!win.isVisible()) win.showInactive(); } else win.hide();
  }
}
async function checkState() {
  try {
    const response = await fetch(`${BASE}/api/bootstrap`, {signal: AbortSignal.timeout(1500)});
    if (!response.ok) throw new Error('Backend unavailable');
    const boot = await response.json(); token = boot.token; snapshot = boot.state;
    updateFrame(frameActive(snapshot));
    return boot;
  } catch { snapshot = null; updateFrame(false); return null; }
}
async function portFree() {
  await new Promise((resolve, reject) => {
    const probe = net.createServer(); probe.once('error', () => reject(new Error('Port 8767 is already in use; no existing service was changed.')));
    probe.listen(8767, '127.0.0.1', () => probe.close(resolve));
  });
}
async function startBackend() {
  await portFree();
  const dataDir = path.join(app.getPath('userData'), 'data'); await fs.mkdir(dataDir, {recursive: true, mode: 0o700});
  child = spawn(python, [path.join(root, 'companion_service.py'), '--port', '8767'], {
    cwd: root, env: launchEnvironment(process.env, dataDir, launchKey), stdio: 'ignore'
  });
  let failed = false; child.once('error', () => {failed = true;});
  child.once('exit', () => {failed = true; updateFrame(false);});
  for (let attempt = 0; attempt < 100; attempt++) {
    if (failed) throw new Error('Ambi backend exited. Review Linux dependencies.');
    if (await checkState()) return;
    await new Promise(resolve => setTimeout(resolve, 200));
  }
  throw new Error('Ambi backend did not become ready.');
}
async function stopOwnedBackend() {
  const owned = child; child = null;
  if (!owned || owned.exitCode !== null || !owned.pid) return;
  await new Promise(resolve => { const timer = setTimeout(resolve, 5000); owned.once('exit', () => {clearTimeout(timer); resolve();}); owned.kill('SIGTERM'); });
  if (owned.exitCode === null) throw new Error('Owned backend has not stopped. No replacement started.');
}
async function configureKey() {
  await checkState(); if (!idle(snapshot)) return dialog.showMessageBox(main, {message: 'End the conversation and tasks before configuring voice.'});
  if (keyWindow && !keyWindow.isDestroyed()) return keyWindow.focus();
  keyWindow = new BrowserWindow({parent: main, modal: true, width: 480, height: 350, webPreferences: preferences});
  secure(keyWindow, url => url === local('key.html')); await keyWindow.loadFile(path.join(here, 'key.html'));
}
ipcMain.handle('ambi-key', async (event, value) => {
  if (!keyWindow || event.sender !== keyWindow.webContents || event.senderFrame?.url !== local('key.html') || event.senderFrame !== event.sender.mainFrame) throw new Error('Untrusted setup');
  if (typeof value !== 'string' || value.trim().length < 10 || value.length > 512) throw new Error('Invalid key');
  await checkState(); if (!idle(snapshot)) throw new Error('End active work first');
  clearInterval(poll); updateFrame(false); await stopOwnedBackend(); launchKey = value.trim();
  try { await startBackend(); keyWindow.close(); main.reload(); }
  finally { poll = setInterval(checkState, 350); }
});
ipcMain.on('ambi-native', (event, message) => {
  if (!main || event.sender !== main.webContents || event.senderFrame !== event.sender.mainFrame || !allowedPage(event.senderFrame.url)) return;
  if (message?.type === 'configure-voice') void configureKey();
});
ipcMain.on('ambi-stop', event => {
  if (stopWindow && event.sender === stopWindow.webContents && event.senderFrame === event.sender.mainFrame && event.senderFrame.url === local('stop.html')) void post('stop-task').catch(() => {});
});

if (!app.requestSingleInstanceLock()) app.quit();
else app.whenReady().then(async () => {
  if (process.platform !== 'linux' || !linuxSession(process.env)) throw new Error('This preview requires a Linux X11 session. Wayland is not supported; no security policy is changed.');
  const preflight = spawnSync(python, [path.join(root, 'linux_session.py')], {stdio: 'ignore'});
  if (preflight.status !== 0) throw new Error('Linux preflight failed. Run python linux_session.py and review the README.');
  await fs.access(path.join(root, 'ui/dist/companion.html'));
  await startBackend();
  main = new BrowserWindow({width: 1040, height: 820, title: 'Ambi — Linux developer preview', webPreferences: preferences}); secure(main, allowedPage);
  const bounds = screen.getPrimaryDisplay().bounds;
  frame = new BrowserWindow({...bounds, frame: false, transparent: true, focusable: false, alwaysOnTop: true, skipTaskbar: true, show: false, webPreferences: preferences});
  frame.setIgnoreMouseEvents(true); secure(frame, url => url === local('frame.html')); await frame.loadFile(path.join(here, 'frame.html'));
  stopWindow = new BrowserWindow({x: bounds.x + Math.round((bounds.width - 340) / 2), y: bounds.y + 12, width: 340, height: 56,
    frame: false, alwaysOnTop: true, skipTaskbar: true, show: false, webPreferences: preferences});
  secure(stopWindow, url => url === local('stop.html')); await stopWindow.loadFile(path.join(here, 'stop.html'));
  Menu.setApplicationMenu(Menu.buildFromTemplate([{label: 'Ambi', submenu: [
    {label: 'Configure voice for this launch…', click: configureKey},
    {label: 'Stop task', click: () => post('stop-task').catch(() => {})},
    {label: 'End conversation', click: () => post('stop').catch(() => {})}, {role: 'quit'}]}]));
  await main.loadURL(`${BASE}/companion.html`); poll = setInterval(checkState, 350);
  main.on('closed', () => app.quit());
}).catch(error => { dialog.showErrorBox('Ambi Linux preview', error.message); app.quit(); });
app.on('before-quit', event => {
  if (quitting) return; event.preventDefault(); quitting = true; clearInterval(poll); updateFrame(false);
  void (async () => {try {if (token && child) await post('stop');} catch {} try {await stopOwnedBackend();} catch {} launchKey = ''; app.quit();})();
});
