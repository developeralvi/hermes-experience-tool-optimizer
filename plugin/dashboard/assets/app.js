/* EBTTO dashboard frontend. All DOM insertion via textContent (no innerHTML
 * with server data) so task text / tool names / error messages cannot inject
 * markup. No external resources. */
"use strict";

const state = {
  page: "overview",
  window: "24h",
  timer: null,
  lastOk: null,
  detail: null,      // {type,id} for detail views
  pages: {},         // per-endpoint current page
};

const $ = (sel) => document.querySelector(sel);
const view = $("#view");

function esc(s) {
  return String(s == null ? "" : s);
}
function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d) ? String(iso) : d.toLocaleString();
}
function fmtDur(ms) {
  if (ms == null) return "—";
  return ms < 1000 ? ms + " ms" : (ms / 1000).toFixed(1) + " s";
}
function pct(x) {
  return x == null ? "—" : (x * 100).toFixed(1) + "%";
}
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}
function badge(ok, label) {
  const b = el("span", "badge " + (ok ? "b-ok" : "b-fail"), label);
  return b;
}
function conn(state_) {
  const dot = $("#conn");
  dot.className = "dot " + (state_ === "down" ? "down" : state_ === "stale" ? "stale" : "");
  dot.title = state_;
}

async function api(path, params) {
  const qs = new URLSearchParams(params || {});
  const r = await fetch("/api/" + path + (qs.toString() ? "?" + qs : ""));
  if (!r.ok && r.status !== 503) throw new Error("HTTP " + r.status);
  const j = await r.json();
  if (j.error) { const e = new Error(j.error); e.payload = j; throw e; }
  return j;
}

function showError(msg) {
  view.textContent = "";
  view.append(el("div", "err", "Error: " + msg));
}

function emptyState(msg) {
  return el("div", "empty", msg);
}

/* ---------------- page renderers ---------------- */

async function renderOverview() {
  const d = await api("overview", { window: state.window });
  view.textContent = "";

  const cards = el("div", "cards");
  const add = (label, value, sub) => {
    const c = el("div", "card");
    c.append(el("div", "label", label), el("div", "value", value));
    if (sub) c.append(el("div", "sub", sub));
    cards.append(c);
  };
  const tc = d.tool_calls;
  add("Tool calls", tc.total, "window: " + d.window);
  add("Success rate", pct(d.success_rate),
      tc.total ? `${tc.succeeded} ok / ${tc.failed} failed` : "no data in window");
  add("Tasks", d.tasks_total, "all time");
  add("Patterns", d.patterns, "");
  add("Strategies", d.strategies.total,
      `${d.strategies.qualified} qualified`);
  if (d.guidance.available) {
    add("Guidance delivered", d.guidance.delivered,
        `${d.guidance.total} retrieval events (all time)`);
  } else {
    add("Guidance", "n/a", "schema v4 telemetry not present in this DB");
  }
  add("DB integrity", d.db_integrity, "");
  view.append(cards);

  if (!tc.total) {
    view.append(emptyState("No tool calls in this window. Widen the time filter, or confirm the plugin is recording."));
  }

  // success/failure trend (14d)
  if (d.failure_trend_14d && d.failure_trend_14d.length) {
    const h = el("h3", null, "Success / failure — last 14 days");
    const t = el("table");
    t.append(el("thead"));
    const thead = el("thead");
    const trh = el("tr");
    ["day", "ok", "fail"].forEach((x) => trh.append(el("th", null, x)));
    thead.append(trh); t.append(thead);
    const tb = el("tbody");
    for (const r of d.failure_trend_14d) {
      const tr = el("tr");
      tr.append(el("td", null, r.day), el("td", null, String(r.ok)),
                el("td", null, String(r.fail)));
      tb.append(tr);
    }
    t.append(tb);
    view.append(h, t);
  }

  // top tools
  if (d.top_tools && d.top_tools.length) {
    const h = el("h3", null, "Most used tools (window)");
    const t = el("table");
    const thead = el("thead"); const trh = el("tr");
    ["tool", "calls", "ok", "fail", "failure rate"].forEach((x) => trh.append(el("th", null, x)));
    thead.append(trh); t.append(thead);
    const tb = el("tbody");
    for (const r of d.top_tools) {
      const tr = el("tr");
      const link = el("a", null, r.tool_name);
      link.href = "#";
      link.onclick = (e) => { e.preventDefault(); state.page = "tools"; state.detail = null;
        sessionStorage.setItem("tool_filter", r.tool_name); render(); };
      tr.append(el("td").appendChild(link).parentNode, el("td", null, String(r.calls)),
                el("td", null, String(r.ok)), el("td", null, String(r.fail)),
                el("td", null, r.calls ? ((r.fail / r.calls) * 100).toFixed(1) + "%" : "—"));
      tb.append(tr);
    }
    t.append(tb);
    view.append(h, t);
  }
}

