import './companion.css';
import { renderCharacter, customizeCharacter } from './character.js';
import { createCompanionClient } from './companion-client.js';
import { createActivityView, shouldExpand, goalProgress } from './activity-view.js';
import { COLORS, DEFAULT_SETTINGS, normalizeSettings, colorFilter } from './companion-settings.js';
import { createSetup } from './companion-setup.js';
import { createComputerFrame } from './computer-frame.js';
import { voicePresentation } from './voice-presentation.js';
import { chatHandoff } from './browser-chats.js';
import { computerSetup } from './computer-setup.js';

let state, connected = false, apiConfigured = false, observeScreen = false, busy = false, sessionOwned = false;
let needsGuidedSetup = false, setupSaved = false, receivedFirstSnapshot = false;
let taskMode = 'voice', jobOwned = false, ownedJobId, ownedClientId, taskSubmitting = false;
let settings = { ...DEFAULT_SETTINGS }, setupPresented = false;
try { settings = normalizeSettings(JSON.parse(localStorage.getItem('ambi.companion.settings') || '{}')); } catch { /* Native settings remain available when local storage is disabled. */ }
const notice = document.querySelector('#notice');
const activityPanel = document.querySelector('#activity-panel');
const activityError = document.querySelector('#activity-error');
const renderActivity = createActivityView(document.querySelector('#activity-steps'));
let expanded = false, transcriptFingerprint = '', settingsFingerprint = '';
const transcripts = new Map();
let olderMessages = [], historyCursor, historyExhausted = false;
const computerFrame = createComputerFrame({ root: document.documentElement,
  banner: document.querySelector('#computer-frame-banner'), label: document.querySelector('#computer-frame-label'),
  action: document.querySelector('#computer-frame-action'), stop: () => window.ambiDesktop.command('stop-task') });
