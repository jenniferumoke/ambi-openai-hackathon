const el = (tag, text, cls) => {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (cls) node.className = cls;
  return node;
};
const link = (label, url, cls = "secondary source-link") => {
  const node = el("a", label, cls);
  node.href = url;
  node.target = "_blank";
  node.rel = "noopener";
  return node;
};

export function createProfileUI({ api, action, notice }) {
  let sessions = [], app = {}, selectedId = null, scenarioId = null;
  let signature = "", catalogSignature = "";
  const button = (text, fn, cls = "secondary") => {
    const node = el("button", text, cls);
    node.type = "button";
    node.onclick = () => action(async () => {
      node.disabled = true;
      try { await fn(); } finally { node.disabled = false; }
    });
    return node;
  };
  const accept = (item) => {
    selectedId = item.id;
    sessions = [item, ...sessions.filter((s) => s.id !== item.id)];
    render();
  };
  function setCatalog(items) {
    const next = JSON.stringify(items);
    if (next === catalogSignature) return;
    catalogSignature = next;
    document.getElementById("profile-catalog").replaceChildren(...items.map((p) => {
      const card = button("", async () => {
        scenarioId = null;
        const existing = sessions.find((s) => s.profile.id === p.id && app.running && s.id === app.session_id)
          || sessions.find((s) => s.profile.id === p.id);
        accept(existing || await api("profile-prepare", { profile: p.id }));
      }, "profile-card");
      card.dataset.profile = p.id;
      card.setAttribute("aria-label", `Choose ${p.name}`);
      card.append(el("strong", p.name), el("span", p.role, "subtle"), el("span", p.summary, "profile-summary"));
      return card;
    }));
  }
  function update(items, appState) {
    sessions = items || [];
    app = appState || {};
    const next = JSON.stringify([sessions, app]);
    if (next === signature) return;
    signature = next;
    if (!selectedId && sessions.length)
      selectedId = sessions.find((s) => app.running && s.id === app.session_id)?.id || sessions[0].id;
    render();
  }
  function render() {
    const target = document.getElementById("profile-session");
    const item = sessions.find((s) => s.id === selectedId);
    for (const card of document.querySelectorAll(".profile-card")) {
      const selected = card.dataset.profile === item?.profile.id;
      card.classList.toggle("selected", selected);
      card.setAttribute("aria-pressed", String(selected));
    }
    if (!item) {
      target.replaceChildren(el("p", "Choose a person above to get started.", "empty"));
      return;
    }
    const profile = item.profile, firstName = profile.name.split(" ")[0];
    if (!profile.scenarios.some((s) => s.id === scenarioId)) scenarioId = profile.scenarios[0].id;
    const scenario = profile.scenarios.find((s) => s.id === scenarioId);
    const running = app.running && app.session_id === item.id;
    const example = el("section", null, "demo-step");
    example.append(el("h2", "1. Pick a situation"));
    const choices = el("div", null, "scenario-choices");
    choices.setAttribute("role", "group");
    choices.setAttribute("aria-label", "Example situation");
    profile.scenarios.forEach((s) => {
      const choice = button(s.title, () => { scenarioId = s.id; render(); });
      choice.setAttribute("aria-pressed", String(s.id === scenario.id));
      choices.append(choice);
    });
    example.append(choices);
    const sources = el("div", null, "profile-actions");
    sources.append(link("Open example", `/profile-view/${item.id}/${scenario.source.split("/").map(encodeURIComponent).join("/")}`));
    if (profile.packs.includes("code")) sources.append(button("Open in editor", () => api("profile-editor", { id: item.id })));
    example.append(sources);

    const launch = el("section", null, "demo-step");
    launch.append(el("h2", "2. Open AMBI"));
    launch.append(el("p", `AMBI gets ${firstName}’s demo memory. In AMBI, click Start session and let the greeting finish.`));
    const launchActions = el("div", null, "profile-actions");
    if (running) launchActions.append(link("Open AMBI", "http://127.0.0.1:8765", "primary source-link"));
    else launchActions.append(button(app.running ? `Switch AMBI to ${firstName}` : "Launch AMBI", async () => {
      if (app.running) await api("profile-stop");
      await api("profile-launch", { id: item.id });
      notice("AMBI is ready. Click Open AMBI below, then Start session.", false);
    }, "primary"));
    launch.append(launchActions);
    if (app.running && !running) launch.append(el("p", "Switching ends the current demo session.", "subtle"));

    const watch = el("section", null, "demo-step");
    watch.append(el("h2", "3. See what AMBI notices"));
    watch.append(el("p", "Return to the example window and wait about a minute without asking for help. Keep this page out of AMBI’s view."));
    const expectation = el("div", null, "demo-expectation");
    expectation.append(el("strong", scenario.expectation === "offer" ? "What to look for" : "This time, staying quiet is helpful"), el("p", scenario.suggestion));
    watch.append(expectation, el("p", "Watch the actual response in AMBI. A suggestion is an offer; you decide whether to act.", "subtle"));

    const context = el("details", null, "demo-details");
    context.append(el("summary", `About ${firstName} and the demo files`));
    context.append(el("p", profile.summary), el("h3", "The last two weeks"));
    const timeline = el("ol", null, "activity-timeline");
    profile.history.forEach(([date, event]) => {
      const row = el("li"); row.append(el("time", date.slice(5)), el("span", event)); timeline.append(row);
    });
    context.append(timeline);
    const memories = el("details", null, "demo-details");
    memories.append(el("summary", "What AMBI remembers"));
    profile.memory.forEach((m) => {
      const row = el("div", null, "memory-item");
      row.append(el("strong", m.title), el("p", m.body)); memories.append(row);
    });
    context.append(memories, link("Browse all demo files", `/profile-files/${item.id}/desktop.html`));
    const controls = el("div", null, "profile-actions");
    controls.append(button("Reset demo data", async () => {
      scenarioId = null;
      accept(await api("profile-prepare", { profile: profile.id }));
      notice("Fresh demo data is ready. Previous sessions remain saved locally.", false);
    }, "text-button"));
    if (running) controls.append(button("Stop demo AMBI", async () => {
      await api("profile-stop"); notice("Demo AMBI stopped.", false);
    }, "text-button"));
    context.append(controls);
    target.replaceChildren(example, launch, watch, context);
  }
  return { setCatalog, update };
}
