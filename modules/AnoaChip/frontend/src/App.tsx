import { Fragment, memo, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { api } from "./api";
import { Artifacts } from "./Artifacts";
import { BlockView } from "./Block";
import { ChipStudio } from "./ChipStudio";
import { IPLibrary } from "./IPLibrary";
import { KnowledgePanel } from "./Knowledge";
import { Simulation } from "./Simulation";
import { DEFAULT_CONSTRAINTS } from "./types";
import type { Block, Chat, KnowledgeStats, Message, OllamaModel, Project, RunConstraints, RunEvent, SystemCaps, TranscriptRecord } from "./types";

type View = "chat" | "ips" | "sim" | "studio" | "knowledge";
const NAV: { key: View; icon: string; label: string }[] = [
  { key: "chat", icon: "💬", label: "Design Chat" },
  { key: "ips", icon: "🧩", label: "IP Library" },
  { key: "sim", icon: "🔬", label: "Simulation" },
  { key: "studio", icon: "▦", label: "Chip Studio" },
];

const STEP_EMOJI: Record<string, string> = {
  plan: "🧭", retrieve: "📚", web: "🌐", generate: "✍️", decompose: "🧩",
  testbench: "🧪", write: "💾", simulate: "⏱️", lint: "🔍",
  fix_design: "🔧", fix_testbench: "🔧", harden: "🏭", error: "❗",
  lvs: "🔍", pex: "🧵", pl_sim: "🔬", report: "📕",
};

// whimsical busy words (à la Claude's "Cogitating…") — Anoa (Sulawesi dwarf buffalo) +
// analog-IC flavoured, rotated every couple of seconds so the wait never feels stale.
const BUSY_WORDS = [
  "Anoaing", "Grazing", "Wallowing", "Foraging", "Roaming", "Trotting", "Wading", "Snorting",
  "Biasing", "Mirroring", "Cascoding", "Degenerating", "Compensating", "Sizing", "gm/Id-ing",
  "Routing", "Placing", "Floorplanning", "Interdigitating", "Common-centroiding", "Guard-ringing",
  "Substrate-tying", "Dummy-filling", "Via-stacking", "C-routing", "L-routing", "Straight-routing",
  "Netlisting", "Subckt-ing", "Bias-pointing", "DC-sweeping", "AC-sweeping", "Transient-solving",
  "Bode-plotting", "Phase-margining", "Gain-measuring", "Bandwidth-checking", "Slewing", "Swinging",
  "Matching", "Trimming", "Tuning", "Decoupling", "Shielding", "Grounding", "Powering",
  "DRC-checking", "LVS-matching", "GDS-streaming", "Layouting", "Extracting", "Simulating",
  "Ngspice-ing", "Glayouting", "Magic-checking", "Netgen-matching", "Bandgapping", "Referencing",
  "Convolving", "Filtering", "Mixing", "Amplifying", "Buffering", "Comparing", "Oscillating",
  "Annealing", "Doping", "Siliconizing", "Transistoring", "Etching", "Wafering", "Tapeout-ing",
  "Probing", "Waveforming", "Sampling", "Linting", "Debugging", "Architecting", "Drafting",
  "Schematicking", "Sketching", "Forging", "Crafting", "Conjuring", "Brewing", "Simmering",
  "Percolating", "Crunching", "Calculating", "Reasoning", "Pondering", "Cogitating", "Recalling",
  "Manifesting", "Solving", "Optimizing", "Converging", "Self-improving",
];

function useBusyWord(active: boolean) {
  const [word, setWord] = useState(() => BUSY_WORDS[Math.floor(Math.random() * BUSY_WORDS.length)]);
  useEffect(() => {
    if (!active) return;
    const tick = () => setWord(BUSY_WORDS[Math.floor(Math.random() * BUSY_WORDS.length)]);
    tick();
    const id = setInterval(tick, 3500);
    return () => clearInterval(id);
  }, [active]);
  return word;
}

function BusyTag() {
  const word = useBusyWord(true);
  return (
    <span className="working">
      <span className="streamdots"><i /><i /><i /></span> {word}…
    </span>
  );
}

// --- grand-plan checklist: each item greens as the DOWNSTREAM agent reaches its phase ---
// (the planner ticks nothing itself). Phases are the pipeline steps after "plan".
const PHASE_ORDER = ["generate", "decompose", "testbench", "write", "simulate", "lint", "harden"];

function itemPhase(text: string): number {
  const t = text.toLowerCase();
  const has = (...ks: string[]) => ks.some((k) => t.includes(k));
  if (has("drc", "lvs", "antenna", "gdsii", "gds", "stream out", "streamout", "sign-off", "signoff", "tape-out", "tapeout")) return 6; // harden
  if (has("floorplan", "placement", "place-and-route", "place and route", "clock tree", " cts", "routing", "physical")) return 6;
  if (has("synthesis", "synthesize", "yosys", "netlist", "gate-level", "timing constraint", "logic synth")) return 6;
  if (has("verify", "corner case", "hazard", "reset behav", "simulat", "regression", "waveform")) return 4; // simulate
  if (has("testbench", "self-checking", "stimulus", "test case", "test bench")) return 2; // testbench
  if (has("integrate", "connect the", "wire up", "assemble", "top-level connect", "hook up")) return 3; // write/integrate
  return 0; // spec, research, design top/sub-modules, LUT/weights → generate phase
}

function planProgress(turn: TranscriptRecord[], live: boolean) {
  const nodes = turn.map((n) => n.node);
  const active = live ? nodes[nodes.length - 1] : null;
  let maxDone = -1;
  for (const n of nodes) {
    if (n === active) continue;
    const idx = PHASE_ORDER.indexOf(n);
    if (idx > maxDone) maxDone = idx;
  }
  return { maxDone, activeIdx: active ? PHASE_ORDER.indexOf(active) : -1 };
}

// the files the agent has actually written this turn — scanned from the streamed
// `write_file_disk · path=rtl/alu.v` tool-call blocks. Used to green a checklist item the
// MOMENT its file lands on disk (not just when the whole phase finishes).
function writtenFiles(turn: TranscriptRecord[]): Set<string> {
  const out = new Set<string>();
  for (const n of turn) {
    for (const b of n.blocks) {
      if (b.kind !== "markdown") continue;
      const s = String(b.payload?.[0] ?? "");
      if (!s.includes("write_file_disk")) continue;
      const m = s.match(/path=([^\s·`]+)/);
      if (m) out.add(m[1].split("/").pop()!.toLowerCase());
    }
  }
  return out;
}

function itemFile(it: string): string | null {
  const m = it.match(/([a-z0-9_]+\.(?:sp|spice|cir|cdl|py|json))\b/i);
  return m ? m[1].toLowerCase() : null;
}

// stem of a filename ("alu_8bit_fp.v" → "alu_8bit_fp")
const stem = (f: string) => f.replace(/\.[^.]+$/, "");

// compact Hz label for the constraints summary (1e6 → "1MHz")
function fmtHz(hz: number): string {
  if (!isFinite(hz) || hz <= 0) return `${hz}Hz`;
  if (hz >= 1e9) return `${+(hz / 1e9).toFixed(2)}GHz`;
  if (hz >= 1e6) return `${+(hz / 1e6).toFixed(2)}MHz`;
  if (hz >= 1e3) return `${+(hz / 1e3).toFixed(2)}kHz`;
  return `${hz}Hz`;
}

// does any written file correspond to this plan filename? The generator often renames
// (plan "alu.v" → written "alu_8bit_fp.v"), so match on equality or a token-prefix.
function fileWritten(itemFn: string, written: Set<string>): boolean {
  const a = stem(itemFn);
  for (const w of written) {
    const b = stem(w);
    // exact, or the written file SPECIALIZES the planned name (plan "alu" → written "alu_8bit").
    // NOT the reverse — a written "fazyrv_rf" must not green the plan item "fazyrv_rf_lut".
    if (a === b || b.startsWith(a + "_")) return true;
  }
  return false;
}

function PlanChecklist({ items, turn, live }: { items: string[]; turn: TranscriptRecord[]; live: boolean }) {
  const { maxDone } = planProgress(turn, live);
  const written = writtenFiles(turn);
  // BINARY states only — done (green ✓) or pending. The orange "in-progress" marker was
  // wrong too often (items stayed orange after their phase finished), so it's gone: an item
  // is simply checked when its work is done, exactly like every other item.
  const stateOf = (it: string): "done" | "pending" => {
    const f = itemFile(it);
    if (f)                                      // an item that names a file → green when written
      return fileWritten(f, written) ? "done" : "pending";
    return itemPhase(it) <= maxDone ? "done" : "pending";
  };
  const states = items.map(stateOf);
  const done = states.filter((s) => s === "done").length;
  return (
    <div className="block planlist">
      <div className="planhead">
        📋 Plan <span className="plansub">— greens as each item is built</span>
        <span className="plancount">{done}/{items.length}</span>
      </div>
      <ul>
        {items.map((it, i) => {
          const st = states[i];
          return (
            <li key={i} className={"planitem " + st}>
              <span className="pmark">{st === "done" ? "✓" : ""}</span>
              <span className="ptext">{it}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

// canonical pipeline for the progress stepper (gives the user an at-a-glance map).
// GLAYOUT-FIRST flow: Plan → Generate (config JSON: wiring + params) → Layout (glayout
// GDS · show · DRC · LVS · PEX · testbench · ngspice sim, looping back to fix/regenerate) →
// Report. There is NO separate split/testbench/write/simulate/lint stage anymore — the SPICE
// is only distilled into the JSON, and all verification happens inside the Layout stage on the
// extracted (PEX) netlist.
const PIPELINE: [string, string][] = [
  ["plan", "Planning"], ["generate", "Generate"],
  ["harden", "GDS"], ["lvs", "LVS"], ["pex", "PEX"],
  ["pl_sim", "Testbench"], ["report", "Report"],
];

function Stepper({ transcript, live }: { transcript: TranscriptRecord[]; live: boolean }) {
  const seen = new Set(transcript.map((n) => n.node));
  const last = transcript[transcript.length - 1]?.node;
  return (
    <div className="stepper">
      {PIPELINE.map(([key, label]) => {
        const active = live && key === last;
        const state = active ? "active" : seen.has(key) ? "done" : "pending";
        return (
          <span key={key} className={"stepchip " + state} title={label}>
            <span className="dotmark">{state === "done" ? "✓" : state === "active" ? "●" : "○"}</span>
            {label}
          </span>
        );
      })}
    </div>
  );
}

// One assistant turn (stepper + step cards). MEMOIZED: while the user types in the
// composer (or an unrelated state changes) every past turn keeps its props by reference
// and skips re-rendering entirely — without this, each keystroke re-rendered the whole
// multi-hundred-block transcript and the input lagged badly.
const TurnView = memo(function TurnView(
  { turn, live, runId }: { turn: TranscriptRecord[]; live: boolean; runId: string | null }) {
  return (
    <>
      <Stepper transcript={turn} live={live} />
      {turn.map((node, i) => (
        <div key={i} className="node">
          <div className="head">
            <span>{STEP_EMOJI[node.node] || "•"}</span>
            <span>{titleFor(node)}</span>
          </div>
          <div className="blocks">
            {node.blocks.map((b, j) => b.kind === "plan"
              ? <PlanChecklist key={j} items={(b.payload?.[0] as string[]) || []} turn={turn} live={live} />
              : <BlockView key={j} block={b} runId={runId} />)}
          </div>
        </div>
      ))}
    </>
  );
});

export default function App() {
  const [chats, setChats] = useState<Chat[]>([]);
  const [chatId, setChatId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [transcript, setTranscript] = useState<TranscriptRecord[]>([]);
  const [running, setRunning] = useState(false);
  const [pausing, setPausing] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [knowledge, setKnowledge] = useState<KnowledgeStats | null>(null);
  const [view, setView] = useState<View>("chat");
  const [projects, setProjects] = useState<Project[]>([]);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [seedIP, setSeedIP] = useState<string | null>(null);
  const [newProject, setNewProject] = useState(false);
  const [projName, setProjName] = useState("");
  const [pendingProject, setPendingProject] = useState<string | null>(null);
  // each finished run's transcript, keyed by the user message that triggered it (so the
  // chat alternates User → Assistant → User → Assistant). The LIVE run uses `transcript`,
  // anchored to `runMsgId`.
  const [pastRuns, setPastRuns] = useState<Record<string, TranscriptRecord[]>>({});
  const [runMsgId, setRunMsgId] = useState<string | null>(null);
  const [artRefresh, setArtRefresh] = useState(0);   // bump to re-list artifacts
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [confirmMsg, setConfirmMsg] = useState<string | null>(null);
  const [editTarget, setEditTarget] = useState<{ id: string; content: string } | null>(null);
  const [editText, setEditText] = useState("");
  const [theme, setTheme] = useState<"dark" | "light">(
    () => (localStorage.getItem("anoa-theme") as "dark" | "light") || "dark");

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("anoa-theme", theme);
  }, [theme]);

  const [prompt, setPrompt] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [opts, setOpts] = useState<RunConstraints>({ ...DEFAULT_CONSTRAINTS });
  const [caps, setCaps] = useState<SystemCaps | null>(null);
  const [models, setModels] = useState<OllamaModel[]>([]);
  const [showConstraints, setShowConstraints] = useState(true);
  const streamRef = useRef<HTMLDivElement>(null);
  const unsubRef = useRef<() => void>();
  const newRunRef = useRef(false);   // force the next step into a FRESH card (continue → new blocks below)
  const setOpt = <K extends keyof RunConstraints>(k: K, v: RunConstraints[K]) =>
    setOpts((o) => ({ ...o, [k]: v }));

  useEffect(() => { refreshChats(); refreshKnowledge(); refreshProjects(); }, []);
  // Size the context-window slider to the user's GPU VRAM (or RAM on CPU) and adopt the
  // hardware-aware default so num_ctx's KV cache always fits.
  useEffect(() => {
    api.systemCaps().then((c) => {
      setCaps(c);
      setOpts((o) => ({ ...o, num_ctx: Math.min(o.num_ctx || c.num_ctx_default, c.num_ctx_max) }));
    }).catch(() => { /* keep the static default */ });
  }, []);
  // Load the installed Ollama models for the picker and adopt the active one as the default.
  useEffect(() => {
    api.systemModels().then((r) => {
      setModels(r.models);
      setOpts((o) => ({ ...o, model: o.model || r.current || r.models[0]?.name }));
    }).catch(() => { /* picker just shows the static label */ });
  }, []);
  // on reload, reopen the chat the user was in (reconnects to a live run via SSE replay)
  useEffect(() => {
    const last = localStorage.getItem("anoa-chat");
    if (last) openChat(last).catch(() => localStorage.removeItem("anoa-chat"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  // STICK-TO-BOTTOM autoscroll: follow new content ONLY while the user is already at the
  // bottom. Scrolling up sets stickToBottom=false (via onScroll below) so reading history is
  // never hijacked; scrolling back down within ~120px re-engages following.
  const stickToBottom = useRef(true);
  const onStreamScroll = () => {
    const el = streamRef.current;
    if (el) stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
  };
  useEffect(() => {
    if (stickToBottom.current) streamRef.current?.scrollTo(0, streamRef.current.scrollHeight);
  }, [transcript, messages]);

  async function refreshChats() { setChats(await api.listChats()); }
  async function refreshKnowledge() { try { setKnowledge(await api.knowledge()); } catch { /* */ } }
  async function refreshProjects() { try { setProjects(await api.listProjects()); } catch { /* */ } }

  async function addProject() {
    const name = projName.trim() || "New project";
    const p = await api.createProject(name);
    setNewProject(false); setProjName("");
    setExpanded((e) => ({ ...e, [p.id]: true }));
    refreshProjects();
  }
  async function removeProject(id: string, ev?: React.MouseEvent) {
    ev?.stopPropagation();
    await api.deleteProject(id, false);   // unfile its chats, keep them
    refreshProjects(); refreshChats();
  }
  function openTab(v: View) { setView(v); }

  async function openChat(id: string) {
    setView("chat");                             // selecting a chat always returns to the chat view
    // NOTE: do NOT pause the run when switching chats — a build must keep running
    // server-side while you look at another chat (like CI). Only the Stop button pauses.
    unsubRef.current?.();
    setChatId(id);
    stickToBottom.current = true;                // a freshly opened chat lands at the bottom
    localStorage.setItem("anoa-chat", id);     // remember it so a reload reopens this chat
    const data = await api.getChat(id);
    setMessages(data.messages || []);
    const byMsg: Record<string, TranscriptRecord[]> = {};
    (data.runs || []).forEach((r: any) => { if (r.message_id) byMsg[r.message_id] = r.transcript || []; });
    setPastRuns(byMsg);
    setRunMsgId(data.run?.message_id ?? null);
    setRunId(data.run?.id ?? null);
    setPausing(false);
    const live = (data.run?.status || "done") === "running";
    setRunning(live);
    if (live && data.run?.id) {
      // RECONNECT to the live run — SSE replays the full backlog (incl. the in-progress
      // step that isn't persisted yet), so the transcript is restored, not lost.
      setTranscript([]);
      newRunRef.current = false;
      unsubRef.current = api.streamRun(data.run.id, applyEvent);
    } else {
      setTranscript(data.run?.transcript || []);
    }
  }

  async function newChat(projectId: string | null = null) {
    setView("chat");                             // new chat always returns to the chat view
    // don't pause the running build — it keeps going server-side in its own chat
    unsubRef.current?.();
    localStorage.removeItem("anoa-chat");
    setChatId(null); setMessages([]); setTranscript([]); setRunId(null); setRunning(false);
    setPastRuns({}); setRunMsgId(null);
    setPendingProject(projectId);                // the next send creates the chat in this project
    // keep the hardware-aware context window from caps + the chosen model; reset everything else
    setOpts((o) => ({ ...DEFAULT_CONSTRAINTS, num_ctx: caps?.num_ctx_default ?? DEFAULT_CONSTRAINTS.num_ctx, model: o.model }));
    setShowConstraints(true);   // pop the constraints picker out on every new chat
  }

  function askDelete(id: string, ev?: React.MouseEvent) {
    ev?.stopPropagation();
    setConfirmDelete(id);              // open the styled confirm modal (no ugly native dialog)
  }

  async function doDelete() {
    const id = confirmDelete;
    setConfirmDelete(null);
    if (!id) return;
    await api.deleteChat(id);          // cascades: chat/messages/run + knowledge rows + MinIO blobs
    if (id === chatId) newChat();
    refreshChats(); refreshKnowledge();
  }

  // delete / edit ONE message (and its run) — open STYLED modals (no native browser dialogs).
  function deleteMessage(id: string, ev?: React.MouseEvent) {
    ev?.stopPropagation();
    if (!chatId || running) return;
    setConfirmMsg(id);
  }
  async function doDeleteMessage() {
    const id = confirmMsg; setConfirmMsg(null);
    if (!id || !chatId) return;
    await api.deleteMessage(chatId, id);
    await openChat(chatId);
    setArtRefresh((k) => k + 1); refreshKnowledge();
  }
  function editMessage(id: string, cur: string, ev?: React.MouseEvent) {
    ev?.stopPropagation();
    if (!chatId || running) return;
    setEditTarget({ id, content: cur }); setEditText(cur);
  }
  async function saveEdit() {
    if (!editTarget || !chatId) return;
    const { id, content } = editTarget;
    const next = editText.trim();
    setEditTarget(null);
    if (!next) return;
    if (next === content.trim()) return;               // no change → nothing to do
    if (running && runId) api.pauseRun(runId);          // never run two at once
    // edit AND auto re-RUN this message (the new run replaces the old) — like ChatGPT.
    setPastRuns((p) => { const c = { ...p }; delete c[id]; return c; });
    setMessages((m) => m.map((x) => (x.id === id ? { ...x, content: next } : x)));
    setTranscript([]); setRunMsgId(id); setRunning(true); setPausing(false);
    const { run } = await api.rerunMessage(chatId, id, next, opts);
    setRunId(run.id);
    newRunRef.current = true;
    unsubRef.current = api.streamRun(run.id, applyEvent);
  }

  function applyEvent(e: RunEvent) {
    // The first event of a (new or resumed) run starts a FRESH card, so a continuation
    // appends BELOW the retained previous transcript instead of merging into it.
    const forceNew = (e.type === "step" || e.type === "block" || e.type === "block_live")
      && newRunRef.current;
    if (forceNew) newRunRef.current = false;

    if (e.type === "step") {
      setTranscript((t) =>
        !forceNew && t.length && t[t.length - 1].node === e.node
          ? t : [...t, { node: e.node, blocks: [] }]);
      setArtRefresh((n) => n + 1);   // each step likely wrote files → refresh the shelf
    } else if (e.type === "block") {
      // IMMUTABLE update — never mutate the previous state.
      setTranscript((t) => {
        const block = { kind: e.kind, payload: e.payload } as Block;
        const last = t[t.length - 1];
        if (forceNew || !last || last.node !== e.node) {
          return [...t, { node: e.node, blocks: [block] }];
        }
        const updated = { ...last, blocks: [...last.blocks, block] };
        return [...t.slice(0, -1), updated];
      });
    } else if (e.type === "block_live") {
      // A live-updating block (librelane log tail / stage panel / LLM token stream):
      // REPLACE the block with the same slot in the current card instead of appending,
      // so a multi-hour harden shows a ticking status, not ten thousand stacked blocks.
      setTranscript((t) => {
        const block = { kind: e.kind, payload: e.payload, slot: e.slot } as Block;
        const last = t[t.length - 1];
        if (forceNew || !last || last.node !== e.node) {
          return [...t, { node: e.node, blocks: [block] }];
        }
        const i = last.blocks.findIndex((b) => b.slot === e.slot);
        const blocks = i >= 0
          ? [...last.blocks.slice(0, i), block, ...last.blocks.slice(i + 1)]
          : [...last.blocks, block];
        return [...t.slice(0, -1), { ...last, blocks }];
      });
    } else if (e.type === "trim") {
      // continue is re-running the interrupted step → remove its partial card
      setTranscript((t) => t.slice(0, -1));
    } else if (e.type === "knowledge") {
      // store changed at a meaningful event (research / fix / verified design)
      setKnowledge((k) => ({ total: e.total, by_kind: k?.by_kind || {} }));
      setArtRefresh((n) => n + 1);   // new artifacts likely landed too
    } else if (e.type === "end") {
      setRunning(false);
      setPausing(false);
      setArtRefresh((n) => n + 1);
      refreshKnowledge();
      if (chatId) api.getChat(chatId).then((d) => setMessages(d.messages || []));
    }
  }

  async function send() {
    if (!prompt.trim() || running) return;
    if (running && runId) api.pauseRun(runId);   // never run two at once in a chat
    let cid = chatId;
    if (!cid) {
      const c = await api.createChatIn(pendingProject); cid = c.id; setChatId(c.id);
      setPendingProject(null); await refreshChats(); refreshProjects();
    }

    const tmpId = "tmp-" + Date.now();
    const userMsg: Message = {
      id: tmpId, chat_id: cid!, role: "user", content: prompt,
      files: files.map((f) => ({ name: f.name, kind: f.type.includes("pdf") ? "pdf" : f.type.startsWith("image") ? "image" : "file" })),
      created_at: new Date().toISOString(),
    };
    // archive the previous turn's transcript under its message, then start a FRESH turn
    setPastRuns((p) => (runMsgId ? { ...p, [runMsgId]: transcript } : p));
    setMessages((m) => [...m, userMsg]);
    setTranscript([]);
    setRunMsgId(tmpId);
    setRunning(true);
    setPausing(false);

    const sentPrompt = prompt, sentFiles = files;
    setPrompt(""); setFiles([]); setShowConstraints(false);

    const { message, run } = await api.sendMessage(cid!, sentPrompt, sentFiles, opts);
    setMessages((m) => m.map((x) => (x.id === tmpId ? { ...x, id: message.id } : x)));
    setRunMsgId(message.id);     // anchor this turn's live transcript to the real message
    setRunId(run.id);
    refreshChats();
    newRunRef.current = true;
    unsubRef.current = api.streamRun(run.id, applyEvent);
  }

  function steer() {
    if (!prompt.trim() || !runId || !running) return;
    api.steerRun(runId, prompt.trim());   // applied as feedback to the next step
    setPrompt("");
  }

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <span className="logomark">🦌</span>
          <div className="brandtext">
            <h1>AnoaChip</h1>
            <small>prompt → SPICE → GDS · analog</small>
          </div>
          <button className="themebtn" title="Toggle light / dark"
                  onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}>
            {theme === "dark" ? "☀️" : "🌙"}
          </button>
        </div>
        <nav className="topnav">
          {NAV.map((n) => (
            <button key={n.key} className={"navbtn" + (view === n.key ? " on" : "")}
                    onClick={() => openTab(n.key)}>
              <span className="navicon">{n.icon}</span>{n.label}
            </button>
          ))}
        </nav>

        {view === "chat" && (
          <div className="chatside">
            <button className="newchat" onClick={() => newChat(null)}>＋ New chat</button>
            <div className="projbar">
              <span>Projects</span>
              <button className="ghost xs" title="New project" onClick={() => setNewProject(true)}>＋</button>
            </div>
            {newProject && (
              <div className="projnew">
                <input autoFocus value={projName} placeholder="Project name…"
                       onChange={(e) => setProjName(e.target.value)}
                       onKeyDown={(e) => { if (e.key === "Enter") addProject(); if (e.key === "Escape") setNewProject(false); }} />
                <button className="ghost xs" onClick={addProject}>✓</button>
              </div>
            )}
            <div className="chatlist">
              {projects.map((p) => {
                const inProj = chats.filter((c) => c.project_id === p.id);
                const isOpen = expanded[p.id] ?? true;
                return (
                  <div key={p.id} className="projgroup">
                    <div className="projhead" onClick={() => setExpanded((e) => ({ ...e, [p.id]: !isOpen }))}>
                      <span className="pchev">{isOpen ? "▾" : "▸"}</span>
                      <span className="picon">📁</span>
                      <span className="pname">{p.name}</span>
                      <span className="pcount">{inProj.length}</span>
                      <span className="padd" title="New chat in project"
                            onClick={(e) => { e.stopPropagation(); newChat(p.id); }}>＋</span>
                      <span className="del" title="Delete project (keeps its chats)"
                            onClick={(e) => removeProject(p.id, e)}>🗑</span>
                    </div>
                    {isOpen && inProj.map((c) => (
                      <div key={c.id} className={"chatitem inproj" + (c.id === chatId ? " active" : "")}
                           onClick={() => openChat(c.id)}>
                        <span className="ctitle">{c.title}</span>
                        <span className="del" onClick={(ev) => askDelete(c.id, ev)}>🗑</span>
                      </div>
                    ))}
                  </div>
                );
              })}
              <div className="projbar"><span>Chats</span></div>
              {chats.filter((c) => !c.project_id).map((c) => (
                <div key={c.id} className={"chatitem" + (c.id === chatId ? " active" : "")}
                     onClick={() => openChat(c.id)}>
                  <span className="ctitle">{c.title}</span>
                  <span className="del" title="Delete chat + its design from DB & object storage"
                        onClick={(ev) => askDelete(c.id, ev)}>🗑</span>
                </div>
              ))}
            </div>
          </div>
        )}
        <div className={"kbadge clickable" + (view === "knowledge" ? " active" : "")}
             title="Browse / search / edit the knowledge store (Postgres + MinIO)"
             onClick={() => setView((v) => (v === "knowledge" ? "chat" : "knowledge"))}>
          🗄️ Knowledge store: <b>{knowledge?.total ?? "…"}</b> items
          <span className="kbadge-cta">{view === "knowledge" ? "← back to chat" : "manage →"}</span>
        </div>
      </aside>

      <main className="main">
        {view === "knowledge" ? <KnowledgePanel /> :
         view === "ips" ? <IPLibrary onSimulate={(id) => { setSeedIP(id); setView("sim"); }} /> :
         view === "sim" ? <Simulation seedIP={seedIP} /> :
         view === "studio" ? <ChipStudio /> : <>
        <div className="topbar">
          <span className="title">{chats.find((c) => c.id === chatId)?.title || "New chat"}</span>
          {models.length ? (
            <select className="modelpick" title="Ollama model — runs the next message (☁ = cloud, runs on Ollama's servers; stronger for hard designs)"
                    value={opts.model || ""} onChange={(e) => setOpt("model", e.target.value)}>
              {models.map((m) => (
                <option key={m.name} value={m.name}>
                  {m.cloud ? "☁ " : ""}{m.name}{m.parameter_size ? ` · ${m.parameter_size}` : ""}{m.cloud ? " · cloud" : ""}
                </option>
              ))}
            </select>
          ) : (
            <span className="pill">{caps?.model || "Ollama · qwen3.5:9b"}</span>
          )}
          {/* token/context shown WITH the model: a cloud model has no local context limit, so we
              show "☁ cloud" instead of a token count (the slider is hidden in constraints too). */}
          {models.find((m) => m.name === opts.model)?.cloud
            ? <span className="pill cloudpill" title="Cloud model — context handled on Ollama's servers">☁ cloud</span>
            : <span className="pill ctxpill" title="Context window (tokens) used for the next message">
                {opts.num_ctx >= 1024 ? `${Math.round(opts.num_ctx / 1024)}k` : opts.num_ctx} tok
              </span>}
          {running && <span className="running"><span className="dot" /> running…</span>}
          <span className="spacer" style={{ flex: 1 }} />
          <Artifacts chatId={chatId} refreshKey={artRefresh} />
        </div>

        <div className="stream" ref={streamRef} onScroll={onStreamScroll}>
          {messages.length === 0 && transcript.length === 0 ? (
            <div className="empty">
              <h2>Describe the analog circuit to build</h2>
              <p>e.g. “a cascode current mirror with a 10 µA reference”, or “a 5T-OTA with 40 dB gain and 1 MHz bandwidth”.<br />
                 Attach a spec PDF or a schematic, and watch it go from prompt → SPICE netlist → GDS (DRC + LVS).</p>
            </div>
          ) : null}

          {/* proper chat alternation: each user turn, then ITS assistant response */}
          {messages.map((m) => {
            if (m.role !== "user") {
              // assistant conclusion / pause / crash note
              return (
                <div key={m.id} className="msg assistant">
                  <div className="avatar">🦌</div>
                  <div className="body"><div className="final"><ReactMarkdown>{m.content}</ReactMarkdown></div></div>
                </div>
              );
            }
            const turn = m.id === runMsgId ? transcript : (pastRuns[m.id] || []);
            const live = m.id === runMsgId && running;
            return (
              <Fragment key={m.id}>
                <div className="msg user">
                  <div className="avatar">🧑</div>
                  <div className="body">
                    <div className="who">You
                      {!running && (
                        <span className="msgactions">
                          <button title="Edit this message" onClick={(e) => editMessage(m.id, m.content, e)}>✎</button>
                          <button title="Delete this message + its run" onClick={(e) => deleteMessage(m.id, e)}>🗑</button>
                        </span>
                      )}
                    </div>
                    <div>{m.content}</div>
                    {m.files?.length ? (
                      <div className="files">
                        {m.files.map((f, i) => (
                          <span key={i} className="chip">{f.kind === "image" ? "🖼️" : f.kind === "pdf" ? "📄" : "📎"} {f.name}</span>
                        ))}
                      </div>
                    ) : null}
                  </div>
                </div>
                {turn.length > 0 && (
                  <div className="msg assistant">
                    <div className="avatar">🦌</div>
                    <div className="body">
                      <div className="who">
                        AnoaChip{live && <BusyTag />}
                      </div>
                      <TurnView turn={turn} live={live} runId={runId} />
                    </div>
                  </div>
                )}
              </Fragment>
            );
          })}
        </div>

        <div className="composer">
          {showConstraints && (
            <ConstraintsPanel opts={opts} setOpt={setOpt} caps={caps}
                              cloud={!!models.find((m) => m.name === opts.model)?.cloud}
                              onClose={() => setShowConstraints(false)} />
          )}
          <div className="box">
            {files.length > 0 && (
              <div className="attachments">
                {files.map((f, i) => (
                  <span key={i} className="chip">
                    {f.type.startsWith("image") ? "🖼️" : f.type.includes("pdf") ? "📄" : "📎"} {f.name}
                    <span style={{ cursor: "pointer", marginLeft: 6 }}
                          onClick={() => setFiles(files.filter((_, k) => k !== i))}>✕</span>
                  </span>
                ))}
              </div>
            )}
            <textarea
              value={prompt}
              placeholder={running ? "Steer the agent — applied at the next step (Enter to send)…"
                                   : "Describe the analog circuit, or steer the run…"}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); running ? steer() : send(); }
              }}
            />
            <div className="row">
              <label className="iconbtn" title="Attach image / PDF / spec">
                📎 Attach
                <input type="file" multiple accept="image/*,.pdf,.txt,.md,.v,.vh,.csv,.json"
                       style={{ display: "none" }}
                       onChange={(e) => setFiles([...files, ...Array.from(e.target.files || [])])} />
              </label>
              <button className={"iconbtn" + (showConstraints ? " active" : "")}
                      onClick={() => setShowConstraints((s) => !s)} title="Build constraints">
                ⚙️ Constraints
              </button>
              <span className="constsum">
                {opts.sim_types.map((s) => s.toUpperCase()).join("·") || "—"}
                {opts.gain_db != null ? ` · ${opts.gain_db}dB` : ""}
                {opts.bw_hz != null ? ` · ${fmtHz(opts.bw_hz)}` : ""}
                {" · "}{opts.run_harden ? "GDS+DRC/LVS" : "spec-only"}
              </span>
              <span className="spacer" />
              {running ? (
                <>
                  <button className="iconbtn-round" disabled={!prompt.trim()} onClick={steer}
                          title="Send a steering message — applied at the next step">↑</button>
                  <button className="iconbtn-round stop"
                          onClick={() => {
                            if (runId) api.pauseRun(runId);  // tell backend to stop (kills subprocess)
                            unsubRef.current?.();             // detach the stream now
                            setRunning(false);                // UI is free immediately
                          }}
                          title="Stop (state saved — say 'continue' to resume)">
                    <span className="sq" />
                  </button>
                </>
              ) : (
                <button className="iconbtn-round" disabled={!prompt.trim()} onClick={send}
                        title="Send">↑</button>
              )}
            </div>
          </div>
        </div>
        </>}
      </main>

      {confirmDelete && (
        <div className="modal-overlay" onClick={() => setConfirmDelete(null)}>
          <div className="confirm-box" onClick={(e) => e.stopPropagation()}>
            <div className="confirm-icon">🗑</div>
            <div className="confirm-title">Delete this chat?</div>
            <div className="confirm-msg">
              This permanently removes the chat and its design from the database and object
              storage. This can’t be undone.
            </div>
            <div className="confirm-actions">
              <button className="btn-ghost" onClick={() => setConfirmDelete(null)}>Cancel</button>
              <button className="btn-danger" onClick={doDelete}>Delete</button>
            </div>
          </div>
        </div>
      )}

      {confirmMsg && (
        <div className="modal-overlay" onClick={() => setConfirmMsg(null)}>
          <div className="confirm-box" onClick={(e) => e.stopPropagation()}>
            <div className="confirm-icon">🗑</div>
            <div className="confirm-title">Delete this message?</div>
            <div className="confirm-msg">
              Removes this message and its run. Your design files are kept unless this run was their
              only owner. This can’t be undone.
            </div>
            <div className="confirm-actions">
              <button className="btn-ghost" onClick={() => setConfirmMsg(null)}>Cancel</button>
              <button className="btn-danger" onClick={doDeleteMessage}>Delete</button>
            </div>
          </div>
        </div>
      )}

      {editTarget && (
        <div className="modal-overlay" onClick={() => setEditTarget(null)}>
          <div className="edit-box" onClick={(e) => e.stopPropagation()}>
            <div className="edit-title">Edit message</div>
            <textarea
              className="edit-area"
              value={editText}
              autoFocus
              rows={4}
              onChange={(e) => setEditText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) saveEdit();
                if (e.key === "Escape") setEditTarget(null);
              }}
            />
            <div className="confirm-actions">
              <button className="btn-ghost" onClick={() => setEditTarget(null)}>Cancel</button>
              <button className="btn-primary" onClick={saveEdit}>Save</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function titleFor(node: TranscriptRecord): string {
  const header = node.blocks.find((b) => b.kind === "header");
  if (header) return String(header.payload[1] ?? node.node);
  return node.node;
}

function ConstraintsPanel({ opts, setOpt, caps, cloud, onClose }: {
  opts: RunConstraints;
  setOpt: <K extends keyof RunConstraints>(k: K, v: RunConstraints[K]) => void;
  caps: SystemCaps | null;
  cloud?: boolean;
  onClose: () => void;
}) {
  const ctxMin = caps?.num_ctx_min ?? 2048;
  const ctxMax = caps?.num_ctx_max ?? 32768;
  const ctxStep = caps?.num_ctx_step ?? 2048;
  const asK = (n: number) => (n >= 1024 ? `${Math.round(n / 1024)}k` : `${n}`);
  return (
    <div className="constraints">
      <div className="chead">
        <span>⚙️ Build constraints</span>
        <span className="x" onClick={onClose}>✕</span>
      </div>
      <div className="cgrid">
        <label>Gain (dB) <span className="opt">optional</span>
          <input type="number" step={1} placeholder="e.g. 40"
                 value={opts.gain_db ?? ""}
                 onChange={(e) => setOpt("gain_db", e.target.value === "" ? null : Number(e.target.value))} />
        </label>
        <label>Bandwidth (Hz) <span className="opt">optional</span>
          <input type="number" step="any" placeholder="e.g. 1e6"
                 value={opts.bw_hz ?? ""}
                 onChange={(e) => setOpt("bw_hz", e.target.value === "" ? null : Number(e.target.value))} />
        </label>
        <label className="simpick">Simulation
          <span className="simboxes">
            {(["dc", "ac", "tran"] as const).map((s) => {
              const on = opts.sim_types.includes(s);
              return (
                <label key={s} className="simbox">
                  <input type="checkbox" checked={on}
                         onChange={() => {
                           const cur = opts.sim_types;
                           const next = on ? cur.filter((x) => x !== s) : [...cur, s];
                           setOpt("sim_types", next.length ? next : cur);
                         }} /> {s.toUpperCase()}
                </label>
              );
            })}
          </span>
          <span className="hint">pick any — DC, AC, TRAN (or all three)</span>
        </label>
        {cloud ? (
          <label className="ctxwin">Context window
            <span className="val">☁ cloud</span>
            <span className="hint">handled on Ollama's servers — no local limit to set</span>
          </label>
        ) : (
          <label className="ctxwin">Context window
            <input type="range" min={ctxMin} max={ctxMax} step={ctxStep}
                   value={Math.min(opts.num_ctx, ctxMax)}
                   onChange={(e) => setOpt("num_ctx", Number(e.target.value))} />
            <span className="val">{asK(opts.num_ctx)} tok</span>
            <span className="hint">
              max {asK(ctxMax)}
              {caps ? ` · ${caps.device === "cuda" ? `${caps.total_gb} GB VRAM` : `${caps.total_gb} GB RAM (CPU)`}` : ""}
            </span>
          </label>
        )}
      </div>
      <div className="ctoggles">
        <label><input type="checkbox" checked={opts.use_web}
                      onChange={(e) => setOpt("use_web", e.target.checked)} /> Web research</label>
        <label><input type="checkbox" checked={opts.deep_steps}
                      onChange={(e) => setOpt("deep_steps", e.target.checked)} /> RLM deep agents</label>
        <label><input type="checkbox" checked={opts.run_harden}
                      onChange={(e) => setOpt("run_harden", e.target.checked)} /> Layout (Glayout GDS · DRC · LVS)</label>
      </div>
    </div>
  );
}
