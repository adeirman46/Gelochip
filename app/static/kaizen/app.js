// Gelochip Kaizen — frontend controller (vanilla JS, SSE-driven).

const $ = (sel) => document.querySelector(sel);
const pipelineEl = $("#pipeline");
const logEl = $("#log");
const runBtn = $("#run-btn");

const NODE_LABELS = {
  plan: "Planner", research: "Researcher", retrieve: "Retriever", generate: "Generator",
  test: "Test", kaizen_memory: "Kaizen memory", persist: "Persist", summarize: "Summarize",
};

// ── collection counts ──────────────────────────────────────────────
async function refreshCollections() {
  try {
    const res = await fetch("/api/kaizen/collections");
    const counts = await res.json();
    document.querySelectorAll(".coll").forEach((el) => {
      const n = counts[el.dataset.name];
      el.querySelector(".n").textContent = n != null ? n.toLocaleString() : "0";
    });
  } catch (_) {}
}
refreshCollections();

// ── example chips ──────────────────────────────────────────────────
document.querySelectorAll(".chip").forEach((c) =>
  c.addEventListener("click", () => { $("#prompt").value = c.textContent; })
);

// ── pipeline helpers ───────────────────────────────────────────────
function resetPipeline() {
  pipelineEl.querySelectorAll("li").forEach((li) =>
    li.classList.remove("active", "done", "fail"));
}
function markNode(node, state) {
  const li = pipelineEl.querySelector(`li[data-node="${node}"]`);
  if (!li) return;
  pipelineEl.querySelectorAll("li.active").forEach((x) => x.classList.remove("active"));
  if (state === "active") li.classList.add("active");
  else { li.classList.remove("active"); li.classList.add(state); }
}
function logLine(node, msg) {
  const ts = new Date().toLocaleTimeString();
  const div = document.createElement("div");
  div.className = "line";
  div.innerHTML = `<span class="ts">${ts}</span> <span class="node">${
    NODE_LABELS[node] || node}</span> ${escapeHtml(msg || "")}`;
  logEl.appendChild(div);
  logEl.scrollTop = logEl.scrollHeight;
}
function escapeHtml(s) {
  return String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}

