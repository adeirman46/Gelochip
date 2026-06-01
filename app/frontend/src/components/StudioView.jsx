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
  const [wireMode, setWireMode] = useState(false);   // manual drag-to-connect tool
  const [pendingPin, setPendingPin] = useState(null); // "uid.pinName" of first click
  const [cursor, setCursor] = useState(null);         // rubber-band endpoint
  const [manualNets, setManualNets] = useState([]);   // user-drawn wires
  const [zoom, setZoom] = useState(1);                // canvas zoom (bigger view)
  const view = "gds";                                 // GDS view only (real layouts)
  const seq = useRef(0);
  const svgRef = useRef(null);

  // Manual wiring: click pin → click another pin → a net between them.
  function onPinClick(ref) {
    if (!wireMode) return;
    if (!pendingPin) { setPendingPin(ref); return; }
    if (pendingPin === ref) { setPendingPin(null); return; }  // cancel
    setManualNets((prev) => [
      ...prev,
      { name: "wire" + (prev.length + 1), pins: [pendingPin, ref], manual: true },
    ]);
    setPendingPin(null);
  }

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
    // block size PROPORTIONAL to the real IP area (√area ≈ linear µm), so a
    // 300µm² current_mirror is visibly small and an 82 000µm² opamp is large.
    const scale = Math.min(460, Math.max(110, Math.sqrt(ip.area_um2 || 4000) * 2.2));
    seq.current += 1;
    setPlaced((prev) => [
      ...prev,
      {
        uid: "U" + seq.current, ip: ip.id, name: ip.name,
        preview: ip.thumb_url || ip.preview_url || null,
        x: c.x - scale / 2, y: c.y - scale / 2, w: scale, h: scale, pins: ip.pins,
      },
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

  // Pad pinout position: pull each named pad IN to the padring's inner edge
  // (≈ core_margin), where the GDS pads meet the core — that's where you wire to.
  function padPos(p) {
    const m = padframe.outline.core_margin, W = padframe.outline.w, H = padframe.outline.h;
    if (p.side === "top") return { x: p.x, y: m };
    if (p.side === "bottom") return { x: p.x, y: H - m };
    if (p.side === "left") return { x: m, y: p.y };
    return { x: W - m, y: p.y };                      // right
  }

  // resolve wire endpoints from current placement (block pins AND padring pinouts)
  const byRef = {};
  placed.forEach((b) => b.pins.forEach((p) => (byRef[`${b.uid}.${p.name}`] = pinPos(b, p))));
  if (padframe) padframe.pads.forEach((p) => (byRef[`PAD.${p.name}`] = padPos(p)));

  // viewBox with zoom: shrink the box around its centre to zoom in.
  const baseX = padframe ? -40 : 0;
  const baseY = padframe ? -40 : 0;
  const baseW = padframe ? padframe.outline.w + 80 : 1200;
  const baseH = padframe ? padframe.outline.h + 80 : 1200;
  const vw = baseW / zoom;
  const vh = baseH / zoom;
  const vb = `${baseX + (baseW - vw) / 2} ${baseY + (baseH - vh) / 2} ${vw} ${vh}`;

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
            <button
              className={(wireMode ? "run" : "ghost") + " small"}
              onClick={() => { setWireMode((m) => !m); setPendingPin(null); }}
              title="Click a pin, then another pin (or a pad), to draw a wire"
            >
              {wireMode ? "✏️ Wiring… (click 2 pins)" : "✏️ Wire"}
            </button>
            <button className="run small" onClick={aiConnect} disabled={connecting}>
              {connecting ? "thinking…" : "⚡ AI connect pins"}
            </button>
            <span className="zoom-ctl">
              <button className="ghost small" onClick={() => setZoom((z) => Math.max(0.5, z / 1.25))} title="Zoom out">−</button>
              <span className="zoom-val">{Math.round(zoom * 100)}%</span>
              <button className="ghost small" onClick={() => setZoom((z) => Math.min(4, z * 1.25))} title="Zoom in">+</button>
            </span>
            <button
              className="ghost small"
              onClick={() => {
                setPlaced([]);
                setNets([]);
                setManualNets([]);
                setPendingPin(null);
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
          className={`view-${view}` + (wireMode ? " wiring" : "")}
          viewBox={vb}
          preserveAspectRatio="xMidYMid meet"
          onDragOver={(e) => e.preventDefault()}
          onDrop={onDrop}
          onMouseMove={(e) => { if (wireMode && pendingPin) setCursor(svgCoords(e)); }}
        >
          {padframe && (
            <>
              {/* GDS view: the real klayout-rendered pad-ring GDS as the backdrop */}
              {view === "gds" && (
                <image
                  href="/datasets/padframe.png?v=4" xlinkHref="/datasets/padframe.png?v=4"
                  x={0} y={0} width={padframe.outline.w} height={padframe.outline.h}
                  preserveAspectRatio="none"
                />
              )}
              <rect className="frame" x={0} y={0} width={padframe.outline.w} height={padframe.outline.h} />
              <rect
                className="core"
                x={padframe.outline.core_margin}
                y={padframe.outline.core_margin}
                width={padframe.outline.w - 2 * padframe.outline.core_margin}
                height={padframe.outline.h - 2 * padframe.outline.core_margin}
              />
              {padframe.pads.map((p, i) => {
                const ref = `PAD.${p.name}`;
                const active = pendingPin === ref;
                const pp = padPos(p);                       // inner-edge pinout point
                const dy = p.side === "top" ? -8 : p.side === "bottom" ? 18 : -8;
                return (
                  <g
                    key={i}
                    style={{ cursor: "crosshair" }}
                    onMouseDown={(e) => { e.stopPropagation(); onPinClick(ref); }}
                  >
                    {/* big invisible hit target so the pinout is easy to click */}
                    <circle cx={pp.x} cy={pp.y} r={16} fill="transparent" />
                    {/* visible pinout marker on the padring's inner edge */}
                    <circle className={"padpin" + (active ? " active" : "")} cx={pp.x} cy={pp.y} r={active ? 9 : 6} />
                    <text className="padpin-label" x={pp.x} y={pp.y + dy} textAnchor="middle">
                      {p.name}
                    </text>
                  </g>
                );
              })}
            </>
          )}

          {placed.map((b) => (
            <g key={b.uid} onMouseDown={wireMode ? undefined : (e) => startDrag(e, b.uid)}>
              {view === "gds" && b.preview ? (
                <>
                  <rect x={b.x} y={b.y} width={b.w} height={b.h} rx={6} fill="#080c12" />
                  {/* the klayout-rendered layout PNG, as a plain SVG <image>
                      (verified to render headlessly). href + xlinkHref covers every
                      React/SVG version; no clipPath (that was the original breaker). */}
                  <image
                    href={b.preview} xlinkHref={b.preview}
                    x={b.x + 2} y={b.y + 2} width={b.w - 4} height={b.h - 4}
                    preserveAspectRatio="xMidYMid meet"
                    style={{ pointerEvents: "none" }}
                  />
                  <rect className="block-rect framed" x={b.x} y={b.y} width={b.w} height={b.h} rx={6} fill="none" />
                </>
              ) : (
                <rect className="block-rect" x={b.x} y={b.y} width={b.w} height={b.h} rx={6} />
              )}
              {/* label bar so the name is readable over the layout */}
              <rect className="block-tab" x={b.x} y={b.y} width={b.w} height={20} rx={6} />
              <text className="block-label" x={b.x + b.w / 2} y={b.y + 14} textAnchor="middle">
                {b.uid} · {b.name || b.ip}
              </text>
              {b.pins.map((pin, i) => {
                const pos = pinPos(b, pin);
                const dx = pin.side === "left" ? -4 : pin.side === "right" ? 4 : 0;
                const anchor = pin.side === "left" ? "end" : pin.side === "right" ? "start" : "middle";
                const ref = `${b.uid}.${pin.name}`;
                const active = pendingPin === ref;
                return (
                  <g key={i} style={wireMode ? { cursor: "crosshair" } : undefined}
                     onMouseDown={wireMode ? (e) => { e.stopPropagation(); onPinClick(ref); } : undefined}>
                    {/* big invisible hit target — easy to grab while wiring */}
                    {wireMode && <circle cx={pos.x} cy={pos.y} r={24} fill="transparent" />}
                    {/* glowing halo so clickable pins are obvious in wire mode */}
                    {wireMode && <circle className="pin-halo" cx={pos.x} cy={pos.y} r={12} />}
                    <circle
                      className={"pin-dot" + (active ? " active" : "") + (wireMode ? " wiring" : "")}
                      cx={pos.x} cy={pos.y} r={active ? 10 : wireMode ? 8 : 5}
                    />
                    <text className="pin-label" x={pos.x + dx} y={pos.y - 7} textAnchor={anchor}>
                      {pin.name}
                    </text>
                  </g>
                );
              })}
            </g>
          ))}

          {[...nets, ...manualNets].map((net, ni) => {
            const pts = net.pins.map((r) => byRef[r]).filter(Boolean);
            if (pts.length < 2) return null;
            const hub = pts[0];
            return (
              <g key={ni}>
                {pts.slice(1).map((pt, i) => (
                  <path key={i} className={"wire" + (net.manual ? " manual" : "")} d={`M ${hub.x} ${hub.y} L ${pt.x} ${pt.y}`} />
                ))}
                <text className="wire-label" x={hub.x + 4} y={hub.y - 4}>
                  {net.name}
                </text>
              </g>
            );
          })}

          {/* rubber-band line from the first clicked pin to the cursor */}
          {wireMode && pendingPin && cursor && byRef[pendingPin] && (
            <path
              className="wire pending"
              d={`M ${byRef[pendingPin].x} ${byRef[pendingPin].y} L ${cursor.x} ${cursor.y}`}
            />
          )}
        </svg>
      </section>

      <aside className="panel net-rail">
        <h2 className="section-title">Pinout / Netlist</h2>
        {manualNets.length > 0 && (
          <div className="netlist" style={{ marginBottom: 10 }}>
            <div className="hint">manual wires ({manualNets.length})</div>
            {manualNets.map((n, i) => (
              <div className="net" key={i}>
                <b>{n.name}</b>
                <span className="pins">{n.pins.join("  ·  ")}</span>
              </div>
            ))}
          </div>
        )}
        <div className="netlist">
          {!netResult ? (
            <span className="placeholder">
              {wireMode ? "Wire mode: click a pin, then another." : "Drag blocks, then ✏️ Wire or ⚡ AI connect."}
            </span>
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
