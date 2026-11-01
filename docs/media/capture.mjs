// Run from the repository root after starting isolated local app/profile-lab servers.
// npm ci --prefix ui; node docs/media/capture.mjs
// All session states below are illustrative fixtures, never live agent evidence.
import { chromium } from '../../ui/node_modules/playwright/index.mjs';
import { mkdir, writeFile } from 'node:fs/promises';
const app = process.env.AMBI_CAPTURE_URL || 'http://127.0.0.1:18765';
const lab = process.env.AMBI_LAB_URL || 'http://127.0.0.1:18766';
const out = new URL('./', import.meta.url).pathname;
await mkdir(out + 'frames', { recursive: true });
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1040 }, deviceScaleFactor: 1 });
const errors = [];
page.on('pageerror', e => errors.push(e.message));
// Read only the isolated empty server's state. Never persist its session token.
const bootstrap = await (await page.request.get(app + '/api/bootstrap')).json();
const date = '2026-11-01T12:00:00Z';
const memory = (id, kind, title, body) => ({ id, kind, title, body, source: 'Fictional Ellis demo', status: 'active', created_at: date, updated_at: date });
const memories = [
  memory('task', 'task', 'Pick up the PairMatch bug', 'PM-17: the duplicate-pair test is failing. Inspect the expected behavior before changing code.'),
  memory('preference', 'preference', 'A little context about Ellis', 'Developer. Prefers a short explanation and a concrete next step.'),
  memory('note', 'note', 'Where we left off', 'The PairMatch workspace is ready. Start with the failing test and its function contract.'),
];
let state = { ...bootstrap.state, memories };
await page.route('**/api/**', route => route.fulfill({ json: { ok: true } }));
await page.route('**/api/bootstrap', route => route.fulfill({ json: { ...bootstrap, token: 'illustrative-local-fixture', api_configured: true, state } }));
let socket;
await page.routeWebSocket('**/ws', ws => { socket = ws; ws.send(JSON.stringify(state)); });
await page.goto(app);
await page.waitForSelector('#ambi[data-pose="waiting"]');
await page.waitForFunction(() => document.querySelector('#memory-count').textContent === '2');
await page.evaluate(() => {
  const label = document.createElement('div');
  label.textContent = 'ILLUSTRATIVE SESSION · FICTIONAL DATA';
  label.style.cssText = 'position:fixed;bottom:12px;left:50%;transform:translateX(-50%);background:#233d35;color:#fffdf7;padding:8px 16px;border-radius:30px;font:11px system-ui;letter-spacing:1px;z-index:9999';
  document.body.append(label);
});
await page.locator('.server-logs-panel > summary').click();
await page.waitForTimeout(500);
await page.screenshot({ path: out + 'ambi-overview.png', fullPage: true });
const send = async patch => { state = { ...state, ...patch }; socket.send(JSON.stringify(state)); await page.waitForTimeout(160); };
const steps = [
  { status: 'idle', phase: 'ready' },
  { status: 'connected', phase: 'speaking', transcript: [{ id: 'greeting', role: 'assistant', text: 'Welcome back, Ellis. You left the PairMatch test ready to investigate. Where shall we start?' }] },
  { status: 'connected', phase: 'ready', proactive: { status: 'offered', reason: 'offer_sent' }, suggestion: { id: 'offer', title: 'A hand with PairMatch?', text: 'Want me to walk through the failing PM-17 test and help you find the next step?', task: 'Inspect and explain the failing PairMatch test.', action: 'offer_task_help', expires_at: 999999999 } },
  { suggestion: null, phase: 'working', job: { id: 'example-job', status: 'running', task: 'Inspect the PairMatch test and explain the mismatch.', started_at: 1 }, proactive: { status: 'paused', reason: 'computer_task_running' } },
  { phase: 'ready', job: { id: 'example-job', status: 'completed', task: 'Inspect the PairMatch test and explain the mismatch.', started_at: 1, result: 'Example report: compare the expected pair order with the returned result. Ask before editing.' } },
];
let frame = 0;
for (let i = 0; i < steps.length; i++) {
  await send(steps[i]);
  if (i === 2) await page.screenshot({ path: out + 'ambi-suggestion.png', fullPage: true });
  if (i === 3) await page.screenshot({ path: out + 'ambi-worker.png', fullPage: true });
  for (let j = 0; j < 12; j++) {
    await page.screenshot({ path: out + `frames/${String(frame++).padStart(3, '0')}.png` });
    await page.waitForTimeout(100);
  }
}
await page.unrouteAll({ behavior: 'wait' });
await page.setViewportSize({ width: 1440, height: 580 });
await page.goto(lab);
await page.getByText('Rowan Vale', { exact: false }).first().waitFor();
await page.screenshot({ path: out + 'ambi-bench.png', fullPage: true });
await writeFile('/tmp/ambi-readme-capture/browser-errors.json', JSON.stringify(errors));
await browser.close();
console.log(`Captured overview, suggestion, worker, profile lab and ${frame} animation frames. Browser errors: ${errors.length}`);
