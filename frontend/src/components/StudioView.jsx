import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";

// absolute pin position for block b given a pin on one of its sides
function pinPos(b, pin) {
  const sidePins = b.pins.filter((p) => p.side === pin.side);
  const i = sidePins.indexOf(pin);
  const f = (i + 1) / (sidePins.length + 1);
  if (pin.side === "left") return { x: b.x, y: b.y + f * b.h };
  if (pin.side === "right") return { x: b.x + b.w, y: b.y + f * b.h };
  if (pin.side === "top") return { x: b.x + f * b.w, y: b.y };
  return { x: b.x + f * b.w, y: b.y + b.h };
}

export default function StudioView() {
  const [padframe, setPadframe] = useState(null);
  const [ips, setIps] = useState(null);
  const [placed, setPlaced] = useState([]);
  const [nets, setNets] = useState([]);
  const [netResult, setNetResult] = useState(null);
  const [connecting, setConnecting] = useState(false);
  const seq = useRef(0);
  const svgRef = useRef(null);

  useEffect(() => {
    api.padframe().then(setPadframe).catch(() => setPadframe(null));
    api
      .ipLibrary()
      .then((d) => setIps(d.ips || []))
      .catch(() => setIps([]));
  }, []);

  function svgCoords(evt) {
    const s = svgRef.current;
    const r = s.getBoundingClientRect();
    const vb = s.viewBox.baseVal;
    return {
      x: ((evt.clientX - r.left) / r.width) * vb.width + vb.x,
      y: ((evt.clientY - r.top) / r.height) * vb.height + vb.y,
    };
  }

  function onDrop(e) {
    e.preventDefault();
    const ip = JSON.parse(e.dataTransfer.getData("application/json"));
    const c = svgCoords(e);
    const scale = Math.min(220, Math.max(120, Math.sqrt(ip.area_um2 || 4000) * 2));
    seq.current += 1;
    setPlaced((prev) => [
      ...prev,
      { uid: "U" + seq.current, ip: ip.id, x: c.x - scale / 2, y: c.y - scale / 2, w: scale, h: scale, pins: ip.pins },
    ]);
    setNets([]);
  }

  function startDrag(e, uid) {
    if (e.target.classList.contains("pin-dot")) return;
    const start = svgCoords(e);
    const block = placed.find((b) => b.uid === uid);
    const ox = block.x;
    const oy = block.y;
    const move = (ev) => {
      const c = svgCoords(ev);
      setPlaced((prev) =>
        prev.map((b) => (b.uid === uid ? { ...b, x: ox + (c.x - start.x), y: oy + (c.y - start.y) } : b))
      );
    };
    const up = () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  }

  async function aiConnect() {
    if (!placed.length) return;
    setConnecting(true);
    try {
      const res = await api.connect({
        blocks: placed.map((b) => ({ id: b.uid, ip: b.ip, pins: b.pins })),
      });
      setNets(res.nets || []);
      setNetResult(res);
    } catch {
      setNetResult({ nets: [], _error: true });
    } finally {
      setConnecting(false);
    }
  }

  // resolve wire endpoints from current placement
  const byRef = {};
  placed.forEach((b) => b.pins.forEach((p) => (byRef[`${b.uid}.${p.name}`] = pinPos(b, p))));

  const vb = padframe
    ? `-40 -40 ${padframe.outline.w + 80} ${padframe.outline.h + 80}`
    : "0 0 1200 1200";

  return (
    <main className="studio view">
      <aside className="panel ip-rail">
        <h2 className="section-title">
          IP Library <em className="muted">(DRC-clean only)</em>
        </h2>
        <p className="hint">Drag a block onto the chip →</p>
        <div className="ip-list">
          {ips === null ? (
            <span className="placeholder">loading…</span>
          ) : !ips.length ? (
            <span className="placeholder">No DRC-clean IPs yet.</span>
          ) : (
            ips.map((ip) => (
              <div
                className="ip-card"
                key={ip.id}
                draggable
                onDragStart={(e) => e.dataTransfer.setData("application/json", JSON.stringify(ip))}
              >
                {ip.preview_url ? <img src={ip.preview_url} alt="" /> : <div style={{ width: 46 }} />}
                <div>
                  <div className="ip-name">
                    {ip.name}
                    <span className="badge">DRC✓</span>
                  </div>
                  <div className="ip-meta">
                    {ip.pins.length} pins · {ip.area_um2 ?? "?"} µm²
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </aside>

      <section className="panel canvas-wrap">
        <div className="canvas-toolbar">
          <h2 className="section-title">
            Chip floorplan{" "}
            <em className="muted">{padframe ? "· " + padframe.source : ""}</em>
          </h2>
          <div className="toolbar-actions">
            <button className="run small" onClick={aiConnect} disabled={connecting}>
              {connecting ? "thinking…" : "⚡ AI connect pins"}
            </button>
            <button
              className="ghost small"
              onClick={() => {
                setPlaced([]);
                setNets([]);
                setNetResult(null);
              }}
            >
              Clear
            </button>
          </div>
        </div>

        <svg
          id="canvas"
          ref={svgRef}
          viewBox={vb}
          preserveAspectRatio="xMidYMid meet"
          onDragOver={(e) => e.preventDefault()}
          onDrop={onDrop}
        >
          {padframe && (
            <>
              <rect className="frame" x={0} y={0} width={padframe.outline.w} height={padframe.outline.h} />
              <rect
                className="core"
                x={padframe.outline.core_margin}
                y={padframe.outline.core_margin}
                width={padframe.outline.w - 2 * padframe.outline.core_margin}
                height={padframe.outline.h - 2 * padframe.outline.core_margin}
              />
              {padframe.pads.map((p, i) => (
                <g key={i}>
                  <rect className="pad" x={p.x - 14} y={p.y - 14} width={28} height={28} rx={3} />
                  <text className="pad-label" x={p.x - 12} y={p.y + 24}>
                    {p.name}
                  </text>
                </g>
              ))}
            </>
          )}

          {placed.map((b) => (
            <g key={b.uid} onMouseDown={(e) => startDrag(e, b.uid)}>
              <rect className="block-rect" x={b.x} y={b.y} width={b.w} height={b.h} rx={6} />
              <text
                className="block-label"
                x={b.x + b.w / 2}
                y={b.y + b.h / 2}
                textAnchor="middle"
                dominantBaseline="middle"
              >
                {b.uid}
              </text>
              {b.pins.map((pin, i) => {
                const pos = pinPos(b, pin);
                const dx = pin.side === "left" ? -4 : pin.side === "right" ? 4 : 0;
                const anchor = pin.side === "left" ? "end" : pin.side === "right" ? "start" : "middle";
                return (
                  <g key={i}>
                    <circle className="pin-dot" cx={pos.x} cy={pos.y} r={3.5} />
                    <text className="pin-label" x={pos.x + dx} y={pos.y - 5} textAnchor={anchor}>
                      {pin.name}
                    </text>
                  </g>
                );
              })}
            </g>
          ))}

          {nets.map((net, ni) => {
            const pts = net.pins.map((r) => byRef[r]).filter(Boolean);
            if (pts.length < 2) return null;
            const hub = pts[0];
            return (
              <g key={ni}>
                {pts.slice(1).map((pt, i) => (
                  <path key={i} className="wire" d={`M ${hub.x} ${hub.y} L ${pt.x} ${pt.y}`} />
                ))}
                <text className="wire-label" x={hub.x + 4} y={hub.y - 4}>
                  {net.name}
                </text>
              </g>
            );
          })}
        </svg>
      </section>

      <aside className="panel net-rail">
        <h2 className="section-title">Pinout / Netlist</h2>
        <div className="netlist">
          {!netResult ? (
            <span className="placeholder">Place blocks, then “AI connect pins”.</span>
          ) : netResult._error ? (
            <span className="placeholder">connect failed</span>
          ) : !netResult.nets || !netResult.nets.length ? (
            <span className="placeholder">No nets proposed.</span>
          ) : (
            <>
              <div className="hint">source: {netResult.source || ""}</div>
              {netResult.nets.map((n, i) => (
                <div className="net" key={i}>
                  <b>{n.name}</b>
                  <span className="pins">{n.pins.join("  ·  ")}</span>
                </div>
              ))}
            </>
          )}
        </div>
      </aside>
    </main>
  );
}
