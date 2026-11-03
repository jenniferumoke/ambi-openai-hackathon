import test from 'node:test';
import assert from 'node:assert/strict';
import { createCompanionClient } from '../src/companion-client.js';

function harness() {
  const calls = [], sockets = [], states = [], errors = [], connections = [], retries = [];
  let token = 'first';
  class Socket {
    constructor(url, protocols) { Object.assign(this, { url, protocols }); sockets.push(this); }
    close() { this.onclose?.(); }
  }
  const client = createCompanionClient({ base: 'http://127.0.0.1:8765', Socket,
    fetcher: async (url, options) => {
      calls.push({ url, options });
      return { ok: true, json: async () => url.endsWith('bootstrap') ? { token, api_configured: true, state: { status: 'idle' } } : { ok: true } };
    }, onState: (...args) => states.push(args), onError: e => errors.push(e),
    onConnection: value => connections.push(value), schedule: fn => { retries.push(fn); return retries.length; }, cancel: () => {},
  });
  return { client, calls, sockets, states, errors, connections, retries, rotate: () => { token = 'second'; } };
}
test('bootstrap does not start sensors or voice; actions require a connected socket', async () => {
  const h = harness();
  await h.client.connect();
  assert.equal(h.calls.length, 1);
  await assert.rejects(h.client.send('start'), /reconnecting/);
  h.sockets[0].onopen();
  await h.client.send('start', { observe_screen: false });
  assert.equal(h.calls[1].options.headers['X-Ambi-Token'], 'first');
  assert.deepEqual(JSON.parse(h.calls[1].options.body), { observe_screen: false });
  assert.deepEqual(h.sockets[0].protocols, ['ambi', 'first']);
});
test('restart reboots authentication and ignores messages from the old socket', async () => {
  const h = harness();
  await h.client.connect(); h.sockets[0].onopen(); h.sockets[0].onclose();
  await assert.rejects(h.client.send('stop'), /reconnecting/);
  h.rotate(); await h.retries[0](); h.sockets[1].onopen();
  const before = h.states.length;
  h.sockets[0].onmessage({ data: '{"status":"connected"}' });
  assert.equal(h.states.length, before);
  await h.client.send('focus', { enabled: true });
  assert.equal(h.calls.at(-1).options.headers['X-Ambi-Token'], 'second');
  h.client.dispose();
  await assert.rejects(h.client.send('start'), /reconnecting/);
  assert.equal(h.retries.length, 1);
});
test('malformed state produces a recoverable error', async () => {
  const h = harness(); await h.client.connect();
  h.sockets[0].onmessage({ data: 'invalid' });
  assert.match(h.errors[0], /Reload/);
});
