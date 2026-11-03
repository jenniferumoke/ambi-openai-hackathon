# Ambi macOS companion

A native AppKit/WebKit window led by the existing animated Ambi character.
It uses the same-origin, authenticated backend API, independently of the demo UI.
The thin web host and process-launch patterns follow the local Sally Mac app;
Sally's authentication, commerce, browser tabs and agent configuration are not included.

## Build and run

Requires macOS 14+, Xcode command-line tools, Node 22+, uv and Python 3.12.
From the repository root:

```sh
uv sync --locked --python 3.12
cp .env.example .env
# Configure the private .env locally, or link your existing private Ambi .env.
(cd ui && npm ci && npm run build)
sh scripts/build-macos.sh
```

Open `artifacts/macos/Ambi.app`. Choose **Connection → Start Local Service** if
the backend is offline. An existing listener is never replaced. The backend
must serve the newly built `/companion.html`; use **Connection → Reload** after
starting it. The full dashboard remains at `http://127.0.0.1:8765/`.

## Controls

- **Session:** start/end (Command-S or Space), stop computer work (Command-period),
  mute/unmute, focus mode, next-session screen context, and review an offer.
- **View:** white/black background, small/medium/large window (Command-1/2/3),
  character scale, always on top, and Show or Hide Activity (Command-D).
  Appearance preferences persist locally.
- **Connection:** reload, start the local service, full browser controls, diagnostics.
- **Ambi → Customize Ambi…** (Command-comma): display name, six colour treatments,
  white/black background, animated/still mode and character size, with live preview.
- Closing the last window quits. A session started in this companion is stopped
  on quit; an externally started session is not adopted. An app-launched service
  is terminated on quit. An externally launched service remains running.

The 0.5 packaged service starts idle, without fictional demo data or sensors.
Typed Codex tasks work independently of voice; see the current 0.5 section below.
The original server CLI retains its explicit demo/development behavior.

## Acceptance and verification

- Native binary compiles; `swift test` checks exact-origin navigation and safe
  bridge argument serialization. The local app bundle passes `codesign --verify`.
- `npm test` checks startup without sensor activation, authentication rotation,
  disconnect handling, and the existing frontend behavior; `npm run build` builds
  both the dashboard and companion.
- Run the repository's `uv run pytest -q` backend suite after integration changes.
- Inspect the actual Mac window: animated character only, white and black themes,
  small/large sizes, menu actions, focus/mute round trips, and shutdown/reconnection.
  Do not equate these checks with live voice, camera or desktop-task success.

This is an **ad-hoc signed development app**, tied to the checkout path embedded
at build time. It needs that checkout, its built UI and local dependencies.
It is not yet a notarized, self-contained distribution. Backend permissions
belong to its launching application; previously granted Codex permissions may
not carry over when the Mac app launches Python.

Service output is stored privately at
`~/Library/Application Support/Ambi/service.log`; it can include task/voice text
emitted by the existing backend. Do not share that log without reviewing it.

## Character asset

`ui/public/ambi-companion.riv` removes only artboard background fills from the
existing v2 controller and nested artboards. The dashboard still uses `ambi.riv`.
To regenerate with the original source pack and Rive CLI 1.8.0:

```sh
python3 ui/scripts/build-rive-controller.py /path/to/ambi-rive-2026-11-01 /path/to/rive \
  --transparent --output ui/public/ambi-companion.riv
```

## Verified locally, 1 November 2026

- Release Swift build, strict Swift formatting, two native policy tests, and
  ad-hoc bundle signature verification passed.
- 49 frontend tests, the two-entry production build, and 318 backend tests passed;
  five opt-in camera/screen/provider checks were skipped.
- The real WKWebView rendered the animated character on pure white and black,
  at 260-, 480- and 720-point window widths. No cream artboard remained.
- Native focus and mute actions were confirmed through backend snapshots and
  restored. A disconnected service produced a recovery pose and actionable text.
- Start Local Service launched the backend from the native app and reconnected;
  quitting terminated the app-owned service. No voice session or desktop task
  was initiated during these surface checks.

Not yet verified: live audio or desktop permissions when Python is launched by
Ambi, suggestion acceptance in a live session, and shutdown of an active voice
session. The session-shutdown path is implemented but needs a supervised check.

## Expanded activity view