function pager(container, info, fetchFn) {
  const p = el("div", "pager");
  const prev = el("button", null, "← prev"); prev.disabled = info.page <= 1;
  prev.onclick = () => { info.page--; fetchFn(); };
  const next = el("button", null, "next →"); next.disabled = info.page >= info.pages;
  next.onclick = () => { info.page++; fetchFn(); };
  const label = el("span", null,
      `page ${info.page} / ${info.pages || 1} — ${info.total} rows`);
  p.append(prev, label, next);
  container.append(p);
}

async function renderToolCalls() {
  const params = { window: state.window, page: state.pages.tools || 1 };
  if (state.statusFilter) params.status = state.statusFilter;
  const tf = sessionStorage.getItem("tool_filter");
  if (tf && !params.tool) params.tool = tf;
  if (state.search) params.q = state.search;
  const d = await api("tool_calls", params);
  view.textContent = "";
  sessionStorage.removeItem("tool_filter");

  const f = el("div", "filters");
  const winSel = windowSelect();
  const stSel = el("select");
  [["", "all"], ["success", "success"], ["failure", "failure"]].forEach(([v, l]) => {
    const o = el("option", null, l); o.value = v; stSel.append(o);
  });
  stSel.value = state.statusFilter || "";
  stSel.onchange = () => { state.statusFilter = stSel.value; state.pages.tools = 1; renderToolCalls(); };
  const search = el("input"); search.type = "search"; search.placeholder = "search tool/args/error";
  search.value = state.search || "";
  const go = el("button", "act", "Search");
  go.onclick = () => { state.search = search.value; state.pages.tools = 1; renderToolCalls(); };
  search.onkeydown = (e) => { if (e.key === "Enter") go.onclick(); };
  f.append(el("span", null, "window:"), winSel, el("span", null, "status:"), stSel, search, go);
  view.append(f);

  if (!d.rows.length) { view.append(emptyState("No tool calls match these filters.")); return; }
  const t = el("table");
  const thead = el("thead"); const trh = el("tr");
  ["time", "tool", "status", "duration", "attempt", "class", "task"].forEach((x) => trh.append(el("th", null, x)));
  thead.append(trh); t.append(thead);
  const tb = el("tbody");
  for (const r of d.rows) {
    const tr = el("tr");
    const tdTool = el("td");
    const link = el("a", null, r.tool_name); link.href = "#";
    link.onclick = (e) => { e.preventDefault(); state.detail = { type: "tool", id: r.tool_call_id }; renderDetail(); };
    tdTool.append(link);
    const okSt = ["ok", "success"].includes(r.result_status);
    tr.append(el("td", null, fmtTime(r.created_at)), tdTool,
      el("td").appendChild(badge(okSt, r.result_status || "?")).parentNode,
      el("td", null, fmtDur(r.duration_ms)), el("td", null, String(r.attempt_number ?? "—")),
      el("td", null, r.classified_class || r.error_class || "—"),
      el("td", null, r.task_id || "—"));
    tb.append(tr);
  }
  t.append(tb);
  view.append(t);
  pager(view, d, () => renderToolCalls());
}

function windowSelect() {
  const sel = el("select");
  [["1h", "last hour"], ["24h", "last 24h"], ["7d", "7 days"],
   ["30d", "30 days"], ["all", "all time"]].forEach(([v, l]) => {
    const o = el("option", null, l); o.value = v; sel.append(o);
  });
  sel.value = state.window;
  sel.onchange = () => { state.window = sel.value; state.pages = {}; render(); };
  return sel;
}

