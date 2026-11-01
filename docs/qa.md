# Demo verification

Checked against the production UI at `http://127.0.0.1:8765` on 1 November 2026.
This inventory distinguishes automated checks, real provider calls, and hardware
checks that still need the launching app's macOS permissions.

| Claim / control | Check | Status |
| --- | --- | --- |
| Short expressions do not require a multi-second hold | Three supporting frames, transient noise, neutral reset, missing/multiple faces, stale gaps | JS tests pass; 134ms synthetic onset |
| Real local vision model loads off the UI thread | Chrome synthetic camera through the normal camera switch | Pass; classic WASM worker, about 10ms/frame on the no-face feed |
| Camera can stop and restart | Toggle off/on, inspect track state and cue clearing | Pending |
| Memory survives a restart | SQLite close/reopen, complete, delete, literal search | Python tests pass |
| Memory UI is usable | Add task and note, refresh, complete task, delete test data, modal keyboard escape | Pending |
| Startup speaks first using saved context | Live Realtime session without microphone input | Pending |
| Decisions classifier is real | Live Decisions request with a synthetic cue and project context | Pass; returned `offer_task_help` |
| Late suggestions cannot interrupt a new user turn | Delayed Decisions result + new user turn | Python test passes |
| Focus / expired suggestion / local API authentication | Focus toggle, expiry, origin and token checks | Python tests pass; browser focus pending |
| Desktop and microphone work on the demo Mac | Terminal permissions, actual voice interruption and computer task | Pending hardware rehearsal |
| Initial layout is readable and unclipped | 1440×1000, 1280×800, 390×844 | 1440 inspected; smaller sizes pending |
| Interactive states remain readable | Memory dialog, populated memory, conversation, suggestion, stopped session | Pending |
| No accidental horizontal overflow or console exceptions | Viewport bounds + browser errors + exploratory clicks | Pending |

Screenshots are kept locally under ignored `artifacts/qa/`. Synthetic camera and
API tests do not establish expression accuracy on a particular face, room, or
lighting setup. Speaker identification/diarization is not implemented; macOS
echo cancellation and speech confirmation mitigate playback/keyboard triggers.
