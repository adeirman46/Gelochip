import { useEffect, useRef } from "react";
import { NODE_LABELS } from "../runState.js";

const PIPELINE = [
  ["plan", "Planner", null],
  ["research", "Researcher", "(arxiv/web/github → temp RAG)"],
  ["retrieve", "Retriever", "(3 collections + research)"],
  ["extract", "Extractor", "(facts from code, knowledge & images)"],
  ["generate", "Generator", "(glayout code)"],
  ["test", "Test", "(build + DRC + testbench)"],
  ["kaizen_memory", "Kaizen memory", "(on fail)"],
  ["persist", "Persist", "(on pass → ChromaDB)"],
  ["summarize", "Summarize", null],
];

const EXAMPLES = [
  "gf180 NMOS current mirror, ratio 2",
  "5-transistor OTA in gf180",
  "CMOS transmission gate, DRC-clean",
];

function bust(url) {
  return url ? `${url}${url.includes("?") ? "&" : "?"}t=${Date.now()}` : url;
}

function Knowledge({ items }) {
  if (!items.length)
    return <span className="placeholder">research + retrieved knowledge will appear here</span>;
  return (
    <>
      {items.map((it, idx) =>
        it.type === "research" ? (
          <ResearchGroup key={idx} sources={it.sources} />
        ) : it.type === "extract" ? (
          <ExtractGroup key={idx} extracted={it.extracted} imageFindings={it.image_findings} />
        ) : (
          <RetrievedGroup key={idx} r={it.r} />
        )
      )}
    </>
  );
}

function ResearchGroup({ sources }) {
  return (
    <>
      <div className="kgroup-title">🔎 Researched sources ({sources.length})</div>
      {!sources.length && (
        <div className="kitem">
          <span className="ksnip">
            No external sources (offline or none found) — using local knowledge only.
          </span>
        </div>
      )}
      {sources.map((s, i) => {
        const isImg = /\.(png|jpe?g|gif|svg)(\?|$)/i.test(s.url || "");
        return (
          <div className="kitem" key={i}>
            <span className="ksrc">{s.source || "src"}</span>
            <span className="ktitle">{s.title || ""}</span>
            {s.url && (
              <div>
                <a href={s.url} target="_blank" rel="noreferrer">
                  {s.url}
                </a>
              </div>
            )}
            {isImg && <img src={s.url} alt="" />}
            {s.snippet && <div className="ksnip">{s.snippet}</div>}
          </div>
        );
      })}
    </>
  );
}

function RetrievedGroup({ r }) {
  const group = (title, items, kind) =>
    items && items.length ? (
      <>
        <div className="kgroup-title">{title}</div>
        {items.map((it, i) => (
          <div className="kitem" key={i}>
            <span className="ksrc">{it.label || ""}</span>
            {kind === "code" ? (
              <code>{(it.snippet || "").slice(0, 280)}</code>
            ) : (
              <div className="ksnip">{it.snippet || ""}</div>
            )}
          </div>
        ))}
      </>
    ) : null;
  return (
    <>
      {group("📐 Retrieved glayout knowledge", r.templates, "code")}
      {group("📖 Retrieved RF theory", r.theory)}
      {group("🧪 From researched papers", r.research)}
    </>
  );
}

function ExtractGroup({ extracted, imageFindings }) {
  return (
    <>
      <div className="kgroup-title">🧠 Extracted design spec</div>
      {imageFindings ? (
        <div className="kitem">
          <span className="ksrc">vision</span>
          <div className="ksnip" style={{ whiteSpace: "pre-wrap" }}>
            {imageFindings}
          </div>
        </div>
      ) : null}
      <div className="kitem">
        <code style={{ whiteSpace: "pre-wrap" }}>{extracted}</code>
      </div>
    </>
  );
}