async function renderDetail() {
  const { type, id } = state.detail;
  view.textContent = "";
  const back = el("button", "act", "← back");
  back.onclick = () => { state.detail = null; render(); };
  view.append(back);
  try {
    if (type === "tool") {
      const d = await api("tool_call", { id });
      const h = el("h2", null, `Tool call — ${d.tool_name}`);
      view.append(h);
      const cards = el("div", "cards");
      const meta = [["task", d.task_id], ["status", d.result_status],
        ["duration", fmtDur(d.duration_ms)], ["attempt", String(d.attempt_number ?? "—")],
        ["error class", d.error_class || "—"], ["classified", d.classified_class || "—"],
        ["time", fmtTime(d.created_at)]];
      for (const [k, v] of meta) {
        const c = el("div", "card");
        c.append(el("div", "label", k), el("div", "value", esc(v)));
        cards.append(c);
      }
      view.append(cards);
      const det = el("details");
      const sum = el("summary", null, "sanitized arguments");
      det.append(sum, el("pre", null, JSON.stringify(d.sanitized_args || d.raw_args, null, 2)));
      view.append(det);
      if (d.error_message) {
        const de = el("details"); de.append(el("summary", null, "error message (sanitized)"), el("pre", null, esc(d.error_message)));
        view.append(de);
      }
      if (d.attempts && d.attempts.length > 1) {
        view.append(el("h3", null, "Attempts on this task+tool"));
        const t = el("table");
        for (const a of d.attempts) {
          const tr = el("tr");
          tr.append(el("td", null, String(a.attempt_number)),
            el("td").appendChild(badge(["ok","success"].includes(a.result_status), a.result_status)).parentNode,
            el("td", null, fmtDur(a.duration_ms)), el("td", null, a.error_class || "—"),
            el("td", null, fmtTime(a.created_at)));
          t.append(tr);
        }
        view.append(t);
      }
    } else if (type === "task") {
      const d = await api("task", { id });
      view.append(el("h2", null, `Task ${d.task.task_id}`));
      const cards = el("div", "cards");
      for (const [k, v] of [["family", d.task.task_family], ["provider", d.task.provider],
        ["model", d.task.model], ["created", fmtTime(d.task.created_at)]]) {
        const c = el("div", "card");
        c.append(el("div", "label", k), el("div", "value", esc(v || "—")));
        cards.append(c);
      }
      view.append(cards);
      if (d.task.sanitized_intent) {
        view.append(el("h3", null, "sanitized intent"), el("pre", null, esc(d.task.sanitized_intent)));
      }
      view.append(el("h3", null, "Timeline"));
      const t = el("table");
      const thead = el("thead"); const trh = el("tr");
      ["stage", "at", "detail"].forEach((x) => trh.append(el("th", null, x)));
      thead.append(trh); t.append(thead);
      const tb = el("tbody");
      for (const e of d.events) {
        const tr = el("tr");
        let detail = "";
        if (e.stage === "tool_call") detail = `${e.data.tool_name} — ${e.data.result_status}`;
        else if (e.stage === "outcome") detail = `${e.data.result} (confidence ${e.data.confidence})`;
        else if (e.stage === "error") detail = `${e.data.error_class}: ${e.data.error_message || ""}`;
        tr.append(el("td", null, e.stage), el("td", null, fmtTime(e.at)), el("td", null, detail));
        tb.append(tr);
      }
      t.append(tb); view.append(t);
      if (d.missing_stages && d.missing_stages.length) {
        view.append(el("p", null, "Not recorded for this task: " + d.missing_stages.join("; ")));
      }
    } else if (type === "strategy") {
      const d = await api("strategy", { id });
      view.append(el("h2", null, d.strategy_name || d.strategy_id));
      const cards = el("div", "cards");
      const rows = [["status", d.status], ["confidence", d.confidence],
        ["evidence", d.evidence_count], ["success", d.success_count],
        ["failures", d.failure_count], ["contexts", d.context_count],
        ["family", d.task_family], ["scope", d.scope], ["version", String(d.version)],
        ["created", fmtTime(d.created_at)], ["last validated", fmtTime(d.last_validated_at)],
        ["last used", fmtTime(d.last_used_at)]];
      for (const [k, v] of rows) {
        const c = el("div", "card");
        c.append(el("div", "label", k), el("div", "value", esc(v ?? "—")));
        cards.append(c);
      }
      view.append(cards);
      view.append(el("h3", null, "Sequence"));
      view.append(el("pre", null, JSON.stringify(d.sequence, null, 2)));
      view.append(el("h3", null, "Evidence sample (outcomes for this family)"));
      if (!d.evidence_sample.length) view.append(emptyState("No outcome rows match this strategy's task family."));
      const t = el("table");
      for (const e of d.evidence_sample) {
        const tr = el("tr");
        tr.append(el("td", null, e.task_id), el("td").appendChild(badge(e.result === "SUCCESS", e.result)).parentNode,
          el("td", null, String(e.confidence ?? "—")), el("td", null, fmtTime(e.recorded_at)));
        t.append(tr);
      }
      view.append(t);
      if (d.guidance_events && d.guidance_events.length) {
        view.append(el("h3", null, "Retrieval events selecting this strategy"));
        const t2 = el("table");
        for (const g of d.guidance_events) {
          const tr = el("tr");
          tr.append(el("td", null, g.task_id || "—"), el("td", null, g.hook),
            el("td", null, g.reason_code), el("td", null, fmtTime(g.created_at)));
          t2.append(tr);
        }
        view.append(t2);
      } else {
        view.append(el("p", null,
          d.guidance_events === undefined
            ? "Retrieval telemetry not available (schema v4 table missing)."
            : "This strategy has never been retrieved (no guidance events reference it)."));
      }
    }
  } catch (e) { showError(e.message); }
}

