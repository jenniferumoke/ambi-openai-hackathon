# AMBI-Bench

A local evaluation dashboard for the team's AMBI implementation. Run real decision logic against labelled synthetic observations, or prepare a fictional workspace and verify the artifact produced by the actual app.

## Start

From the repository root:

```sh
uv sync --locked --python 3.12
uv run python -m bench --serve
```

Open **http://127.0.0.1:8766**. No frontend build or new dependencies are needed. The dashboard does not start AMBI's camera, microphone or desktop worker. Keep AMBI on its own port, 8765, using the root README instructions.

1. In **Results**, select offline mode and AMBI implementation, then **Run evaluation**.
2. Watch real progress, suite bars, the decision matrix and the scenario grid.
3. Select **Failures & errors** and open a case to inspect its expected/observed values, rationale and inputs.
4. Run the always-quiet and always-intervene baselines. **Policy comparison** uses only the policy suite, matching dataset, source fingerprint and split. Never compare a 24-case baseline's aggregate score to all 50 product cases.
5. Export JSON for reproducible evidence. Reports, prepared folders and local paths stay under ignored `data/bench/`.

CLI equivalents:

```sh
uv run python -m bench
uv run python -m bench --adapter always_quiet
uv run python -m bench --adapter always_intervene
uv run python -m bench --split holdout
uv run pytest tests/test_bench.py -q
```

The CLI returns nonzero for failures/errors. A failing product scenario is useful benchmark evidence; the grader tests can pass while AMBI has a regression.

## Test the actual app with curated workspaces

In **Workspaces**, choose **Prepare workspace**, then **Open in VS Code**. **Copy task** provides the exact folder and task to give AMBI. Start the actual AMBI app with the team's configured credentials, give it that task, wait for it to save the output, then click **Verify saved result** in AMBI-Bench.

| Scenario | Source files | Required result | Verification |
| --- | --- | --- | --- |
| Pending bills | Three unpaid fictional bills; one paid bill | `outputs/payment-plan.json` | £153 unpaid, only BILL-103 overdue, due-date order, paid bill excluded, source hashes unchanged |
| Meeting notes | Current note plus superseded draft | `outputs/meeting-brief.md` | Current event facts, sections, decisions, owner/deadline pairs, unknown station count, source hashes unchanged |
| Coding session | Broken `two_sum`, task README | Repaired `exercise.py` | Eight executable vectors, duplicate/negative/empty inputs, distinct indices, no mutation, unchanged README |

Every preparation makes a fresh copy. All people, bills and addresses are fictional; no payment, sending or deletion is requested. Bills are dated relative to **1 November 2026**, not the day the test is rerun. The source dataset is committed in `bench/fixtures/`; prepared folders and results are ignored. VS Code is optional; any editor can open the generated folder.

This is an **operator-driven app test**: AMBI-Bench does not impersonate AMBI or silently run desktop actions. A passing artifact does not prove which agent created it, that no external side effects occurred, or that the entire voice/camera journey worked. Report who/what produced the artifact in your demo notes. The automated grader tests use reference answers and are not evidence of AMBI task success.

Document checks are deliberately bounded lexical checks, not a semantic judge. Follow TASK.md's date/time and action-line format. They can reject valid paraphrases or miss other unsupported prose. Code evaluation accepts only the small plain-function subset described in the exercise, runs in a separate process with a three-second timeout, and is not a general Python sandbox. Do not point it at arbitrary untrusted projects.

## Live model evaluation

The 62 authored scenarios contain **50 offline product cases** and **12 live classifier cases**. Live product mode invokes the existing `AmbientClassifier` via Decisions. Configure the team's `OPENAI_API_KEY` in the ignored local `.env` and restart the server. Do not paste keys into the dashboard or chat.

```sh
uv run python -m bench --mode live --split dev
```

