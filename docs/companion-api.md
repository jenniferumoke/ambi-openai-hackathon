# Companion API additions — 0.5.0

The bootstrap token, exact-origin checks, loopback-only service, 20 KB request
limit and WebSocket transport in `AGENTS.md` apply to every action here.
Successful responses include `ok: true`; validation failures return 400.

| POST /api/action | Body | Result / behavior |
| --- | --- | --- |
| codex-connect | `{}` | Starts only the owned Codex app-server; reads account/models. |
| codex-login | `{}` | `auth_url` or null; native host accepts only HTTPS auth.openai.com. |
| codex-model | `{model}` | Must be in the discovered model catalog; tasks must be idle. |
| codex-message | `{text,writable?,new_thread?,client_id?}` | 1–4000 characters; `job_id`; file writes default off; model execution is asynchronous. |
| codex-approval | `{id,decision}` | Current generation/thread/turn only; accept once, decline or cancel. |
| stop-task | `{client_id?}` | If supplied, stops only that client's current task. Prior changes remain. |
| workspace | `{path}` | Existing local directory; resets resumed Codex thread; requires idle task. |
| computer-access | `{enabled}` | Boolean true enables the opt-in for this process only; voice must be idle. OS access is still required. |
| request-screen-permission | `{}` | macOS system request, task/voice idle; user handles the OS prompt. |
| diagnostics | `{}` | Version/platform, permission/auth/status booleans and history counts; no keys/content. |
| history | `{before?}` | Up to 40 chronological `messages`, next `cursor`, `has_more`. Cursor is a positive integer. |

State adds `version`, `platform`, `workspace`, `workspace_notice`, `permissions`,
`computer_enabled`, `codex`, `history_saved`, `history_error`, `history_cursor`,
`history_has_more`. `transcript` contains the most recent 40 messages; the local
archive is not silently pruned. `activity` contains the recent 200 task/actions.
The restart checkpoint restores messages and marks running activity cancelled;
it never silently resumes a task or permission grant.

`codex` includes availability, authentication, connection status, discovered
models/selection, thread ID and transient pending approvals. Pending approvals
can include command/cwd, grant root, bounded path/diff previews and a network
host/protocol. They are not written into the conversation journal. UI must use
text rendering, never HTML interpretation, for all provider/file content.
`job` adds `engine` and `client_id`. A returned tool or turn is not proof of the
user's requested outcome. Stored timestamps from prior processes are reset;
monotonic times are not wall-clock dates.

History and task text can contain private user content. Storage is local SQLite,
not encrypted by Ambi; protection relies on the user's OS account and disk.
No automatic telemetry, sensor launch, release installation or update occurs.


### Computer reliability candidate — 2 November 2026

The Mac computer worker also exposes a narrow `open_application` function for Chrome, Safari, TV, TextEdit and Calculator. It uses NSWorkspace application URLs, no shell, arbitrary executable, document argument or URL. Native read-back returns running/frontmost and visible-window/primary-display booleans without window titles or contents. Existing screenshot/input remains primary-display only. Unknown applications use the existing screenshot workflow; this addition does not imply general multi-display input. The same serialized Desktop generation/Stop checks guard the native action. Windows keeps its existing computer tool.

`session_end_requested` diagnostic events identify `voice_exit_agent`, `voice_stop_when_idle` or `app_session_control`, without transcript or credentials. Provider failure summaries expose an exception type and caution that earlier actions may have happened; they omit raw error/request bodies and never replay a failed task automatically. Voice instructions distinguish a task completion boundary from an explicit request to end the voice session.

The driver-lab iteration adds explicit `bring_to_primary` to the supported Mac app-opening tool, default false. Only an explicit request to move that app authorizes true. It uses granted AX access to move only the app focused window; messaging is bounded and position is read back. It does not resize windows or provide secondary-monitor mouse input. The native host sets AMBI_NATIVE_HOST=1 so workspace-backed native launches skip dotenv and use the masked launch-key flow. The normal source CLI dotenv behavior remains unchanged.

After selecting a supported native app, Desktop guards subsequent screenshot/input operations using the frontmost bundle identity and focused-window primary-display position; it refuses before OS capture/input when the target changes. Native app tasks select the target before screenshots. New task generations clear that scope. Review setup exposes idle reconnect even when permissions are already ready.


## Reviewed computer goals

The desktop AppRuntime enables a bounded goal controller around the existing OpenAI computer worker. A work attempt is followed by a separate read-only review using fresh evidence. The reviewer has screenshot inspection, native app-state inspection on Mac, and exact saved-text comparison only when both the path and expected text are explicitly present in the goal and the resolved path stays inside the selected workspace. It has no input, launch, file-write or shell tools. Screenshots remain transient; checkpoints contain only goal, current step, concise observed progress, state and review count.

Incomplete routine work may continue through a different permitted UI approach, target refocus, another observation, or remaining steps. Unsupported/contradictory success claims cannot complete. Safety/permission boundaries, approval requirements, repeated approaches and budgets pause the goal; no blind replay after uncertain side effects. Stop cancels execution and review and checkpoints cancellation.

Private checkpoints use companion_goals in the existing private SQLite database. Restart converts running goals to paused; it never starts desktop work automatically. An explicit spoken/typed continuation may pass resume_goal_id to use_computer; fresh review precedes any resumed action, and the original goal/permissions remain unchanged. Paused or explicitly stopped goals can be resumed only on a fresh user request. Review IDs remain monotonic across continuation.

job snapshots add goal_id, goal_status and review_round. Activity entries show Checking progress, Progress checked and Next step selected. Reviewed completion uses checked status rather than treating an executor reply alone as success. The pinned status follows the current goal; legacy Codex replies retain their existing uncertainty label. Defaults: GOAL_REVIEW_ROUNDS=6 and GOAL_TIMEOUT_SECONDS=900, validated at at most 20 rounds and 3600 seconds per explicit run/resume. The older standalone ComputerWorker mode remains unchanged unless review=True; the desktop runtime explicitly enables it. These are bounded workflows, not AGI or a guarantee of arbitrary task completion.

## Linux source preview

On Linux, `permissions` reports `X11 session`, `Screenshot utility` and `Clipboard utility` booleans. These are prerequisites, not proof of successful desktop control. All must be true for the UI to offer per-run Enable; Desktop checks again per operation. Wayland/XWayland are unsupported. Linux uses compatible PortAudio and keeps background screen observation disabled. The explicit computer worker retains primary-display screenshots, Stop and reviewed-goal semantics. The new host uses the existing loopback 8767 routes; no route/schema change. See `desktop/linux/README.md` for limitations and live acceptance criteria.