let frameFingerprint = '';
function applySettings(value) {
  settings = normalizeSettings(value);
  const fingerprint = JSON.stringify(settings);
  if (fingerprint === settingsFingerprint) return;
  settingsFingerprint = fingerprint;
  const accent = COLORS.find(color => color.id === settings.color).hex;
  document.documentElement.style.setProperty('--agent-accent', accent);
  native({ type: 'frame-color', hex: accent });
  document.documentElement.dataset.background = settings.background;
  document.documentElement.style.setProperty('--character-scale', String(settings.scale));
  customizeCharacter(settings, colorFilter(settings.color));
  document.querySelector('.activity-header h2').textContent = `With ${settings.displayName}`;
}
const setup = createSetup({ getSettings: () => settings,
  save(value) {
    const nativeHost = Boolean(window.webkit?.messageHandlers?.ambi);
    try { localStorage.setItem('ambi.companion.settings', JSON.stringify(value)); }
    catch (exc) { if (!nativeHost) throw exc; }
    setupSaved = true;
    applySettings(value);
    native({ type: 'preferences', value });
  }, onOpen: () => native({ type: 'setup-layout', open: true }),
  onClose: () => { native({ type: 'setup-layout', open: false }); if (needsGuidedSetup && setupSaved) { needsGuidedSetup = false; queueMicrotask(openConnections); } },
});
function expand(value) {
  expanded = value === true;
  document.documentElement.classList.toggle('expanded', expanded);
  activityPanel.hidden = !expanded;
  document.querySelector('#show-activity').hidden = expanded;
  native({ type: 'layout', expanded });
}
function native(message) { window.webkit?.messageHandlers?.ambi?.postMessage(message); }
function error(message) {
  notice.textContent = message; notice.hidden = expanded;
  activityError.textContent = message; activityError.hidden = false;
  native({ type: 'error', message });
}
const connectionDialog = document.querySelector('#connection-dialog');
function openConnections() { native({ type: 'setup-layout', open: true }); connectionDialog.hidden = false; document.querySelector('#workspace').hidden = true; document.querySelector('#show-setup').hidden = true; document.querySelector('#show-activity').hidden = true; document.querySelector('#connect-codex').focus(); }
function closeConnections() { connectionDialog.hidden = true; document.querySelector('#workspace').hidden = false; document.querySelector('#show-setup').hidden = false; document.querySelector('#show-activity').hidden = expanded; native({ type: 'setup-layout', open: false }); }
document.querySelector('#earlier-messages').addEventListener('click', async () => {
  const button = document.querySelector('#earlier-messages'); button.disabled = true;
  try { const page = await client.send('history', { before: historyCursor ?? state?.history_cursor }); olderMessages = [...page.messages, ...olderMessages]; historyCursor = page.cursor; historyExhausted = !page.has_more; renderInformation(); document.querySelector('#conversation').scrollIntoView({ block: 'start' }); } catch (exc) { error(exc.message); } finally { button.disabled = false; }
});
document.querySelector('#connections').addEventListener('click', openConnections);
document.querySelector('#voice-connections').addEventListener('click', openConnections);
document.querySelector('#configure-voice').addEventListener('click', () => {
  if (window.webkit?.messageHandlers?.ambi) native({ type: 'configure-voice' });
  else { document.querySelector('#connection-error').textContent = 'Open Ambi’s desktop app and choose Connection → Configure API Key for This Launch.'; document.querySelector('#connection-error').hidden = false; }
});
function showComposer() {
  expand(true);
  document.documentElement.classList.add('typing');
  document.querySelector('#message-form').hidden = false;
  document.querySelector('#type-instead').setAttribute('aria-expanded', 'true');
  document.querySelector('#message').focus();
}
document.querySelector('#type-instead').addEventListener('click', () => {
  if (document.querySelector('#message-form').hidden) showComposer();
  else { document.documentElement.classList.remove('typing'); document.querySelector('#message-form').hidden = true; document.querySelector('#type-instead').setAttribute('aria-expanded', 'false'); }
});
document.querySelector('#mute-voice').addEventListener('click', () => window.ambiDesktop.command('microphone'));
document.querySelector('#close-connections').addEventListener('click', closeConnections);
document.addEventListener('keydown', event => { if (event.key === 'Escape' && !connectionDialog.hidden) closeConnections(); });
document.querySelector('#task-mode').addEventListener('change', event => { taskMode = event.target.value; renderInformation(); });
async function action(name, value = {}) {
  try { await client.send(name, value); document.querySelector('#connection-error').hidden = true; return true; }
  catch (exc) { const node = document.querySelector('#connection-error'); node.textContent = exc.message; node.hidden = false; error(exc.message); return false; }
}
document.querySelector('#copy-diagnostics').addEventListener('click', async () => {
  try { const value = await client.send('diagnostics'); const text = JSON.stringify(value, null, 2);
    if (window.webkit?.messageHandlers?.ambi) native({ type: 'copy-diagnostics', text }); else await navigator.clipboard.writeText(text);
    document.querySelector('#copy-diagnostics').textContent = 'Diagnostics copied';
  } catch (exc) { error(exc.message); }
});
document.querySelector('#codex-model').addEventListener('change', event => action('codex-model', { model: event.target.value }));
document.querySelector('#sign-in-codex').addEventListener('click', async () => {
  try { const result = await client.send('codex-login'); if (result.auth_url) native({ type: 'open-codex-login', url: result.auth_url }); }
  catch (exc) { error(exc.message); }
});
document.querySelector('#connect-codex').addEventListener('click', () => action('codex-connect'));
document.querySelector('#choose-workspace').addEventListener('click', () => native({ type: 'choose-workspace' }));
document.querySelector('#request-screen-permission').addEventListener('click', () => {
  if (state?.platform === 'darwin' && window.webkit?.messageHandlers?.ambi) native({ type: 'request-screen-permission' });
  else action('request-screen-permission');
});
document.querySelector('#open-permissions').addEventListener('click', () => native({ type: 'open-permissions' }));
function openComputerSetup() {
  openConnections();
  document.querySelector('#computer-setup').hidden = false;
  document.querySelector('#computer-access-heading').scrollIntoView({ block: 'start', behavior: 'instant' });
}
document.querySelector('#review-computer-setup').addEventListener('click', openComputerSetup);
document.querySelector('#toggle-computer-access').addEventListener('click', () => {
  const setup = computerSetup(state, connected);
  if (setup.blocked) return;
  if (state?.computer_enabled && state.status === 'idle') return action('computer-access', { enabled: false });
  if (setup.enableAllowed) return action('computer-access', { enabled: true });
  openComputerSetup();
});
document.querySelector('#reconnect-driver').addEventListener('click', () => {
  if (computerSetup(state, connected).blocked) return;
  if (!window.webkit?.messageHandlers?.ambi) return error('Use the desktop Ambi app to reconnect its driver.');
  try { sessionStorage.setItem('ambi.computerSetup', 'open'); } catch { /* Setup can be reopened manually. */ }
  native({ type: 'reconnect-driver' });
});
document.querySelector('#first-task').addEventListener('click', () => {
  closeConnections(); taskMode = 'codex'; document.querySelector('#task-mode').value = taskMode; showComposer(); renderInformation();
  document.querySelector('#message').value = 'Create a three-step plan for testing Ambi. Reply here only; do not open apps or change files.';
  document.querySelector('#message').focus();
});
let approvalFingerprint = '';
function renderInformation() {
  if (!state) return;
  const voice = voicePresentation(state, connected, apiConfigured);
  document.documentElement.dataset.presence = voice.phase;
  document.querySelector('#presence').textContent = voice.label;
  document.querySelector('#voice-label').textContent = voice.button;
  document.querySelector('#voice-hint').textContent = voice.hint;
  document.querySelector('#start').disabled = busy || voice.disabled;
  document.querySelector('#start').setAttribute('aria-pressed', String(['connected', 'connecting'].includes(state.status)));
  document.querySelector('#mute-voice').hidden = state.status !== 'connected';
  document.querySelector('#mute-voice').textContent = state.microphone_enabled ? 'Mute microphone' : 'Unmute microphone';
  document.querySelector('#activity-status').textContent = !connected ? 'Reconnecting to your computer…'
    : taskMode === 'codex' ? (state.codex?.status === 'running' ? 'Codex is working…' : state.codex?.status === 'approval-required' ? 'Codex needs your permission.' : state.codex?.authenticated ? 'Codex connected. History saved on this computer.' : 'Connect Codex in Setup & connections. No microphone needed.')
    : state.status === 'connected' ? (goalProgress(state) || (state.job?.status === 'running' ? 'Working on your task' : state.microphone_enabled ? 'Listening. Speak naturally.' : 'Microphone muted. Unmute to speak.'))
    : state.status === 'connecting' ? 'Connecting voice…' : state.status === 'error' ? 'Session needs attention'
    : 'Your actions and conversation appear here.';
  document.querySelector('#voice-connection-status').textContent = apiConfigured ? 'A voice key is configured. Start a conversation to connect.' : 'Add a voice API key to start a conversation.';
  document.querySelector('#configure-voice').textContent = apiConfigured ? 'Voice key options…' : 'Set up voice…';
  document.querySelector('#sign-in-codex').hidden = Boolean(state.codex?.authenticated);
  document.querySelector('#codex-connection-status').textContent = state.codex?.authenticated ? 'Codex is connected using its existing local sign-in.' : state.codex?.error || (state.codex?.available ? 'Codex is installed. Connect it to check your sign-in.' : 'Install Codex CLI and sign in, then connect here.');
  document.querySelector('#app-version').textContent = `Ambi ${state.version || ''} · Conversation history stays on this computer.`;
  document.querySelector('#workspace-notice').textContent = state.workspace_notice || '';
  document.querySelector('#workspace-notice').hidden = !state.workspace_notice;
  document.querySelector('#earlier-messages').hidden = historyExhausted || !state.history_has_more;
  document.querySelector('#working-folder').textContent = state.workspace || 'Ambi’s private working folder';
  const driver = computerSetup(state, connected);
  document.querySelector('#computer-permissions').textContent = driver.checks.map(([key, value]) => `${key}: ${value ? 'available' : 'needed'}`).join(' · ');
  document.querySelector('#computer-setup-status').textContent = driver.message;
  document.querySelector('#request-screen-permission').hidden = !driver.mac;
  document.querySelector('#open-permissions').hidden = !driver.mac;
  document.querySelector('#computer-setup-explanation').textContent = driver.mac
    ? 'Review Device Control & Data Access (called Accessibility on older macOS), and screen access. Ambi never approves the system prompts for you.'
    : driver.linux ? 'Linux developer preview: X11 primary-display control only. Wayland is unsupported. Setup never changes system security policy.'
    : 'Use an unlocked Windows desktop in your normal user session. Ambi does not control secure/UAC screens or elevate itself.';
  const checks = document.querySelector('#computer-setup-checks');
  const checkFingerprint = JSON.stringify(driver.checks);
  if (checks.dataset.snapshot !== checkFingerprint) {
    checks.dataset.snapshot = checkFingerprint; checks.replaceChildren();
    for (const [name, ready] of driver.checks) {
      const row = document.createElement('li'); row.textContent = `${name}: ${ready === true ? 'Ready' : 'Needed'}`; checks.append(row);
    }
  }
  document.querySelector('#toggle-computer-access').disabled = driver.blocked;
  document.querySelector('#toggle-computer-access').textContent = driver.button;
  document.querySelector('#reconnect-driver').disabled = driver.blocked;
  document.querySelector('#request-screen-permission').disabled = driver.blocked;
  const modelSelect = document.querySelector('#codex-model');
  const modelFingerprint = JSON.stringify(state.codex?.models || []);
  if (modelSelect.dataset.models !== modelFingerprint) {
    modelSelect.dataset.models = modelFingerprint; modelSelect.replaceChildren();
    for (const model of state.codex?.models || []) { const option = document.createElement('option'); option.value = model.id; option.textContent = model.name; modelSelect.append(option); }
  }
  modelSelect.disabled = !state.codex?.models?.length || ['running', 'approval-required'].includes(state.codex?.status);
  modelSelect.value = state.codex?.model || '';
  const pending = state.codex?.pending || [];
  const fingerprintApprovals = JSON.stringify(pending);
  if (fingerprintApprovals !== approvalFingerprint) {
    approvalFingerprint = fingerprintApprovals;
    const host = document.querySelector('#codex-approvals'); host.replaceChildren(); host.hidden = !pending.length;
    for (const request of pending) {
      const title = document.createElement('h3'), reason = document.createElement('p'), command = document.createElement('pre');
      title.textContent = request.network?.host ? 'Allow this network access?' : request.kind === 'command' ? 'Allow this command?' : 'Allow these file changes?';
      reason.textContent = request.reason; command.textContent = [request.command, request.cwd, request.grant_root ? `Requested scope: ${request.grant_root}` : '', request.network?.host ? `${request.network.protocol}://${request.network.host}` : '', ...(request.changes || []).map(change => `${change.path}\n${change.diff}`)].filter(Boolean).join('\n');
      host.append(title, reason, command);
      for (const [label, decision] of [['Allow once', 'accept'], ['Decline', 'decline'], ['Cancel task', 'cancel']]) {
        if (decision === 'accept' && request.can_accept === false) continue;
        const button = document.createElement('button'); button.textContent = label;
        button.addEventListener('click', async () => { button.disabled = true; if (!await action('codex-approval', { id: request.id, decision })) button.disabled = false; }); host.append(button);
      }
    }
  }
  renderActivity(state.activity);
  document.querySelector('#activity-empty').hidden = Boolean(state.activity?.length || state.transcript?.length);
  const nextFrame = JSON.stringify([connected, state.job?.id, state.job?.status]);
  if (nextFrame !== frameFingerprint) { frameFingerprint = nextFrame; computerFrame.update(state, connected); }
  document.querySelector('#start-session').hidden = taskMode === 'codex' || state.status === 'connected';
  document.querySelector('#start-session').disabled = !connected || !apiConfigured || ['connecting', 'stopping'].includes(state.status);
  document.querySelector('#send-message').disabled = !connected || (taskMode === 'codex' ? state.job?.status === 'running' || taskSubmitting || !state.codex?.authenticated || ['running', 'approval-required', 'connecting'].includes(state.codex?.status) : state.status !== 'connected');
  document.querySelector('#stop-work').hidden = state.job?.status !== 'running';
  document.querySelector('#offer').hidden = !state.suggestion;
  document.querySelector('#offer-text').textContent = state.suggestion?.text || '';
  activityError.hidden = !(state.error || state.codex?.error || state.history_error);
  activityError.textContent = state.error || state.codex?.error || state.history_error || '';
  const seen = new Set();
  const visibleTranscript = [...olderMessages, ...(state.transcript || [])].filter(item => { if (seen.has(item.id)) return false; seen.add(item.id); return true; });
  const fingerprint = JSON.stringify(visibleTranscript);
  if (fingerprint !== transcriptFingerprint) {
    transcriptFingerprint = fingerprint;
    const ids = new Set(visibleTranscript.map(item => item.id));
    for (const [id, entry] of transcripts) if (!ids.has(id)) { entry.node.remove(); transcripts.delete(id); }
    const addedOlder = [], olderIds = new Set(olderMessages.map(item => item.id));
    for (const item of visibleTranscript) {
      let entry = transcripts.get(item.id);
      if (!entry) {
        const node = document.createElement('article'), who = document.createElement('h3'), text = document.createElement('p');
        who.textContent = item.role === 'user' ? 'You' : 'Ambi'; node.append(who, text);
        if (olderIds.has(item.id)) addedOlder.push(node); else document.querySelector('#conversation').append(node); entry = { node, text }; transcripts.set(item.id, entry);
      }
      entry.text.textContent = item.text;
    }
    if (addedOlder.length) document.querySelector('#conversation').prepend(...addedOlder);
  }
}
function publish() {
  native({ type: 'state', connected, apiConfigured, status: state?.status ?? 'offline',
    phase: state?.phase ?? 'ready', focus: state?.focus ?? false,
    microphoneEnabled: state?.microphone_enabled ?? true, error: state?.error ?? '',
    jobRunning: state?.job?.status === 'running', jobOwned: taskSubmitting || (jobOwned && state?.job?.client_id === ownedClientId && state?.job?.status === 'running'), ownedJobClientId: ownedClientId || '', mode: state?.observations?.mode ?? '', sessionOwned,
    suggestion: state?.suggestion ? { id: state.suggestion.id, text: state.suggestion.text } : null });
}
const client = createCompanionClient({
  onState(next, configured) {
    if (shouldExpand(state, next)) expand(true);
    state = next;
    if (!receivedFirstSnapshot) {
      receivedFirstSnapshot = true;
      try { if (sessionStorage.getItem('ambi.computerSetup') === 'open') { sessionStorage.removeItem('ambi.computerSetup'); openComputerSetup(); } } catch { /* Private browsing may disable session storage. */ }
    }
    if (next.job?.client_id === ownedClientId && next.job?.status !== 'running') { jobOwned = false; ownedJobId = undefined; }
    if (!busy && ['idle', 'error'].includes(next.status)) sessionOwned = false;
    if (configured !== undefined) apiConfigured = configured;
    notice.hidden = expanded || !next.error;
    if (next.error) notice.textContent = next.error;
    renderCharacter(next); renderInformation(); publish();
  },
  onError: error,
  onConnection(value) {
    connected = value;
    if (!value) { renderCharacter({ status: 'error', phase: 'ready' }); error('Connection lost. Reconnecting to Ambi…'); }
    else { notice.hidden = expanded || !state?.error; if (!state?.error) native({ type: 'error', message: '' }); }
    renderInformation();
    publish();
  },
});
window.ambiDesktop = {
  appearance(background, scale) {
    applySettings({ ...settings, background, scale });
  },
  configure(value) {
    applySettings(value);
    if (value.needsSetup && !setupPresented) { needsGuidedSetup = true; setupPresented = true; setup.open(); }
  },
  showSetup() { setupPresented = true; setup.open(); },
  showConnections: openConnections,
  selectWorkspace(path) { document.querySelector('#allow-file-changes').checked = false; return action('workspace', { path }); },
  screenContext(value) { observeScreen = value === true; },
  showActivity() { expand(!expanded); },
  async command(name, value) {
    if (busy) return;
    busy = true;
    try {
      if (name === 'toggle-session') {
        if (['connected', 'connecting'].includes(state?.status)) await client.send('stop');
        else {
          if (!apiConfigured) { openConnections(); error('Voice needs an API key. Use Connection → Configure API Key for This Launch, then try again.'); return; }
          taskMode = 'voice'; document.querySelector('#task-mode').value = taskMode;
          expand(true); sessionOwned = true; publish(); await client.send('start', { observe_screen: observeScreen });
        }
      } else if (name === 'stop') await client.send('stop');
      else if (name === 'stop-task') await client.send('stop-task');
      else if (name === 'microphone') await client.send('microphone', { enabled: !state?.microphone_enabled });
      else if (name === 'focus') await client.send('focus', { enabled: !state?.focus });
      else if (name === 'accept' || name === 'dismiss') {
        if (!state?.suggestion || value !== state.suggestion.id) throw new Error('That suggestion has expired.');
        await client.send(name, { id: value });
      } else throw new Error('Unknown Ambi action.');
    } catch (exc) { error(exc.message); }
    finally { busy = false; renderInformation(); }
  },
};
document.querySelector('#start').addEventListener('click', () => window.ambiDesktop.command('toggle-session'));
document.querySelector('#ambi').addEventListener('click', () => document.querySelector('#start').click());
document.querySelector('#show-setup').addEventListener('click', () => setup.open());
document.querySelector('#collapse-activity').addEventListener('click', () => expand(false));
document.querySelector('#show-activity').addEventListener('click', () => expand(true));
document.querySelector('#start-session').addEventListener('click', () => window.ambiDesktop.command('toggle-session'));
document.querySelector('#sample-prompt').addEventListener('click', () => {
  taskMode = 'codex'; document.querySelector('#task-mode').value = taskMode; showComposer(); renderInformation();
  const field = document.querySelector('#message');
  field.value = 'Create a three-step plan for testing Ambi. Reply here only; do not open apps or change files.';
  field.focus();
});
document.querySelector('#preview-frame').addEventListener('click', () => computerFrame.preview());
document.querySelector('#stop-work').addEventListener('click', () => window.ambiDesktop.command('stop-task'));
document.querySelector('#accept-offer').addEventListener('click', () => window.ambiDesktop.command('accept', state?.suggestion?.id));
document.querySelector('#dismiss-offer').addEventListener('click', () => window.ambiDesktop.command('dismiss', state?.suggestion?.id));
document.querySelector('#message-form').addEventListener('submit', async event => {
  event.preventDefault();
  const field = document.querySelector('#message'), button = document.querySelector('#send-message');
  const text = field.value.trim();
  if (!text || button.disabled) return;
  button.disabled = true;
  try {
    if (taskMode === 'codex') { ownedClientId = crypto.randomUUID(); taskSubmitting = true; publish();
      try { const result = await client.send('codex-message', { text, client_id: ownedClientId, writable: document.querySelector('#allow-file-changes').checked }); ownedJobId = result.job_id; jobOwned = true; }
      finally { taskSubmitting = false; publish(); } }
    else await client.send('message', { text });
    field.value = '';
  }
  catch (exc) { error(exc.message); }
  finally { renderInformation(); }
});
document.querySelector('#message').addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); document.querySelector('#message-form').requestSubmit(); }
});
window.addEventListener('pagehide', () => client.dispose());
applySettings(settings);
client.connect();

