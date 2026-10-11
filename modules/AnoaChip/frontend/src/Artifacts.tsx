import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";

interface Art { name: string; path: string; kind: string; size: number; }
interface Ver { v: number; id: string; label: string; when: number; files: number; adds: number; dels: number; }
interface VerFile { path: string; adds: number; dels: number; }

/** GitHub-style unified diff, colored +green / −red per line. */
function DiffView({ text }: { text: string }) {
  if (!text) return <div className="artnote">loading diff…</div>;
  return (
    <pre className="code diff">
      {text.split("\n").map((l, i) => (
        <div key={i}
             className={"diffline " + (l.startsWith("+") && !l.startsWith("+++") ? "add"
               : l.startsWith("-") && !l.startsWith("---") ? "del"
               : l.startsWith("@@") ? "hunk" : "")}>{l || " "}</div>
      ))}
    </pre>
  );
}

const ICON: Record<string, string> = {
  code: "💻", pdf: "📄", image: "🖼️", gds: "🏭", waveform: "📈",
  doc: "📝", log: "📋", data: "🔧", file: "📎", reference: "📚",
};
const TEXTY = ["code", "doc", "log", "data", "reference"];

/** A "shelf" of the design's artifacts (papers, code, GDS, waveforms, uploads). Click a
 *  tile to open its full content — transparent + understandable. */
