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
server's live camera state. All ten cue names are supported:

`neutral`, `smiling`, `frowning`, `furrowed_brow`, `tense_expression`, `confused_look`,
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

`neutral` is a stable visible pattern and must appear alone in `cues`; combining
it with another cue returns 400. Its 0–1 strength can appear in `scores` alongside
the other nine strengths. `cues:[]` means no stable classified cue, not confirmed
neutrality; older producers may continue sending it. Neither means the face is
unusable, which is represented separately by `usable:false`.

## Read live and stored cues

`GET /api/cues?limit=50` returns:

```json
{
  "schema_version": 2,
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
patterns do not initiate proactive offers. Neutral never initiates an offer in
either mode and clears earlier expression evidence when received.

Schema 2 adds the `neutral` cue and allows ten score keys, replacing the former
empty-list representation of a confirmed neutral expression. Update clients with
exhaustive cue enums. Existing journal events and older packets remain valid;
historical empty cue lists are not retroactively labeled neutral. The camera
fields in `/api/state` and `/ws` use the same extended enum.

## Diagnose cues without a reply

The browser detector runs independently of voice. Visible cue meters do not mean
that a voice session is connected. Bootstrap, `/api/state`, and `/ws` now include:

```ts
proactive: {
  status: 'paused' | 'waiting' | 'evaluating' | 'offered' | 'error';
  reason: string;
}
```

Reasons describe the current gate, not permission to act. Typical values are
`session_not_connected`, `focus_mode`, `response_in_progress`, `audio_playing`,
`computer_task_running`, `recent_user_activity`, `session_warmup`, `cooldown`,
`pending_suggestion`, `no_fresh_camera`, `no_matching_cue`, `no_relevant_context`,
`no_task_context`, `already_considered`, `already_offered`, `checking_context`,
`preparing_offer`, `voice_busy`, `decision_unavailable`, and `retry_backoff`.
Clients should tolerate additional reason strings. `already_offered` in Ellis
means that category has used its one offer for this session; ask directly or
start another session to rehearse the offer again. `concentrating_look` alone
does not trigger a demo offer. Focus and user/activity gates always take priority.

A held cue keeps its episode while fresh packets support it. After release,
unclassified frames may retain that episode for four seconds after its last
supporting frame; confirmed neutral, face loss, and camera-off clear it. A
two-second packet gap starts a new episode. Intervention-model failures retry
with bounded backoff. Busy voice sends retry the already computed decision while
context remains relevant; a failed/declined send does not consume the cooldown
or create a suggestion card. The normal 45-second cooldown remains unchanged.

The local camera samples advancing video frames on a timer at up to 15 fps;
frozen frames cannot count toward a stable cue. Browsers can still throttle
background tabs. Uploads time out after 1.2 seconds, discard stale data, and keep
the latest pending packet so a queued smile cannot replace a newer neutral face.

The screen observer samples the **primary display** every two seconds by default;
model latency can lengthen the interval. Identical newly captured pixels refresh
the existing observation without another model call, with periodic reanalysis at
the configured TTL. Changed pixels clear the previous screen context while the
replacement is analyzed. `observations.computer.reason` distinguishes
`screen_permission_missing`, `screen_observation_off`, `analysis_unavailable`,
`model_access_or_configuration`, and `screen_changed`. Screen Recording is needed
for observation; Accessibility is also needed for actions. Grant these to the
app launching Python, then quit/reopen it and restart the server.

If `status` is `error`, inspect the error text and `session_error` diagnostic
event. Realtime errors include an allowlisted `code`, `error_type`, and source
`location`, without exposing provider error bodies. Restarting the browser alone
does not reload changed Python code; restart the Terminal server after an update.
An interruption arriving after a reply finishes can emit `realtime_warning` with
code `response_cancel_not_active`. This is recoverable; the session stays connected
and accepts the next turn. Cancellation targets the original reply's response ID.
The additive `proactive` field does not change the cue journal schema version.

## Voice delivery from cues

In both modes, Python samples the latest usable camera packet when a reply is
actually sent, including replies queued behind another response. Delivery uses
only current stable cue names and ignores packets received two or more seconds
ago. The request and snapshot shapes remain unchanged.

| Current cue | Delivery for the next reply |
| --- | --- |
| `smiling` | Playful, fun, upbeat intonation at normal playback level. |
| `tired_look`, `sleepy_look` | Calm, soothing, slightly slower and quieter; local PCM amplitude is 78% of normal. |
| `frowning`, `furrowed_brow`, `tense_expression`, `confused_look`, `irritated_look` | Patient, steady, reassuring delivery with clear steps. |
| `neutral`, no stable cue, unavailable/stale camera, or other cues | Default warm conversational delivery at normal playback level. |

Tired cues take priority over supportive cues, then smiles. The selected delivery
is held for the reply; the next reply rechecks the camera. This does not generate
speech on its own or change action permissions. Explicit user tone preferences
and the seriousness of a request take precedence in the delivery prompt. The
model is told not to announce inferred emotions or the adaptation.

Implementation uses [Realtime per-response instructions](https://developers.openai.com/api/reference/resources/realtime/client-events#response.create)
and [voice prompting guidance](https://developers.openai.com/api/docs/guides/voice-prompting).
The configured voice identity and macOS system volume stay the same. Attenuation
is applied to this app's generated PCM before either playback backend, preserving
sample count and timing. Automated tests check selection, prompts, permissions,
and sample amplitude; live listening is needed to assess prosody and naturalness.

## Ellis sample context

Ellis loads fictional memory and files, using the normal structured intervention model.
No fixed responses or cue-to-action catalog are supplied.

## Local detector rules

`ui/src/cue-filter.js` maps the worker's MediaPipe blendshapes to the ten public
cues. These rules are application heuristics; MediaPipe produces facial movement
coefficients, not these look labels (see its [blendshape model card](https://storage.googleapis.com/mediapipe-assets/Model%20Card%20Blendshape%20V2.pdf)).
Scores remain 0–1 signal strengths, including while a pattern is waiting for its
hold time.

| Cue | Visible evidence and minimum hold |
| --- | --- |
| `neutral` | All tracked brow, eye, mouth/jaw, and nose movement coefficients ≤0.25 for 600 ms; three supporting frames and no other active cue. |
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
milliseconds rather than a fixed frame rate. Neutral requires complete, finite
scores for the tracked movements; its strength is one minus their maximum.
Gaze direction is excluded. Neutral clears as soon as movement exceeds its
threshold, without hysteresis, and never coexists with an active expression.
For the other cues, pending evidence tolerates dips
below entry strength for up to 150 ms, provided it stays at least 65% of the
entry threshold. Active cues use that lower threshold to avoid flicker; a
neutral frame clears them immediately. Face loss, multiple faces, an explicit
reset, or a frame gap over 500 ms clears all evidence. Old timestamps are ignored.

The automated tests replay synthetic blendshape sequences for yawns, speech-like
mouth movement, blinks, brow patterns, neutral transitions, missing model output, overlapping expressions, jitter, and
different frame rates. They verify rule behavior, not measured accuracy on
people. Sustained open-mouth speech can still resemble a yawn, and lighting,
pose, and individual facial movement can change the model's scores. Validate
with representative camera sessions before treating these thresholds as tuned
for a particular user; the labels do not establish tiredness or emotions.