// ── verdict + results ──────────────────────────────────────────────
function setVerdict(cls, text) {
  const v = $("#verdict");
  v.className = "verdict " + cls;
  v.textContent = text;
}
function showPreview(url) {
  const p = $("#preview");
  p.innerHTML = `<img src="${url}?t=${Date.now()}" alt="GDS preview" />`;
}
function showLinks(ev) {
  const links = $("#gds-links");
  links.innerHTML = "";
  if (ev.gds_url) links.innerHTML += `<a href="${ev.gds_url}" download>⬇ download GDS</a>`;
  if (ev.png_url) links.innerHTML += `<a href="${ev.png_url}" target="_blank">↗ open PNG</a>`;
}
function showThinking(node, text) {
  const el = $("#thinking");
  const label = (NODE_LABELS[node] || node);
  el.innerHTML = `<div class="think-label">${escapeHtml(label)} is thinking…</div>` +
    `<div class="think-body">${escapeHtml(text)}</div>`;
  const b = el.querySelector(".think-body"); if (b) b.scrollTop = b.scrollHeight;
}
let _lastCode = null;
function stripFence(s) {
  const m = String(s).match(/```(?:python|py)?\s*\n([\s\S]*?)```/);
  return (m ? m[1] : String(s)).trim();
}
function showCode(code, tag) {
  const hdr = tag ? `<div class="code-tag">${escapeHtml(tag)}</div>` : "";
  $("#code").innerHTML = hdr + `<code>${escapeHtml(code)}</code>`;
}
// minimal LCS line-diff → red (−) removed / green (+) added
function showCodeDiff(oldC, newC, version) {
  const a = oldC.split("\n"), b = newC.split("\n");
  const n = a.length, m = b.length;
  const L = Array.from({ length: n + 1 }, () => new Int32Array(m + 1));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      L[i][j] = a[i] === b[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  let i = 0, j = 0, out = "";
  const row = (cls, sign, txt) => `<div class="dl ${cls}">${sign} ${escapeHtml(txt)}</div>`;
  while (i < n && j < m) {
    if (a[i] === b[j]) { out += row("dctx", " ", a[i]); i++; j++; }
    else if (L[i + 1][j] >= L[i][j + 1]) { out += row("ddel", "-", a[i]); i++; }
    else { out += row("dadd", "+", b[j]); j++; }
  }
  while (i < n) out += row("ddel", "-", a[i++]);
  while (j < m) out += row("dadd", "+", b[j++]);
  $("#code").innerHTML = `<div class="code-tag">v${version} · diff vs v${version - 1}</div>` +
    `<div class="diff">${out}</div>`;
}
// ── knowledge & research panel (verify before generation) ──────────
let _kInit = false;
function _kReset() { $("#knowledge").innerHTML = ""; _kInit = true; }
function addResearch(sources) {
  if (!_kInit) _kReset();
  const k = $("#knowledge");
  let html = `<div class="kgroup-title">🔎 Researched sources (${sources.length})</div>`;
  if (!sources.length) html += '<div class="kitem"><span class="ksnip">No external sources (offline or none found) — using local knowledge only.</span></div>';
  sources.forEach((s) => {
    const isImg = /\.(png|jpe?g|gif|svg)(\?|$)/i.test(s.url || "");
    html += `<div class="kitem">
      <span class="ksrc">${escapeHtml(s.source || "src")}</span><span class="ktitle">${escapeHtml(s.title || "")}</span>
      ${s.url ? `<div><a href="${escapeHtml(s.url)}" target="_blank">${escapeHtml(s.url)}</a></div>` : ""}
      ${isImg ? `<img src="${escapeHtml(s.url)}" alt="">` : ""}
      ${s.snippet ? `<div class="ksnip">${escapeHtml(s.snippet)}</div>` : ""}
    </div>`;
  });
  k.insertAdjacentHTML("beforeend", html);
}
function addRetrieved(r) {
  if (!_kInit) _kReset();
  const k = $("#knowledge");
  const grp = (title, items, kind) => {
    if (!items || !items.length) return "";
    let h = `<div class="kgroup-title">${title}</div>`;
    items.forEach((it) => {
      const body = kind === "code"
        ? `<code>${escapeHtml((it.snippet || "").slice(0, 280))}</code>`
        : `<div class="ksnip">${escapeHtml(it.snippet || "")}</div>`;
      h += `<div class="kitem"><span class="ksrc">${escapeHtml(it.label || "")}</span>${body}</div>`;
    });
    return h;
  };
  k.insertAdjacentHTML("beforeend",
    grp("📐 Retrieved glayout knowledge", r.templates, "code") +
    grp("📖 Retrieved RF theory", r.theory) +
    grp("🧪 From researched papers", r.research));
}

function showTestbench(ev) {
  const box = $("#tb-plots");
  const imgs = [];
  if (ev.ac_plot_url) imgs.push(`<figure><img src="${ev.ac_plot_url}?t=${Date.now()}"><figcaption>AC</figcaption></figure>`);
  if (ev.tran_plot_url) imgs.push(`<figure><img src="${ev.tran_plot_url}?t=${Date.now()}"><figcaption>Transient</figcaption></figure>`);
  box.innerHTML = imgs.length ? imgs.join("") : '<span class="placeholder">no simulation output</span>';
  const sl = $("#spice-link");
  sl.innerHTML = ev.spice_url ? `<a href="${ev.spice_url}" target="_blank">↗ extracted SPICE netlist</a>` : "";
}

// ── handle one streamed event ──────────────────────────────────────
function handleEvent(ev) {
  if (ev.node === "error") {
    logLine("error", ev.msg);
    setVerdict("fail", "Agent error — " + ev.msg);
    pipelineEl.querySelector("li.active")?.classList.add("fail");
    return;
  }
  if (ev.node === "done") return;

  logLine(ev.node, ev.msg);

  if (ev.node in NODE_LABELS) {
    const prev = pipelineEl.querySelector("li.active");
    if (prev) prev.classList.add("done");
    markNode(ev.node, "active");
  }
  if (ev.thinking) showThinking(ev.node, ev.thinking);
  if (ev.node === "research" && ev.sources) addResearch(ev.sources);
  if (ev.node === "retrieve" && ev.retrieved) addRetrieved(ev.retrieved);
  if (ev.node === "generate" && ev.code) {
    const code = stripFence(ev.code);
    if (ev.streaming) {
      showCode(code, `v${ev.version || 1} · writing…`);     // live stream
    } else {
      if ((ev.version || 1) > 1 && _lastCode) showCodeDiff(_lastCode, code, ev.version);
      else showCode(code, `v${ev.version || 1}`);
      _lastCode = code;
    }
  }
  if (ev.node === "test") {
    if (ev.png_url) showPreview(ev.png_url);
    showLinks(ev);
    showTestbench(ev);
    if (ev.passed) setVerdict("pass", "✅ DRC clean — layout passed");
    else setVerdict("fail", "❌ failed — agent will self-correct");
  }
  if (ev.node === "summarize") {
    markNode("summarize", "done");
    const ok = /✅|clean/.test(ev.msg);
    const warn = /skipped/.test(ev.msg);
    setVerdict(warn ? "warn" : ok ? "pass" : "fail", ev.msg.split("\n")[0]);
  }
}

// ── run ────────────────────────────────────────────────────────────
$("#prompt-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const prompt = $("#prompt").value.trim();
  if (!prompt) return;

  resetPipeline();
  logEl.innerHTML = "";
  _kReset(); $("#knowledge").innerHTML = '<span class="placeholder">researching + retrieving…</span>';
  $("#thinking").innerHTML = '<span class="placeholder">the agent\'s reasoning streams here…</span>';
  $("#preview").innerHTML = '<span class="placeholder">generating…</span>';
  $("#gds-links").innerHTML = "";
  $("#tb-plots").innerHTML = '<span class="placeholder">no simulation yet</span>'; $("#spice-link").innerHTML = "";
  showCode("// generating…");
  _lastCode = null;
  setVerdict("idle", "running…");
  runBtn.disabled = true; $("#stop-btn").hidden = false;
  document.querySelectorAll(".hist-item.active").forEach((x) => x.classList.remove("active"));

  let job;
  try {
    const res = await fetch("/api/kaizen/run", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      const detail = err.detail?.[0]?.msg || err.error || `HTTP ${res.status}`;
      setVerdict("fail", "rejected: " + detail);
      runBtn.disabled = false; $("#stop-btn").hidden = true; return;
    }
    job = await res.json();
  } catch (err) {
    setVerdict("fail", "could not reach backend");
    runBtn.disabled = false; $("#stop-btn").hidden = true; return;
  }

  _currentJob = job.job_id;
  loadHistory();   // the run is saved immediately → show it in the sidebar now

  const es = new EventSource(`/api/kaizen/stream/${job.job_id}`);
  es.onmessage = (m) => {
    try { handleEvent(JSON.parse(m.data)); } catch (_) {}
  };
  const finish = () => {
    es.close(); runBtn.disabled = false; $("#stop-btn").hidden = true; _currentJob = null;
    refreshCollections(); loadHistory();
  };
  es.addEventListener("end", finish);
  es.onerror = () => finish();
});