The Mac companion draws a native teal frame around every connected display,
with a separate **Stop task** control while a backend computer task is running.
The display-sized panels pass mouse events through and never take keyboard
focus. The small control bar alone accepts clicks. Frames join Spaces and
support full-screen apps, and rebuild when the display configuration changes.
They clear on task completion, disconnect, reload, web-process failure, quit,
or a three-second lapse in backend state updates. They are an activity indicator,
not a permission boundary. **View → Preview Whole-Screen Frame**, or the activity
panel's preview button, shows a labelled preview with **Close preview**.
The ordinary browser retains its window-local fallback. The empty view includes
a sample prompt that fills a draft without starting voice or sending.
Saving a character colour also updates the display glow and control-bar tint.
The frontend's existing palette supplies the colour; the native bridge accepts
only a six-digit hexadecimal RGB value. A saved Blue choice was confirmed as
`#83a9ec` in native diagnostics, then the original Teal choice was restored.
Drafts can be edited before a session connects; Send still requires a session.

Frame checks on 1 November: 55 frontend tests and the production build passed.
The native window displayed the labelled preview in both themes. The companion
keeps a fixed 1360×960 backing canvas and scales it with CSS so WKWebView layout
changes do not discard the character. Conversation scrolling stays inside the
activity panel, with the header and composer visible.

A real typed sample asked for a three-step Ambi test plan with no app/file
actions. The session connected and returned a three-part reply, with microphone
muted and screen observation disabled. The backend reported compatibility audio;
audible playback and spoken interruption were not verified. The session was
ended afterward, the previous microphone preference restored, and no computer
job was launched. Live desktop actions remain unverified.

Whole-screen follow-up: 56 frontend tests, four native tests, release build,
strict Swift formatting and signature verification passed. Native diagnostics
confirmed two visible panels on the one connected display during preview and
zero after reload. Command-D continued to operate the underlying main window.
The preview is left enabled. Our window-scoped computer-use screenshots do not
capture these separate overlay panels. Multi-display placement, other Spaces,
full-screen third-party apps, and the Stop button during a live computer task
still need supervised visual checks.

Starting a session expands the window, moves Ambi left, and opens the activity
panel on the right. Command-D or the activity control opens it without starting
voice. Collapsing it restores the previous compact window dimensions; subsequent
snapshots do not force it open until a new session/task begins. Reduced-motion
preferences are respected by the character and step indicators.

The panel shows real session events, computer tasks, and individual desktop
operations. Each operation has expandable details, including returned/failed/
cancelled status. Disclosure state survives streaming updates. The feed retains
up to 200 process-local entries separately from the short diagnostic buffer.
It does not expose internal model reasoning. Typing actions report a character
count, not entered text, and screenshots never enter the activity log.

Assistant/user messages appear below the operation feed. A composer supports
typed turns when the voice session is connected; Enter sends, Shift-Enter adds
a line. Suggestions have explicit accept/dismiss controls, and active computer
tasks have a Stop button. The worker-returned label deliberately does not claim
independent verification of task success.

This section records the earlier presentation/feed milestone. The 0.5 section
below supersedes its earlier Codex/history and platform limitations.

Expanded-view checks: 321 backend tests (five live checks skipped), 51 frontend
tests, two native tests, release build and signature checks passed. The actual
Mac window expanded/collapsed and rendered both themes. A separate, clearly
labelled synthetic fixture verified populated action disclosures and their
persistence across WebSocket updates. No live computer action, microphone or
screen capture was initiated for these UI checks.

## Personal setup

The first launch without completed preferences opens **Make Ambi yours**. The
character-only and activity views also have a Customize Ambi control. Settings
are previewed in a modal and applied only with **Save my Ambi**. Closing the
modal or pressing Escape discards the draft. The window returns to its previous
dimensions after closing setup.

Native preferences are validated and saved to the app's own UserDefaults;
browser use falls back to local storage. Only appearance is stored. Display
name does not rewrite the voice agent's identity or saved memory. The six
colours are runtime colour treatments of the existing artwork, preserving
its animations. Classic Ambi is the currently available character; this screen
does not include OpenAI's Dot characters or ChatGPT Pets.

Reduced-motion settings take precedence over the Animated choice. The main
character and both setup previews share the selected motion preference.
Native Edit commands support ordinary selection, copy/paste and name editing.

Setup verification: 53 frontend tests, four native tests, the production UI and
Swift release builds, strict Swift formatting, and bundle signature checks
passed. In the actual Mac app, a test name, Lilac and Still survived a restart;
unsaved changes were discarded on closing. The original Ambi/Teal/Animated
choices were restored and setup was left open. No voice session was started.

## Navy/blue identity and character icon (0.2.0)

The default palette is Blue (`#5b8def`) on Navy (`#0d1b2a`), with white text,
blue actions and a matching display glow. White/Black and the other character
colours remain available. Existing saved preferences are respected; this Mac
was explicitly switched to Blue/Navy through setup and the choices survived
restart. The application icon is the blue Ambi mascot, exported from the shared
transparent artwork as ICNS/ICO/PNG. Bundle metadata, the runtime icon and native
alert icon are wired to this asset. Rebuild with `sh scripts/build-macos.sh`.

