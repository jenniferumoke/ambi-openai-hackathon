# AMBI-Bench: hackathon demo

Show AMBI's proactive behavior: **choose a person → open their example and AMBI**. The dashboard prepares realistic context. The actual AMBI app provides the live response; there is no assessment form or score to complete.

## Start locally

From the repository root:

```sh
uv sync --locked --python 3.12
(cd ui && npm ci && npm run build)
uv run python -m bench --serve
```

Open **http://127.0.0.1:8766**. The dashboard uses the existing Python dependencies and needs no separate frontend build. The `ui` build above is for the actual AMBI app that the lab launches.

## The core journey

1. Choose Rowan, Ellis or Nora. The card resumes their latest demo, or prepares separate memory and files on first use.
2. Click **Open example**. Each person has one default example: Rowan’s overdue invoice, Ellis’s failing test log, or Nora’s hotel email. Ellis also has **Open in editor**, using your installed `code` command (VS Code or Cursor).
3. Click **Launch AMBI**, then **Open AMBI**. If another demo is running, **Switch AMBI** ends it and launches the selected person's memory. An unrelated app on port 8765 is never replaced.
4. In AMBI, click **Start session** and let the greeting finish. Return to the example window, keep the demo instructions out of AMBI's view, and wait about a minute without asking for help.
5. Watch the actual response in AMBI. No situation picker, review form, grading, capture or export is required. Other source files remain available under the profile details.

History, memory, all files, reset and stop controls are tucked under **About … and the demo files**. Reset creates fresh data and retains previous sessions locally. Demo memory lives under ignored `data/bench/profiles/<session>/`; normal user memory is not replaced.

The dashboard starts the app server, not its sensors. Start the session and grant permissions in AMBI. Live behavior needs the team's `OPENAI_API_KEY` in the ignored `.env`. The current app does not use ChatGPT subscription login as its API credential.

## Included profiles

| Profile | Two-week context | Sources | Scenarios |
| --- | --- | --- | --- |
| Rowan Vale, community organizer | Paperwork backlog, volunteer tasks, completed hall payment | Four formatted invoice PDFs, one receipt, supplier emails, approved meeting record and withdrawn draft | Unattended invoice; planning brief; paid bill that should not trigger another payment reminder |
| Ellis Reed, developer | Paused debugging, agreed function contract, resolved setup issue | Real editor workspace, broken function, PM-17 issue, visible tests, captured failing session | Offer help with concrete failing tests; avoid interrupting ordinary reading |
| Nora Patel, trip planner | Budgets/preferences, unfinished arrangements, completed museum decision | Local email messages, itinerary, saved train comparison | Expiring hotel hold; unanswered dinner email; leave a resolved planning question alone |

All users, organizations, events, email domains, travel details, prices and transactions are fictional. The snapshot is **1 November 2026**. These are offline saved sources, not live inboxes or real travel offers. The app currently sees the open desktop and its stored memory; this lab does not add background Downloads watching or real email integration to AMBI.

Profiles contain identity/preferences, attributed memory, a dated activity timeline and scenario setup. Source copies retain plausible historical file-modification times, including the equipment invoice downloaded on 19 October. Each new preparation resets the demo data. Memory rows use the team's real `MemoryStore` schema.

## Showing the concept honestly

Only the live response in AMBI demonstrates behavior. A loaded profile or successful launch does not prove that AMBI noticed anything. Some examples deliberately call for staying quiet. Camera cues are optional hints, not proof of mood.

The underlying observation/review endpoints remain available for developer use and compatibility with saved sessions, but are not part of the demo interface. No automatic grading is performed.

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

A 75-second demo can show a profile's history (10s), open its invoice/email (15s), show an actual proactive AMBI suggestion (30s), then explain what AMBI noticed and the next step it offered (20s). Record the actual live result; never present a prepared expectation or reference answer as AMBI output. Keep this setup page out of the observed desktop. Use only the fictional profile windows in the recording. Publish the final video with public, signed-out access and a maximum duration of 90 seconds.

Profile manifests, source documents, code fixtures and the lab were authored during the hackathon with Codex. No real personal records or third-party document templates were used. Codex connected the team's existing memory and server interfaces without modifying product behavior, built reproducible profile sessions, and wrote isolation/capture checks. The team's imported prototype retains its existing history and credits.

The interface is a plain, compact profile lab. See [architecture](../docs/ambi-bench-architecture.md).
