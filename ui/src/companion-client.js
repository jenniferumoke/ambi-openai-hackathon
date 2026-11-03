// The companion uses the documented API, independently of the demo UI's DOM.
export function createCompanionClient({ fetcher = fetch, Socket = WebSocket, base = location.origin,
  onState, onError, onConnection = () => {}, schedule = setTimeout, cancel = clearTimeout }) {
  let token, socket, timer, disposed = false, ready = false, generation = 0;
  async function connect() {
    const current = ++generation;
    ready = false;
    try {
      const response = await fetcher(`${base}/api/bootstrap`, { cache: 'no-store' });
      if (!response.ok) throw new Error('Ambi service is unavailable. Use Connection → Reload.');
      const data = await response.json();
      if (disposed || current !== generation) return;
      token = data.token;
      onState(data.state, data.api_configured);
      socket = new Socket(`${base.replace(/^http/, 'ws')}/ws`, ['ambi', token]);
      socket.onopen = () => { if (!disposed && current === generation) { ready = true; onConnection(true); } };
      socket.onmessage = ({ data }) => {
        if (disposed || current !== generation) return;
        try { onState(JSON.parse(data)); } catch { onError('Could not read Ambi state. Reload the connection.'); }
      };
      socket.onclose = () => {
        if (disposed || current !== generation) return;
        ready = false; onConnection(false); timer = schedule(connect, 2000);
      };
    } catch {
      if (disposed || current !== generation) return;
      ready = false; onConnection(false);
      onError('Local Ambi service is offline. Use Connection → Start Local Service.');
      timer = schedule(connect, 2000);
    }
  }
  return {
    connect,
    async send(action, body = {}) {
      if (!ready || disposed) throw new Error('Ambi is reconnecting. Please wait.');
      const response = await fetcher(`${base}/api/${action}`, { method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Ambi-Token': token }, body: JSON.stringify(body) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'The action could not be completed.');
      return result;
    },
    dispose() { disposed = true; ready = false; generation++; cancel(timer); socket?.close(); },
  };
}
