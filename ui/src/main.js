import './style.css';
import { Camera } from './camera.js';
import { renderCharacter } from './character.js';

const $ = selector => document.querySelector(selector);
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
let token, state, tab = 'today', socket, reconnectTimer, memoryFingerprint, transcriptFingerprint, suggestionFingerprint;
let serverReady = false, sessionWasActive = false, toastTimer, cameraEnabled = false;
const streamId = crypto.randomUUID();
let sequence = 0, pendingSignal = null, sendingSignal = false, lastSignalSent = 0, lastCues = '';

function toast(text) {
  $('#toast').textContent = text; $('#toast').classList.remove('hidden');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => $('#toast').classList.add('hidden'), 5500);
}
async function api(action, data = {}) {
  if (!serverReady) throw new Error('The local app is reconnecting. Please try again in a moment.');
  const response = await fetch('/api/' + action, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Ambi-Token': token }, body: JSON.stringify(data) });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Something went wrong. Please try again.');
  return result;
}
async function action(fn) { try { await fn(); } catch (error) { toast(error.message); } }

function cameraStatus(status, message) {
  cameraEnabled = status === 'loading' || status === 'active';
  $('#camera-status').textContent = message;
  $('#camera-toggle').setAttribute('aria-checked', String(cameraEnabled));
  $('#camera-placeholder').classList.toggle('hidden', status === 'active');
  $('#camera-badge').classList.toggle('hidden', status !== 'active');
  if (!cameraEnabled) {
    pendingSignal = null; lastCues = '';
    updateCues(null);
    if (serverReady) api('camera-off').catch(() => {});
  }
  if (status === 'error') toast(message);
}
function updateCues(signal) {
  for (const cue of ['neutral', 'smiling', 'furrowed_brow', 'frowning', 'confused_look',
                     'concentrating_look', 'irritated_look', 'tired_look', 'sleepy_look']) {
    const score = signal?.usable ? Math.round((signal.scores[cue] || 0) * 100) : null;
    $('#meter-' + cue).style.width = `${score || 0}%`;
    $('#score-' + cue).textContent = score === null ? '—' : `${score}`;
    $('#meter-' + cue).closest('.cue').classList.toggle('active', Boolean(signal?.cues?.includes(cue)));
  }
  $('#camera-latency').textContent = signal ? `${Math.round(signal.inference_ms)} ms / frame` : '—';
  if (signal) $('#camera-status').textContent = !signal.usable ? 'Keep one face clearly in view'
    : signal.cues.includes('neutral') ? 'Neutral expression · processing locally'
    : signal.cues.length ? 'A brief cue, noticed' : 'One face · processing locally';
}
async function flushSignal() {
  if (sendingSignal || !pendingSignal || !serverReady || !cameraEnabled) return;
  const signal = pendingSignal; pendingSignal = null; sendingSignal = true;
  lastSignalSent = performance.now();
  try {
    const age = performance.now() - signal.at;
    if (age <= 1500) await api('camera', {
      stream_id: streamId, sequence: ++sequence, usable: signal.usable,
      cues: signal.cues, scores: signal.scores, age_ms: Math.max(0, age),
      inference_ms: signal.inference_ms, detection_ms: signal.detection_ms,
    });
  } catch { /* A disconnected UI never queues a backlog of frames. */ }
  finally { sendingSignal = false; if (pendingSignal) flushSignal(); }
}
const camera = new Camera($('#camera-video'), signal => {
  updateCues(signal);
  const cues = signal.cues.join(',');
  const onset = signal.cues.some(cue => cue !== 'neutral') && cues !== lastCues;
  lastCues = cues;
  // Keep a short positive event while a request is in flight. A neutral frame
  // may replace it after delivery; a missing face always clears it.
  if (!signal.usable || onset || !pendingSignal?.cues?.some(cue => cue !== 'neutral')) pendingSignal = signal;
  if (onset || !signal.usable || performance.now() - lastSignalSent > 250) flushSignal();
}, cameraStatus);

