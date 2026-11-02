# Desktop companion UI preview — 2 November 2026

These screenshots and silent walkthrough show the locally built companion UI with the existing Rive animation. They use an isolated loopback fixture with synthetic state and fictional text. No live microphone, AI task, inbox, real screen action or existing chat history was recorded. The caption remains visible in every frame.

The sequence contains60 browser screenshots: idle, listening, working, stopped, and the browser-chat handoff form,12 frames each. Playback is retimed to5fps (12seconds); this is not measured latency or a continuous native screen recording. The listening state is synthetic. Native screen-edge overlays cannot be established from this browser fallback.

Assets: `idle.jpg`, `working.jpg`, `browser-chats.jpg`, `ambi-companion-walkthrough.gif`, `ambi-companion-walkthrough.mp4`. The MP4 is940x640, H.264, silent,12seconds; the GIF is840px wide. Original capture uses the computer-use screenshot API against the compiled UI, with no user desktop or account screenshots.

Source: local `codex/macos-companion` and `codex/windows-companion` worktrees. They contain a development candidate beyond the current main-branch demo. These images do not imply that a packaged release or the candidate source has been merged into main.

Browser chat compatibility is currently a handoff: select ChatGPT, Claude or Gemini, optionally copy a prompt, then review and send it yourself. It does not import conversations, read replies, or send automatically. The three destinations opened in browser testing; authenticated conversations and native clipboard/open behavior remain unverified.

Wake-word listening (Hey Ambi) with explicit microphone opt-in is requested but not implemented. Live voice, real native desktop control, updated native overlays, signing/notarization and installer acceptance remain release gates. Existing installed demos were not replaced for this capture.
