# Ellis: one-minute proactive demo

`ellis.json` copies the existing fictional developer profile from
`bench/profiles/ellis.json` and adds the requested preferences and cue/action
catalog. Ellis Reed is resuming PairMatch issue PM-17: the pair lookup returns
the wrong kind of result. The profile, history, preferences, and all five
possible actions are preloaded into the voice agent's system context. You act
as Ellis; no introductory prompt is needed.

## Launch

From the repository root in Terminal:

```sh
./scripts/start.sh
```

Ellis is the default. This builds the demo UI, opens Ambi, and automatically starts the voice session.
Ambi welcomes Ellis with the saved PM-17 context. Turn on **Camera cues** in the
browser and allow camera access. Use good light with one face visible. The
backend remains `http://127.0.0.1:8765`; another local frontend can use the same
bootstrap, camera, state, and accept routes. No frontend-specific payloads are
required. Screen context is optional; saved PM-17 context is enough for the
demo's coding offer.

If the UI is already built, the shorter command is:

```sh
uv run python server.py --open
```

Add `--no-autostart` to wait for **Start session** instead. Use `--no-demo` for
ordinary saved memory, the normal Decisions policy, and its 45-second cooldown.
`--demo ellis` remains supported as an explicit selection of the default.
The demo creates a new ignored `data/demo/ellis/<run-id>/` containing isolated
memory, cue history, and an editable copy of `bench/fixtures/code`. Its workspace
path prints in Terminal. Open that copy's `exercise.py` and
`logs/test-session.txt` before recording. Original fixtures and ordinary user
memory are preserved. Each server launch creates a fresh run; ending and
restarting the voice session resets which cue categories have been offered.

Stop any existing server first. To identify a listener without stopping it:

```sh
lsof -nP -iTCP:8765 -sTCP:LISTEN
```

Voice needs the local `.env` API key and microphone access. Computer actions
need Terminal's Accessibility and Screen Recording permissions. Grant these
and load the camera model before the timed rehearsal. The server reports a
missing key in the UI and still exposes the profile and local camera features.

## Cue-to-offer mapping

The `happy`, `tired`, and `unsure` keys are demo scenario names, not emotional
diagnoses. Numeric camera cues still come from the existing local detector.
This demo uses deterministic catalog selection instead of the
Decisions classifier; it is a rehearsal of personalized offers, not an
evaluation of emotion recognition.

| Scenario / camera cues | Proactive default | Other stored choices / confirmation |
| --- | --- | --- |
| Happy / `smiling` | “Ellis, fancy Pharrell’s Happy? Shall I play it in Brave?” | On acceptance, open Brave and verify playback. Alternatives: a **self-reported** local Ambi mood-log note, or Magic Mike Live ticket planning in London. Ask for an alternative verbally; no inferred mood is saved. |
| Tired / `tired_look`, `sleepy_look` | “Would you like me to switch this Mac to Dark Mode and turn on Night Shift?” | Acceptance covers both named settings. Verify each; report unavailable controls. No automatic theme change on detection. |
| Unsure / `furrowed_brow`, `confused_look`, `frowning`, `tense_expression` | “Want me to walk through the failing PairMatch test and help you find the next step?” | Acceptance permits inspection and explanation in the disposable workspace. Ask separately before editing. |

The first action in each rule is the automatic offer. To make mood logging or
ticket planning the smile offer for a different rehearsal, reorder that rule's
`actions` in `ellis.json` and relaunch. All alternatives are available to voice
without changing the default. Mood logging uses Ambi's existing `save_note`
tool; no external mood tracker is connected. Ticket planning first asks for
date, quantity, and budget. A booking requires confirmation of the exact show,
seats, total, and terms; the worker does not enter payment details.

There is a five-second startup settling period and a six-second minimum gap
between offers. Each category is offered at most once per voice session. A
pending offer lasts twelve seconds and is never replaced by another offer.
Dismiss or answer it before trying the next cue. Focus mode, speech, response
audio, recent user activity, and computer work suppress offers. Neutral frames,
camera-off, face loss, expired observations, and activity changes at the actual
voice-send boundary prevent stale offers. Nothing executes during the opening
or proactive voice turn: those turns have tools disabled. Accept the current
card or explicitly agree verbally to authorize its specific task.

## Rehearse the minute

| Time | Presenter action | Expected behavior |
| --- | --- | --- |
| 0–10s | Start/open the Ellis session; let the welcome finish. Camera already allowed. | Ambi addresses Ellis and mentions PM-17 without prompting. |
| 10–22s | Smile until the cue appears; listen to the offer. Dismiss it for this run. | Offers Happy in Brave; playback waits for approval. |
| 22–36s | Return to neutral, then make a sustained yawn-like expression. Dismiss the offer. | Offers Dark Mode plus Night Shift; settings remain unchanged. |
| 36–48s | Return to neutral, then furrow your brow with the copied PairMatch code visible. | Offers to walk through the PM-17 failure. |
| 48–60s | Say “Yes, inspect it,” or accept the card. | The approved computer task starts. Completion can take longer than the minute. |

For a demo centered on a completed desktop action, show only one cue and
accept it early; browser playback and macOS settings are subject to model and
app latency. The timings above are a rehearsal target, not a latency guarantee.
There are no simulated sensor events in this launch path. If a cue fails to
register, adjust lighting/expression and check the camera cue display. Do not
claim detection when using a direct spoken request.

## Offline verification

```sh
uv run pytest -q
(cd ui && npm test && npm run build)
```

`tests/test_ellis_demo.py` checks profile isolation, actual voice system-context
preloading, startup, every mapped category, suppression, cooldown, expiry,
deduplication, transport retries, and tools being disabled at the Realtime
send boundary. `tests/test_ambient_app.py` checks that live demo cues use the
unchanged authenticated API and acceptance is required before sending a task.
