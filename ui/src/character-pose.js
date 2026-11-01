// Presentation-only state: never changes session or backend state.
export function createPoseController({ now = () => performance.now(), schedule = setTimeout, cancel = clearTimeout, changed = () => {} } = {}) {
  let previousJob, initialized = false, successUntil = 0, timer;
  return {
    update(state) {
      const job = state.job;
      // An already-completed job in the initial snapshot is not a new completion.
      if (initialized && job?.status === 'completed' && (previousJob?.id !== job.id || previousJob?.status !== 'completed')) {
        successUntil = now() + 3000;
        cancel(timer);
        timer = schedule(() => { successUntil = 0; changed(); }, 3000);
      }
      initialized = true;
      previousJob = job ? { id: job.id, status: job.status } : null;
      if (state.status === 'connecting') return 'thinking';
      if (state.status === 'error') return 'recovering';
      if (state.status !== 'connected') { successUntil = 0; return 'waiting'; }
      if (now() < successUntil) return 'success';
      if (state.suggestion) return 'needsYou';
      return { listening: 'listening', speaking: 'speaking', working: 'working', ready: 'listening' }[state.phase] || 'waiting';
    },
    dispose() { cancel(timer); },
  };
}
