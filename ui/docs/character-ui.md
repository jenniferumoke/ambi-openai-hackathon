# Character-only Ambi

Only ui/ changes. main.js adds a presentation import and a render hook; existing session, voice, websocket, camera and state logic is preserved. Original DOM controls remain hidden. Camera stays off. Space toggles the existing start button.

The supplied ambi-v2.riv contained 18 individual artboards but no Ambi controller. With user approval, public/ambi.riv was rebuilt from the supplied v2 source with the earlier native controller adapted to its artboard IDs and 512-square dimensions. The wrapper is 340×240, with pose and play data binding. Original v2 artboards are retained.

Rebuild with the supplied source pack and official Rive CLI 1.8.0:

```sh
python3 ui/scripts/build-rive-controller.py /path/to/ambi-rive-2026-11-01 /path/to/rive
```

Rive verification/build: zero errors and warnings.

Verification on 2026-11-01:

- npm run build: passed.
- npm test: 6 passed.
- uv run pytest -q: 198 passed, 5 skipped.
- node ui/scripts/verify-character.mjs (server running): all eight poses, ready mapping, success expiry, Space start/stop, camera off, single visible button, mobile aspect/overflow, and reduced motion passed. Paused canvas frames were pixel-identical. No browser page errors.
- Browser lifecycle states and start/stop endpoints are mocked in the pose checks; these do not prove live voice or computer-task execution.
- Screenshots: artifacts/character/ (ignored by git).
- Live backend served the UI and reported API configured. Accessibility, Screen Recording, and microphone authorization were granted. The live session nevertheless reported a sanitized RuntimeError; voice operation remains unverified. Backend code was not changed.

Run from the repository root with `uv run python server.py --open`. The backend currently ignores --open; open http://127.0.0.1:8765 in Chrome separately.
