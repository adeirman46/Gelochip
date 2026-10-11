import { memo } from "react";
import ReactMarkdown from "react-markdown";
import type { Block } from "./types";

// The deep-agent sub-plan (write_todos) arrives as a markdown block like:
//   **📋 Plan:**
//   - ✅ done item
//   - 🔄 in-progress item
//   - ⬜ pending item
// Render it with the SAME styled checklist as the design "Plan" (green ✓ squares),
// instead of raw emoji markdown.
function parseTodos(text: string): { text: string; st: string }[] | null {
  if (!/📋\s*Plan/.test(text) && !/[⬜✅🔄]/.test(text)) return null;
  const items: { text: string; st: string }[] = [];
  for (const raw of text.split("\n")) {
    const m = raw.match(/^\s*[-*]?\s*([✅🔄⬜☑️])\s*(.+)$/u);
    if (!m) continue;
    const mark = m[1];
    // binary only — the orange "in-progress" state lingered after completion, so 🔄 renders
    // as pending until the agent actually marks it ✅
    const st = mark === "✅" || mark === "☑️" ? "done" : "pending";
    items.push({ text: m[2].trim(), st });
  }
  return items.length ? items : null;
}

function TodoList({ items }: { items: { text: string; st: string }[] }) {
  const done = items.filter((i) => i.st === "done").length;
  return (
    <div className="block planlist">
      <div className="planhead">
        📋 Plan <span className="plansub">— this step’s sub-tasks</span>
        <span className="plancount">{done}/{items.length}</span>
      </div>
      <ul>
        {items.map((it, i) => (
          <li key={i} className={"planitem " + it.st}>
            <span className="pmark">{it.st === "done" ? "✓" : ""}</span>
            <span className="ptext">{it.text}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Renders one Recorder block (the same block kinds the pipeline emits).
 * MEMOIZED: blocks are immutable, so unchanged blocks skip re-render entirely —
 * without this, every live tick (and every keystroke in the composer) re-parsed
 * every ReactMarkdown block in a huge transcript and the whole UI lagged. */
export const BlockView = memo(function BlockView(
  { block, runId }: { block: Block; runId: string | null }) {
  const p = block.payload || [];
  switch (block.kind) {
    case "markdown":
    case "write": {
      const text = String(p[0] ?? "");
      const todos = parseTodos(text);
      if (todos) return <TodoList items={todos} />;
      return <div className="block"><ReactMarkdown>{text}</ReactMarkdown></div>;
    }
    case "caption":
      return <div className="block caption">{String(p[0] ?? "")}</div>;
    case "success":
      return <div className="block success">✅ {String(p[0] ?? "")}</div>;
    case "error":
      return <div className="block error">❌ {String(p[0] ?? "")}</div>;
    case "warning":
      return <div className="block warning">⚠️ {String(p[0] ?? "")}</div>;
    case "info":
      return <div className="block info">ℹ️ {String(p[0] ?? "")}</div>;
    case "code": {
      const code = String(p[0] ?? "");
      // LIVE harden stage panel (language "stages"): one row per LibreLane stage —
      // ✓ done (with runtime) · ▶ running (with ticking elapsed) · so the user always
      // knows WHICH stage the flow is in and that it is alive.
      if (String(p[1] ?? "") === "stages") {
        const rows = code.split("\n").filter((l) => l.trim());
        return (
          <div className="block stagelist">
            {rows.map((l, i) => {
              const running = l.trimStart().startsWith("▶");
              const done = l.trimStart().startsWith("✓");
              return (
                <div key={i} className={"stagerow " + (running ? "running" : done ? "done" : "pending")}>
                  {running ? <span className="streamdots"><i /><i /><i /></span> : null}
                  <span className="stagetext">{l}</span>
                </div>
              );
            })}
          </div>
        );
      }
      // LIVE streaming status from stream_to (💭 thinking / ⏳ generating / "… N tokens") →
      // an ANIMATED indicator (bouncing dots + ticking token count + the live text scrolling).
      if (/💭\s*thinking|⏳\s*generating|\(\d+\s*tokens\)/.test(code)) {
        const tok = code.match(/(\d+)\s*tokens/);
        const body = code.replace(/^[⏳💭].*$/gmu, "").replace(/^———$/gmu, "").trim();
        return (
          <div className="block streaming">
            <div className="streamhead">
              <span className="streamdots"><i /><i /><i /></span>
              Thinking{tok ? <> · <span className="tokcount">{tok[1]}</span> tokens</> : "…"}
            </div>
            {body && <pre className="code streamcode">{body.slice(-2400)}</pre>}
          </div>
        );
      }
      // Long code → collapsible dropdown so the transcript isn't lengthy; short stays inline.
      const lines = code.split("\n").length;
      if (lines > 12) {
        return (
          <details className="exp block">
            <summary>{`‹/› code · ${lines} lines`}</summary>
            <pre className="code">{code}</pre>
          </details>
        );
      }
      return <pre className="code">{code}</pre>;
    }
    case "expander_code":
      return (
        <details className="exp block">
          <summary>{String(p[0] ?? "details")}</summary>
          <pre className="code">{String(p[1] ?? "")}</pre>
        </details>
      );
    case "image": {
      const path = String(p[0] ?? "");
      const src = runId ? `/api/runs/${runId}/file?path=${encodeURIComponent(path)}` : path;
      return (
        <div className="block">
          {p[1] ? <div className="caption">{String(p[1])}</div> : null}
          <img src={src} alt={String(p[1] ?? "image")} />
        </div>
      );
    }
    case "table": {
      // payload[0] = { ColName: [values...] } → render an HTML table (was [object Object]).
      const data = (p[0] ?? {}) as Record<string, unknown[]>;
      const cols = Object.keys(data);
      const nrows = cols.length ? Math.max(...cols.map((c) => (data[c] || []).length)) : 0;
      return (
        <div className="block">
          <table className="metricstable">
            <thead><tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr></thead>
            <tbody>
              {Array.from({ length: nrows }).map((_, r) => (
                <tr key={r}>{cols.map((c) => <td key={c}>{String((data[c] || [])[r] ?? "")}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }
    case "json": {
      // payload[0] = an object → pretty-print in a collapsible block (was [object Object]).
      let text = "";
      try { text = JSON.stringify(p[0] ?? {}, null, 2); } catch { text = String(p[0] ?? ""); }
      return (
        <details className="exp block">
          <summary>{`{} all metrics · ${text.split("\n").length} lines`}</summary>
          <pre className="code">{text}</pre>
        </details>
      );
    }
    case "file": {
      // A downloadable artifact (e.g. the generated PDF report): payload = (path, label)
      const path = String(p[0] ?? "");
      const label = String(p[1] ?? path.split("/").pop() ?? "file");
      const href = runId ? `/api/runs/${runId}/file?path=${encodeURIComponent(path)}` : path;
      return (
        <div className="block">
          <a className="fileblock" href={href} target="_blank" rel="noreferrer">
            📄 {label} <span className="filehint">— open / download</span>
          </a>
        </div>
      );
    }
    case "header":
      return null; // node header is rendered by the card itself
    default:
      return <div className="block caption">{String(p[0] ?? "")}</div>;
  }
});
