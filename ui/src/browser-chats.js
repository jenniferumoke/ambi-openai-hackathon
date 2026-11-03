// Browser handoff only. Never reads cookies, conversation history or a reply.
export const BROWSER_CHATS = Object.freeze({
  chatgpt: Object.freeze({ name: 'ChatGPT', url: 'https://chatgpt.com/' }),
  claude: Object.freeze({ name: 'Claude', url: 'https://claude.ai/' }),
  gemini: Object.freeze({ name: 'Gemini', url: 'https://gemini.google.com/' }),
});
export function chatHandoff(provider, draft = '') {
  if (!Object.hasOwn(BROWSER_CHATS, provider)) throw new Error('Choose ChatGPT, Claude or Gemini.');
  if (typeof draft !== 'string' || draft.length > 4000) throw new Error('Keep the prompt within 4,000 characters.');
  return { provider, draft: draft.trim(), ...BROWSER_CHATS[provider] };
}