Model: `DECISIONS_MODEL`, default `gpt-6-luna`, matching AMBI. Calls are sequential, have no automatic retries, and stop after three consecutive adapter errors. The UI disables live product runs when no key is available. Baselines do not call a model even in live mode. ChatGPT subscription login is not a drop-in credential for the team's Decisions/Realtime routes.

No live model or hardware success is implied by an offline run. A scripted scheduler classifier is labelled as such in its report.

## Curating and reviewing cases

`cases.json` contains stable IDs, suite/category, inputs, expected outputs, rationale, severity and a dev/holdout split. Another teammate should review the labels independently before demo claims. The holdout split is a development convention, not an independently hidden test set. The initial fixtures were authored while inspecting AMBI's implementation; do not claim broad population validity or a fair comparison between unrelated agents.

For each added scenario:

1. Define a user-visible requirement and a success/failure oracle first.
2. Use synthetic inputs or material with explicit reuse permission. Record its source and licence.
3. Include a normal/quiet case and a plausible failure case. For artifacts, test both a valid reference and a near-miss answer.
4. Run the grader tests, check a trivial baseline, and freeze the dataset version before comparing runs.

Errors never count as passes; unavailable denominators show as unavailable. Latencies are adapter wall times, with separate suite percentiles. Scheduler timings include the observation window and are not camera-to-speech measurements.

## Current finding and demo evidence

On initial base `f5f38bb`, offline evaluation completed **49/50** with one critical failure, **A11**: a worker-generation change during queued proactive delivery is not checked by the final `still_relevant` guard. The adapter simulates the transport wait and invokes the real guard. It does not play audio. Reproduce by running the suite and opening A11. The product source has intentionally not been modified by this eval change.

The other 49 cases passing does not establish live model quality or camera accuracy. Retest this finding after any team integration.

## Team sync

Work on `ambi-bench`. Fetch `origin` regularly. Merge `origin/main` only at a clean checkpoint with no benchmark running; do not stash teammates' work, force-push or merge unmerged feature branches automatically. `data/bench/running.lock` marks an active run. Restart the benchmark server after source changes: the UI detects changed imported code, and runs changed mid-execution are marked invalidated.

Reports identify commit, origin/main base, dirty-worktree state, source/dataset hashes, execution mode, model (if used), split and exact results. Only compare compatible reports. Historical reports from other dataset versions remain inspectable but are excluded from the policy comparison chart.

## 75-second evaluation demo

- **0–10s:** Explain: AMBI should help when useful and stay quiet otherwise.
- **10–25s:** Run offline evaluation; show live suite bars and A11's failure.
- **25–40s:** Show the quiet/intervene baseline comparison: silence alone is not success.
- **40–65s:** Show a previously prepared fictional workspace, AMBI's actual task completion, and artifact verification. Record this segment only after a real app run; do not present reference-answer tests as AMBI output.
- **65–75s:** Show reproducible JSON and source. Explain Codex's concrete contribution: it inspected the team's real scheduling code, authored a race scenario, and exposed the missing final generation check.

Before submission, record the actual workflow, keep the complete video under 90 seconds, exclude keys and personal windows, and open the public repository/video URLs in a signed-out browser. This local dashboard URL is not a public submission link.

## Credits and references

Benchmark code and fictional fixtures were authored during this hackathon with Codex. No benchmark-site code, fonts, datasets or visual assets were copied. The interface takes structural inspiration from [SWE-bench](https://www.swebench.com/) and [Terminal-Bench on Harbor Hub](https://hub.harborframework.com/datasets/terminal-bench/terminal-bench/latest?leaderboard=terminal-bench&tab=leaderboard): compact tables, comparable runs and inspectable task evidence. AMBI's pre-existing prototype and dependencies retain the credits in the root README and Git history.

See [architecture](../docs/ambi-bench-architecture.md), [OpenAI eval guidance](https://developers.openai.com/api/docs/guides/evaluation-best-practices), [Decisions](https://developers.openai.com/api/docs/guides/decisions), and the [Decisions Cookbook example](https://developers.openai.com/cookbook/examples/decisions/customer_request_routing).
