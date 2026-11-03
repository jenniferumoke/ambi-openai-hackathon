# Ambi 0.5.0 product readiness — 2 November 2026

This records the six requested work areas. The local implementation is a usable
candidate; it is not yet a fully validated public release. At the time of this historical snapshot, these changes had not been pushed,
merged, deployed or published. See [current verification](verification-2026-11-03.md) for later integration and live-test evidence.

| Area | Implemented and verified | Remaining gate |
| --- | --- | --- |
| Codex | Owned app-server; discovered models; typed tasks; actual progress/replies; read-only default; explicit scoped command/file approvals; stop/reconnect. Real provider task passed from native Mac and latest frozen helper. | New-account sign-in, real write/approval and interrupt/recovery UX need final native acceptance. |
| Computer control | Explicit per-run opt-in; OS capability reporting; cancellation; Windows interactive-desktop check; primary-display driver. Colour-matched native glow covers connected displays. | User OS permission review; real Mac/Windows input, lock/UAC, multiple displays and mixed DPI. Input currently targets primary display only. |
| Guided setup | Accessible full-page connection screen; account/model/folder; permission explanation and controls; first prompt draft; diagnostics. Native Mac controls inspected. | Mac native setup/restart inspected after unlock; fresh-user and Windows setup checks remain. |
| History | Private SQLite message/task archive; older-message paging; restart checkpoint; no task/sensor autoresume. Archive, lifecycle and actual frozen-service restart passed. | User-facing deletion/export and retention preferences remain future product work. OS account/disk protection, no Ambi database encryption. |
| Workflow checks | Mac: 332 Python tests, 57 UI tests, 5 native tests; Windows: 337 Python tests, 56 UI tests, 24 native policy/lifecycle checks. Both UI/native builds pass. Five live-dependent Python checks skipped per suite. | Windows app launch/acceptance; Mac permissions; real voice and desktop acceptance. Mac native restart passed. |
| Distribution | Source-independent arm64 Mac package, Python/dependencies/Codex bundled, Developer ID signature verified. Windows x64 ZIP includes .NET/Python/locked dependencies/Codex with pinned provenance. Checksums. Per-user installer and signing hooks prepared. | Mac notarization profile; Windows installed signing certificate/compiler and actual install/upgrade/uninstall testing. Check for Updates is manual; automatic updater remains unimplemented. |

## Release evidence

`artifacts/release-candidate/release-status.json` records the latest Mac signature
and checksum; `smoke-checks.json` records the standalone real Codex/restart test.
The frozen helper was launched from `/tmp`, using temporary private storage and
its bundled Codex. A real reply completed, messages survived process restart,
and the next process had no running task, microphone, camera or computer access.
The native signed companion also completed a read-only fixture-file task before
the Mac locked. No live computer control was enabled or tested by that task.

Mac notarization is false. Windows signing and full Windows application acceptance
remain unverified. Bundled Python and Codex have executed on Windows; the
new app launch is blocked by an older preview listener. No installer has been compiled on this Mac. A build/test result does
not establish physical OS permission, input, audio or multi-monitor readiness.

## Next acceptance session

1. Unlock Mac; review the latest native setup and restored messages. Deliberately
   test startup cancellation, a scoped write approval and restart recovery with
   a disposable workspace.
2. The user reviews Accessibility/Screen Recording, then explicitly enables
   computer control for a harmless supervised task. Verify stop and frame cleanup.
3. On a Windows PC, test WebView2/voice/input, lock/UAC, display scaling, restart,
   install/upgrade/uninstall and signatures. Do not claim Mac audio behavior there.
4. Notarize Mac using an existing keychain profile; sign Windows using the
   installed certificate. Then perform fresh-user installation acceptance.
5. Implement and verify an automatic updater before claiming automatic updates.
   Until then the native menu opens the canonical GitHub releases page.

Source: Jennifer's canonical `jenniferumoke/ambi-openai-hackathon` codebase;
Mac worktree `codex/macos-companion`, Windows `codex/windows-companion`.

## Native follow-up — 2 November 2026

After the user unlocked the Mac, the latest signed candidate was launched through
the native UI. It started its bundled service, restored the earlier real task
and reply, and reconnected Codex using its existing sign-in. The backend confirmed
voice idle, computer control off and history saved. Native setup controls exposed
the selected model and read-only default. Accessibility/Screen Recording remain
unavailable and were not granted. Approval/write/interrupt and physical desktop
acceptance remain outstanding. The user requested continuing Windows installation
in the existing “Continue Ambi Windows app testing” chat; the exact 0.5.0 ZIP,
checksum and scoped acceptance instructions were sent there. Installation is not
yet claimed complete.


## Cross-chat coordination — 2 November 2026

The “Continue Ambi Windows app testing” chat reported that the new ZIP was
extracted into a separate Windows test folder, its SHA256 matched, bundled
Python 3.12.16 and Codex 0.149.0 ran, and the temporary transfer tunnel closed.
The older preview service occupies port 8767, so the new app has not completed
launch acceptance. That chat is awaiting the user's approval to back up its data,
close the old companion and stop only that preview service. The user's earlier
instruction forbade stopping existing processes; coordination does not override
it. Existing demos/services remain untouched.

Ownership: the Windows chat handles the scoped replacement and actual Windows
acceptance. This chat owns Mac acceptance and consolidated readiness. The
Windows agent was asked to maintain a dated acceptance checklist in its worktree's
copy of this document without changing shared source/packages.

Remaining: (1) resolve the Windows preview approval in that chat, then verify
new app launch, setup, Codex task, Stop and restart history; (2) user-reviewed
OS access and supervised voice/computer control on both platforms, including
lock/UAC, display/DPI and cleanup; (3) real write-approval/cancel/recovery UX;
(4) Mac notarization, Windows signing and installer/upgrade/uninstall acceptance;
(5) automatic updater implementation and validation. Per-platform verified
results must remain distinct from automated or cross-build checks.
