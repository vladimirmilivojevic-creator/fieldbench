// FieldBench console: talks to the bench API, draws results with Chart.js.
const API = window.FIELDBENCH_API;
const $ = (sel) => document.querySelector(sel);
const charts = [];
let currentRun = null;
let procedures = [];

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children) node.append(child instanceof Node ? child : String(child ?? ""));
  return node;
}

const badge = (text, kind) => el("span", { class: `badge ${kind}` }, text);
const resultBadge = (passed) => (passed == null ? badge("not run", "wait") : passed ? badge("PASS", "pass") : badge("FAIL", "fail"));

async function api(path, options = {}) {
  const response = await fetch(API + path, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `${response.status} ${response.statusText}`);
  }
  return response.status === 204 ? null : response;
}
const getJson = async (path) => (await api(path)).json();

// --- server status: the free server sleeps, so wake it and say so ---------
function setStatus(kind, text) {
  $("#api-status").className = `status ${kind}`;
  $("#api-status .text").textContent = text;
}

async function wakeUp() {
  const started = Date.now();
  for (;;) {
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 8000);
      await fetch(`${API}/health`, { signal: controller.signal });
      clearTimeout(timer);
      setStatus("online", "Bench server online");
      return true;
    } catch {
      const seconds = Math.round((Date.now() - started) / 1000);
      if (seconds > 120) {
        setStatus("offline", "Bench server not reachable. The CI reports above still work.");
        return false;
      }
      setStatus("waking", `Waking up the free bench server... ${seconds} s (usually under a minute)`);
      await new Promise((resolve) => setTimeout(resolve, 2500));
    }
  }
}

// --- campaign ----------------------------------------------------------------
function renderProcedures(results = []) {
  const byId = Object.fromEntries(results.map((r) => [r.id, r]));
  const body = $("#procedures tbody");
  body.replaceChildren(
    ...procedures.map((p) => {
      const result = byId[p.id];
      const row = el(
        "tr",
        { class: result ? "clickable" : "", "data-id": p.id },
        el("td", {}, el("b", {}, p.id)),
        el("td", {}, p.title, p.faults.length ? el("div", { class: "muted" }, "fault: " + p.faults.map((f) => f.type).join(", ")) : ""),
        el("td", {}, p.requirement, p.safety ? el("div", { class: "muted" }, "safety") : ""),
        el("td", {}, resultBadge(result ? result.passed : null)),
      );
      if (result) row.addEventListener("click", () => showDetail(result));
      return row;
    }),
  );
}

function selectedRelease() {
  return document.querySelector("input[name=release]:checked").value;
}

async function runCampaign() {
  const button = $("#run-btn");
  button.disabled = true;
  $("#downloads").classList.add("hidden");
  $("#detail").classList.add("hidden");
  renderProcedures([]);
  try {
    const { id } = await (await api("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ release: selectedRelease() }),
    })).json();
    let run;
    do {
      await new Promise((resolve) => setTimeout(resolve, 700));
      run = await getJson(`/api/runs/${id}`);
      $("#progress-bar").style.width = `${(100 * run.done) / run.total}%`;
      $("#run-info").textContent = `${run.status}: ${run.done}/${run.total} procedures, release ${run.release}`;
      renderProcedures(run.results);
    } while (run.status === "queued" || run.status === "running");
    if (run.status === "error") throw new Error(run.error);
    currentRun = run;
    $("#run-info").textContent = `Release ${run.release}: ${run.passed} passed, ${run.failed} failed`;
    showDownloads(run);
    await loadIssues();
    // open the most telling result: a failure under fault injection, else the GNSS dropout test
    const withFault = (r) => procedures.find((p) => p.id === r.id).faults.length > 0;
    showDetail(
      run.results.find((r) => !r.passed && withFault(r)) ||
        run.results.find((r) => !r.passed) ||
        run.results.find((r) => r.id === "TP-GUI-10"),
    );
  } catch (error) {
    $("#run-info").textContent = `Run failed: ${error.message}`;
  } finally {
    button.disabled = false;
  }
}

function showDownloads(run) {
  const base = `${API}/api/runs/${run.id}`;
  $("#downloads").replaceChildren(
    el("b", {}, "Downloads:"),
    el("a", { href: `${base}/report.html`, target: "_blank", rel: "noopener" }, "HTML report"),
    el("a", { href: `${base}/report.xlsx` }, "Excel report"),
    el("a", { href: `${base}/logs/TP-GUI-10_${run.release}.blf` }, "TP-GUI-10 log (BLF)"),
    el("a", { href: `${base}/logs/TP-GUI-10_${run.release}.asc`, target: "_blank", rel: "noopener" }, "TP-GUI-10 log (ASC)"),
  );
  $("#downloads").classList.remove("hidden");
}

