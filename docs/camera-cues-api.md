# Camera cue backend contract

The test UI sends local MediaPipe cue results to the Python server. Another
frontend can use the same API; it does not need the test UI's JavaScript.
The camera cue endpoint receives cue names and numeric strengths, never image
frames. If screen context is enabled, its separate observer may capture a
visible camera preview as part of the screen.

## Connect from another frontend

The server listens at `http://127.0.0.1:8765`. It accepts its own origin and
`http://localhost:5173` by default. For another development origin, set an exact
origin in `.env` and restart the server:

```dotenv
AMBI_FRONTEND_ORIGINS=http://localhost:3000
```

Multiple origins can be comma-separated. Only configured origins receive CORS
headers or a bootstrap token. All endpoints except `/api/bootstrap` require the
`X-Ambi-Token` header. Fetch a new token after each server restart:

```js
const base = 'http://127.0.0.1:8765';
const { token } = await (await fetch(`${base}/api/bootstrap`)).json();
const response = await fetch(`${base}/api/cues?limit=20`, {
  headers: { 'X-Ambi-Token': token },
});
const { current, events } = await response.json();
```

## Write camera observations

`POST /api/camera` accepts one validated packet. `stream_id` should be a new ID
for each browser page load or camera stream; `sequence` must increase within that
stream. Run one active camera producer at a time; a new stream replaces the
server's live camera state. All nine cue names are supported:

`smiling`, `frowning`, `furrowed_brow`, `tense_expression`, `confused_look`,
`concentrating_look`, `irritated_look`, `tired_look`, `sleepy_look`.

```js
const streamId = crypto.randomUUID(); // Reuse for every packet from this stream.
await fetch(`${base}/api/camera`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', 'X-Ambi-Token': token },
  body: JSON.stringify({
    stream_id: streamId, sequence: 0, usable: true,
    cues: ['confused_look'], scores: { confused_look: 0.72 },
    age_ms: 40, inference_ms: 12, detection_ms: 335,
  }),
});
```

The response contains `accepted` (fresh packet), `stored` (new cue state in the
journal), and `event_id` (integer or `null`). Repeated frames with the same cue
set update the live state but do not add journal rows. An unusable frame must
have empty `cues` and `scores`. `POST /api/camera-off` clears the live state.

## Read live and stored cues

`GET /api/cues?limit=50` returns:

```json
{
  "schema_version": 1,
  "current": {
    "usable": true,
    "cues": ["confused_look"],
    "scores": { "confused_look": 0.72 },
    "inference_ms": 12,
    "detection_ms": 335,
    "age_ms": 81
  },
  "events": [{
    "id": 1,
    "stream_id": "example-stream-id",
    "sequence": 0,
    "observed_at": "2026-11-01T13:00:00+00:00",
    "received_at": "2026-11-01T13:00:00.040000+00:00",
    "usable": true,
    "cues": ["confused_look"],
    "scores": { "confused_look": 0.72 },
    "inference_ms": 12,
    "detection_ms": 335
  }]
}
```

`current` is `null` when the camera is off, the server restarted, or no packet
arrived in the last two seconds. Its `age_ms` is the time since the backend
received the latest packet, rounded to milliseconds; it is not the packet's
original frame age. `events` is newest first and survives a server
restart. `limit` must be 1–100. The same live `camera` field is also present in
`GET /api/state` and the `/ws` state stream (subprotocols `ambi`, then the token).

The journal is `data/ambi_cues.sqlite3`, separate from the user's saved memory.
It keeps at most 500 cue changes and deletes records older than 24 hours. It
stores no images or audio. Scores are visual signal strengths, not confidence
that a person feels or thinks a certain way. In normal mode, the five new look
patterns do not initiate proactive offers.

## Opt-in Ellis sample data

`./scripts/start.sh --demo ellis` loads fictional memory and an isolated PairMatch
workspace. It uses the same Decisions classifier, cue gates and cooldown as
normal sessions. There are no cue-to-offer rules or fixed responses.
`state.observations.mode` remains `ellis_demo` to identify the sample context;
HTTP/WS shapes and cue schema version are unchanged. See the
[demo guide](../eval/test/README.md).

## Local detector rules

`ui/src/cue-filter.js` maps the worker's MediaPipe blendshapes to the nine public
cues. These rules are application heuristics; MediaPipe produces facial movement
coefficients, not these look labels (see its [blendshape model card](https://storage.googleapis.com/mediapipe-assets/Model%20Card%20Blendshape%20V2.pdf)).
Scores remain 0–1 signal strengths, including while a pattern is waiting for its
hold time. The HTTP packet and history schema are unchanged.

| Cue | Visible evidence and minimum hold |
| --- | --- |
| `smiling` | Average mouth-corner lift ≥0.45; three supporting frames. |
| `frowning` | Average mouth-corner lowering ≥0.35; three supporting frames; suppressed by a smile or yawn-like posture. |
| `furrowed_brow` | Both brow-lowering scores ≥0.28; three supporting frames. One lowered brow alone is insufficient. Suppressed during a yawn-like posture. |
| `tense_expression` | Average lip-press score ≥0.45; three supporting frames; suppressed during a yawn-like posture. |
| `confused_look` | Brow asymmetry ≥0.25 with squint, lip press, or frown ≥0.25; alternatively, both brow lowering and inner-brow lift ≥0.25; 350 ms. |
| `concentrating_look` | Both brow lowering and squint ≥0.30; 500 ms. Confused/irritated patterns take precedence. Eye closure reduces support. |
| `irritated_look` | Both brow lowering and lip press or nose wrinkle ≥0.40; 300 ms. Eye closure reduces support. |
| `tired_look` | Jaw opening ≥0.55 and narrowing/closure in each eye ≥0.275 for 700 ms; alternatively, jaw opening ≥0.72 for 1200 ms, including with open eyes. |
| `sleepy_look` | Both eye-closure scores ≥0.70 for 700 ms; ordinary brief blinks do not qualify. |

Confused, concentrating, irritated, and sleepy patterns require a relatively
closed mouth (`jawOpen < 0.35`) and no strong smile. The yawn paths reject a
strong smile or average eye widening ≥0.45, reducing overlap with laughing and
wide-eyed mouth opening. Each yawn path has its own timer, so switching patterns
cannot inherit the shorter hold. Only `tired_look` is emitted for either path;
there is no extra public yawn cue. Once confirmed, a yawn continues while the
eyes reopen if the jaw stays open (≥0.55), retaining the initial detection time.

Every pattern requires at least three supporting frames. Timing uses elapsed
milliseconds rather than a fixed frame rate. Pending evidence tolerates dips
below entry strength for up to 150 ms, provided it stays at least 65% of the
entry threshold. Active cues use that lower threshold to avoid flicker; a
neutral frame clears them immediately. Face loss, multiple faces, an explicit
reset, or a frame gap over 500 ms clears all evidence. Old timestamps are ignored.

The automated tests replay synthetic blendshape sequences for yawns, speech-like
mouth movement, blinks, brow patterns, overlapping expressions, jitter, and
different frame rates. They verify rule behavior, not measured accuracy on
people. Sustained open-mouth speech can still resemble a yawn, and lighting,
pose, and individual facial movement can change the model's scores. Validate
with representative camera sessions before treating these thresholds as tuned
for a particular user; the labels do not establish tiredness or emotions.
