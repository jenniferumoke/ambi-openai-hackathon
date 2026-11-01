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
that a person feels or thinks a certain way. The five new look patterns do not
initiate proactive offers.
