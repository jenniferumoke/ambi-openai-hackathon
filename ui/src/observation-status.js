// Explanations use server state, never infer a session or emotion from a face.
const proactiveReasons = {
  session_not_connected: 'Start a voice session for cue-based offers.',
  focus_mode: 'Focus mode is on. Ambi responds only when you ask.',
  user_speaking: 'Listening to you before offering help.',
  recent_user_activity: 'Waiting for a pause in the conversation.',
  response_in_progress: 'Finishing the current reply.',
  audio_playing: 'Waiting for speech playback to finish.',
  computer_task_running: 'Finishing the current computer task.',
  session_warmup: 'Offers begin after the opening greeting.',
  cooldown: 'Taking a short pause between offers.',
  pending_suggestion: 'Accept or dismiss the current offer.',
  offer_sent: 'An offer is ready. Accept it to authorize the task.',
  already_offered: 'This demo offer was already made. Ask directly, or start a new session to rehearse it again.',
  no_fresh_camera: 'Waiting for fresh camera cues. Keep one face in view.',
  no_matching_cue: 'Watching for a stable cue that matches a demo offer.',
  no_relevant_context: 'Waiting for a relevant cue or noteworthy screen change.',
  already_considered: 'This context was already considered. You can still ask for help.',
  no_offer_needed: 'No useful offer for the current context. You can still ask for help.',
  no_task_context: 'Add a task or enable screen context for a relevant offer.',
  checking_context: 'Checking whether an offer would help…',
  preparing_offer: 'Preparing a brief offer…',
  voice_busy: 'Voice is busy. Retrying while the cue is still relevant.',
  retry_backoff: 'The last check failed. Retrying shortly.',
  decision_unavailable: 'The offer check failed. Retrying shortly.',
};

export function proactiveStatus(state) {
  if (state.status === 'error') return 'Voice session stopped. Start a new session to hear replies.';
  if (state.status === 'connecting') return 'Connecting voice…';
  if (state.status === 'stopping') return 'Ending the session…';
  return proactiveReasons[state.proactive?.reason]
    ?? (state.status === 'connected' ? 'Say “stop” to cancel computer work. “Bye” ends the session.'
      : proactiveReasons.session_not_connected);
}

export function screenStatus(computer = {}) {
  if (computer.reason === 'screen_permission_missing') return 'Screen Recording permission needed for the launching app';
  if (computer.reason === 'screen_observation_off') return 'Screen observation is switched off';
  if (computer.reason === 'model_access_or_configuration') return 'Screen observer unavailable · check model/API access';
  if (computer.reason === 'capture_unavailable') return 'Screen capture unavailable · check Screen Recording permission';
  if (computer.reason === 'analysis_unavailable') return 'Screen analysis failed · retrying';
  if (['screen_changed', 'task_context_changed', 'context_changed_during_analysis', 'context_changed_during_capture'].includes(computer.reason)) return 'Screen changed · refreshing context…';
  if (computer.reason === 'expired' || computer.reason === 'expired_during_analysis') return 'Screen context expired · refreshing…';
  return { available: 'Screen context active · primary display', waiting: 'Reading screen context…',
    paused: 'Screen observer paused during computer work' }[computer.status] ?? 'Screen context off';
}
