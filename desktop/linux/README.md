# Ambi Linux developer preview

This source preview reuses the current Python reviewed-goal backend and companion UI. It has not been launched on a Linux desktop. Mac-based policy/regression tests do not prove Linux voice, input, frame placement or window-manager behavior.

## First target

An existing non-root Ubuntu/Debian **X11** desktop, primary display only. Wayland and XWayland are refused; the preview does not change your login session or security policy. No `--no-sandbox`, display-server permission changes or elevation are used.

Electron 45.2.1 matches the original desktop prototype's pinned version. The renderer is sandboxed, has no Node integration, and has an exact companion-page native bridge. External navigation/popups are blocked. Browser chat handoff and folder picking are not implemented in this host yet; use the private default workspace.

The backend stays on `127.0.0.1:8767`. Startup refuses an occupied port instead of attaching to or terminating another service. Closing Ambi ends its owned session and child only. No task runs automatically at launch.

## Prepare on Linux

Prerequisites: Node 22+, uv, Python 3.11+, PortAudio, Tkinter, `scrot`, and `xclip` or `xsel`, plus normal Electron desktop libraries. Ubuntu/Debian packages include `libportaudio2`, `python3-tk`, `scrot`, and `xclip`. Have your Linux administrator provision missing system packages; this project does not install them or elevate itself. Use the distro Python if its Tkinter package is required.

From the repository root:

```sh
uv sync --frozen
uv run --frozen python linux_session.py
npm --prefix ui ci
npm --prefix ui run build
npm --prefix desktop/linux ci
npm --prefix desktop/linux start
```

Preflight reads prerequisites only; it neither captures the display nor calls an API. Passing is not a live-control test. Desktop operations recheck prerequisites and retain the corner fail-safe and per-task Stop generation.

Choose **Ambi → Configure voice for this launch…** or Connections → Set up voice. Enter the key directly in the masked dialog. The host retains it in memory and passes it only to its owned backend; it is never saved, printed, returned to the companion UI or inherited from an unrelated launch environment. The native-host flag prevents dotenv loading. Reconfiguration requires an observed idle backend and no running job.

Computer control starts off. Review Connections, enable it for this run, then explicitly start the conversation. Linux uses compatible PortAudio, muting capture during playback; spoken interruption and production wake-word behavior remain unverified. Background screen observation stays disabled on Linux; screenshots during explicitly requested computer tasks remain available.

The native teal frame and separate Stop task window follow a real running job and hide on completion/cancellation/lost backend connection. They cover the primary display only. This is implemented source awaiting a real Linux/window-manager test. Main UI Stop remains available.

## Linux acceptance required before release

1. Launch non-elevated. Verify key absent, mic idle, control off, private user-data storage, loopback-only listener.
2. Enter key privately; test speech input/output, then mute. Keep private pages/credentials out of recordings.
3. Request a harmless task confined to a new Ambi-owned text document; verify saved contents independently.
4. Observe frame and Stop during work. Click native Stop; verify no more actions and overlays disappear.
5. Test routine fallback and explicit checkpoint resume with fresh checks before action.
6. Check occupied-port refusal, lost prerequisites, backend failure, app close, missing audio and interrupted startup preserve unrelated processes and never silently replay work.
7. Test distro/compositor/DPI combinations. Wayland needs a separate portal-based design and explicit permission flow.

## Local checks

```sh
uv run --frozen pytest -q
npm --prefix ui test
npm --prefix ui run build
npm --prefix desktop/linux test
npm --prefix desktop/linux run check
```

3 November source results on Mac: **372 Python passed, 5 skipped; 72 UI passed/build passed; 5 Linux-host policy tests passed; JS syntax passed.** No Linux binary/installer is published and Linux runtime is unverified.

References: [Electron security checklist](https://www.electronjs.org/docs/latest/tutorial/security), [PyAutoGUI Linux prerequisites](https://pyautogui.readthedocs.io/en/latest/install.html).