async function renderFailures() {
  const d = await api("failures", { window: state.window, page: state.pages.failures || 1 });
  view.textContent = "";
  const f = el("div", "filters");
  f.append(el("span", null, "window:"), windowSelect());
  view.append(f);

  if (d.by_class && d.by_class.length) {
    view.append(el("h3", null, "Failure categories (window)"));
    const t = el("table");
    for (const r of d.by_class) {
      const tr = el("tr");
      tr.append(el("td", null, r.cls), el("td", null, String(r.n)));
      t.append(tr);
    }
    view.append(t);
  }
  if (d.recoveries && d.recoveries.length) {
    view.append(el("h3", null, "Failed then recovered (same task + tool)"));
    const t = el("table");
    for (const r of d.recoveries) {
      const tr = el("tr");
      const link = el("a", null, r.task_id); link.href = "#";
      link.onclick = (ev) => { ev.preventDefault(); state.detail = { type: "task", id: r.task_id }; renderDetail(); };
      tr.append(el("td").appendChild(link).parentNode, el("td", null, r.tool_name),
        el("td", null, fmtTime(r.failed_at)), el("td", null, fmtTime(r.recovered_at)));
      t.append(tr);
    }
    view.append(t);
  }
  if (!d.rows.length) { view.append(emptyState("No failures in this window.")); return; }
  view.append(el("h3", null, `Failures (${d.total})`));
  const t = el("table");
  const thead = el("thead"); const trh = el("tr");
  ["time", "tool", "class", "message (sanitized)", "task"].forEach((x) => trh.append(el("th", null, x)));
  thead.append(trh); t.append(thead);
  const tb = el("tbody");
  for (const r of d.rows) {
    const tr = el("tr");
    tr.append(el("td", null, fmtTime(r.created_at)), el("td", null, r.tool_name),
      el("td", null, r.classified_class || r.error_class || "—"),
      el("td", null, (r.error_message || "").slice(0, 120)),
      el("td", null, r.task_id || "—"));
    tb.append(tr);
  }
  t.append(tb); view.append(t);
  pager(view, d, () => renderFailures());
}