// --- procedure detail: checks + signal charts ------------------------------
const shading = {
  id: "shading",
  beforeDatasetsDraw(chart, _args, options) {
    const { ctx, chartArea: area, scales } = chart;
    for (const span of options.spans || []) {
      const x0 = Math.max(scales.x.getPixelForValue(span.start), area.left);
      const x1 = Math.min(scales.x.getPixelForValue(span.end), area.right);
      if (x1 <= x0) continue;
      ctx.save();
      ctx.fillStyle = span.color;
      ctx.fillRect(x0, area.top, x1 - x0, area.bottom - area.top);
      ctx.restore();
    }
  },
};

function destroyCharts() {
  while (charts.length) charts.pop().destroy();
}

async function showDetail(result) {
  if (!result || !currentRun) return;
  document.querySelectorAll("#procedures tr").forEach((row) => row.classList.toggle("selected", row.dataset.id === result.id));
  const procedure = procedures.find((p) => p.id === result.id);
  $("#detail").classList.remove("hidden");
  $("#detail-title").textContent = `${result.id} - ${result.title}`;
  $("#detail-sub").textContent = `${procedure.requirement}: ${window.requirements[procedure.requirement].text} (release ${currentRun.release})`;
  $("#checks tbody").replaceChildren(
    ...result.checks.map((c) => el("tr", {}, el("td", {}, c.name), el("td", {}, c.expected), el("td", {}, c.measured), el("td", {}, resultBadge(c.passed)))),
  );

  const data = await getJson(`/api/runs/${currentRun.id}/signals/${result.id}`);
  const spans = [
    ...data.faults.map((f) => ({ start: f.start, end: f.end, color: "rgba(242,153,0,0.22)" })),
    ...data.dropouts.map((d) => ({ start: d.start_s, end: d.end_s, color: "rgba(217,48,37,0.25)" })),
  ];
  destroyCharts();
  const box = $("#charts");
  box.replaceChildren();
  for (const [name, series] of Object.entries(data.signals)) {
    const canvas = el("canvas");
    box.append(el("div", { class: "chart-box" }, canvas));
    charts.push(
      new Chart(canvas, {
        type: "line",
        data: { datasets: [{ label: name, data: series.t.map((t, i) => ({ x: t, y: series.v[i] })), stepped: true, borderColor: "#2f6f4a", borderWidth: 1.6, pointRadius: 0 }] },
        options: {
          animation: false,
          maintainAspectRatio: false,
          scales: {
            x: { type: "linear", min: 0, max: Math.round(series.t[series.t.length - 1]), title: { display: name === "CrossTrackError", text: "time [s]" } },
            // fixed axis width so the stacked charts line up
            y: { ticks: { maxTicksLimit: 4 }, afterFit: (scale) => { scale.width = 56; } },
          },
          plugins: {
            legend: { display: false },
            title: { display: true, text: name, align: "start", font: { size: 12, weight: "600" }, padding: { top: 0, bottom: 2 } },
            shading: { spans },
          },
        },
        plugins: [shading],
      }),
    );
  }
  $("#detail").scrollIntoView({ behavior: "smooth", block: "start" });
}

// --- issues --------------------------------------------------------------------
async function loadIssues() {
  const issues = await getJson("/api/issues");
  const body = $("#issue-table tbody");
  if (!issues.length) {
    body.replaceChildren(el("tr", {}, el("td", { colspan: 6, class: "muted" }, "No issues yet. Run release 1.3.0.")));
    $("#issue-report").classList.add("hidden");
    return;
  }
  body.replaceChildren(
    ...issues.map((issue) =>
      el(
        "tr",
        { class: "clickable", onclick: () => showIssue(issue.id) },
        el("td", {}, el("b", {}, issue.id)),
        el("td", {}, issue.title, el("div", { class: "muted" }, `actual: ${issue.actual}`)),
        el("td", {}, issue.severity),
        el("td", {}, badge(issue.status, issue.status === "open" ? "open" : "verified")),
        el("td", {}, issue.found_in),
        el("td", {}, issue.verified_in || ""),
      ),
    ),
  );
}

async function showIssue(id) {
  const text = await (await api(`/api/issues/${id}.md`)).text();
  const pre = $("#issue-report");
  pre.textContent = text;
  pre.classList.remove("hidden");
}

async function resetIssues() {
  await api("/api/issues", { method: "DELETE" });
  await loadIssues();
}

