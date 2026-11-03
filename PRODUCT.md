# Ambi desktop companion

Ambi is a local, voice-first mascot for macOS and Windows. Tap Talk with Ambi (or the mascot) to start an explicit voice conversation. Startup remains silent; no always-listening wake-word detector is included. Listening, muted, speaking, working and permission states are visible. Actions expand beside the mascot, and Stop remains available independently of the optional Type instead composer.

Retain the existing Rive character, saved colour/background/size/movement choices, private local history, and separate platform audio implementations. Voice uses the existing private backend API key, entered only in the native masked setup field. Codex tasks retain Codex sign-in and explicit command/file approvals. Computer access stays a separate opt-in, off at launch. No automatic camera or screen observation.

This is a narrow refinement of the existing native companion surface in Operate mode, following the user-pinned larger mascot, stronger tint and voice-first hierarchy. It does not replace the visual world. Routing follows Impeccable SKILL.md line75: narrow refinements proceed on incumbent code rather than treating missing PRODUCT.md as a new-surface init. No concept lottery or invented historical seed is claimed.

Verification distinguishes synthetic browser UI, native compilation, installed runtime, live voice and real computer actions. Current UI previews use labelled fictional tasks and establish no provider or OS-control success. See ../outputs/ambi-voice-ui-2026-11-02/verification.md. LED signalling is a future extension of the presentation state; no hardware transport is implemented.

## Accepted follow-up requirements

The user selected Hey Ambi wake-word listening with explicit microphone opt-in. This is the desired next voice interaction, not yet implemented. The current tap-to-talk path remains the fallback. Wake-word detection must visibly distinguish armed listening from an active conversation, offer a single off control, and report lock/sleep/device failures honestly.

Browser chat targets are ChatGPT, Claude and Gemini. The first implemented step is an explicit browser handoff with optional user-initiated prompt copy; no conversation import, reply reading or automatic sending. README screenshots and recordings belong on the canonical project page, labelled with actual verification scope.

## Guided computer-use setup

Choosing computer use exposes readiness checks and the missing permission actions. Mac requires Accessibility/Device Control and Data Access plus Screen Recording; Windows requires an unlocked interactive desktop. Incomplete, unknown or non-boolean permission reports never enable input. Status refreshes automatically through existing snapshots. OS permission decisions remain the user's.

Driver reconnect is explicit and only restarts this app's own idle service, retaining its in-memory launch key and local history; it never auto-enables input. Active conversations/tasks and external services block reconnect. Access remains a per-run opt-in, off at launch. Mac acceptance now includes both OS grants, owned-idle reconnect with retained key, native app targeting, Calculator, saved-text read-back, Safari interaction, and Stop/frame lifecycle. Windows coverage is tracked separately.


## Reviewed computer goals

Mac computer work now has a bounded execute/check/replan loop. A read-only reviewer checks fresh evidence before completion or continuation; incomplete work may use another permitted approach. Private text checkpoints preserve the original goal and progress. Explicit resume rechecks state before action. Stop cancels both work and review and never triggers an automatic restart. The activity header pins current work/check status; history distinguishes checked completion from a worker reply.

This is task autonomy within existing permissions, not AGI. Defaults are six review rounds and fifteen minutes per explicit run/resume; unsafe/ambiguous or exhausted work pauses honestly. Live tests include routine UI fallback, checkpoint survival over a backend restart, explicit resume of the same file goal to an exact saved result, and cancellation with no further actions. Long-duration/general reliability and Windows parity for this revision remain unverified.
