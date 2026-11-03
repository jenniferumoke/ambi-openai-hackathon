# Source provenance

The Windows host was initially ported from the native Mac companion and earlier Electron voice/Notepad prototype on 1 November 2026. `mac-source-snapshot.json` preserves the initial file hashes as historical provenance, not a claim that this old snapshot is the current shared backend.

The integrated source keeps the newer common backend/UI, reviewed goal loop and Mac application targeting, then adds the Windows-specific WPF/WebView2 host, compatibility audio, validated native bridge, menus, service ownership, screen frame and packaging. No API key, user history, logs, private environment, Codex account state or running session was copied.

See [dated verification](../../docs/verification-2026-11-03.md) for the distinction between narrow live Lenovo acceptance, cross-build checks and remaining runtime/distribution gates.