export function Artifacts({ chatId, refreshKey }: { chatId: string | null; refreshKey: number }) {
  const [items, setItems] = useState<Art[]>([]);
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<Art | null>(null);
  const [content, setContent] = useState("");
  const [exportState, setExportState] = useState<"idle" | "exporting" | "exported">("idle");
  const [exportCount, setExportCount] = useState(0);
  const [versions, setVersions] = useState<Ver[]>([]);
  const [selVer, setSelVer] = useState<Ver | null>(null);     // dropdown: null = current files
  const [verItems, setVerItems] = useState<Art[]>([]);        // the shelf AT the chosen version
  const [verOpen, setVerOpen] = useState<Ver | null>(null);   // "± changes" diff modal
  const [verFiles, setVerFiles] = useState<VerFile[]>([]);
  const [verTab, setVerTab] = useState<"files" | "changes">("changes");
  const [verTree, setVerTree] = useState<{ path: string; changed: boolean }[]>([]);
  const [diff, setDiff] = useState<{ path: string; text: string; mode: "diff" | "file" } | null>(null);

  // file kind from extension (mirrors the backend map) for version-scoped tiles
  const kindOf = (p: string) => {
    const e = (p.split(".").pop() || "").toLowerCase();
    return ({ v: "code", sv: "code", vh: "code", svh: "code", tex: "doc", md: "doc",
              txt: "doc", json: "data", log: "log", pdf: "pdf", png: "image",
              jpg: "image", svg: "image", gds: "gds", vcd: "waveform",
              mem: "data" } as Record<string, string>)[e] || "file";
  };

  async function pickVersion(v: Ver | null) {
    setSelVer(v); setVerItems([]);
    if (!v) return;
    try {
      const d = await (await fetch(`/api/chats/${chatId}/versions/${v.id}/tree`)).json();
      setVerItems((d.tree || []).map((f: { path: string }) => ({
        name: f.path.split("/").pop() || f.path, path: f.path,
        kind: kindOf(f.path), size: -1,
      })));
    } catch { /* */ }
  }

  useEffect(() => {
    if (!chatId) { setItems([]); setVersions([]); return; }
    fetch(`/api/chats/${chatId}/artifacts`).then((r) => r.json())
      .then((d) => setItems(d.artifacts || [])).catch(() => {});
    fetch(`/api/chats/${chatId}/versions`).then((r) => r.json())
      .then((d) => setVersions(d.versions || [])).catch(() => {});
  }, [chatId, refreshKey, open]);   // refetch when (re)opened too, so fresh netlists show

  async function openVersion(v: Ver) {
    setVerOpen(v); setVerFiles([]); setVerTree([]); setDiff(null); setVerTab("changes");
    try {
      const d = await (await fetch(`/api/chats/${chatId}/versions/${v.id}/files`)).json();
      setVerFiles(d.files || []);
      const t = await (await fetch(`/api/chats/${chatId}/versions/${v.id}/tree`)).json();
      setVerTree(t.tree || []);
    } catch { /* */ }
  }
  async function openDiff(v: Ver, path: string) {
    setDiff({ path, text: "", mode: "diff" });
    try {
      const d = await (await fetch(
        `/api/chats/${chatId}/versions/${v.id}/diff?path=${encodeURIComponent(path)}`)).json();
      setDiff({ path, text: d.diff || "(empty diff)", mode: "diff" });
    } catch { setDiff({ path, text: "(could not load diff)", mode: "diff" }); }
  }
  async function openAtVersion(v: Ver, path: string) {
    setDiff({ path, text: "", mode: "file" });
    try {
      const d = await (await fetch(
        `/api/chats/${chatId}/versions/${v.id}/file?path=${encodeURIComponent(path)}`)).json();
      setDiff({ path, text: d.content || "(empty file)", mode: "file" });
    } catch { setDiff({ path, text: "(could not load file)", mode: "file" }); }
  }

  useEffect(() => {                 // already exported? reflect it on the button
    if (!chatId) { setExportState("idle"); return; }
    fetch(`/api/chats/${chatId}/export-knowledge`).then((r) => r.json())
      .then((d) => { if (d.exported) { setExportState("exported"); setExportCount(d.count || 0); } })
      .catch(() => {});
  }, [chatId, open]);

  async function exportKnowledge() {
    if (!chatId || exportState === "exporting") return;
    setExportState("exporting");
    try {
      const d = await (await fetch(`/api/chats/${chatId}/export-knowledge`, { method: "POST" })).json();
      setExportCount(d.count || 0);
      setExportState("exported");
    } catch { setExportState("idle"); }
  }

  if (!chatId) return null;
  const fileUrl = (p: string) => `/api/chats/${chatId}/file?path=${encodeURIComponent(p)}`;

  async function openItem(a: Art) {
    setView(a); setContent("");
    if (selVer) {              // reading a file AT an old version → content from git
      try {
        const d = await (await fetch(
          `/api/chats/${chatId}/versions/${selVer.id}/file?path=${encodeURIComponent(a.path)}`)).json();
        setContent(d.content || "(empty at this version)");
      } catch { setContent("(could not load this version)"); }
      return;
    }
    if (TEXTY.includes(a.kind)) {
      try { setContent(await (await fetch(fileUrl(a.path))).text()); }
      catch { setContent("(could not load)"); }
    }
  }

  const byKind = (k: string) => items.filter((a) => a.kind === k);
  const groups: [string, string][] = [
    ["code", "Netlist / Glayout code"], ["reference", "References (anchors)"], ["pdf", "Papers"],
    ["doc", "Notes"], ["image", "Images"], ["waveform", "Waveforms"], ["gds", "GDS"],
    ["log", "Logs"], ["data", "Data"], ["file", "Files"],
  ];

  return (
    <>
      <button className="artbtn" onClick={() => setOpen((o) => !o)}
              title="Artifacts — papers, code, GDS, waveforms">
        📦 Artifacts <span className="cnt">{items.length}</span>
      </button>

      {open && (
        <div className="artpanel">
          <div className="arthead">
            <span>📦 Artifacts <small>{items.length} item(s)</small></span>
            <span className="x" onClick={() => setOpen(false)}>✕</span>
          </div>
          {versions.length > 0 && (
            <div className="verbar">
              <span className="verbar-l">🧬 Version</span>
              <select value={selVer?.id || ""} onChange={(e) => {
                const v = versions.find((x) => x.id === e.target.value) || null;
                pickVersion(v);
              }}>
                <option value="">current (latest files)</option>
                {versions.map((v) => (
                  <option key={v.id} value={v.id}>
                    {`v${v.v} — ${v.label}  ·  +${v.adds} −${v.dels}  ·  ${new Date(v.when * 1000).toLocaleTimeString()}`}
                  </option>
                ))}
              </select>
              {selVer && (
                <button className="verdiffbtn" onClick={() => openVersion(selVer)}
                        title="What changed in this version (+/− diff)">± changes</button>
              )}
            </div>
          )}
          <div className="artscroll">
            {items.length === 0 && <div className="artempty">Nothing yet — artifacts appear as the run produces netlists, glayout code, references and GDS.</div>}
            {selVer && (
              <div className="artnote" style={{ padding: "4px 2px 8px" }}>
                Browsing <b>v{selVer.v} — {selVer.label}</b>: every file below is shown AS IT
                WAS at that version. Pick “current” to go back.
              </div>
            )}
            {groups.map(([k, label]) => {
              const list = (selVer ? verItems : items).filter((a) => a.kind === k);
              if (!list.length) return null;
              return (
                <div key={k} className="artsec">
                  <div className="artsec-h">{ICON[k]} {label} <span>{list.length}</span></div>
                  <div className="artgrid">
                    {list.map((a) => (
                      <div key={a.path} className="arttile" onClick={() => openItem(a)} title={a.path}>
                        <div className="ico">{ICON[a.kind] || "📎"}</div>
                        <div className="nm">{a.name}</div>
                        <div className="kd">{a.size >= 0 ? `${(a.size / 1024).toFixed(1)} KB`
                          : `@ v${selVer?.v}`}</div>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
          <div className="artfoot">
            <button className={"artexport " + exportState}
                    disabled={exportState !== "idle" || items.length === 0}
                    onClick={exportKnowledge}
                    title="Save this design (netlist/config/glayout/refs/GDS) to the knowledge store (Postgres + MinIO). It survives deleting the chat.">
              {exportState === "exported"
                ? `✅ Exported to knowledge store${exportCount ? ` (${exportCount})` : ""}`
                : exportState === "exporting" ? "⏳ Exporting…"
                : "📤 Export to knowledge store"}
            </button>
            <div className="artfoot-note">
              Exported knowledge stays in db/pg/object storage even if you delete this chat.
            </div>
          </div>
        </div>
      )}

      {verOpen && (
        <div className="artmodal" onClick={() => { setVerOpen(null); setDiff(null); }}>
          <div className="artmodal-box" onClick={(e) => e.stopPropagation()}>
            <div className="arthead">
              <span>🧬 v{verOpen.v} — {verOpen.label}
                <em className="vadd"> +{verOpen.adds}</em>
                <em className="vdel"> −{verOpen.dels}</em>
              </span>
              <span className="x" onClick={() => { setVerOpen(null); setDiff(null); }}>✕</span>
            </div>
            <div className="vertabs">
              <button className={verTab === "changes" ? "active" : ""}
                      onClick={() => { setVerTab("changes"); setDiff(null); }}>
                ± Changes ({verFiles.length})
              </button>
              <button className={verTab === "files" ? "active" : ""}
                      onClick={() => { setVerTab("files"); setDiff(null); }}>
                📁 Files at v{verOpen.v} ({verTree.length})
              </button>
            </div>
            <div className="artbody verbody">
              <div className="verfiles">
                {verTab === "changes" ? (<>
                  {verFiles.map((f) => (
                    <div key={f.path}
                         className={"verfile" + (diff?.path === f.path ? " active" : "")}
                         onClick={() => openDiff(verOpen, f.path)}>
                      <span className="nm">{f.path}</span>
                      <span className="vstat"><em className="vadd">+{f.adds}</em>
                        <em className="vdel"> −{f.dels}</em></span>
                    </div>
                  ))}
                  {verFiles.length === 0 && <div className="artnote">loading files…</div>}
                </>) : (<>
                  {verTree.map((f) => (
                    <div key={f.path}
                         className={"verfile" + (diff?.path === f.path ? " active" : "")}
                         onClick={() => openAtVersion(verOpen, f.path)}>
                      <span className="nm">{f.path}</span>
                      {f.changed && <span className="vstat"><em className="vadd">±</em></span>}
                    </div>
                  ))}
                  {verTree.length === 0 && <div className="artnote">loading tree…</div>}
                </>)}
              </div>
              {diff ? (diff.mode === "diff" ? <DiffView text={diff.text} />
                       : <pre className="code diff">{diff.text}</pre>)
                    : <div className="artnote">← click a file: Changes = +/− diff · Files =
                        the file's full content at this version</div>}
            </div>
          </div>
        </div>
      )}

      {view && (
        <div className="artmodal" onClick={() => setView(null)}>
          <div className="artmodal-box" onClick={(e) => e.stopPropagation()}>
            <div className="arthead">
              <span>{ICON[view.kind] || "📎"} {view.name}</span>
              <span>
                <a className="dl" href={fileUrl(view.path)} target="_blank" rel="noreferrer">open ↗</a>
                <span className="x" onClick={() => setView(null)}>✕</span>
              </span>
            </div>
            <div className="artbody">
              {selVer ? <pre className="code">{content || "loading…"}</pre> : <>
              {view.kind === "image" && <img src={fileUrl(view.path)} alt={view.name} />}
              {view.kind === "pdf" && <iframe src={fileUrl(view.path)} title={view.name} />}
              {view.kind === "gds" && <div className="artnote">GDS layout — <a href={fileUrl(view.path)} target="_blank" rel="noreferrer">download</a> and open in KLayout.</div>}
              {view.kind === "waveform" && <div className="artnote">VCD waveform — <a href={fileUrl(view.path)} target="_blank" rel="noreferrer">download</a> to view, or ask the agent to render it.</div>}
              {view.kind === "doc" && <ReactMarkdown>{content || "loading…"}</ReactMarkdown>}
              {TEXTY.includes(view.kind) && view.kind !== "doc" && <pre className="code">{content || "loading…"}</pre>}
              {view.kind === "file" && <div className="artnote"><a href={fileUrl(view.path)} target="_blank" rel="noreferrer">download {view.name}</a></div>}
              </>}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
