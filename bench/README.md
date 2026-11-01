# AMBI-Bench: profile lab

A simple way to test AMBI's proactive behavior: **load a fictional user → open their sources → observe AMBI → record whether its suggestion was useful**. The primary result is a short human review of a real session, not a leaderboard score.

## Start locally

From the repository root:

```sh
uv sync --locked --python 3.12
(cd ui && npm ci && npm run build)
uv run python -m bench --serve
```

Open **http://127.0.0.1:8766**. The dashboard uses the existing Python dependencies and needs no separate frontend build. The `ui` build above is for the actual AMBI app that the lab launches.

## The core journey

1. Open Rowan, Ellis or Nora using their profile card. This resumes their latest test (or their running AMBI session); the first visit creates a source folder and memory database under ignored `data/bench/profiles/<session>/`. Use **Start a fresh test for this profile** below the results when you want to reset the test data. Previous results stay saved locally. Your normal AMBI database is not replaced.
2. Choose a scenario. Open its source or **Open demo workspace**. For Ellis, **Open coding session** opens the generated workspace, function and failing log through your installed `code` command (VS Code or Cursor).
3. Click **Launch AMBI with this memory**, then **Open AMBI**. The unmodified team app runs on port 8765 with the selected database and no default hackathon-memory seed. If another app already uses that port, the lab refuses to replace it.
4. In AMBI, start a session and wait for its greeting to finish. Back in the lab, click **Begin observation**, then show the scenario source and keep the reviewer instructions out of the observed screen. Do not ask AMBI for the expected answer. Observe for about 60 seconds.
5. Click **Capture AMBI response**, review the suggestion against the short expectation, and **Save review**. You can also enter a manual observation. Export the session JSON if needed.

The lab launches the app server; it does not silently enable the microphone, camera or screen observer. AMBI's own session controls and permissions remain in charge. Live sessions need the team's configured `OPENAI_API_KEY` in the ignored `.env`. ChatGPT subscription login is not a drop-in credential for the current Decisions/Realtime implementation. Use **Stop demo AMBI** before launching another profile.

## Included profiles

| Profile | Two-week context | Sources | Scenarios |
| --- | --- | --- | --- |
| Rowan Vale, community organizer | Paperwork backlog, volunteer tasks, completed hall payment | Four formatted invoice PDFs, one receipt, supplier emails, approved meeting record and withdrawn draft | Unattended invoice; planning brief; paid bill that should not trigger another payment reminder |
| Ellis Reed, developer | Paused debugging, agreed function contract, resolved setup issue | Real editor workspace, broken function, PM-17 issue, visible tests, captured failing session | Offer help with concrete failing tests; avoid interrupting ordinary reading |
| Nora Patel, trip planner | Budgets/preferences, unfinished arrangements, completed museum decision | Local email messages, itinerary, saved train comparison | Expiring hotel hold; unanswered dinner email; leave a resolved planning question alone |

All users, organizations, events, email domains, travel details, prices and transactions are fictional. The snapshot is **1 November 2026**. These are offline saved sources, not live inboxes or real travel offers. The app currently sees the open desktop and its stored memory; this lab does not add background Downloads watching or real email integration to AMBI.

Profiles contain identity/preferences, attributed memory, a dated activity timeline and scenario setup. Source copies retain plausible historical file-modification times, including the equipment invoice downloaded on 19 October. Each new preparation resets the demo data. Memory rows use the team's real `MemoryStore` schema.

## What counts as a result

Choose **Helpful suggestion**, **Wrong or unwanted suggestion**, **Correctly stayed quiet**, **Missed the opportunity**, or **Not tested yet**, and record what happened. These are operator assessments. There is no model judge, ranking, or automatic claim that the agent succeeded.

Captures include new assistant text, the current suggestion and recent suggestion events, focus state, whether camera data was present, and elapsed observation time. They exclude the greeting and raw user transcript. A new user turn is flagged so a prompted answer is not mistaken for proactive behavior. Captures read only a lab-launched process whose memory marker matches the selected profile. They do not record screenshots, microphone audio or camera images.

Capture while the observation is fresh: AMBI's in-memory transcript/event buffers are bounded. A single late capture is not a guaranteed full recording. The observation window is an operator guideline, not a claim about real-world response latency. Camera cues are optional hints, not ground truth about mood.

## Moving to the VNC desktop

Use the same repository, fixture files and profile manifests on the test machine. On that machine, the standalone entry point can prepare and load a fresh profile:

```sh
uv run python -m bench.profile_app --profile rowan
```

Or run the dashboard there and use the same buttons in the VNC desktop's browser. Connections stay on that machine's loopback addresses. **VNC transport and the team's AMBI compatibility with that host are not configured or validated yet.** The current local smoke test was on macOS. Do not assume a profile launcher changes AMBI's OS support or grants desktop permissions.

## Add or edit a profile

Edit a manifest under `bench/profiles/` or add a new JSON file using the same structure. Keep source packs under `bench/fixtures/`. Include a dated history and truthful completed-task memory, both helpful-offer and stay-quiet scenarios, the file to show, a short expected suggestion and a clear boundary. Keep names and details invented; use `.example` email domains. `packs` names must refer to local fixture folders.

AMBI's memory briefing has a length budget; keep important identity/preferences and active tasks concise. The expected answer belongs in the reviewer scenario, not in a fake assistant response. The saved sources should support the answer. Rebuild the PDFs after changing their Markdown sources or invoice data:

```sh
uv run --with reportlab==4.4.9 python bench/tools/build_documents.py
```

ReportLab is only an optional authoring dependency. Committed PDFs work without installing it. Render and visually review changed pages before committing them. `test_examples.py` inside the coding fixture is deliberately failing until AMBI or the operator fixes `exercise.py`; it is not part of the repository's passing test suite.

## Validation

```sh
uv run pytest tests/test_profile_lab.py -q
uv run pytest -q
```


The profile loader has been tested for independent memory stores, source access boundaries, file age, preview escaping, greeting exclusion, and refusal to capture a different AMBI session. A successful loader test is not a successful live AMBI behavior test.

## Demo and credit

A 75-second demo can show a profile's history (10s), open its invoice/email (15s), show an actual proactive AMBI suggestion (30s), then save the review and explain what was observed (20s). Record the actual live result; never present a prepared expectation or reference answer as AMBI output. Keep the reviewer page out of the observed desktop. Use only the fictional profile windows in the recording. Publish the final video with public, signed-out access and a maximum duration of 90 seconds.

Profile manifests, source documents, code fixtures and the lab were authored during the hackathon with Codex. No real personal records or third-party document templates were used. Codex connected the team's existing memory and server interfaces without modifying product behavior, built reproducible profile sessions, and wrote isolation/capture checks. The team's imported prototype retains its existing history and credits.

The interface is a plain, compact profile lab. See [architecture](../docs/ambi-bench-architecture.md).