async function renderTasks() {
  const d = await api("tasks", { window: state.window, q: state.search, page: state.pages.tasks || 1 });
  view.textContent = "";
  const f = el("div", "filters");
  const search = el("input"); search.type = "search"; search.placeholder = "search task id / family / intent";
  search.value = state.search || "";
  const go = el("button", "act", "Search");
  go.onclick = () => { state.search = search.value; state.pages.tasks = 1; renderTasks(); };
  f.append(el("span", null, "window:"), windowSelect(), search, go);
  view.append(f);
  if (!d.rows.length) { view.append(emptyState("No tasks match.")); return; }
  const t = el("table");
  const thead = el("thead"); const trh = el("tr");
  ["time", "task", "family", "provider", "model", "intent (sanitized)"].forEach((x) => trh.append(el("th", null, x)));
  thead.append(trh); t.append(thead);
  const tb = el("tbody");
  for (const r of d.rows) {
    const tr = el("tr");
    const link = el("a", null, r.task_id); link.href = "#";
    link.onclick = (ev) => { ev.preventDefault(); state.detail = { type: "task", id: r.task_id }; renderDetail(); };
    tr.append(el("td", null, fmtTime(r.created_at)), el("td").appendChild(link).parentNode,
      el("td", null, r.task_family || "—"), el("td", null, r.provider || "—"),
      el("td", null, r.model || "—"),
      el("td", null, (r.sanitized_intent || "").slice(0, 100)));
    tb.append(tr);
  }
  t.append(tb); view.append(t);
  pager(view, d, () => renderTasks());
}

async function renderMemory() {
  const d = await api("strategies", { status: state.statusFilter, q: state.search,
    page: state.pages.strategies || 1 });
  view.textContent = "";
  const f = el("div", "filters");
  const stSel = el("select");
  [["", "all"], ["validated", "qualified"], ["candidate", "candidate"], ["disabled", "disabled"]]
    .forEach(([v, l]) => { const o = el("option", null, l); o.value = v; stSel.append(o); });
  stSel.value = state.statusFilter || "";
  stSel.onchange = () => { state.statusFilter = stSel.value; state.pages.strategies = 1; renderMemory(); };
  const search = el("input"); search.type = "search"; search.placeholder = "search strategies";
  search.value = state.search || "";
  const go = el("button", "act", "Search");
  go.onclick = () => { state.search = search.value; state.pages.strategies = 1; renderMemory(); };
  f.append(el("span", null, "status:"), stSel, search, go);
  view.append(f);

  view.append(el("p", null,
    "Lifecycle: RAW OBSERVATION → CLASSIFIED EXPERIENCE → CANDIDATE PATTERN → " +
    "QUALIFIED STRATEGY → RETRIEVED STRATEGY → GUIDANCE DELIVERED → BEHAVIORAL EFFECT MEASURED. " +
    "Rows below are persisted strategies/patterns only; retrieval, delivery and behavioral effect are separate (see Guidance page)."));

  if (!d.rows.length) { view.append(emptyState("No strategies stored.")); return; }
  const t = el("table");
  const thead = el("thead"); const trh = el("tr");
  ["name", "status", "confidence", "evidence", "success", "fail", "contexts", "family", "created"].forEach((x) => trh.append(el("th", null, x)));
  thead.append(trh); t.append(thead);
  const tb = el("tbody");
  for (const r of d.rows) {
    const tr = el("tr");
    const link = el("a", null, r.strategy_name || r.strategy_id); link.href = "#";
    link.onclick = (ev) => { ev.preventDefault(); state.detail = { type: "strategy", id: r.strategy_id }; renderDetail(); };
    tr.append(el("td").appendChild(link).parentNode,
      el("td").appendChild(badge(r.status === "validated", r.status)).parentNode,
      el("td", null, r.confidence != null ? Number(r.confidence).toFixed(3) : "—"),
      el("td", null, String(r.evidence_count ?? "—")),
      el("td", null, String(r.success_count ?? "—")),
      el("td", null, String(r.failure_count ?? "—")),
      el("td", null, String(r.context_count ?? "—")),
      el("td", null, r.task_family || "—"),
      el("td", null, fmtTime(r.created_at)));
    tb.append(tr);
  }
  t.append(tb); view.append(t);
  pager(view, d, () => renderMemory());
}

