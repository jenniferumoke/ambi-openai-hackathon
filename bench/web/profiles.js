const el = (tag, text, cls) => {
  const n = document.createElement(tag);
  if (text != null) n.textContent = text;
  if (cls) n.className = cls;
  return n;
};
const link = (label, url) => {
  const a = el("a", label, "secondary source-link");
  a.href = url;
  a.target = "_blank";
  a.rel = "noopener";
  return a;
};
const verdicts = {
  helpful: "Helpful suggestion",
  unwanted: "Wrong or unwanted suggestion",
  quiet: "Correctly stayed quiet",
  missed: "Missed the opportunity",
  not_tested: "Not tested yet",
};

export function createProfileUI({ api, action, notice }) {
  let catalog = [],
    sessions = [],
    app = {},
    selectedId = null,
    scenarioId = null,
    signature = "",
    catalogSignature = "";
  const drafts = new Map();
  const button = (text, fn, cls = "secondary") => {
    const b = el("button", text, cls);
    b.type = "button";
    b.onclick = () => action(fn);
    return b;
  };
  const accept = (item) => {
    selectedId = item.id;
    sessions = [item, ...sessions.filter((s) => s.id !== item.id)];
    render();
  };
  function setCatalog(items) {
    catalog = items;
    const next = JSON.stringify(items);
    if (next === catalogSignature) return;
    catalogSignature = next;
    document.getElementById("profile-catalog").replaceChildren(
      ...items.map((p) => {
        const card = el("article", null, "profile-card");
        card.append(
          el("h2", p.name),
          el("span", p.role, "subtle"),
          el("p", p.summary),
        );
        const meta = el(
          "div",
          `${p.memory.length} memories · ${p.scenarios.length} scenarios · 2 weeks`,
          "profile-meta",
        );
        card.append(
          meta,
          button(
            "Load " + p.name.split(" ")[0] + "’s profile",
            async () => {
              scenarioId = null;
              accept(await api("profile-prepare", { profile: p.id }));
              notice(
                "Profile loaded into a fresh folder and isolated memory database.",
                false,
              );
            },
            "primary",
          ),
        );
        return card;
      }),
    );
  }
  function update(items, appState) {
    sessions = items || [];
    app = appState || {};
    const next = JSON.stringify([sessions, app]);
    if (next === signature) return;
    signature = next;
    if (!selectedId && sessions.length) selectedId = sessions[0].id;
    render();
  }
  function render() {
    const target = document.getElementById("profile-session");
    const item = sessions.find((s) => s.id === selectedId);
    if (!item) {
      target.replaceChildren(
        el(
          "p",
          "Load a profile to see its memory, sources and test scenarios.",
          "empty",
        ),
      );
      return;
    }
    const profile = item.profile;
    if (!profile.scenarios.some((s) => s.id === scenarioId))
      scenarioId = profile.scenarios[0].id;
    const scenario = profile.scenarios.find((s) => s.id === scenarioId),
      observation = item.observations[scenarioId],
      capture = observation?.captures.at(-1);
    const key = item.id + ":" + scenarioId,
      draft = drafts.get(key) || { verdict: "not_tested", notes: "" };
    const running = app.running && app.session_id === item.id;
    const head = el("div", null, "section-heading"),
      picker = el("select");
    picker.setAttribute("aria-label", "Prepared profile session");
    sessions.forEach((s) => {
      const opt = el(
        "option",
        `${s.profile.name} · ${new Date(s.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`,
      );
      opt.value = s.id;
      opt.selected = s.id === item.id;
      picker.append(opt);
    });
    picker.onchange = () => {
      selectedId = picker.value;
      scenarioId = null;
      render();
    };
    head.append(el("h2", `${profile.name} / ${profile.role}`), picker);
    const steps = el("div", null, "profile-steps");
    for (const [i, label, done] of [
      [1, "Memory loaded", true],
      [2, "Sources ready", true],
      [3, "Observation", Boolean(observation)],
      [4, "Review suggestion", item.reviews.length > 0],
    ]) {
      const step = el("span", `${i}. ${label}`, done ? "done" : "");
      steps.append(step);
    }
    const actions = el("div", null, "profile-actions");
    actions.append(
      link("Open demo workspace", `/profile-files/${item.id}/desktop.html`),
    );
    if (profile.packs.includes("code"))
      actions.append(
        button("Open coding session", () =>
          api("profile-editor", { id: item.id }),
        ),
      );
    if (running) {
      actions.append(
        link("Open AMBI", "http://127.0.0.1:8765"),
        button("Stop demo AMBI", async () => {
          await api("profile-stop");
          notice(
            "Demo AMBI stopped. The profile folder and results are retained.",
            false,
          );
        }),
      );
    } else if (app.running) {
      actions.append(
        button("Stop current demo to switch profiles", async () => {
          await api("profile-stop");
          notice(
            "Previous demo stopped. You can now launch this profile.",
            false,
          );
        }),
      );
    } else
      actions.append(
        button(
          "Launch AMBI with this memory",
          async () => {
            await api("profile-launch", { id: item.id });
            notice(
              "Demo AMBI is ready on port 8765. Open it and start the session when ready.",
              false,
            );
          },
          "primary",
        ),
      );
    const setup = el(
      "p",
      "1. Open a source or coding session. 2. Launch AMBI with this memory and start its session. 3. Let the greeting finish, then begin observation. Keep this reviewer page out of the observed desktop.",
      "profile-instructions",
    );
    const grid = el("div", null, "profile-layout"),
      context = el("section", null, "profile-context"),
      test = el("section", null, "profile-test");
    context.append(el("h3", "Recent activity"));
    const timeline = el("ol", null, "activity-timeline");
    profile.history.forEach(([date, event]) => {
      const li = el("li");
      li.append(el("time", date.slice(5)), el("span", event));
      timeline.append(li);
    });
    context.append(timeline);
    const memories = el("details"),
      summary = el("summary", `Loaded memory (${profile.memory.length} items)`);
    memories.append(summary);
    profile.memory.forEach((m) => {
      const row = el("div", null, "memory-item");
      row.append(
        el("strong", m.title),
        el("small", `${m.kind} · ${m.status} · ${m.at.slice(0, 10)}`),
        el("p", m.body),
      );
      memories.append(row);
    });
    context.append(memories);
    const sourceDetails = el("details");
    sourceDetails.append(
      el("summary", `Source files (${Object.keys(item.sources).length - 1})`),
    );
    const sources = el("ul", null, "source-files");
    Object.keys(item.sources)
      .filter((p) => p !== "desktop.html")
      .forEach((path) => {
        const li = el("li"),
          a = link(
            path,
            `/profile-view/${item.id}/${path.split("/").map(encodeURIComponent).join("/")}`,
          );
        a.className = "";
        li.append(a);
        sources.append(li);
      });
    sourceDetails.append(sources);
    context.append(sourceDetails);
    const choose = el("label", "Scenario", "scenario-label"),
      select = el("select");
    select.setAttribute("aria-label", "Profile scenario");
    profile.scenarios.forEach((s) => {
      const option = el("option", s.title);
      option.value = s.id;
      option.selected = s.id === scenario.id;
      select.append(option);
    });
    select.onchange = () => {
      scenarioId = select.value;
      render();
    };
    choose.append(select);
    test.append(choose);
    test.append(
      el("p", scenario.setup, "scenario-setup"),
      link(
        "Open scenario source",
        `/profile-view/${item.id}/${scenario.source.split("/").map(encodeURIComponent).join("/")}`,
      ),
    );
    const expect = el("div", null, "scenario-expectation");
    expect.append(
      el(
        "strong",
        scenario.expectation === "offer"
          ? "Expected: a relevant offer"
          : "Expected: stay quiet",
      ),
      el("p", scenario.suggestion),
      el("p", scenario.boundary, "subtle"),
    );
    test.append(expect);
    const watch = el("div", null, "profile-actions");
    const begin = button(
      observation ? "Restart observation" : "Begin observation",
      async () =>
        accept(
          await api("profile-observe", { id: item.id, scenario: scenario.id }),
        ),
    );
    begin.disabled = !running;
    const collect = button("Capture AMBI response", async () =>
      accept(
        await api("profile-capture", { id: item.id, scenario: scenario.id }),
      ),
    );
    collect.disabled = !running || !observation;
    watch.append(begin, collect);
    test.append(watch);
    test.append(
      el(
        "p",
        `Observe for about ${scenario.observe_seconds} seconds without prompting for the answer. Camera cues are optional and do not establish a person’s mood.`,
        "subtle",
      ),
    );
    const evidence = el("div", null, "profile-evidence");
    if (capture) {
      evidence.append(
        el("strong", `Captured after ${capture.elapsed_seconds}s`),
      );
      if (capture.user_prompted)
        evidence.append(
          el(
            "p",
            "A user turn occurred during this observation. Review whether the response was actually proactive.",
            "warning",
          ),
        );
      const texts = [
        ...(capture.suggestion ? [capture.suggestion.text] : []),
        ...(capture.suggestion_events || []),
        ...capture.assistant_text,
      ];
      evidence.append(
        el(
          "p",
          [...new Set(texts)].join("\n\n") ||
            "No new suggestion or assistant speech captured.",
        ),
      );
    } else
      evidence.append(
        el(
          "p",
          observation
            ? "Observation started. Keep the scenario source visible, then capture the response."
            : "No observation recorded. You can also record a manual review below.",
          "subtle",
        ),
      );
    test.append(evidence);
    const form = el("form", null, "profile-review"),
      verdictLabel = el("label", "Your assessment"),
      verdictSelect = el("select");
    verdictSelect.setAttribute("aria-label", "Assessment");
    Object.entries(verdicts).forEach(([value, label]) => {
      const option = el("option", label);
      option.value = value;
      option.selected = value === draft.verdict;
      verdictSelect.append(option);
    });
    verdictLabel.append(verdictSelect);
    const notesLabel = el("label", "What did AMBI say or do?"),
      notes = el("textarea");
    notes.rows = 3;
    notes.maxLength = 3000;
    notes.placeholder =
      "Record the observed suggestion, or explain why it was missed or unwanted.";
    notes.value = draft.notes;
    notesLabel.append(notes);
    const remember = () =>
      drafts.set(key, { verdict: verdictSelect.value, notes: notes.value });
    verdictSelect.onchange = remember;
    notes.oninput = remember;
    const save = el("button", "Save review", "primary");
    save.type = "submit";
    form.append(verdictLabel, notesLabel, save);
    form.onsubmit = (e) => {
      e.preventDefault();
      action(async () => {
        accept(
          await api("profile-review", {
            id: item.id,
            scenario: scenario.id,
            verdict: verdictSelect.value,
            notes: notes.value,
          }),
        );
        notice(
          "Review saved locally. This is an operator assessment, not an automated grade.",
          false,
        );
      });
    };
    test.append(form);
    grid.append(context, test);
    const reviews = el("section", null, "profile-results");
    const reviewHead = el("div", null, "section-heading");
    reviewHead.append(
      el("h3", "Session results"),
      button(
        "Export session",
        async () => {
          const blob = new Blob([JSON.stringify(item, null, 2)], {
              type: "application/json",
            }),
            url = URL.createObjectURL(blob),
            a = el("a");
          a.href = url;
          a.download = `ambi-profile-${profile.id}-${item.id.slice(0, 8)}.json`;
          a.click();
          setTimeout(() => URL.revokeObjectURL(url), 1000);
        },
        "text-button",
      ),
    );
    reviews.append(reviewHead);
    if (!item.reviews.length)
      reviews.append(
        el(
          "p",
          "No results yet. Load a scenario, observe AMBI, then save your assessment.",
          "empty",
        ),
      );
    else {
      const table = el("table"),
        header = el("tr");
      ["Scenario", "Assessment", "Notes"].forEach((label) =>
        header.append(el("th", label)),
      );
      table.append(header);
      item.reviews
        .slice()
        .reverse()
        .forEach((r) => {
          const row = el("tr");
          row.append(
            el(
              "td",
              profile.scenarios.find((s) => s.id === r.scenario_id)?.title ||
                r.scenario_id,
            ),
            el("td", verdicts[r.verdict]),
            el("td", r.notes || "—"),
          );
          table.append(row);
        });
      reviews.append(table);
    }
    target.replaceChildren(
      head,
      steps,
      actions,
      setup,
      grid,
      reviews,
      el(
        "p",
        `Fictional snapshot ${profile.snapshot.slice(0, 10)} · fixture ${profile.version} · isolated session ${item.id.slice(0, 8)} · local sources and memory only`,
        "provenance",
      ),
    );
  }
  return { setCatalog, update };
}
