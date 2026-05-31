export default function Sidebar({ sessions, activeId, onNew, onRefresh, onRestore }) {
  return (
    <aside className="sidebar">
      <button className="new-chat" onClick={onNew}>
        ＋ New design
      </button>
      <div className="side-title">
        History <em className="muted">(click to restore)</em>
        <button className="ghost xs" title="refresh" onClick={onRefresh}>
          ↻
        </button>
      </div>
      <div className="history">
        {!sessions.length ? (
          <span className="placeholder">No runs yet.</span>
        ) : (
          sessions.map((s) => (
            <div
              key={s.id}
              className={"hist-item" + (s.id === activeId ? " active" : "")}
              title={new Date(s.created_at * 1000).toLocaleString()}
              onClick={() => onRestore(s.id)}
            >
              <span className="hi-icon">{s.passed ? "✅" : "○"}</span>
              <span className="hi-prompt">{(s.prompt || "").slice(0, 70)}</span>
            </div>
          ))
        )}
      </div>
    </aside>
  );
}
