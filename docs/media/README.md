# Ambi README media

Captured on **1 November 2026** from main commit **`70a7d1b`** (the repository's
current **test/demo frontend**, not a claim about another frontend or a shipped app).

| Asset | Source / what it proves |
| --- | --- |
| `ambi-overview.png` | Actual built UI and Rive asset, with fictional saved context supplied through a browser fixture. Camera off. |
| `ambi-suggestion.png` | Actual UI rendering a staged PairMatch offer, showing the accept/dismiss design. |
| `ambi-worker.png` | Actual UI rendering a staged running task and cancellation control. No task was executed. |
| `ambi-preview.gif` | Five staged UI states: standby, greeting, offer, work, completion. Not a live AI recording or measured response time. |
| `ambi-bench.png` | Screenshot of the actual local profile-lab landing page. No sensors or live AMBI sessions started. |

Every staged app frame includes **ILLUSTRATIVE SESSION · FICTIONAL DATA**.
Ellis text is synthetic documentation input inspired by the repository's demo.
No real inbox, personal saved memory, microphone, camera, screen capture of the
operator's desktop, provider request, or computer action was used for these assets.
The local Rive animation is the repository's existing character asset.

## Reproduce

Install UI dependencies and build (`npm ci --prefix ui; npm run build --prefix ui`).
Start an isolated app with `server.create_app(db_path=<temporary path>, seed=False)`
on loopback port 18765, with no API key, no autostart, and the exact
`AMBI_FRONTEND_ORIGINS=http://127.0.0.1:18765`. Start
`bench.server.create_app(output_dir=<temporary directory>, port=18766)` on loopback
18766. Do not reuse a personal session/database for capture.

```sh
node docs/media/capture.mjs
ffmpeg -framerate 5 -i docs/media/frames/%03d.png \
  -filter_complex '[0:v]scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=3' \
  -loop 0 docs/media/ambi-preview.gif
```

`AMBI_CAPTURE_URL` and `AMBI_LAB_URL` can select other isolated loopback ports.
The capture script reads the app's empty bootstrap state, supplies fictional
memory and session snapshots through Playwright routes, and never saves its
session token. It makes no session-start, camera, or computer-action requests.
The script captures 60 frames; playback at 5 fps gives a 12-second preview.
Raw frames are generated output and excluded from version control.

For real voice/camera/computer evidence, record an explicitly supervised session
following [the Ellis rehearsal](../../eval/test/README.md). Do not present these
fixtures as proof of provider or device behavior.