let _currentJob = null;
$("#stop-btn").addEventListener("click", async () => {
  if (!_currentJob) return;
  $("#stop-btn").disabled = true;
  try { await fetch(`/api/kaizen/cancel/${_currentJob}`, { method: "POST" }); } catch (_) {}
  logLine("system", "⏹ cancel requested — stopping at the next step…");
  setTimeout(() => { $("#stop-btn").disabled = false; }, 1000);
});

// ── health badge (poll readiness) ──────────────────────────────────
async function pollHealth() {
  const el = $("#health"); if (!el) return;
  try {
    const h = await (await fetch("/api/health")).json();
    const ok = h.status === "ok";
    el.className = "health-dot " + (ok ? "ok" : "degraded");
    el.title = ok ? `healthy · ollama ${h.ollama?.up ? "up" : "down"}`
      : `degraded · ${h.ollama?.up ? "" : "ollama down"} ${h.collections_error || ""}`.trim();
  } catch (_) {
    el.className = "health-dot down"; el.title = "backend unreachable";
  }
}
pollHealth(); setInterval(pollHealth, 15000);

// ════════════════════════════════════════════════════════════════════
//  CHAT / BUILD HISTORY  (click to restore last state)
// ════════════════════════════════════════════════════════════════════
async function loadHistory() {
  try {
    const { sessions } = await (await fetch("/api/kaizen/history")).json();
    const el = $("#history");
    if (!sessions.length) { el.innerHTML = '<span class="placeholder">No runs yet.</span>'; return; }
    el.innerHTML = sessions.map((s) => {
      const icon = s.passed ? "✅" : "○";
      const when = new Date(s.created_at * 1000).toLocaleString();
      return `<div class="hist-item" data-id="${s.id}" title="${when}">
        <span class="hi-icon">${icon}</span>
        <span class="hi-prompt">${escapeHtml(s.prompt).slice(0, 70)}</span></div>`;
    }).join("");
    el.querySelectorAll(".hist-item").forEach((it) =>
      it.addEventListener("click", () => restoreSession(it.dataset.id)));
  } catch (_) {}
}