const browserChat = document.querySelector('#browser-chat');
const browserDraft = document.querySelector('#browser-draft');
function updateHandoffLabel() {
  const chat = chatHandoff(browserChat.value, browserDraft.value);
  document.querySelector('#open-browser-chat').textContent = `${chat.draft ? 'Copy prompt & open' : 'Open'} ${chat.name}`;
}
browserChat.addEventListener('change', updateHandoffLabel);
browserDraft.addEventListener('input', updateHandoffLabel);
document.querySelector('#open-browser-chat').addEventListener('click', async () => {
  const status = document.querySelector('#browser-chat-status');
  try {
    const chat = chatHandoff(browserChat.value, browserDraft.value);
    if (window.webkit?.messageHandlers?.ambi) {
      native({ type: 'browser-chat', provider: chat.provider, draft: chat.draft });
      status.textContent = `Opening ${chat.name} in your browser.${chat.draft ? ' Your prompt is copied for you to paste and review.' : ''} Nothing is sent automatically.`;
    } else {
      // A normal link preserves browser popup policy; no token or draft goes in its URL.
      const link = document.createElement('a'); link.href = chat.url; link.target = '_blank'; link.rel = 'noopener noreferrer';
      link.click();
      if (chat.draft) await navigator.clipboard.writeText(chat.draft);
      status.textContent = `${chat.name} handoff requested.${chat.draft ? ' Prompt copied; paste and review it there.' : ''} Nothing is sent automatically.`;
    }
  } catch (exc) { status.textContent = exc.message; }
});