// --- guidance ------------------------------------------------------------------
async function loadGuidance() {
  const g = await getJson("/api/guidance");
  $("#guidance-sub").textContent = `Source: ${g.source}. AB line heading ${g.line_heading_deg} deg, accuracy class ${g.fix_class}.`;
  const stat = (label, value) => el("div", { class: "stat" }, el("span", { class: "muted" }, label), el("b", {}, value));
  $("#guidance-stats").replaceChildren(
    stat("Fixes used", `${g.stats.fixes_used} / ${g.stats.fixes_total}`),
    stat("Pass length", `${g.stats.duration_s} s`),
    stat("RMS XTE", `${g.stats.xte_rms_m} m`),
    stat("95th pct |XTE|", `${g.stats.xte_p95_m} m`),
    stat(`Limit (${g.fix_class})`, `${g.limit_m} m`),
    el("div", { class: "stat" }, el("span", { class: "muted" }, "Verdict"), el("b", {}, resultBadge(g.passed))),
  );
  const p = g.points;
  new Chart($("#track-chart"), {
    type: "scatter",
    data: { datasets: [{ label: "track (east / north, m)", data: p.east.map((x, i) => ({ x, y: p.north[i] })), pointRadius: 1.8, borderColor: "#2f6f4a", backgroundColor: "#2f6f4a" }] },
    options: { animation: false, maintainAspectRatio: false, scales: { x: { title: { display: true, text: "east [m]" } }, y: { title: { display: true, text: "north [m]" } } } },
  });
  const limit = (sign) => ({ label: sign > 0 ? `limit ${g.limit_m} m` : "", data: p.t.map((t) => ({ x: t, y: sign * g.limit_m })), borderDash: [4, 4], borderColor: "#888", pointRadius: 0, borderWidth: 1 });
  new Chart($("#xte-chart"), {
    type: "line",
    data: { datasets: [{ label: "cross-track error [m]", data: p.t.map((t, i) => ({ x: t, y: p.xte[i] })), borderColor: "#c0392b", pointRadius: 0, borderWidth: 1.6 }, limit(1), limit(-1)] },
    options: { animation: false, maintainAspectRatio: false, scales: { x: { type: "linear", title: { display: true, text: "time [s]" } } }, plugins: { legend: { labels: { filter: (item) => item.text } } } },
  });
}

// --- log upload ------------------------------------------------------------------
async function analyzeUpload(event) {
  event.preventDefault();
  const file = $("#log-file").files[0];
  if (!file) return;
  const out = $("#analyze-out");
  out.textContent = "Analysing...";
  try {
    const form = new FormData();
    form.append("file", file);
    const r = await (await api("/api/analyze", { method: "POST", body: form })).json();
    const rows = r.messages.map((m) => el("tr", {}, el("td", {}, m.message), el("td", {}, m.frames), el("td", {}, m.nominal_ms), el("td", {}, m.mean_ms ?? "-"), el("td", {}, m.max_gap_ms ?? "-")));
    const drops = r.dropouts.length
      ? el("ul", {}, ...r.dropouts.map((d) => el("li", {}, `${d.message}: ${d.start_s.toFixed(3)} s to ${d.end_s.toFixed(3)} s (${d.gap_ms} ms)`)))
      : el("p", {}, "No dropouts.");
    out.replaceChildren(
      el("p", {}, `${r.frames} frames, ${r.error_frames} error frames.`),
      el("div", { class: "table-wrap" }, el("table", {}, el("thead", {}, el("tr", {}, ...["Message", "Frames", "Nominal ms", "Mean ms", "Max gap ms"].map((h) => el("th", {}, h)))), el("tbody", {}, ...rows))),
      el("h3", {}, "Dropouts (gap > 3 x cycle time)"),
      drops,
    );
  } catch (error) {
    out.textContent = `Could not analyse: ${error.message}`;
  }
}

// --- start ---------------------------------------------------------------------
async function main() {
  $("#docs-link").href = `${API}/docs`;
  $("#run-btn").addEventListener("click", runCampaign);
  $("#reset-btn").addEventListener("click", resetIssues);
  $("#upload-form").addEventListener("submit", analyzeUpload);
  if (!(await wakeUp())) return;
  const spec = await getJson("/api/spec");
  procedures = spec.procedures;
  window.requirements = spec.requirements;
  $("#run-btn").textContent = `Run ${procedures.length} procedures`;
  $("#run-btn").disabled = false;
  renderProcedures();
  await Promise.all([loadIssues(), loadGuidance()]);
}

main();