async function restoreSession(id) {
  try {
    const s = await (await fetch(`/api/kaizen/history/${id}`)).json();
    const st = s.state || {};
    $("#prompt").value = s.prompt || "";
    document.querySelectorAll(".hist-item").forEach((x) =>
      x.classList.toggle("active", x.dataset.id === id));
    // replay the saved pipeline marks + log + knowledge
    resetPipeline(); logEl.innerHTML = ""; _kReset();
    $("#thinking").innerHTML = '<span class="placeholder">(restored run)</span>';
    (s.events || []).forEach((ev) => {
      if (ev.node in NODE_LABELS) markNode(ev.node, "done");
      if (ev.msg && !ev.streaming) logLine(ev.node, ev.msg);
      if (ev.thinking) showThinking(ev.node, ev.thinking);
      if (ev.node === "research" && ev.sources) addResearch(ev.sources);
      if (ev.node === "retrieve" && ev.retrieved) addRetrieved(ev.retrieved);
    });
    if (!$("#knowledge").innerHTML) $("#knowledge").innerHTML =
      '<span class="placeholder">no research/knowledge saved for this run</span>';
    showCode(st.code || "// (no code saved)");
    if (st.png_url) showPreview(st.png_url); else
      $("#preview").innerHTML = '<span class="placeholder">no preview saved</span>';
    showTestbench({ ac_plot_url: st.ac_plot_url, tran_plot_url: st.tran_plot_url, spice_url: st.spice_url });
    showLinks({ gds_url: st.gds_url, png_url: st.png_url });
    const drcErr = (st.drc || {}).total_errors;
    if (st.passed) setVerdict("pass", `✅ restored — DRC clean (${drcErr ?? 0} errors)`);
    else setVerdict("fail", "○ restored — was not clean");
  } catch (_) {}
}

$("#history-refresh").addEventListener("click", loadHistory);
$("#new-chat").addEventListener("click", () => {
  $("#prompt").value = ""; $("#prompt").focus();
  resetPipeline(); logEl.innerHTML = "";
  $("#knowledge").innerHTML = '<span class="placeholder">research + retrieved knowledge will appear here</span>';
  $("#thinking").innerHTML = '<span class="placeholder">the agent\'s reasoning streams here…</span>';
  $("#preview").innerHTML = '<span class="placeholder">No layout yet</span>';
  $("#gds-links").innerHTML = ""; $("#tb-plots").innerHTML = '<span class="placeholder">no simulation yet</span>';
  $("#spice-link").innerHTML = ""; showCode("// generated code appears here");
  setVerdict("idle", "awaiting run…"); _kInit = false; _lastCode = null;
  document.querySelectorAll(".hist-item.active").forEach((x) => x.classList.remove("active"));
  // ensure we're on the Prompt tab
  document.querySelector('.tab[data-tab="prompt"]').click();
});
loadHistory();   // on page load

// ════════════════════════════════════════════════════════════════════
//  TAB SWITCHING
// ════════════════════════════════════════════════════════════════════
document.querySelectorAll(".tab").forEach((t) =>
  t.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
    t.classList.add("active");
    document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));
    document.getElementById("view-" + t.dataset.tab).classList.remove("hidden");
    if (t.dataset.tab === "studio") initStudio();
  })
);

