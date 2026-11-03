# Ambi Windows companion 0.5.0

A native WPF/WebView2 host for the shared Ambi character, setup, Codex tasks,
conversation/activity view and colour-matched screen-edge glow.

Extract the complete `Ambi-Windows-Companion-0.5.0.zip`, then run `Ambi/Ambi.exe`
as an ordinary Windows user. Keep all extracted files together. Windows 10/11
x64 and Microsoft Edge WebView2 Runtime are required. The package includes .NET,
Python 3.12.16, locked Python dependencies and Codex 0.149.0. Python does not
need downloading on first launch; online model requests and sign-in still need
internet. The host is cross-buildable on Mac and remains **unsigned**. A separate native
candidate passed narrow Lenovo acceptance; the current integrated build still
needs fresh Windows runtime acceptance. See the dated evidence below.

Choose Connection → Start Local Service, then Setup & connections. Connect
Codex using its own sign-in, choose an available model and a working folder.
Typed tasks need no voice API key or microphone. File writes default off;
permission requests show command/patch context with explicit one-time decisions.
Conversations and tasks stay in local SQLite storage across restarts. Earlier
messages load in pages; interrupted work never automatically resumes.

For voice, Configure API Key for This Launch uses a masked field; the key stays
in host/process memory. Starting voice is explicit. Windows uses compatible
PortAudio capture, muted during playback; spoken interruption is not claimed.
Computer control requires a separate per-run opt-in and an available interactive
desktop. Actions target the primary display, are cancellable, and stop if the
interactive desktop becomes unavailable. Actual lock/UAC behavior still needs
Windows validation. The Mac passive screen observer remains unavailable here.
Opening the app/service never activates voice, camera or desktop access.

Ctrl+D expands activity, Ctrl+period stops the current task. The blue mascot is
the executable/taskbar icon. Customize Ambi offers six character colours, navy,
white/black backgrounds, size and animation. Screen-edge glow follows the chosen
agent colour across monitors, with a separate Stop/Close control. It is
click-through, non-activating and clears on disconnect, timeout or shutdown.
Real mixed-DPI, multi-monitor, full-screen and lock/UAC checks remain outstanding.

The host only accepts messages from the exact authenticated loopback companion
page. It binds its service to 127.0.0.1:8767 and never replaces a foreign listener.
Preferences and service data live under `%LOCALAPPDATA%/AmbiCompanion`. The
backend source is copied from an explicit package allowlist. No `.env`, keys,
Codex auth, history or logs are shipped. Closing stops owned tasks/session and
owned processes; an externally started service is left running. Logs may contain
user task/voice content; review them before sharing. Copy diagnostics omits
content and credentials. Check for Updates opens the releases page; no automatic
update installer is implemented.

## Build and verify

```sh
(cd ui && npm ci && npm run build)
uv run --locked python scripts/prepare-windows-runtime.py
uv run --locked pytest -q
dotnet run --project desktop/windows/tests/Ambi.PolicyTests.csproj -c Release
uv run --locked python scripts/build-windows.py
```

The runtime preparer verifies pinned official Python/Codex archive hashes and
installs the lockfile's Windows wheels. Set `AMBI_DOTNET` for a specific SDK.
The host publishes self-contained win-x64. Runtime provenance and the final ZIP
checksum are stored beside the build. No Windows binaries were executed on Mac.

A per-user Inno Setup definition is prepared in `installer/Ambi.iss`. On Windows,
with Inno Setup installed, run `python scripts/build-windows-installer.py`.
`AMBI_ISCC` selects its compiler. Optional `AMBI_SIGN_CERT` is an installed
certificate-store thumbprint; `AMBI_SIGNTOOL` and the provider's HTTPS
`AMBI_SIGN_TIMESTAMP` enable verified signing of the host and outer installer.
No private key or password is exported. Without those inputs, the installer
remains unsigned. The installer has not been compiled or installed here.

Before release, test on Windows: first launch/WebView2, Codex sign-in/task,
read-only versus write approval, cancellation and recovery, history after restart,
real microphone/audio, explicit desktop opt-in/input, lock/UAC, monitor scaling,
frame cleanup, installer upgrade/uninstall and certificate verification.

References: [companion API](../../docs/companion-api.md),
[release evidence](../../docs/product-readiness.md),
[Microsoft WPF/WebView2](https://learn.microsoft.com/en-us/microsoft-edge/webview2/get-started/wpf).

## Guided computer-use setup candidate — 2 November 2026

The shared UI checks for an available interactive Windows desktop before the per-run Enable action. It gives unlocked-session guidance rather than Mac permission links. Reconnect only handles this host's owned idle service and retains its in-memory launch key; active voice/jobs and external listeners are refused. No elevation, UAC bypass, automatic input grant, or kiosk/service changes.

68 UI tests,24 native policy/lifecycle checks and win-x64 publish pass on Mac. The new host is in `artifacts/driver-setup-preview/windows-native`; it has not been installed or runtime-tested on Lenovo. Cross-compilation and offline tests are not Windows-control proof.

## Live Lenovo acceptance — 3 November 2026

A separate copied test app with the service-log restart repair was launched under the non-elevated maintenance account. Direct masked key configuration successfully restarted its owned backend. A live typed computer task opened a new Notepad document, saved the exact 59-byte test line, closed/reopened it and completed; independent file read/hash matched. Actual teal frame and native Stop banner appeared during control and cleared afterward. A separate read-only task was cancelled by clicking the native banner's Stop; the job became cancelled, action rows stayed 46 across five seconds, and the file hash stayed unchanged. Final session idle, microphone off, control off. Original test folder, older Electron processes and original voice demo preserved; approved temporary ZIP-only transfer tunnel closed.

Recordings and verification are in the workspace's `outputs/ambi-recordings-2026-11-03/`. The updated host passed 27 native checks and win-x64 publish before transfer. This validates these narrow live tasks and the key restart fix, not arbitrary Windows reliability or parity with the newer Mac reviewed-goal loop. Fresh spoken-command acceptance and broader Windows testing remain separate.
