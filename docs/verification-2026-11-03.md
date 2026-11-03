# Companion integration evidence — 3 November 2026

Ambi is a local, voice-led desktop-agent prototype. This integration publishes source that was developed across the Mac and Windows worktrees. It does not release a newly notarized/signed installer or establish arbitrary-task reliability.

## Actual recorded tests

- Mac: the user confirmed audible replies and a spoken Chrome-open request; later recorded Calculator tasks displayed and independently verified their expected results. A separate screen-edge frame and Stop banner appeared during work and cleared afterward. The native permission setup required the user's OS review.
- Windows: the native WPF/WebView2 app on the Lenovo completed a harmless Notepad save in Ambi's own workspace. Exact text and the original earlier test file's hash were independently checked. One run briefly edited the earlier test tab, recovered and saved the new document; its recovery disclosure is retained in the narrated recording. The teal frame/Stop banner and a separate cancellation test were observed.
- Live tests apply to the recorded candidates. The newer shared goal-review loop was tested live on Mac; parity of that newer loop on a Windows-native build remains unverified. Offline tests and cross-compilation are separate evidence.
- Both narration-recording sessions ended idle with microphone and computer access off. API keys were entered only in masked native dialogs, retained in memory and never included in the source or media.

## Source and build checks

Fresh integration checks are recorded in the associated PRs. The shared candidate originally passed 372 Python tests (five live-dependent checks skipped), 72 UI tests and the UI production build. Native Swift and .NET checks establish build/policy behavior, not new permission grants or live OS input. Linux has an X11-only Electron source preview with policy tests; it has not been installed or run on Linux. Wayland and root sessions are refused.

## Remaining limits

Wake-word detection is not implemented. Browser connections are user-reviewed copy/open handoffs to ChatGPT, Claude and Gemini; there is no authenticated conversation import, reply reading or auto-send. Input targets the primary display. Lock/UAC, mixed DPI, secondary-display input and fresh-user installation need separate platform acceptance. Mac notarization, Windows signing and installer upgrade/uninstall acceptance remain open. Automatic updates are not implemented. The bounded goal controller can pause for permissions, uncertainty, repeated approaches or its configured budget; it is not AGI or an unbounded execution promise.

The earlier [product-readiness snapshot](product-readiness.md) and [companion finish checklist](companion-finish-checklist.md) preserve the historical gates and must be read with this dated follow-up.

## Windows integration checks

After adding the Windows-specific host and compatibility service without overwriting the shared runtime/UI, the combined source passed 377 Python tests with five live-dependent checks skipped. The portable .NET policy/lifecycle executable passed 27 checks, including the owned-service log restart regression. The win-x64 WPF host cross-published successfully. Backend bundle inspection confirmed both Ambi MIT and Codex licenses and no private environment, database, auth or log files. This build was not installed on the Lenovo and does not replace its existing tested candidate; bundled Python/Codex preparation and the installer were not newly runtime-tested. The shared UI, Swift and Linux sources retain the checks above.
