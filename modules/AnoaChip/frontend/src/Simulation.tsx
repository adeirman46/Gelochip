import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { WaveformView } from "./Waveform";
import type { SimResult, SimWorkspace, SimWorkspaceMeta } from "./types";

export function Simulation({ seedIP }: { seedIP?: string | null }) {
  const [list, setList] = useState<SimWorkspaceMeta[]>([]);
  const [ws, setWs] = useState<SimWorkspace | null>(null);
  const [active, setActive] = useState<string>("");
  const [draft, setDraft] = useState<string>("");
  const [dirty, setDirty] = useState(false);
  const [result, setResult] = useState<SimResult | null>(null);
  const [running, setRunning] = useState(false);
  const [tab, setTab] = useState<"log" | "wave">("wave");
  const seeded = useRef<string | null>(null);

  async function refreshList() { setList(await api.listWorkspaces()); }
  useEffect(() => { refreshList(); }, []);

  // open a workspace seeded from an IP (from the IP tab's "Simulate" button), once
  useEffect(() => {
    if (seedIP && seeded.current !== seedIP) {
      seeded.current = seedIP;
      api.createWorkspace(undefined, seedIP).then((w) => { refreshList(); openWs(w.id); });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seedIP]);

  async function openWs(id: string) {
    const w = await api.getWorkspace(id);
    // a stale id (server restarted / workspace deleted) returns {detail} with no files —
    // drop the selection and refresh the list instead of opening an empty, broken editor.
    if (!w || !w.id || !w.files) {
      setWs(null); refreshList();
      return;
    }
    setWs(w); setResult(null);
    const first = Object.keys(w.files)[0] || "";
    setActive(first); setDraft(w.files[first] || ""); setDirty(false);
  }

  function selectFile(name: string) {
    if (!ws) return;
    setActive(name); setDraft(ws.files[name] || ""); setDirty(false);
  }

  async function save() {
    if (!ws || !active) return;
    await api.saveFile(ws.id, active, draft);
    setWs({ ...ws, files: { ...ws.files, [active]: draft } });
    setDirty(false);
  }

  async function run() {
    if (!ws) return;
    if (dirty) await save();
    setRunning(true); setResult(null);
    try {
      const r = await api.runSim(ws.id);
      setResult(r);
      // workspace vanished server-side (stale id after a restart / deletion): re-sync the list
      // and reopen the same workspace by id if it still exists, so the next Run targets a real one.
      if (r.gone) {
        const fresh = await api.listWorkspaces();
        setList(fresh);
        if (fresh.some((w) => w.id === ws.id)) { await openWs(ws.id); }
        else { setWs(null); }
        setTab("log");
        return;
      }
      setTab(r.waveform && r.waveform.signals.length ? "wave" : "log");
    } finally { setRunning(false); }
  }

  async function onUpload(files: File[]) {
    if (!ws || !files.length) return;
    const w2 = await api.uploadToWorkspace(ws.id, files);
    setWs(w2); refreshList();
    const f = Object.keys(w2.files); if (f.length && !active) selectFile(f[0]);
  }

  async function newWs() {
    const w = await api.createWorkspace("Simulation " + (list.length + 1));
    await refreshList(); openWs(w.id);
  }

  return (
    <div className="tabpane sim">
      <aside className="sim-rail">
        <button className="btn-primary full" onClick={newWs}>＋ New simulation</button>
        <div className="raillabel">Workspaces</div>
        <div className="wslist">
          {list.map((w) => (
            <div key={w.id} className={"wsitem" + (ws?.id === w.id ? " on" : "")} onClick={() => openWs(w.id)}>
              <span className="wsname">{w.name}</span>
              <span className="wsfiles">{w.files}</span>
              <span className="del" onClick={async (e) => { e.stopPropagation(); await api.deleteWorkspace(w.id); if (ws?.id === w.id) setWs(null); refreshList(); }}>🗑</span>
            </div>
          ))}
          {!list.length && <div className="placeholder">No simulations yet.</div>}
        </div>
      </aside>

      {!ws ? (
        <div className="sim-empty">
          <h2>Simulation</h2>
          <p>Create a workspace, upload your RTL + testbench, edit them inline, then run Icarus Verilog and watch the waveform. Add <code>$dumpfile("design.vcd"); $dumpvars(0, tb);</code> to your testbench to capture signals.</p>
          <button className="btn-primary" onClick={newWs}>＋ New simulation</button>
        </div>
      ) : (
        <div className="sim-main">
          <div className="sim-files">
            <div className="filetabs">
              {Object.keys(ws.files).map((f) => (
                <button key={f} className={"ftab" + (f === active ? " on" : "")} onClick={() => selectFile(f)}>
                  {f}{f === active && dirty ? " •" : ""}
                </button>
              ))}
              <label className="ftab add" title="Upload files">＋
                <input type="file" multiple accept=".v,.sv,.vh,.svh" style={{ display: "none" }}
                       onChange={(e) => onUpload(Array.from(e.target.files || []))} />
              </label>
            </div>
            <div className="editorwrap">
              <textarea className="editor" value={draft} spellCheck={false}
                        onChange={(e) => { setDraft(e.target.value); setDirty(true); }}
                        onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === "s") { e.preventDefault(); save(); } }}
                        placeholder="// upload or write Verilog here" />
            </div>
            <div className="sim-toolbar">
              <button className="btn-ghost" disabled={!dirty} onClick={save}>💾 Save{dirty ? " *" : ""}</button>
              <span className="spacer" />
              <button className="btn-primary" disabled={running} onClick={run}>{running ? "Running…" : "▶ Run iverilog"}</button>
            </div>
          </div>

          <div className="sim-output">
            <div className="outtabs">
              <button className={tab === "wave" ? "on" : ""} onClick={() => setTab("wave")}>Waveform</button>
              <button className={tab === "log" ? "on" : ""} onClick={() => setTab("log")}>Log</button>
              {result && <span className={"runverdict " + (result.compiled ? (result.ok ? "ok" : "warn") : "bad")}>
                {result.gone ? "⚠ workspace reloaded"
                  : result.compiled ? (result.vcd ? "✓ simulated" : "compiled") : "✗ compile error"}
              </span>}
            </div>
            <div className="outbody">
              {!result && <div className="placeholder">Run a simulation to see the waveform + log.</div>}
              {result && tab === "wave" && (result.waveform && result.waveform.signals.length
                ? <WaveformView wave={result.waveform} />
                : <div className="placeholder">{result.hint || "No waveform — add $dumpfile/$dumpvars to your testbench."}</div>)}
              {result && tab === "log" && <pre className="joblog"><code>{result.log || (result as any).detail || "(no output)"}</code></pre>}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
