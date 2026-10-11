import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { IP, IPLibraryResponse } from "./types";

const STATUS: Record<string, { label: string; cls: string }> = {
  rtl: { label: "RTL", cls: "st-rtl" },
  sim: { label: "compiles", cls: "st-sim" },
  hardening: { label: "hardening…", cls: "st-run" },
  hardened: { label: "GDS ✓", cls: "st-gds" },
  harden_dirty: { label: "GDS (ECO)", cls: "st-run" },
  harden_failed: { label: "harden failed", cls: "st-fail" },
};

const SIM: Record<string, { label: string; cls: string } | undefined> = {
  pass: { label: "✓ TB Verified", cls: "st-verified" },
  fail: { label: "✗ TB Failed", cls: "st-fail" },
};

export function IPLibrary({ onSimulate }: { onSimulate?: (ipId: string) => void }) {
  const [lib, setLib] = useState<IPLibraryResponse | null>(null);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [sel, setSel] = useState<IP | null>(null);
  const [creating, setCreating] = useState(false);
  const [query, setQuery] = useState("");

  async function refresh() { setLib(await api.listIPs()); }
  useEffect(() => { refresh(); }, []);

  if (!lib) return <div className="tabpane"><div className="loading">Loading IP library…</div></div>;

  const q = query.trim().toLowerCase();
  const match = (m: IP) => !q || m.name.toLowerCase().includes(q) ||
    m.top.toLowerCase().includes(q) || (m.subtitle || "").toLowerCase().includes(q);
  const total = lib.ips.length;
  const gdsCount = lib.ips.filter((m) => m.status === "hardened").length;
  // include any CUSTOM category the user added (not in the fixed list) with a fallback label/icon
  const extraCats = [...new Set(lib.ips.map((m) => m.category))].filter((c) => !lib.categories.includes(c));
  const allCats = [...lib.categories, ...extraCats];
  const labelOf = (c: string) => lib.labels[c] || c.replace(/_/g, " ").replace(/\b\w/g, (x) => x.toUpperCase());
  const iconOf = (c: string) => lib.icons[c] || "📦";

  return (
    <div className="tabpane iplib">
      <div className="tabhead">
        <div>
          <h2>IP Library</h2>
          <p className="sub">{total} IPs · {gdsCount} hardened to GDS · grouped by function. Harden a block to make it placeable in Chip Studio.</p>
        </div>
        <div className="headactions">
          <input className="search" placeholder="Search IPs…" value={query} onChange={(e) => setQuery(e.target.value)} />
          <button className="btn-primary" onClick={() => setCreating(true)}>＋ Create IP</button>
        </div>
      </div>

      <div className="folders">
        {allCats.map((cat) => {
          const items = lib.ips.filter((m) => m.category === cat && match(m));
          if (!items.length) return null;
          const isOpen = open[cat] ?? true;
          return (
            <div key={cat} className="folder">
              <div className="folderhead" onClick={() => setOpen((o) => ({ ...o, [cat]: !isOpen }))}>
                <span className="fchev">{isOpen ? "▾" : "▸"}</span>
                <span className="ficon">{iconOf(cat)}</span>
                <span className="fname">{labelOf(cat)}</span>
                <span className="fcount">{items.length}</span>
              </div>
              {isOpen && (
                <div className="ipgrid">
                  {items.map((m) => (
                    <div key={m.id} className={"ipcard" + (m.status === "hardened" ? " hardened" : "")}
                         onClick={() => api.getIP(m.id).then(setSel)}>
                      <div className="ipcard-top">
                        <span className="ipname">{m.name}</span>
                        <span className="badges">
                          {m.tapeout_ready && <span className="stbadge st-verified" title="tape-out sign-off clean">🏭 Tape-out</span>}
                          {m.sim_status && SIM[m.sim_status] && <span className={"stbadge " + SIM[m.sim_status]!.cls}>{SIM[m.sim_status]!.label}</span>}
                          <span className={"stbadge " + (STATUS[m.status]?.cls || "")}>{STATUS[m.status]?.label || m.status}</span>
                        </span>
                      </div>
                      {m.subtitle && <div className="ipsub">{m.subtitle}</div>}
                      <div className="ipmeta">
                        <span title="top module" className="topmod">⌁ {m.top}</span>
                        <span title="ports">{m.ports.length} ports</span>
                        {m.lines ? <span title="lines">{m.lines} ln</span> : null}
                      </div>
                      <div className="ipports">
                        {m.ports.slice(0, 6).map((p, i) => (
                          <span key={i} className={"portchip " + p.dir}>{p.dir === "input" ? "→" : p.dir === "output" ? "←" : "↔"} {p.name}</span>
                        ))}
                        {m.ports.length > 6 && <span className="portmore">+{m.ports.length - 6}</span>}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {sel && <IPDetail ip={sel} onClose={() => setSel(null)} onChanged={refresh} onSimulate={onSimulate} />}
      {creating && <CreateIP onClose={() => setCreating(false)} categories={lib.categories} labels={lib.labels} onCreated={() => { setCreating(false); refresh(); }} />}
    </div>
  );
}

function IPDetail({ ip, onClose, onChanged, onSimulate }: {
  ip: IP; onClose: () => void; onChanged: () => void; onSimulate?: (id: string) => void;
}) {
  const [log, setLog] = useState<string[]>([]);
  const [hardening, setHardening] = useState(ip.status === "hardening");
  const [activeFile, setActiveFile] = useState(ip.rtl[0] || "");
  const [simLog, setSimLog] = useState(ip.sim_log || "");
  const [simStatus, setSimStatus] = useState(ip.sim_status || "untested");
  const [verifying, setVerifying] = useState(false);
  const unsub = useRef<() => void>();
  useEffect(() => () => unsub.current?.(), []);

  async function verify() {
    setVerifying(true);
    try { const r = await api.simulateIP(ip.id); setSimStatus(r.status as any); setSimLog(r.log); onChanged(); }
    finally { setVerifying(false); }
  }

  async function harden() {
    setHardening(true); setLog(["⚙️ starting LibreLane (gf180)…"]);
    const { job_id } = await api.hardenIP(ip.id, { core_util: 40, clock_period: 20 });
    unsub.current = api.streamJob(job_id, (e) => {
      if (e.type === "log") setLog((l) => [...l, e.text]);
      else if (e.type === "end") { setHardening(false); onChanged(); }
    });
  }

  const m = ip.metrics || {};
  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div className="drawer" onClick={(e) => e.stopPropagation()}>
        <div className="drawerhead">
          <div>
            <h3>{ip.name}</h3>
            <span className="dsub">{ip.subtitle || ip.top} · <code>{ip.category}</code></span>
          </div>
          <button className="x" onClick={onClose}>✕</button>
        </div>

        <div className="drawerbody">
          <div className="dsec">
            <div className="dseclabel">Ports ({ip.ports.length})</div>
            <div className="portlist">
              {ip.ports.map((p, i) => (
                <span key={i} className={"portchip " + p.dir}>
                  <b>{p.dir === "input" ? "IN" : p.dir === "output" ? "OUT" : "IO"}</b> {p.name}{p.width && <em>{p.width}</em>}
                </span>
              ))}
            </div>
          </div>

          {ip.status === "hardened" && (
            <div className="dsec metrics">
              <div className="dseclabel">GDS metrics</div>
              <div className="metricgrid">
                {m.die_area_um2 != null && <div><b>{Math.round(m.die_area_um2).toLocaleString()}</b><span>die µm²</span></div>}
                {m.cell_count != null && <div><b>{Math.round(m.cell_count).toLocaleString()}</b><span>cells</span></div>}
                {m.util_pct != null && <div><b>{(m.util_pct * 100).toFixed(0)}%</b><span>util</span></div>}
                {m.power_mw != null && <div><b>{m.power_mw.toFixed(2)}</b><span>mW</span></div>}
              </div>
              {ip.png && <img className="gdsimg" src={api.ipFileUrl(ip.id, ip.png)} alt="layout" />}
              {ip.gds && <a className="btn-ghost dl" href={api.ipFileUrl(ip.id, ip.gds)} download>⬇ download {ip.gds}</a>}
            </div>
          )}

          {ip.tb && ip.tb.length > 0 && (
            <div className="dsec">
              <div className="dseclabel">Verification
                <span className={"stbadge inline " + (simStatus === "pass" ? "st-verified" : simStatus === "fail" ? "st-fail" : "st-rtl")}>
                  {simStatus === "pass" ? "✓ TB Verified" : simStatus === "fail" ? "✗ TB Failed" : "untested"}
                </span>
                <button className="btn-ghost sm vbtn" disabled={verifying} onClick={verify}>
                  {verifying ? "running…" : "▶ Run testbench"}
                </button>
              </div>
              {simLog && <pre className="joblog"><code>{simLog}</code></pre>}
            </div>
          )}

          <div className="dsec">
            <div className="dseclabel">RTL</div>
            <div className="filetabs">
              {ip.rtl.map((f) => (
                <button key={f} className={"ftab" + (f === activeFile ? " on" : "")} onClick={() => setActiveFile(f)}>{f}</button>
              ))}
            </div>
            <pre className="codeview"><code>{ip.files?.[activeFile] || "(file)"}</code></pre>
          </div>

          {(hardening || log.length > 0) && (
            <div className="dsec">
              <div className="dseclabel">Harden log</div>
              <pre className="joblog"><code>{log.join("\n")}</code></pre>
            </div>
          )}
        </div>

        <div className="draweractions">
          {onSimulate && <button className="btn-ghost" onClick={() => onSimulate(ip.id)}>🔬 Simulate</button>}
          <span className="spacer" />
          {ip.status !== "hardened" && (
            <button className="btn-primary" disabled={hardening} onClick={harden}>
              {hardening ? "Hardening…" : "🏭 Harden to GDS"}
            </button>
          )}
          <button className="btn-danger" onClick={async () => { await api.deleteIP(ip.id); onChanged(); onClose(); }}>Delete</button>
        </div>
      </div>
    </div>
  );
}

function CreateIP({ onClose, onCreated, categories, labels }: {
  onClose: () => void; onCreated: () => void; categories: string[]; labels: Record<string, string>;
}) {
  const [name, setName] = useState("");
  const [category, setCategory] = useState("");
  const [newCat, setNewCat] = useState("");      // custom category when category === "__new__"
  const [subtitle, setSubtitle] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [mods, setMods] = useState<string[]>([]);  // module names parsed from the uploaded files
  const [top, setTop] = useState("");              // chosen top ("" = auto-detect)
  const [busy, setBusy] = useState(false);

  // parse `module <name>` from every uploaded file so the user can pick the right top
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const names: string[] = [];
      for (const f of files) {
        try {
          const t = await f.text();
          for (const m of t.matchAll(/\bmodule\s+([A-Za-z_]\w*)/g)) names.push(m[1]);
        } catch { /* */ }
      }
      if (!cancelled) {
        const uniq = [...new Set(names)];
        setMods(uniq);
        if (top && !uniq.includes(top)) setTop("");
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [files]);

  async function submit() {
    if (!name.trim() || !files.length) return;
    setBusy(true);
    const cat = category === "__new__" ? newCat.trim() : category;
    try { await api.createIP(name.trim(), cat, subtitle.trim(), files, top); onCreated(); }
    finally { setBusy(false); }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card wide" onClick={(e) => e.stopPropagation()}>
        <div className="modalhead"><h3>Create IP from RTL</h3><button className="x" onClick={onClose}>✕</button></div>
        <p className="modalhint">Upload Verilog/SystemVerilog files. Pick the top module (so it's never wrong) and a category — or add your own. Harden it afterward to produce a GDS macro for Chip Studio.</p>
        <div className="formgrid">
          <label>Name<input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. AXI-Lite UART" autoFocus /></label>
          <label>Category
            <select value={category} onChange={(e) => setCategory(e.target.value)}>
              <option value="">auto-detect</option>
              {categories.map((c) => <option key={c} value={c}>{labels[c] || c}</option>)}
              <option value="__new__">＋ Add new category…</option>
            </select>
          </label>
          {category === "__new__" && (
            <label>New category<input value={newCat} autoFocus placeholder="e.g. Sensor Interface"
                   onChange={(e) => setNewCat(e.target.value)} /></label>
          )}
          <label>Top module
            <select value={top} onChange={(e) => setTop(e.target.value)} disabled={!mods.length}>
              <option value="">{mods.length ? "auto-detect" : "add files first"}</option>
              {mods.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </label>
          <label className="full">Description<input value={subtitle} onChange={(e) => setSubtitle(e.target.value)} placeholder="one-line summary (optional)" /></label>
        </div>
        <label className="dropzone full">
          <input type="file" multiple accept=".v,.sv,.vh,.svh" style={{ display: "none" }}
                 onChange={(e) => setFiles([...files, ...Array.from(e.target.files || [])])} />
          {files.length ? <div className="filechips">{files.map((f, i) => (
            <span key={i} className="chip">📄 {f.name}<span className="rm" onClick={(ev) => { ev.preventDefault(); setFiles(files.filter((_, k) => k !== i)); }}>✕</span></span>
          ))}</div> : <span>＋ Click to add .v / .sv files</span>}
        </label>
        {mods.length > 0 && <div className="modnote">{mods.length} module(s) found: {mods.slice(0, 8).join(", ")}{mods.length > 8 ? "…" : ""}</div>}
        <div className="confirm-actions">
          <button className="btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={busy || !name.trim() || !files.length} onClick={submit}>
            {busy ? "Creating…" : "Create IP"}
          </button>
        </div>
      </div>
    </div>
  );
}
