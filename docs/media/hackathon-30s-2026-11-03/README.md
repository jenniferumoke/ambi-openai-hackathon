# Meet Ambi — 30-second hackathon introduction

[Watch the video](ambi-hackathon-30s.mp4) · [Captions](captions.srt) · [Extended recorded walkthrough](../product-demo-2026-11-03/ambi-product-demo.mp4)

Ambi is an open-source AI agent originating at the London Codex Community hackathon on 1 November 2026. The event name/date were supplied by the project owner. The native desktop follow-up continued after the hackathon; this is a working prototype, not a claim that every current feature was demonstrated on the first day. Original project code is [MIT licensed](../../../LICENSE).

The film introduces voice, local memory and computer use on Mac/Windows, then shows visible Stop control and invites people to explore the repository. Its visuals crop real task excerpts from the existing public extended demo, with retimed Windows footage and held result frames. These were typed tests; they are edited examples, not a continuous new voice-to-action task. The extended video retains the Windows recovery disclosure. Linux runtime and arbitrary-task reliability are not claimed.

The narrator is OpenAI-generated speech from Ambi’s existing configured voice connection, with microphone, computer control and passive screen observation off. The generated response matched the requested script. No API key was retrieved, stored in this folder or included in the soundtrack. App state returned to idle afterward. Only the final narration WAV is included, not the raw system-playback capture.

Exactly 30.000 seconds; H.264 1920×1080 at 30 fps, AAC 48 kHz. Full decode, sound-level and caption-bound checks passed. `verification.json` contains the checksum and details. The separate SRT and phrase timing file support editing; the video has burned-in captions.

## Rebuild from the repository root

Install FFmpeg/ffprobe and the project’s locked Python environment. The renderer uses Pillow and locally available fonts, without a provider request or a running Ambi service. macOS Arial paths are the defaults; on other systems set `AMBI_DEMO_FONT` and `AMBI_DEMO_BOLD_FONT` to suitable local font files.

```sh
uv run python docs/media/hackathon-30s-2026-11-03/render.py \
  --source-demo docs/media/product-demo-2026-11-03/ambi-product-demo.mp4 \
  --illustration docs/media/hackathon-30s-2026-11-03/illustration.png \
  --narration docs/media/hackathon-30s-2026-11-03/narration.wav \
  --script docs/media/hackathon-30s-2026-11-03/narration.txt \
  --output /tmp/ambi-hackathon-demo-rebuild
```

For the checked phrase timings, copy `phrase-timings.json` into the output folder before rendering; without it the renderer estimates phrase timing. The script produces `Ambi-Hackathon-30s.mp4` and its SRT. No original app installation or private data is needed.