// ════════════════════════════════════════════════════════════════════
//  CHIP STUDIO  (IP library + padframe + drag-n-drop + pin wiring)
// ════════════════════════════════════════════════════════════════════
const SVGNS = "http://www.w3.org/2000/svg";
let studioReady = false;
let PADFRAME = null;
let placed = [];           // {uid, ip, x, y, w, h, pins:[{name,side}]}
let placeSeq = 0;

async function initStudio() {
  if (studioReady) return;
  studioReady = true;
  await loadPadframe();
  await loadIPs();
  $("#ai-connect").addEventListener("click", aiConnect);
  $("#clear-canvas").addEventListener("click", () => {
    placed = []; renderCanvas(); $("#netlist").innerHTML =
      '<span class="placeholder">Place blocks, then “AI connect pins”.</span>';
  });
}

async function loadIPs() {
  const list = $("#ip-list");
  list.innerHTML = '<span class="placeholder">loading…</span>';
  const { ips } = await (await fetch("/api/ip/library")).json();
  list.innerHTML = "";
  if (!ips.length) { list.innerHTML = '<span class="placeholder">No DRC-clean IPs yet.</span>'; return; }
  ips.forEach((ip) => {
    const card = document.createElement("div");
    card.className = "ip-card";
    card.draggable = true;
    card.innerHTML = `
      ${ip.preview_url ? `<img src="${ip.preview_url}" alt="">` : '<div style="width:46px"></div>'}
      <div>
        <div class="ip-name">${ip.name}<span class="badge">DRC✓</span></div>
        <div class="ip-meta">${ip.pins.length} pins · ${ip.area_um2 ?? "?"} µm²</div>
      </div>`;
    card.addEventListener("dragstart", (e) =>
      e.dataTransfer.setData("application/json", JSON.stringify(ip)));
    list.appendChild(card);
  });
}

async function loadPadframe() {
  PADFRAME = await (await fetch("/api/padframe")).json();
  $("#pf-source").textContent = "· " + PADFRAME.source;
  renderCanvas();
}

const svg = () => $("#canvas");

// SVG client→viewBox coordinate transform
function svgCoords(evt) {
  const s = svg(), r = s.getBoundingClientRect(), vb = s.viewBox.baseVal;
  return { x: (evt.clientX - r.left) / r.width * vb.width,
           y: (evt.clientY - r.top) / r.height * vb.height };
}
function mk(tag, attrs, parent) {
  const el = document.createElementNS(SVGNS, tag);
  for (const k in attrs) el.setAttribute(k, attrs[k]);
  if (parent) parent.appendChild(el);
  return el;
}

// absolute pin position for block b given pin index on its side
function pinPos(b, pin) {
  const sidePins = b.pins.filter((p) => p.side === pin.side);
  const i = sidePins.indexOf(pin), n = sidePins.length;
  const f = (i + 1) / (n + 1);
  if (pin.side === "left")   return { x: b.x,        y: b.y + f * b.h };
  if (pin.side === "right")  return { x: b.x + b.w,  y: b.y + f * b.h };
  if (pin.side === "top")    return { x: b.x + f * b.w, y: b.y };
  return { x: b.x + f * b.w, y: b.y + b.h };
}

function renderCanvas() {
  const s = svg();
  s.innerHTML = "";
  if (!PADFRAME) return;
  const { w, h, core_margin: m } = PADFRAME.outline;
  s.setAttribute("viewBox", `-40 -40 ${w + 80} ${h + 80}`);
  mk("rect", { class: "frame", x: 0, y: 0, width: w, height: h }, s);
  mk("rect", { class: "core", x: m, y: m, width: w - 2 * m, height: h - 2 * m }, s);
  PADFRAME.pads.forEach((p) => {
    mk("rect", { class: "pad", x: p.x - 14, y: p.y - 14, width: 28, height: 28, rx: 3 }, s);
    mk("text", { class: "pad-label", x: p.x - 12, y: p.y + 24,
      transform: (p.side === "left" || p.side === "right") ? `rotate(0 ${p.x} ${p.y})` : "" }, s)
      .textContent = p.name;
  });
  placed.forEach(drawBlock);
  drawWires();
}

