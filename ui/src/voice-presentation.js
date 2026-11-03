// Presentation only: no microphone, permission or task is started here.
export function voicePresentation(state = {}, connected = false, configured = false) {
  const active = ['connected', 'connecting'].includes(state.status);
  const result = { phase: 'idle', label: 'Ready when you are', button: active ? 'End conversation' : 'Talk with Ambi', disabled: !connected || state.status === 'stopping', hint: 'Tap to talk. Your microphone stays off until you start.' };
  if (!connected) return { ...result, phase: 'offline', label: 'Reconnecting to Ambi', hint: 'Waiting for the local connection…' };
  if (state.codex?.pending?.length || state.codex?.status === 'approval-required') return { ...result, phase: 'attention', label: 'Your permission is needed', hint: 'Review the request in your activity panel.' };
  if (state.status === 'error') return { ...result, phase: 'error', label: 'Voice needs attention', hint: 'Check the connection message, then try again.' };
  if (state.job?.status === 'running') return { ...result, phase: 'working', label: 'Working on your task', hint: 'Follow the actions alongside Ambi. Stop at any time.' };
  if (state.status === 'connecting') return { ...result, phase: 'connecting', label: 'Connecting your voice', hint: 'You can end the connection at any time.' };
  if (state.status === 'stopping') return { ...result, label: 'Ending conversation', hint: 'Turning off the voice session…' };
  if (state.status === 'connected') {
    if (state.phase === 'speaking') return { ...result, phase: 'speaking', label: 'Ambi is speaking', hint: 'Your conversation and actions appear alongside Ambi.' };
    if (state.phase === 'working') return { ...result, phase: 'working', label: 'Thinking it through', hint: 'Ambi is preparing a response.' };
    return { ...result, phase: state.microphone_enabled ? 'listening' : 'muted', label: state.microphone_enabled ? 'Listening to you' : 'Microphone muted', hint: state.microphone_enabled ? 'Speak naturally. End the conversation when you’re done.' : 'Unmute your microphone or choose Type instead.' };
  }
  return configured ? result : { ...result, hint: 'Set up your voice connection to start talking.' };
}
