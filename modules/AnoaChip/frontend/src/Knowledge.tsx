import { useCallback, useEffect, useState } from "react";

// Knowledge-store browser: view / search / add / delete the Postgres rows (semantic
// recall over pgvector) AND the MinIO objects (the raw blobs behind the rows).

interface Item {
  id: string;
  kind: string;
  design?: string;
  title?: string;
  source?: string;
  text?: string;
  object_key?: string | null;
  has_vector?: boolean;
  score?: number;
  created_at?: string;
}
interface Obj { key: string; size: number; }

const KINDS = ["", "fix", "design", "code", "reference", "paper", "note", "gds", "image", "pdf"];

export function KnowledgePanel() {
  const [tab, setTab] = useState<"rows" | "objects">("rows");
  const [items, setItems] = useState<Item[]>([]);
  const [objects, setObjects] = useState<Obj[]>([]);
  const [kind, setKind] = useState("");
  const [q, setQ] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [loading, setLoading] = useState(false);
  const [sel, setSel] = useState<Item | null>(null);
  const [stats, setStats] = useState<{ total: number; by_kind?: Record<string, number> } | null>(null);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ kind: "note", title: "", design: "", tags: "", text: "" });

  const loadStats = useCallback(async () => {
    try { setStats(await (await fetch("/api/knowledge/stats")).json()); } catch { /* ignore */ }
  }, []);

  const loadRows = useCallback(async () => {
    setLoading(true);
    try {
      const p = new URLSearchParams();
      if (kind) p.set("kind", kind);
      if (q.trim()) p.set("q", q.trim());
      p.set("limit", "300");
      const r = await (await fetch(`/api/knowledge/items?${p}`)).json();
      setItems(r.items || []);
      setEnabled(r.enabled !== false);
    } finally { setLoading(false); }
  }, [kind, q]);

  const loadObjects = useCallback(async () => {
    setLoading(true);
    try {
      const r = await (await fetch("/api/knowledge/objects")).json();
      setObjects(r.objects || []);
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { loadStats(); }, [loadStats]);
  useEffect(() => { if (tab === "rows") loadRows(); else loadObjects(); }, [tab, loadRows, loadObjects]);

  async function openItem(id: string) {
    try { setSel(await (await fetch(`/api/knowledge/item/${id}`)).json()); } catch { /* ignore */ }
  }
  async function del(id: string) {
    if (!confirm("Delete this knowledge item (row + its MinIO blob)?")) return;
    await fetch(`/api/knowledge/item/${id}`, { method: "DELETE" });
    setSel(null); loadRows(); loadStats();
  }
  async function delKind() {
    if (!kind) { alert("Pick a kind filter first (this bulk-deletes that kind)."); return; }
    if (!confirm(`Delete ALL '${kind}' items? This cannot be undone.`)) return;
    await fetch(`/api/knowledge/items?kind=${encodeURIComponent(kind)}`, { method: "DELETE" });
    loadRows(); loadStats();
  }
  async function add() {
    if (!form.text.trim()) { alert("Text is required."); return; }
    const r = await fetch("/api/knowledge/items", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(form),
    });
    if (r.ok) { setAdding(false); setForm({ kind: "note", title: "", design: "", tags: "", text: "" }); loadRows(); loadStats(); }
    else alert("Add failed (is the knowledge store up? `docker compose up -d`).");
  }

  const kib = (n: number) => (n < 1024 ? `${n} B` : `${(n / 1024).toFixed(1)} KB`);

  return (
    <div className="kpanel">
      <div className="khead">
        <h2>🗄️ Knowledge store</h2>
        <span className="kstat">
          {stats ? <><b>{stats.total}</b> items</> : "…"}
          {stats?.by_kind && Object.entries(stats.by_kind).map(([k, v]) => (
            <span key={k} className="kchip" onClick={() => { setTab("rows"); setKind(k); }}>{k}:{v}</span>
          ))}
        </span>
        <span style={{ flex: 1 }} />
        <button className={"ktab" + (tab === "rows" ? " on" : "")} onClick={() => setTab("rows")}>Postgres rows</button>
        <button className={"ktab" + (tab === "objects" ? " on" : "")} onClick={() => setTab("objects")}>MinIO objects</button>
      </div>

      {!enabled && <div className="kwarn">Knowledge store offline — run <code>docker compose up -d</code> (Postgres + MinIO).</div>}

      {tab === "rows" && (
        <>
          <div className="ktoolbar">
            <input className="ksearch" placeholder="🔎 semantic search (pgvector)…" value={q}
                   onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && loadRows()} />
            <select value={kind} onChange={(e) => setKind(e.target.value)}>
              {KINDS.map((k) => <option key={k} value={k}>{k || "all kinds"}</option>)}
            </select>
            <button onClick={loadRows}>Search</button>
            <button onClick={() => { setQ(""); setKind(""); }}>Clear</button>
            <span style={{ flex: 1 }} />
            <button className="kadd" onClick={() => setAdding((a) => !a)}>＋ Add</button>
            {kind && <button className="kdanger" onClick={delKind}>Delete all “{kind}”</button>}
          </div>

          {adding && (
            <div className="kform">
              <div className="krow">
                <select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
                  {KINDS.filter(Boolean).map((k) => <option key={k} value={k}>{k}</option>)}
                </select>
                <input placeholder="title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
                <input placeholder="design (optional)" value={form.design} onChange={(e) => setForm({ ...form, design: e.target.value })} />
                <input placeholder="tags" value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} />
              </div>
              <textarea placeholder="knowledge text (a fix, a rule, a note…) — embedded into pgvector on save"
                        value={form.text} onChange={(e) => setForm({ ...form, text: e.target.value })} />
              <div className="krow"><button className="kadd" onClick={add}>Save to DB</button>
                <button onClick={() => setAdding(false)}>Cancel</button></div>
            </div>
          )}

          <div className="ktablewrap">
            <table className="ktable">
              <thead><tr><th>kind</th><th>title</th><th>design</th><th>vec</th><th>created</th><th></th></tr></thead>
              <tbody>
                {items.map((it) => (
                  <tr key={it.id} onClick={() => openItem(it.id)} className={sel?.id === it.id ? "on" : ""}>
                    <td><span className={"tag tag-" + it.kind}>{it.kind}</span></td>
                    <td className="ktitle">{it.title || it.source || it.id}
                      {it.score != null && <span className="kscore"> {(it.score * 100).toFixed(0)}%</span>}</td>
                    <td>{it.design || "—"}</td>
                    <td>{it.has_vector ? "✓" : "—"}</td>
                    <td className="kdate">{(it.created_at || "").slice(0, 16).replace("T", " ")}</td>
                    <td><span className="del" title="Delete" onClick={(e) => { e.stopPropagation(); del(it.id); }}>🗑</span></td>
                  </tr>
                ))}
                {items.length === 0 && <tr><td colSpan={6} className="kempty">{loading ? "loading…" : "no items"}</td></tr>}
              </tbody>
            </table>
          </div>
        </>
      )}

      {tab === "objects" && (
        <div className="ktablewrap">
          <table className="ktable">
            <thead><tr><th>object key (MinIO)</th><th>size</th><th></th></tr></thead>
            <tbody>
              {objects.map((o) => (
                <tr key={o.key}>
                  <td className="kmono">{o.key}</td>
                  <td>{kib(o.size)}</td>
                  <td><a href={`/api/knowledge/object?key=${encodeURIComponent(o.key)}`} target="_blank" rel="noreferrer">open ↗</a></td>
                </tr>
              ))}
              {objects.length === 0 && <tr><td colSpan={3} className="kempty">{loading ? "loading…" : "no objects"}</td></tr>}
            </tbody>
          </table>
        </div>
      )}

      {sel && (
        <div className="kdetail" onClick={() => setSel(null)}>
          <div className="kcard" onClick={(e) => e.stopPropagation()}>
            <div className="khead">
              <span className={"tag tag-" + sel.kind}>{sel.kind}</span>
              <b>{sel.title || sel.id}</b>
              <span style={{ flex: 1 }} />
              <button className="kdanger" onClick={() => del(sel.id)}>Delete</button>
              <button onClick={() => setSel(null)}>Close</button>
            </div>
            <div className="kmeta">
              design: {sel.design || "—"} · source: {sel.source || "—"}
              {sel.object_key && <> · blob: <a href={`/api/knowledge/object?key=${encodeURIComponent(sel.object_key)}`} target="_blank" rel="noreferrer">{sel.object_key} ↗</a></>}
            </div>
            <pre className="ktext">{sel.text || "(no text)"}</pre>
          </div>
        </div>
      )}
    </div>
  );
}