function renderMemory(items) {
  $('#task-count').textContent = items.filter(m => m.kind === 'task' && m.status !== 'done').length;
  $('#memory-count').textContent = items.filter(m => m.kind !== 'task').length;
  const selected = items.filter(m => tab === 'today' ? m.kind === 'task' : m.kind !== 'task');
  const fingerprint = JSON.stringify([selected, tab]);
  if (fingerprint === memoryFingerprint) return;
  memoryFingerprint = fingerprint;
  $('#memory-list').innerHTML = selected.length ? selected.map(item => `
    <article class="memory-item ${item.status === 'done' ? 'done' : ''}">
      <div class="memory-meta"><span>${escape(item.kind)}</span><span>${item.status === 'done' ? 'DONE' : 'SAVED'}</span></div>
      <h3>${escape(item.title)}</h3><button class="delete-memory" data-delete="${escape(item.id)}" aria-label="Delete ${escape(item.title)}">×</button>
      <p title="${escape(item.body)}">${escape(item.body || item.source)}</p>
      ${item.kind === 'task' && item.status !== 'done' ? `<button class="complete-memory" data-complete="${escape(item.id)}">✓ Mark complete</button>` : ''}
    </article>`).join('') : `<p class="empty-state">${tab === 'today' ? 'A clear slate.<br>Add something you want a hand with.' : 'Keep a useful note, a preference,<br>or a little context for later.'}</p>`;
  $('#memory-status').textContent = `${items.length} ${items.length === 1 ? 'item' : 'items'} in local memory`;
}
function renderTranscript(items) {
  const fingerprint = JSON.stringify(items);
  if (fingerprint === transcriptFingerprint) return;
  transcriptFingerprint = fingerprint;
  const box = $('#transcript');
  const atBottom = box.scrollHeight - box.clientHeight - box.scrollTop < 60;
  box.innerHTML = items.map(item => `<div class="chat-line ${item.role === 'user' ? 'user' : 'assistant'}"><span class="speaker">${item.role === 'user' ? 'You' : 'Ambi'}</span>${escape(item.text)}</div>`).join('');
  if (atBottom) box.scrollTop = box.scrollHeight;
}
function renderSuggestion(item) {
  const fingerprint = JSON.stringify(item);
  if (suggestionFingerprint === fingerprint) return;
  suggestionFingerprint = fingerprint;
  $('#suggestion').classList.toggle('hidden', !item);
  $('#suggestion').innerHTML = item ? `<strong>✧ ${escape(item.title)}</strong><p>${escape(item.text)}</p><div class="suggestion-actions">${item.task ? `<button class="button" data-accept="${escape(item.id)}">Yes, help me ↗</button>` : ''}<button class="button" data-dismiss="${escape(item.id)}">Not now</button></div>` : '';
}
function render(next) {
  state = next;
  renderCharacter(state);
  const active = ['connected', 'connecting', 'stopping'].includes(state.status);
  const connected = state.status === 'connected';
  if (sessionWasActive && !active && cameraEnabled) camera.stop();
  sessionWasActive = active;
  $('.app').classList.toggle('connected-view', active || Boolean(state.transcript.length));
  $('#connection').classList.toggle('online', connected);
  $('#connection').innerHTML = `<i></i> ${escape(connected ? 'Right here with you' : state.status === 'connecting' ? 'Connecting…' : state.status === 'error' ? 'Needs attention' : 'Ready when you are')}`;
  $('#mode-pill').textContent = state.focus ? 'FOCUS' : connected ? state.phase.toUpperCase() : state.status === 'connecting' ? 'CONNECTING' : 'STANDBY';
  $('#orb').className = `orb ${connected ? state.phase : ''}`;
  $('#hero-title').textContent = connected ? ({ ready: 'Go ahead. I’m here.', speaking: 'A thought for you.', listening: 'I’m listening.', working: 'Taking a little off your plate.' }[state.phase]) : state.status === 'connecting' ? 'Getting settled in…' : 'Here, before you ask.';
  $('#hero-subtitle').innerHTML = connected ? state.focus ? 'Quiet company. I’ll respond when you ask.' : 'Speak naturally, or type a thought below.' : 'I’ll keep the context.<br>You keep your train of thought.';
  $('#start').innerHTML = state.status === 'stopping' ? 'Stopping…' : active ? '■ End session' : '<span class="play-icon">▶</span> Start session';
  $('#start').disabled = state.status === 'stopping' || !serverReady;
  $('#message').disabled = $('#send').disabled = !connected;
  $('#session-options').classList.toggle('hidden', active);
  $('#control-hint').textContent = connected ? 'Say “stop” to cancel computer work. “Bye” ends the session.' : 'Start a session and Ambi will speak first.';
  $('#focus').setAttribute('aria-pressed', String(state.focus));
  $('#microphone').setAttribute('aria-pressed', String(state.microphone_enabled));
  $('#microphone').textContent = state.microphone_enabled ? 'Mic on' : 'Mic muted';
  $('#microphone').disabled = !serverReady;
  if (connected && !state.microphone_enabled) $('#hero-subtitle').textContent = 'Microphone muted. You can still type a thought below.';
  if (state.error) { $('#setup-warning').textContent = state.error; $('#setup-warning').classList.remove('hidden'); }
  renderMemory(state.memories); renderTranscript(state.transcript); renderSuggestion(state.suggestion);
  const computer = state.observations.computer;
  $('#screen-status').innerHTML = `<i></i> ${computer.status === 'available' ? 'Screen context active' : computer.status === 'waiting' ? 'Reading the room…' : computer.status === 'paused' ? 'Screen observer paused' : 'Screen context off'}`;
  const job = state.job;
  $('#stop-task').classList.toggle('hidden', job?.status !== 'running');
  if (job) {
    $('#activity-content').innerHTML = `<span class="activity-icon">${job.status === 'running' ? '↗' : job.status === 'completed' ? '✓' : '−'}</span><h3>${escape(job.status === 'running' ? 'On it.' : job.status === 'completed' ? 'Worker finished' : 'Task stopped')}</h3><p>${escape(job.task)}</p>${job.result ? `<p>${escape(job.result)}</p>` : '<p>You can keep talking while I work.</p>'}`;
  } else if (computer.status === 'available') {
    $('#activity-content').innerHTML = `<span class="activity-icon">↗</span><h3>Following your context</h3><p>${escape(computer.payload.visible_activity)}</p>`;
  }
}

