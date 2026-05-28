import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { api } from "./api.js";
import { initialRun, runReducer, fromSession } from "./runState.js";
import PromptView from "./components/PromptView.jsx";
import StudioView from "./components/StudioView.jsx";
import Sidebar from "./components/Sidebar.jsx";

const COLL_META = [
  ["glayout_knowledge", "glayout knowledge"],
  ["rf_theory", "rf theory"],
  ["error_feedback", "error feedback"],
];

export default function App() {
  const [tab, setTab] = useState("prompt");
  const [prompt, setPrompt] = useState("");
  const [run, dispatch] = useReducer(runReducer, initialRun);
  const [running, setRunning] = useState(false);
  const [counts, setCounts] = useState({});
  const [health, setHealth] = useState({ cls: "", title: "checking…" });
  const [sessions, setSessions] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const esRef = useRef(null);
  const jobRef = useRef(null);

  const refreshCollections = useCallback(() => {
    api.collections().then(setCounts).catch(() => {});
  }, []);
  const loadHistory = useCallback(() => {
    api
      .history()
      .then((d) => setSessions(d.sessions || []))
      .catch(() => {});
  }, []);

  const pollHealth = useCallback(async () => {
    try {
      const h = await api.health();
      const ok = h.status === "ok";
      setHealth({
        cls: ok ? "ok" : "degraded",
        title: ok
          ? `healthy · ollama ${h.ollama?.up ? "up" : "down"}`
          : `degraded · ${h.ollama?.up ? "" : "ollama down"} ${h.collections_error || ""}`.trim(),
      });
    } catch {
      setHealth({ cls: "down", title: "backend unreachable" });
    }
  }, []);

  useEffect(() => {
    refreshCollections();
    loadHistory();
    pollHealth();
    const t = setInterval(pollHealth, 15000);
    return () => clearInterval(t);
  }, [refreshCollections, loadHistory, pollHealth]);

  function finish() {
    if (esRef.current) esRef.current.close();
    esRef.current = null;
    setRunning(false);
    jobRef.current = null;
    refreshCollections();
    loadHistory();
  }

  async function onSubmit() {
    const p = prompt.trim();
    if (!p || running) return;
    dispatch({ type: "reset" });
    dispatch({ type: "verdict", cls: "idle", text: "running…" });
    setActiveId(null);
    setRunning(true);

    let job;
    try {
      job = await api.run(p);
    } catch (err) {
      dispatch({
        type: "verdict",
        cls: "fail",
        text: err.rejected ? "rejected: " + err.message : "could not reach backend",
      });
      setRunning(false);
      return;
    }

    jobRef.current = job.job_id;
    setActiveId(job.job_id);
    loadHistory(); // run is saved immediately → show it now

    const es = api.stream(job.job_id);
    esRef.current = es;
    es.onmessage = (m) => {
      try {
        dispatch({ type: "event", ev: JSON.parse(m.data) });
      } catch {
        /* ignore malformed frame */
      }
    };
    es.addEventListener("end", finish);
    es.onerror = finish;
  }

  async function onStop() {
    if (!jobRef.current) return;
    try {
      await api.cancel(jobRef.current);
    } catch {
      /* best effort */
    }
  }

  async function onRestore(id) {
    try {
      const s = await api.session(id);
      setPrompt(s.prompt || "");
      setActiveId(id);
      setTab("prompt");
      dispatch({ type: "set", patch: fromSession(s) });
    } catch {
      /* ignore */
    }
  }

  function onNew() {
    setPrompt("");
    setActiveId(null);
    setTab("prompt");
    dispatch({ type: "new" });
  }

  return (
    <>
      <header className="topbar">
        <div className="brand">
          <span className="logo">◳</span>
          <div>
            <h1>
              Gelochip <span className="accent">Studio</span>
            </h1>
            <p className="tagline">
              Kaizen RAG · gf180 RF/mmWave · plan · retrieve · generate · DRC · self-correct
            </p>
          </div>
        </div>
        <nav className="tabs">
          <button
            className={"tab" + (tab === "prompt" ? " active" : "")}
            onClick={() => setTab("prompt")}
          >
            Prompt → GDSII
          </button>
          <button
            className={"tab" + (tab === "studio" ? " active" : "")}
            onClick={() => setTab("studio")}
          >
            Chip Studio
          </button>
          <span className={"health-dot " + health.cls} title={health.title}>
            ●
          </span>
        </nav>
        <div className="collections">
          {COLL_META.map(([name, label]) => (
            <div className="coll" key={name}>
              <span className="n">
                {counts[name] != null ? counts[name].toLocaleString() : "–"}
              </span>
              <label>{label}</label>
            </div>
          ))}
        </div>
      </header>

      <div className="app-body">
        <Sidebar
          sessions={sessions}
          activeId={activeId}
          onNew={onNew}
          onRefresh={loadHistory}
          onRestore={onRestore}
        />
        <div className="content">
          {tab === "prompt" ? (
            <PromptView
              run={run}
              running={running}
              prompt={prompt}
              setPrompt={setPrompt}
              onSubmit={onSubmit}
              onStop={onStop}
            />
          ) : (
            <StudioView />
          )}
        </div>
      </div>
    </>
  );
}
