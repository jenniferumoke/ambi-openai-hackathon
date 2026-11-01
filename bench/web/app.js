const $ = (id) => document.getElementById(id);
const node = (tag, text, cls) => {
  const el = document.createElement(tag);
  if (text != null) el.textContent = text;
  if (cls) el.className = cls;
  return el;
};
const percent = (value) =>
  value == null ? "—" : `${(value * 100).toFixed(1)}%`;
const names = {
  policy: "Notification policy",
  cues: "Cue state",
  speech: "Speech gate",
  scheduler: "UI scheduler",
  classifier: "Live classifier",
};
let token,
  catalog,
  current = null,
  selected = null,
  state = {},
  viewRun = null,
  lastRender = "",
  socket;
function notice(message, error = true) {
  $("message").textContent = message;
  $("message").hidden = !message;
  $("message").className = error ? "warning" : "mode-note";
}
async function api(action, body = {}) {
  const response = await fetch(`/api/${action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Bench-Token": token },
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Request failed");
  return data;
}
async function action(fn) {
  try {
    notice("");
    await fn();
  } catch (err) {
    notice(err.message);
  }
}
function button(label, fn, cls = "secondary") {
  const el = node("button", label, cls);
  el.type = "button";
  el.onclick = () => action(fn);
  return el;
}
function modeNote() {
  const live = $("mode").value === "live",
    baseline = $("adapter").value !== "product";
  $("mode-note").textContent = baseline
    ? "Diagnostic baseline: fixed predictions, no model calls. Compare the same mode, split and dataset; offline baselines cover policy cases only."
    : live
      ? `Real Decisions calls on synthetic observations · ${catalog.model}. ${catalog.api_configured ? "API key configured; this run uses API credits." : "API key not configured. Offline checks are ready."}`
      : "Offline checks use the team's real logic with synthetic inputs. No cameras, microphones or desktop actions.";
  $("run-button").disabled = Boolean(
    state.run?.status === "running" ||
      state.restart_required ||
      (live && !baseline && !catalog.api_configured),
  );
}
function renderCases(run) {
  const results = new Map((run?.results || []).map((row) => [row.id, row]));
  const cases = catalog.cases.filter(
    (c) =>
      ($("suite-filter").value === "all" ||
        c.suite === $("suite-filter").value) &&
      ($("case-filter").value === "all" ||
        ($("case-filter").value === "critical"
          ? c.critical
          : ["fail", "error"].includes(results.get(c.id)?.status))),
  );
  $("case-grid").replaceChildren(
    ...cases.map((c) => {
      const r = results.get(c.id);
      const el = button(
        c.id,
        async () => {
          selected = c.id;
          renderCases(run);
        },
        `case-dot ${r?.status || "pending"}`,
      );
      el.title = `${c.id}: ${c.title} — ${r?.status || "not run"}`;
      el.setAttribute("aria-label", el.title);
      return el;
    }),
  );
  for (const el of $("case-grid").children)
    el.setAttribute("aria-pressed", String(el.textContent === selected));
  renderDetail(run);
}
function renderDetail(run) {
  const meta = catalog.cases.find((c) => c.id === selected);
  if (!meta) return;
  const r = run?.results.find((c) => c.id === selected),
    box = $("case-detail");
  const heading = node("div", null, "section-heading");
  heading.append(
    node("h3", `${meta.id} · ${meta.title}`),
    node("span", r?.status || "Not run", `tag ${r?.status || ""}`),
  );
  box.replaceChildren(
    heading,
    node("p", meta.rationale),
    node(
      "p",
      `${names[meta.suite]} · ${meta.split} · ${meta.critical ? "Critical" : "Standard"} case`,
      "subtle",
    ),
  );
  const compare = node("div", null, "decision-comparison");
  for (const [label, value] of [
    ["Expected", meta.expected.join(" → ")],
    ["Observed", r?.actual.join(" → ") || "Not evaluated"],
  ]) {
    const item = node("div");
    item.append(
      node("span", label),
      node(
        "code",
        value,
        label === "Observed" && r?.status === "fail" ? "incorrect" : "",
      ),
    );
    compare.append(item);
  }
  box.append(compare);
  const disclosure = node("details"),
    details = node("pre");
  disclosure.append(node("summary", "Input and execution details"));
  details.textContent = JSON.stringify(
    r
      ? { duration_ms: r.duration_ms, input: r.input, detail: r.detail }
      : { note: "Run this suite to inspect the executed inputs and result." },
    null,
    2,
  );
  disclosure.append(details);
  box.append(disclosure);
}
function renderRun(run) {
  const m = run?.metrics?.overall;
  current = run;
  $("run-status").textContent = run
    ? `${run.status === "running" ? "Running" : run.status} · ${run.execution.replaceAll("_", " ")}${run.active_case ? " · " + run.active_case : ""}`
    : "Ready for a first run";
  $("run-count").textContent = run
    ? `${run.completed} / ${run.total} cases`
    : "—";
  $("run-progress-fill").style.width = run
    ? `${(100 * run.completed) / run.total}%`
    : "0%";
  $("cancel-button").hidden = state.run?.status !== "running";
  $("download").disabled = !run;
  $("pass-value").textContent = percent(m?.pass_rate);
  $("pass-detail").textContent = m
    ? `${m.passed} passed · ${m.failed} failed · ${m.errors} errors`
    : "Run a suite to see evidence";
  $("interrupt-value").textContent = percent(m?.false_interruption_rate);
  $("interrupt-detail").textContent = m
    ? `${m.false_interruptions} unwanted / ${m.quiet_opportunities} quiet opportunities`
    : "Unwanted offers / quiet opportunities";
  $("miss-value").textContent = percent(m?.missed_help_rate);
  $("miss-detail").textContent = m
    ? `${m.missed_help} missed / ${m.help_opportunities} help opportunities`
    : "Missed / relevant opportunities";
  $("critical-value").textContent = m ? m.critical_failures : "—";
  $("critical-detail").textContent =
    run?.stop_reason || "Errors are never counted as passes";
  const bars = Object.entries(run?.metrics?.suites || {}).map(
    ([suite, metric]) => {
      const row = node("div", null, "suite-row"),
        heading = node("div", null, "suite-row-heading");
      heading.append(
        node("span", names[suite]),
        node("strong", `${metric.passed} / ${metric.total}`),
      );
      const track = node("div", null, "suite-track");
      for (const [count, cls] of [
        [metric.passed, "pass"],
        [metric.failed, "fail"],
        [metric.errors, "error"],
      ]) {
        const fill = node("div", null, `suite-fill ${cls}`);
        fill.style.width = `${(100 * count) / metric.total}%`;
        track.append(fill);
      }
      track.setAttribute("role", "img");
      track.setAttribute(
        "aria-label",
        `${metric.passed} passed, ${metric.failed} failed, ${metric.errors} errors`,
      );
      row.append(
        heading,
        track,
        node(
          "small",
          `${metric.failed} failed · ${metric.errors} errors · p95 ${metric.latency_p95_ms ?? "—"} ms`,
          "subtle",
        ),
      );
      return row;
    },
  );
  $("suite-bars").replaceChildren(
    ...(bars.length
      ? bars
      : [
          node(
            "p",
            "Policy, cues, speech and timing appear here as they run.",
            "empty",
          ),
        ]),
  );
  const labels = [
    ...new Set(
      (m?.confusion || []).flatMap((item) => [item.expected, item.actual]),
    ),
  ].sort();
  const table = node("table", null, "matrix"),
    thead = node("thead"),
    head = node("tr");
  head.append(node("th", "↓ / →"));
  const short = (value) =>
    ({ offer_task_help: "help", acknowledge_progress: "progress" })[value] ||
    value;
  labels.forEach((label) => head.append(node("th", short(label))));
  thead.append(head);
  table.append(thead);
  for (const expected of labels) {
    const row = node("tr");
    row.append(node("th", short(expected)));
    for (const actual of labels) {
      const count =
        m.confusion.find((c) => c.expected === expected && c.actual === actual)
          ?.count || 0;
      const cell = node(
        "td",
        count,
        count ? (expected === actual ? "hit" : "mismatch") : "zero",
      );
      cell.title = `Expected ${expected}, observed ${actual}: ${count}`;
      row.append(cell);
    }
    table.append(row);
  }
  $("confusion").replaceChildren(
    labels.length
      ? table
      : node("p", "Expected decisions versus observed decisions.", "empty"),
  );
  $("provenance").textContent = run
    ? `Commit ${run.commit.slice(0, 8)}${run.worktree_dirty ? " + local edits" : ""} · dataset ${run.dataset_hash.slice(0, 10)} · source ${run.source_hash.slice(0, 10)} · ${run.config.split} split`
    : "";
  $("footer-source").textContent = run
    ? `${run.branch} / ${run.commit.slice(0, 8)}`
    : "Local evaluation";
  renderCases(run);
  renderComparison(run);
}
function renderComparison(run) {
  const seen = new Set();
  const candidates = run
    ? [run, ...(state.history || [])].filter(
        (r) =>
          r.status === "completed" &&
          r.dataset_hash === run.dataset_hash &&
          r.source_hash === run.source_hash &&
          r.config.mode === run.config.mode &&
          r.config.split === run.config.split &&
          r.metrics.suites.policy,
      )
    : [];
  const rows = [];
  for (const r of candidates) {
    if (seen.has(r.config.adapter)) continue;
    seen.add(r.config.adapter);
    const m = r.metrics.suites.policy,
      row = node("div", null, "comparison-row");
    row.append(
      node(
        "strong",
        {
          product: "AMBI policy",
          always_quiet: "Always quiet",
          always_intervene: "Always intervene",
        }[r.config.adapter],
      ),
    );
    for (const [label, value] of [
      ["False interruptions", m.false_interruption_rate],
      ["Missed help", m.missed_help_rate],
    ]) {
      const group = node("div", null, "comparison-measure"),
        track = node("div", null, "suite-track"),
        bar = node("div", null, `suite-fill ${value ? "nonzero" : ""}`);
      bar.style.width = `${100 * (value || 0)}%`;
      track.append(bar);
      group.append(node("span", label), node("span", percent(value)), track);
      row.append(group);
    }
    rows.push(row);
  }
  $("comparison").replaceChildren(
    ...(rows.length
      ? rows
      : [
          node(
            "p",
            "Run AMBI and the two baselines on the same offline split to compare policy behavior.",
            "empty",
          ),
        ]),
  );
}
function renderHistory(rows) {
  $("history").replaceChildren(
    ...rows.map((r) => {
      const tr = node("tr"),
        cell = node("td");
      cell.append(
        button(
          new Date(r.started_at).toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
          }),
          async () => {
            const response = await fetch(`/api/report/${r.id}`, {
              headers: { "X-Bench-Token": token },
            });
            if (!response.ok) throw new Error("Could not load report");
            viewRun = await response.json();
            renderRun(viewRun);
          },
          "text-button",
        ),
      );
      const m = r.metrics.overall;
      tr.append(
        cell,
        node(
          "td",
          `${r.config.adapter} / ${r.config.mode} / ${r.config.split}`,
        ),
        node("td", `${m.passed}/${r.completed} of ${r.total}`),
        node("td", percent(m.false_interruption_rate)),
        node("td", percent(m.missed_help_rate)),
        node("td", r.status),
      );
      return tr;
    }),
  );
}
function renderCatalog(items) {
  $("workspace-catalog").replaceChildren(
    ...items.map((item, index) => {
      const card = node("article", null, "workspace-card");
      card.append(
        node("span", `0${index + 1} / ${item.surface}`, "eyebrow"),
        node("h2", item.title),
        node("p", item.description),
      );
      const checks = node("ul");
      item.checks.forEach((c) => checks.append(node("li", c)));
      card.append(
        checks,
        button(
          "Prepare workspace",
          async () => {
            const result = await api("prepare", { scenario: item.id });
            notice(
              `Prepared ${result.title}. Copy the task into AMBI and use the generated folder.`,
              false,
            );
            renderWorkspaces([result, ...(state.workspaces || [])]);
          },
          "primary",
        ),
      );
      return card;
    }),
  );
}
function renderWorkspaces(items) {
  $("workspaces").replaceChildren(
    ...(items.length
      ? items.map((item) => {
          const card = node("article", null, "workspace-instance"),
            head = node("div", null, "section-heading");
          head.append(
            node("h3", item.title),
            node(
              "span",
              item.status,
              `tag ${item.status === "failed" ? "fail" : item.status === "passed" ? "pass" : ""}`,
            ),
          );
          card.append(head, node("p", item.path, "workspace-path"));
          const task = node("details"),
            summary = node("summary", "Task to give AMBI");
          task.append(summary, node("pre", item.task));
          card.append(task);
          const controls = node("div", null, "workspace-actions");
          controls.append(
            button("Copy task", async () => {
              await navigator.clipboard.writeText(item.task);
              notice(
                "Task copied. Paste it into AMBI to run against these files.",
                false,
              );
            }),
            button("Open in VS Code", async () => {
              await api("open-workspace", { id: item.id });
              notice("Workspace opened in VS Code.", false);
            }),
            button(
              "Verify saved result",
              async () => {
                await api("verify", { id: item.id });
              },
              "primary",
            ),
          );
          card.append(controls);
          if (item.verification) {
            card.append(
              node(
                "p",
                `${item.verification.passed} / ${item.verification.total} checks passed`,
                "verification-summary",
              ),
            );
            const checks = node("ul", null, "verification-checks");
            item.verification.checks.forEach((c) =>
              checks.append(
                node(
                  "li",
                  `${c.passed ? "✓" : "×"} ${c.name}${c.detail ? " · " + c.detail : ""}`,
                  c.passed ? "check-pass" : "check-fail",
                ),
              ),
            );
            card.append(checks);
          }
          return card;
        })
      : [
          node(
            "p",
            "Prepare a fresh workspace above. Files stay local and contain no personal data.",
            "empty",
          ),
        ]),
  );
}
function update(next) {
  state = next;
  $("restart-warning").hidden = !state.restart_required;
  modeNote();
  const signature = JSON.stringify([
    next.revision,
    next.history,
    next.workspaces,
    next.restart_required,
  ]);
  if (signature === lastRender) return;
  lastRender = signature;
  renderRun(viewRun || next.run);
  renderHistory(next.history);
  const workspaceSignature = JSON.stringify(next.workspaces);
  if ($("workspaces").dataset.signature !== workspaceSignature) {
    renderWorkspaces(next.workspaces);
    $("workspaces").dataset.signature = workspaceSignature;
  }
}
function connect() {
  socket = new WebSocket(
    `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`,
    ["ambi-bench", token],
  );
  socket.onopen = () => {
    $("connection").textContent = "Live · connected";
    $("connection").className = "connection connected";
  };
  socket.onmessage = (e) => update(JSON.parse(e.data));
  socket.onclose = () => {
    $("connection").textContent = "Disconnected · retrying";
    $("connection").className = "connection";
    setTimeout(bootstrap, 2000);
  };
}
async function bootstrap() {
  try {
    const response = await fetch("/api/bootstrap");
    if (!response.ok) throw new Error("Dashboard unavailable");
    const data = await response.json();
    token = data.token;
    catalog = data.catalog;
    $("case-count").textContent = catalog.cases.length;
    $("dataset-version").textContent = `Fixture set ${catalog.version}`;
    renderCatalog(data.workspace_catalog);
    update(data);
    connect();
  } catch (err) {
    notice(err.message);
    setTimeout(bootstrap, 3000);
  }
}
for (const tab of document.querySelectorAll("[data-tab]"))
  tab.onclick = () => {
    for (const other of document.querySelectorAll("[data-tab]"))
      other.classList.toggle("selected", other === tab);
    for (const section of document.querySelectorAll(".view"))
      section.hidden = section.id !== `${tab.dataset.tab}-view`;
  };
$("run-form").onsubmit = (e) => {
  e.preventDefault();
  action(async () => {
    viewRun = null;
    await api("run", {
      mode: $("mode").value,
      adapter: $("adapter").value,
      split: $("split").value,
    });
  });
};
$("cancel-button").onclick = () => action(() => api("cancel"));
for (const id of ["mode", "adapter"]) $(id).onchange = modeNote;
for (const id of ["case-filter", "suite-filter"])
  $(id).onchange = () => renderCases(current);
$("download").onclick = () =>
  action(async () => {
    if (!current) return;
    const response = await fetch(`/api/report/${current.id}`, {
      headers: { "X-Bench-Token": token },
    });
    if (!response.ok) throw new Error("Could not export report");
    const url = URL.createObjectURL(await response.blob());
    const link = node("a");
    link.href = url;
    link.download = `ambi-bench-${current.id.slice(0, 8)}.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
bootstrap();
