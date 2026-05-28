// Pipeline run state — a faithful React port of the event handling that used to
// live in app.js (handleEvent / restoreSession). One reducer drives the whole
// Prompt → GDSII view; the same `apply` action serves both live SSE events and
// replayed events from saved history.

export const NODE_LABELS = {
  plan: "Planner",
  research: "Researcher",
  retrieve: "Retriever",
  generate: "Generator",
  test: "Test",
  kaizen_memory: "Kaizen memory",
  persist: "Persist",
  summarize: "Summarize",
};

export function stripFence(s) {
  const m = String(s).match(/```(?:python|py)?\s*\n([\s\S]*?)```/);
  return (m ? m[1] : String(s)).trim();
}

// minimal LCS line diff → array of {cls, sign, text}
export function lineDiff(oldC, newC) {
  const a = oldC.split("\n");
  const b = newC.split("\n");
  const n = a.length;
  const m = b.length;
  const L = Array.from({ length: n + 1 }, () => new Int32Array(m + 1));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      L[i][j] = a[i] === b[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  let i = 0;
  let j = 0;
  const out = [];
  while (i < n && j < m) {
    if (a[i] === b[j]) out.push({ cls: "dctx", sign: " ", text: a[i++] }), j++;
    else if (L[i + 1][j] >= L[i][j + 1]) out.push({ cls: "ddel", sign: "-", text: a[i++] });
    else out.push({ cls: "dadd", sign: "+", text: b[j++] });
  }
  while (i < n) out.push({ cls: "ddel", sign: "-", text: a[i++] });
  while (j < m) out.push({ cls: "dadd", sign: "+", text: b[j++] });
  return out;
}

export const initialRun = {
  pipeline: {}, // node -> "active" | "done" | "fail"
  log: [], // {ts, node, msg}
  thinking: null, // {node, text}
  knowledge: [], // ordered list of {type:'research'|'retrieved', ...}
  kInit: false,
  code: { tag: "", code: "// generated code appears here", diff: null },
  lastCode: null,
  preview: null, // png url
  links: {}, // {gds_url, png_url}
  tb: {}, // {ac_plot_url, tran_plot_url, spice_url}
  verdict: { cls: "idle", text: "awaiting run…" },
};

function markActive(pipeline, node) {
  const next = {};
  for (const k of Object.keys(pipeline)) next[k] = pipeline[k] === "active" ? "done" : pipeline[k];
  next[node] = "active";
  return next;
}

export function runReducer(state, action) {
  switch (action.type) {
    case "reset":
      return { ...initialRun, knowledge: [], kInit: true };
    case "new":
      return { ...initialRun };
    case "restore-begin":
      return { ...initialRun, knowledge: [], kInit: true, thinking: { node: "plan", text: "(restored run)" } };
    case "verdict":
      return { ...state, verdict: { cls: action.cls, text: action.text } };
    case "set":
      return { ...state, ...action.patch };
    case "event":
      return applyEvent(state, action.ev, action.restore);
    default:
      return state;
  }
}

function applyEvent(state, ev, restore) {
  let s = state;
  if (ev.node === "error") {
    const active = Object.keys(s.pipeline).find((k) => s.pipeline[k] === "active");
    const pipeline = { ...s.pipeline };
    if (active) pipeline[active] = "fail";
    return {
      ...s,
      pipeline,
      log: [...s.log, line("error", ev.msg)],
      verdict: { cls: "fail", text: "Agent error — " + ev.msg },
    };
  }
  if (ev.node === "done") return s;

  // pipeline marks + log
  if (restore) {
    if (ev.node in NODE_LABELS) s = { ...s, pipeline: { ...s.pipeline, [ev.node]: "done" } };
    if (ev.msg && !ev.streaming) s = { ...s, log: [...s.log, line(ev.node, ev.msg)] };
  } else {
    s = { ...s, log: [...s.log, line(ev.node, ev.msg)] };
    if (ev.node in NODE_LABELS) s = { ...s, pipeline: markActive(s.pipeline, ev.node) };
  }

  if (ev.thinking) s = { ...s, thinking: { node: ev.node, text: ev.thinking } };
  if (ev.node === "research" && ev.sources)
    s = { ...s, kInit: true, knowledge: [...s.knowledge, { type: "research", sources: ev.sources }] };
  if (ev.node === "retrieve" && ev.retrieved)
    s = { ...s, kInit: true, knowledge: [...s.knowledge, { type: "retrieved", r: ev.retrieved }] };

  if (ev.node === "generate" && ev.code) {
    const code = stripFence(ev.code);
    if (ev.streaming) {
      s = { ...s, code: { tag: `v${ev.version || 1} · writing…`, code, diff: null } };
    } else if ((ev.version || 1) > 1 && s.lastCode) {
      s = {
        ...s,
        code: { tag: `v${ev.version} · diff vs v${ev.version - 1}`, code, diff: lineDiff(s.lastCode, code) },
        lastCode: code,
      };
    } else {
      s = { ...s, code: { tag: `v${ev.version || 1}`, code, diff: null }, lastCode: code };
    }
  }

  if (ev.node === "test" && !restore) {
    s = {
      ...s,
      preview: ev.png_url || s.preview,
      links: { gds_url: ev.gds_url, png_url: ev.png_url },
      tb: { ac_plot_url: ev.ac_plot_url, tran_plot_url: ev.tran_plot_url, spice_url: ev.spice_url },
      verdict: ev.passed
        ? { cls: "pass", text: "✅ DRC clean — layout passed" }
        : { cls: "fail", text: "❌ failed — agent will self-correct" },
    };
  }

  if (ev.node === "summarize" && !restore) {
    const ok = /✅|clean/.test(ev.msg || "");
    const warn = /skipped/.test(ev.msg || "");
    s = {
      ...s,
      pipeline: { ...s.pipeline, summarize: "done" },
      verdict: { cls: warn ? "warn" : ok ? "pass" : "fail", text: (ev.msg || "").split("\n")[0] },
    };
  }
  return s;
}

function line(node, msg) {
  return { ts: new Date().toLocaleTimeString(), node, msg: msg || "" };
}

// Build the full run state from a saved history session (state + events).
export function fromSession(s) {
  let st = { ...initialRun, knowledge: [], kInit: true, log: [], pipeline: {} };
  st.thinking = { node: "plan", text: "(restored run)" };
  for (const ev of s.events || []) st = applyEvent(st, ev, true);
  const sv = s.state || {};
  st.code = { tag: "", code: sv.code || "// (no code saved)", diff: null };
  st.preview = sv.png_url || null;
  st.links = { gds_url: sv.gds_url, png_url: sv.png_url };
  st.tb = { ac_plot_url: sv.ac_plot_url, tran_plot_url: sv.tran_plot_url, spice_url: sv.spice_url };
  const drcErr = (sv.drc || {}).total_errors;
  st.verdict = sv.passed
    ? { cls: "pass", text: `✅ restored — DRC clean (${drcErr ?? 0} errors)` }
    : { cls: "fail", text: "○ restored — was not clean" };
  return st;
}
