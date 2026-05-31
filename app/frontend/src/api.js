// Thin wrappers around the Kaizen FastAPI backend. Same-origin in production
// (served by FastAPI); proxied to :8090 in dev via vite.config.js.

async function jget(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export const api = {
  collections: () => jget("/api/kaizen/collections"),
  health: () => jget("/api/health"),
  history: () => jget("/api/kaizen/history"),
  session: (id) => jget(`/api/kaizen/history/${id}`),
  delSession: (id) => fetch(`/api/kaizen/history/${id}`, { method: "DELETE" }),
  ipLibrary: () => jget("/api/ip/library"),
  padframe: () => jget("/api/padframe"),
  connect: (body) =>
    fetch("/api/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => r.json()),
  run: async (prompt) => {
    const res = await fetch("/api/kaizen/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      const detail = err.detail?.[0]?.msg || err.error || `HTTP ${res.status}`;
      const e = new Error(detail);
      e.rejected = true;
      throw e;
    }
    return res.json();
  },
  cancel: (jobId) => fetch(`/api/kaizen/cancel/${jobId}`, { method: "POST" }),
  stream: (jobId) => new EventSource(`/api/kaizen/stream/${jobId}`),
};
