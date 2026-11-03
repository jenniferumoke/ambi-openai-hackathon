export function actionTitle(label) {
  if (label === 'screenshot') return 'Reading the screen';
  if (label === 'open application') return 'Opening the app';
  if (label.startsWith('paste ')) return 'Entering text';
  if (label.startsWith('keypress ')) return 'Using a keyboard shortcut';
  if (label.includes('click')) return 'Clicking a control';
  if (label.startsWith('move ')) return 'Moving the pointer';
  return ({ scroll: 'Scrolling', drag: 'Dragging', wait: 'Waiting for the interface' })[label] || label;
}
export function goalProgress(state) {
  const job = state?.job;
  if (!job?.goal_status) return null;
  if (job.status === 'running') {
    const active = [...(state.activity || [])].reverse().find(row => row.job_id === job.id && row.status === 'running');
    return active ? (active.kind === 'action' ? actionTitle(active.title) : active.title) : 'Working on your goal…';
  }
  return ({ achieved: 'Goal checked.', paused: 'Goal paused. Ask Ambi to continue.', cancelled: 'Goal stopped.' })[job.goal_status] || null;
}
export function shouldExpand(previous, next) {
  const active = value => ['connecting', 'connected', 'stopping'].includes(value?.status) || value?.job?.status === 'running';
  return active(next) && !active(previous);
}
const statusLabels = { running: 'In progress', completed: 'Done', returned: 'Worker returned',
  failed: 'Needs attention', cancelled: 'Stopped', checked: 'Checked' };

export function createActivityView(root) {
  const nodes = new Map();
  return function render(items = []) {
    const ids = new Set(items.map(item => item.id));
    for (const [id, entry] of nodes) if (!ids.has(id)) { entry.node.remove(); nodes.delete(id); }
    for (const item of items) {
      let entry = nodes.get(item.id);
      if (!entry) {
        const node = document.createElement('details');
        const summary = document.createElement('summary');
        const dot = document.createElement('span'); dot.className = 'step-mark'; dot.setAttribute('aria-hidden', 'true');
        const title = document.createElement('span'); title.className = 'step-title';
        const status = document.createElement('span'); status.className = 'step-status';
        const detail = document.createElement('p'); detail.className = 'step-detail';
        summary.append(dot, title, status); node.append(summary, detail); root.append(node);
        entry = { node, title, status, detail }; nodes.set(item.id, entry);
      }
      entry.node.dataset.status = item.status;
      entry.node.dataset.kind = item.kind;
      entry.title.textContent = item.kind === 'action' ? actionTitle(item.title) : item.title;
      entry.status.textContent = statusLabels[item.status] || item.status;
      entry.detail.textContent = [item.kind === 'action' ? item.title : '', item.detail,
        item.status === 'returned' ? 'The worker finished responding. This does not independently verify task success.' : ''].filter(Boolean).join('\n\n');
    }
  };
}