async function connect() {
  clearTimeout(reconnectTimer);
  try {
    const response = await fetch('/api/bootstrap', { cache: 'no-store' });
    if (!response.ok) throw new Error('Local app is unavailable');
    const data = await response.json(); token = data.token; serverReady = true;
    const missing = Object.entries(data.permissions).filter(([, granted]) => !granted).map(([name]) => name);
    const warning = !data.api_configured ? 'Add your OpenAI API key to .env and restart the local server to enable voice. Memory and local camera detection are available now.' : missing.length ? `For computer help, allow ${missing.join(' and ')} for your terminal in macOS Privacy & Security, then restart Ambi. Voice and memory are still available.` : '';
    $('#setup-warning').textContent = warning; $('#setup-warning').classList.toggle('hidden', !warning);
    render(data.state);
    socket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`, ['ambi', token]);
    socket.onmessage = ({ data }) => render(JSON.parse(data));
    socket.onclose = () => {
      serverReady = false; $('#start').disabled = true;
      $('#connection').innerHTML = '<i></i> Reconnecting…';
      $('#connection').classList.remove('online');
      reconnectTimer = setTimeout(connect, 2000);
    };
  } catch {
    serverReady = false; $('#start').disabled = true;
    $('#connection').innerHTML = '<i></i> Local app offline';
    $('#setup-warning').textContent = 'Start the local Ambi server, then this page will reconnect automatically.';
    $('#setup-warning').classList.remove('hidden');
    reconnectTimer = setTimeout(connect, 2500);
  }
}

$('#start').addEventListener('click', () => action(async () => {
  if (['connected', 'connecting'].includes(state?.status)) { camera.stop(); await api('stop'); }
  else { $('#setup-warning').classList.add('hidden'); await api('start', { observe_screen: $('#observe-screen').checked }); }
}));
$('#focus').addEventListener('click', () => action(() => api('focus', { enabled: !state?.focus })));
$('#microphone').addEventListener('click', () => action(() => api('microphone', { enabled: !state?.microphone_enabled })));
$('#stop-task').addEventListener('click', () => action(() => api('stop-task')));
$('#camera-toggle').addEventListener('click', () => cameraEnabled ? camera.stop() : camera.start());
$('#message-form').addEventListener('submit', event => { event.preventDefault(); action(async () => { const input = $('#message'); await api('message', { text: input.value }); input.value = ''; }); });
document.querySelectorAll('[data-tab]').forEach(button => button.addEventListener('click', () => {
  tab = button.dataset.tab;
  document.querySelectorAll('[data-tab]').forEach(b => { b.classList.toggle('selected', b === button); b.setAttribute('aria-selected', String(b === button)); });
  if (state) renderMemory(state.memories);
}));
const openMemory = () => { $('#memory-dialog').showModal(); $('#memory-title').focus(); };
$('#add-memory').addEventListener('click', openMemory); $('#add-context').addEventListener('click', openMemory);
$('#close-dialog').addEventListener('click', () => $('#memory-dialog').close());
$('#memory-form').addEventListener('submit', event => { event.preventDefault(); action(async () => {
  await api('memory', { kind: $('#memory-kind').value, title: $('#memory-title').value, body: $('#memory-body').value, source: $('#memory-source').value });
  $('#memory-dialog').close(); $('#memory-title').value = ''; $('#memory-body').value = ''; toast('Kept in mind.');
}); });
$('#memory-list').addEventListener('click', event => action(async () => {
  const remove = event.target.closest('[data-delete]'), complete = event.target.closest('[data-complete]');
  if (remove) await api('memory-delete', { id: remove.dataset.delete });
  if (complete) await api('memory-complete', { id: complete.dataset.complete });
}));
$('#suggestion').addEventListener('click', event => action(async () => {
  const accept = event.target.closest('[data-accept]'), dismiss = event.target.closest('[data-dismiss]');
  if (accept) await api('accept', { id: accept.dataset.accept });
  if (dismiss) await api('dismiss', { id: dismiss.dataset.dismiss });
}));
window.addEventListener('pagehide', () => { camera.stop(); socket?.close(); });
connect();