Verified: 321 backend tests (five opt-in checks skipped), 57 frontend tests,
five native tests, production UI/native builds, strict formatting, diff checks
and bundle signature passed. The actual Mac window displayed the navy palette,
blue character and blue native alert icon. Native diagnostics confirmed a blue
`#5b8def` display preview with two visible panels on the connected screen.

The matching Windows build lives in the separate `ambi-windows-companion`
checkout. Its 0.4.0 ZIP cross-build passed; it has not been run on Windows here,
and its computer worker remains disabled. See that checkout's Windows README
for the exact runtime acceptance checks.


## Current 0.5.0 companion

The full Setup & connections screen connects bundled Codex using its own sign-in,
discovers available models, selects a working folder and explains OS access.
Typed Codex tasks stream replies and actual operation progress. File writes are
opt-in for the selected folder; explicit approval requests show command/patch
context with one-time decisions. Stop supports connection startup and active
turns. Closing cancels only the app's owned task/session and service tree.

Conversations and task activity persist in a private local SQLite archive.
Earlier messages can be loaded in pages. Restart marks interrupted operations
cancelled and never resumes tasks, desktop access, voice or sensors automatically.
Copy diagnostics excludes messages, keys, raw errors and sign-in credentials.
Check for Updates opens the canonical releases page; automatic updating is not
implemented.

Build a standalone service and signed arm64 bundle:

```sh
(cd ui && npm ci && npm run build)
uv run --with pyinstaller==6.16.0 python scripts/build-service.py
uv run --locked python scripts/build-macos-release.py
```

The bundle includes Python/dependencies and the complete pinned Codex 0.149.0
standalone package, preserving its vendor signature. No root `.env`, auth files
or user data are included. Set `AMBI_RELEASE_DIR` to a fresh candidate directory
when another built bundle is running. An installed Developer ID Application
identity signs the app; no key is exported. `AMBI_NOTARY_PROFILE` optionally names
an existing notarytool keychain profile. Without it, the signed build remains
**not notarized**, and is not ready for public distribution.

The actual signed companion connected Codex and completed a read-only fixture
file task with voice and computer control off. The newer frozen helper was also
checked outside the checkout with a real Codex task and restart persistence.
Final native UI/restart and Accessibility/Screen Recording acceptance still need
the Mac unlocked and the user's OS permission review. Multi-monitor glow is
implemented; computer actions currently target the primary display only.
See [product-readiness](../../docs/product-readiness.md) for remaining gates.

## Guided computer-use setup candidate — 2 November 2026

Connections → Computer use now offers Set up computer use when permissions are missing, a live checklist, links to Device Control and Data Access (older macOS: Accessibility), a screen-access request, and Reconnect driver & check again. Reconnect restarts only an owned idle service, retains the native in-memory launch key, and keeps input disabled until the explicit per-run Enable action. Active voice/tasks and external listeners fail closed. User reviews every OS grant.

Voice-key setup now handles the auto-started owned service: the masked Use Key action reconnects it instead of refusing setup. The corrected native candidate completed a real microphone/provider reply; the user confirmed hearing it. End conversation reached idle. Compatibility audio was active; spoken interruption is not established. A Chrome task was blocked by missing computer permissions, not counted as a successful action. Original bundle and private SQLite backups retained.

`artifacts/driver-setup-preview/Ambi.app` is a separate Developer ID signed test candidate, not notarized and not launched. New setup flow has synthetic UI coverage,69 UI tests and6 native tests; actual reconnect/OS-grant/input acceptance remains pending. Running `browser-chat-preview-fixed` app is an earlier candidate with the working key fix, not the new checklist flow.


## Reviewed-goal development acceptance — 2 November 2026

The signed `artifacts/computer-driver-lab/Ambi.app` runs the locked workspace backend, retaining its masked launch key through owned-idle reconnects. Computer goals execute, check fresh evidence, replan within scope and save text-only private checkpoints. Explicit continuation rechecks the original goal before further actions; Stop cancels the whole loop. The native host marks its launch so workspace dotenv is not loaded.

Live Mac checks passed: synthetic Safari quick-save failure recovered through Standard save; a paused file goal survived backend restart and explicit resume, completing at review round four with independent exact file read-back; Stop cancelled and persisted cancellation with no more actions; native frame panels changed four across two displays to zero. Some recovery required a developer activation fix before resume, so this does not establish autonomous self-modification or arbitrary task reliability.

Final source checks: 368 Python passed/5 skipped; 71 UI passed/build passed; six Swift host tests passed. Separate `artifacts/reviewed-goals-preview-v2/Ambi.app` bundles the frozen service, passes deep/strict Developer ID signature verification and frozen startup/UI smoke checks. Its native host/keyed loop was not launched and it is not notarized. The live development host remains separate. Long-duration soak, Windows parity and general secondary-display input remain open.