function drawBlock(b) {
  const s = svg();
  const g = mk("g", { "data-uid": b.uid }, s);
  mk("rect", { class: "block-rect", x: b.x, y: b.y, width: b.w, height: b.h, rx: 6 }, g);
  mk("text", { class: "block-label", x: b.x + b.w / 2, y: b.y + b.h / 2,
    "text-anchor": "middle", "dominant-baseline": "middle" }, g).textContent = b.uid;
  b.pins.forEach((pin) => {
    const pos = pinPos(b, pin);
    mk("circle", { class: "pin-dot", cx: pos.x, cy: pos.y, r: 3.5 }, g);
    const dx = pin.side === "left" ? -4 : pin.side === "right" ? 4 : 0;
    const anchor = pin.side === "left" ? "end" : pin.side === "right" ? "start" : "middle";
    mk("text", { class: "pin-label", x: pos.x + dx, y: pos.y - 5, "text-anchor": anchor }, g)
      .textContent = pin.name;
  });
  // drag to reposition
  g.addEventListener("mousedown", (e) => {
    if (e.target.classList.contains("pin-dot")) return;
    const start = svgCoords(e), ox = b.x, oy = b.y;
    const move = (ev) => { const c = svgCoords(ev);
      b.x = ox + (c.x - start.x); b.y = oy + (c.y - start.y); renderCanvas(); };
    const up = () => { window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up); };
    window.addEventListener("mousemove", move); window.addEventListener("mouseup", up);
  });
}

let currentNets = [];
function drawWires() {
  const byRef = {};
  placed.forEach((b) => b.pins.forEach((p) => { byRef[`${b.uid}.${p.name}`] = pinPos(b, p); }));
  currentNets.forEach((net) => {
    const pts = net.pins.map((r) => byRef[r]).filter(Boolean);
    if (pts.length < 2) return;
    const hub = pts[0];
    pts.slice(1).forEach((pt) =>
      mk("path", { class: "wire", d: `M ${hub.x} ${hub.y} L ${pt.x} ${pt.y}` }, svg()));
    mk("text", { class: "wire-label", x: hub.x + 4, y: hub.y - 4 }, svg()).textContent = net.name;
  });
}

// drag-n-drop drop handler
$("#canvas").addEventListener("dragover", (e) => e.preventDefault());
$("#canvas").addEventListener("drop", (e) => {
  e.preventDefault();
  const ip = JSON.parse(e.dataTransfer.getData("application/json"));
  const c = svgCoords(e);
  const scale = Math.min(220, Math.max(120, Math.sqrt(ip.area_um2 || 4000) * 2));
  placeSeq += 1;
  placed.push({
    uid: "U" + placeSeq, ip: ip.id, x: c.x - scale / 2, y: c.y - scale / 2,
    w: scale, h: scale, pins: ip.pins,
  });
  currentNets = [];
  renderCanvas();
});

async function aiConnect() {
  if (placed.length < 1) return;
  const btn = $("#ai-connect"); btn.disabled = true; btn.textContent = "thinking…";
  try {
    const body = { blocks: placed.map((b) => ({ id: b.uid, ip: b.ip, pins: b.pins })) };
    const res = await (await fetch("/api/connect", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    })).json();
    currentNets = res.nets || [];
    renderCanvas();
    renderNetlist(res);
  } catch (_) {
    $("#netlist").innerHTML = '<span class="placeholder">connect failed</span>';
  } finally { btn.disabled = false; btn.textContent = "⚡ AI connect pins"; }
}

function renderNetlist(res) {
  const el = $("#netlist");
  if (!res.nets || !res.nets.length) {
    el.innerHTML = '<span class="placeholder">No nets proposed.</span>'; return;
  }
  el.innerHTML = `<div class="hint">source: ${escapeHtml(res.source || "")}</div>` +
    res.nets.map((n) =>
      `<div class="net"><b>${escapeHtml(n.name)}</b><span class="pins">${
        n.pins.map(escapeHtml).join("  ·  ")}</span></div>`).join("");
}