export default function PromptView({ run, running, prompt, setPrompt, onSubmit, onStop }) {
  const logRef = useRef(null);
  const thinkRef = useRef(null);
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [run.log]);
  useEffect(() => {
    if (thinkRef.current) thinkRef.current.scrollTop = thinkRef.current.scrollHeight;
  }, [run.thinking]);

  return (
    <main className="grid view">
      <section className="panel">
        <form
          className="prompt-box"
          onSubmit={(e) => {
            e.preventDefault();
            onSubmit();
          }}
        >
          <textarea
            rows={3}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="e.g. Design a gf180 NMOS current mirror with ratio 2 and substrate ties, DRC-clean"
          />
          <div className="prompt-actions">
            <div className="examples">
              {EXAMPLES.map((ex) => (
                <button type="button" className="chip" key={ex} onClick={() => setPrompt(ex)}>
                  {ex}
                </button>
              ))}
            </div>
            <button type="submit" className="run" disabled={running}>
              Generate ▸
            </button>
            {running && (
              <button type="button" className="ghost stop" onClick={onStop}>
                ⏹ Stop
              </button>
            )}
          </div>
        </form>

        <h2 className="section-title">Pipeline</h2>
        <ol className="pipeline">
          {PIPELINE.map(([node, label, hint]) => (
            <li key={node} className={run.pipeline[node] || ""}>
              <span className="dot" />
              {label}
              {hint && <em> {hint}</em>}
            </li>
          ))}
        </ol>

        <h2 className="section-title">
          💭 Agent thinking <em className="muted">(live reasoning)</em>
        </h2>
        <div className="thinking" ref={thinkRef}>
          {run.thinking ? (
            <>
              <div className="think-label">
                {(NODE_LABELS[run.thinking.node] || run.thinking.node)} is thinking…
              </div>
              <div className="think-body">{run.thinking.text}</div>
            </>
          ) : (
            <span className="placeholder">the agent's reasoning streams here…</span>
          )}
        </div>

        <h2 className="section-title">Event log</h2>
        <div className="log" ref={logRef}>
          {run.log.map((l, i) => (
            <div className="line" key={i}>
              <span className="ts">{l.ts}</span>{" "}
              <span className="node">{NODE_LABELS[l.node] || l.node}</span> {l.msg}
            </div>
          ))}
        </div>
      </section>

      <section className="panel results">
        <div className="result-card">
          <h2 className="section-title">
            Knowledge &amp; research{" "}
            <em className="muted">(what the agent found — verify before it generates)</em>
          </h2>
          <div className="knowledge">
            <Knowledge items={run.knowledge} />
          </div>
        </div>

        <div className="result-card">
          <h2 className="section-title">Layout (GDS preview)</h2>
          <div className="preview">
            {run.preview ? (
              <img src={bust(run.preview)} alt="GDS preview" />
            ) : (
              <span className="placeholder">No layout yet</span>
            )}
          </div>
          <div className="links">
            {run.links.gds_url && (
              <a href={run.links.gds_url} download>
                ⬇ download GDS
              </a>
            )}
            {run.links.png_url && (
              <a href={run.links.png_url} target="_blank" rel="noreferrer">
                ↗ open PNG
              </a>
            )}
          </div>
        </div>

        <div className="result-card">
          <h2 className="section-title">DRC verdict</h2>
          <div className={"verdict " + run.verdict.cls}>{run.verdict.text}</div>
        </div>

        <div className="result-card">
          <h2 className="section-title">
            Testbench <em className="muted">(SPICE · AC · transient — no LVS)</em>
          </h2>
          <div className="tb-plots">
            {run.tb.ac_plot_url || run.tb.tran_plot_url ? (
              <>
                {run.tb.ac_plot_url && (
                  <figure>
                    <img src={bust(run.tb.ac_plot_url)} alt="AC" />
                    <figcaption>AC</figcaption>
                  </figure>
                )}
                {run.tb.tran_plot_url && (
                  <figure>
                    <img src={bust(run.tb.tran_plot_url)} alt="Transient" />
                    <figcaption>Transient</figcaption>
                  </figure>
                )}
              </>
            ) : (
              <span className="placeholder">no simulation yet</span>
            )}
          </div>
          <div className="links">
            {run.tb.spice_url && (
              <a href={run.tb.spice_url} target="_blank" rel="noreferrer">
                ↗ extracted SPICE netlist
              </a>
            )}
          </div>
        </div>

        <div className="result-card">
          <h2 className="section-title">Generated glayout code</h2>
          <pre className="code">
            {run.code.tag && <div className="code-tag">{run.code.tag}</div>}
            {run.code.diff ? (
              <div className="diff">
                {run.code.diff.map((d, i) => (
                  <div className={"dl " + d.cls} key={i}>
                    {d.sign} {d.text}
                  </div>
                ))}
              </div>
            ) : (
              <code>{run.code.code}</code>
            )}
          </pre>
        </div>
      </section>
    </main>
  );
}