async function renderGuidance() {
  const d = await api("guidance", { reason: state.reasonFilter, page: state.pages.guidance || 1 });
  view.textContent = "";
  if (!d.available) {
    view.append(emptyState(
      "Retrieval/guidance telemetry table (retrieval_guidance_events, schema v4) " +
      "is not present in this database. Recordings made before the upgrade are not retroactively available."));
    return;
  }
  const f = el("div", "filters");
  const rSel = el("select");
  [["", "all reasons"], ["guidance_returned", "guidance returned"],
   ["no_candidate", "no candidate"], ["candidate_below_threshold", "candidate below threshold"]]
    .forEach(([v, l]) => { const o = el("option", null, l); o.value = v; rSel.append(o); });
  rSel.value = state.reasonFilter || "";
  rSel.onchange = () => { state.reasonFilter = rSel.value; state.pages.guidance = 1; renderGuidance(); };
  f.append(el("span", null, "reason:"), rSel);
  view.append(f);
  view.append(el("p", null,
    "These events record what the EBTTO hooks did (retrieval, qualification, construction, return). " +
    "They do NOT prove delivery to the model or any behavioral effect. " +
    "BEHAVIORAL IMPROVEMENT NOT YET PROVEN."));
  if (!d.rows.length) { view.append(emptyState("No retrieval events yet.")); return; }
  const t = el("table");
  const thead = el("thead"); const trh = el("tr");
  ["time", "hook", "reason", "strategy", "candidates", "qualified", "task"].forEach((x) => trh.append(el("th", null, x)));
  thead.append(trh); t.append(thead);
  const tb = el("tbody");
  for (const r of d.rows) {
    const tr = el("tr");
    tr.append(el("td", null, fmtTime(r.created_at)), el("td", null, r.hook),
      el("td").appendChild(badge(!!r.guidance_returned, r.reason_code)).parentNode,
      el("td", null, r.selected_strategy_id || "—"),
      el("td", null, String(r.candidate_count)), el("td", null, String(r.qualified_count)),
      el("td", null, r.task_id || "—"));
    tb.append(tr);
  }
  t.append(tb); view.append(t);
  pager(view, d, () => renderGuidance());
}

async function renderSystem() {
  const d = await api("system");
  view.textContent = "";
  const cards = el("div", "cards");
  const add = (k, v, sub) => {
    const c = el("div", "card");
    c.append(el("div", "label", k), el("div", "value", esc(v ?? "—")));
    if (sub) c.append(el("div", "sub", sub));
    cards.append(c);
  };
  add("Schema version", d.schema_version, d.schema_version >= 4 ? "guidance telemetry present" : "pre-v4: guidance telemetry unavailable");
  add("DB integrity", d.integrity, "");
  add("Last event", fmtTime(d.last_event_at), "tool_calls");
  add("Read-only", "yes", "no writes possible through this UI");
  for (const [k, v] of Object.entries(d.counts || {})) add(k, v, "rows");
  view.append(cards);
  const p = el("p", null, "Database: " + d.db_path);
  view.append(p);
  const missing = [];
  if (!d.guidance_telemetry) missing.push("retrieval_guidance_events (schema v4)");
  if (!d.counts.evaluations) missing.push("benchmark evaluations");
  if (missing.length) {
    view.append(el("p", null, "Missing telemetry: " + missing.join("; ") +
      " — the dashboard reports these as unavailable rather than fabricating values."));
  }
}

/* ---------------- shell ---------------- */

async function render() {
  if (state.detail) { await renderDetail(); return; }
  document.querySelectorAll("#nav button").forEach((b) =>
    b.setAttribute("aria-current", String(b.dataset.page === state.page)));
  try {
    if (state.page === "overview") await renderOverview();
    else if (state.page === "activity") { state.page = "tools"; await renderToolCalls(); }
    else if (state.page === "tools") await renderToolCalls();
    else if (state.page === "failures") await renderFailures();
    else if (state.page === "tasks") await renderTasks();
    else if (state.page === "memory") await renderMemory();
    else if (state.page === "guidance") await renderGuidance();
    else if (state.page === "system") await renderSystem();
    else await renderOverview();
    state.lastOk = new Date();
    $("#last-refresh").textContent = "updated " + state.lastOk.toLocaleTimeString();
    conn("ok");
  } catch (e) {
    conn("down");
    showError(e.message);
  }
}

function startTimer() {
  if (state.timer) clearInterval(state.timer);
  const ms = parseInt($("#interval").value, 10);
  if (ms > 0) state.timer = setInterval(() => {
    if (!document.hidden) render();
  }, ms);
}

$("#nav").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-page]");
  if (!b) return;
  state.page = b.dataset.page; state.detail = null; state.search = "";
  state.statusFilter = ""; state.reasonFilter = ""; state.pages = {};
  render();
});
$("#refresh-now").onclick = () => render();
$("#interval").onchange = startTimer;
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) render();  // refresh immediately on tab focus
});

startTimer();
render();
