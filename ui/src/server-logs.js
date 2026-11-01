const detailFields = ['message', 'reason', 'status', 'error_type', 'code', 'location', 'action', 'rule', 'action_id', 'latency_ms'];

export function createServerLog(limit = 200) {
  const events = new Map();
  let startedAt = null;
  let clearedIds = new Set();
  return {
    reset() { events.clear(); startedAt = null; clearedIds.clear(); },
    clear(items = []) {
      events.clear(); startedAt = null;
      // The server repeats its latest events on every snapshot.
      clearedIds = new Set(items.map(event => event?.id));
    },
    update(items = []) {
      for (const event of items) {
        if (!event?.id || !event.type || clearedIds.has(event.id)) continue;
        if (startedAt === null && Number.isFinite(event.at)) startedAt = event.at;
        events.set(event.id, event);
      }
      while (events.size > limit) events.delete(events.keys().next().value);
      return [...events.values()].map(event => {
        // These are server monotonic seconds, not browser wall-clock dates.
        const elapsed = Number.isFinite(event.at) && startedAt !== null ? `+${Math.max(0, event.at - startedAt).toFixed(3)}s` : '—';
        const details = detailFields.filter(key => event[key] !== undefined && event[key] !== null)
          .map(key => `${key}=${typeof event[key] === 'string' ? event[key] : JSON.stringify(event[key])}`).join(' · ');
        return `[${elapsed}] ${event.type}${details ? ` — ${details}` : ''}`;
      }).join('\n');
    },
  };
}
