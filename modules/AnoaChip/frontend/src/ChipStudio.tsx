import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { Floorplan, IP, IPLibraryResponse, Padframe, PlacedBlock } from "./types";

const VB = 1000;                 // SVG viewBox is VB×VB over the square padframe
const BW = 150, BH = 110;        // default placed-block size

export function ChipStudio() {
  const [pf, setPf] = useState<Padframe | null>(null);
  const [lib, setLib] = useState<IPLibraryResponse | null>(null);
  const [fps, setFps] = useState<{ id: string; name: string; blocks: number }[]>([]);
  const [fp, setFp] = useState<Floorplan | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [openCat, setOpenCat] = useState<Record<string, boolean>>({});
  const svgRef = useRef<SVGSVGElement>(null);
  const drag = useRef<{ uid: string; dx: number; dy: number } | null>(null);

  async function boot() {
    const [p, l, f] = await Promise.all([api.padframe(), api.listIPs(), api.listFloorplans()]);
    setPf(p); setLib(l); setFps(f);
    if (f.length) setFp(await api.getFloorplan(f[0].id));
    else { const nf = await api.createFloorplan("My chip"); setFp(nf); setFps(await api.listFloorplans()); }
  }
  useEffect(() => { boot(); }, []);

  // Chip Studio shows every block that produced a real GDS macro (the retain policy);
  // tape-out-clean + TB-verified ones are badged as such in the rail.
  const hardened = (lib?.ips || []).filter((m) => !!m.gds);
  const extraCats = [...new Set((lib?.ips || []).map((m) => m.category))].filter((c) => !(lib?.categories || []).includes(c));
  const allCats = [...(lib?.categories || []), ...extraCats];
  const labelOf = (c: string) => lib?.labels[c] || c.replace(/_/g, " ");
  const iconOf = (c: string) => lib?.icons[c] || "📦";

  // Block size REFLECTS the real hardened die area (√area), so a big macro looks big and a small
  // one small — the floorplan reads true to silicon instead of every block being identical.
  function blockSize(ip: IP): [number, number] {
    const area = ip.metrics?.die_area_um2 || 0;
    const side = area ? Math.max(72, Math.min(340, Math.sqrt(area) * 0.16)) : BW;
    return [side, Math.max(BH, side * 0.72)];
  }

  function toVB(clientX: number, clientY: number): [number, number] {
    const svg = svgRef.current!;
    const r = svg.getBoundingClientRect();
    return [((clientX - r.left) / r.width) * VB, ((clientY - r.top) / r.height) * VB];
  }

  function addBlock(ip: IP, x: number, y: number) {
    if (!fp) return;
    const [w, h] = blockSize(ip);
    const blk: PlacedBlock = {
      uid: "b_" + Math.random().toString(36).slice(2, 8), ip_id: ip.id, name: ip.name,
      x: Math.max(0, Math.min(VB - w, x - w / 2)), y: Math.max(0, Math.min(VB - h, y - h / 2)),
      w, h, ports: ip.ports,
    };
    setFp({ ...fp, placed: [...fp.placed, blk] });
    setSel(blk.uid);
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    const id = e.dataTransfer.getData("ip");
    const ip = hardened.find((m) => m.id === id);
    if (!ip) return;
    const [x, y] = toVB(e.clientX, e.clientY);
    addBlock(ip, x, y);
  }

  function onPointerDown(e: React.PointerEvent, blk: PlacedBlock) {
    e.stopPropagation();
    setSel(blk.uid);
    const [x, y] = toVB(e.clientX, e.clientY);
    drag.current = { uid: blk.uid, dx: x - blk.x, dy: y - blk.y };
    (e.target as Element).setPointerCapture(e.pointerId);
  }
  function onPointerMove(e: React.PointerEvent) {
    if (!drag.current || !fp) return;
    const [x, y] = toVB(e.clientX, e.clientY);
    const d = drag.current;
    setFp({
      ...fp, placed: fp.placed.map((b) => b.uid === d.uid
        ? { ...b, x: Math.max(0, Math.min(VB - b.w, x - d.dx)), y: Math.max(0, Math.min(VB - b.h, y - d.dy)) } : b),
    });
  }
  function onPointerUp() { drag.current = null; }

  function removeSel() {
    if (!fp || !sel) return;
    setFp({ ...fp, placed: fp.placed.filter((b) => b.uid !== sel) });
    setSel(null);
  }

  async function save() { if (fp) { await api.saveFloorplan(fp); setFps(await api.listFloorplans()); } }
  async function newFp() { const nf = await api.createFloorplan("Chip " + (fps.length + 1)); setFp(nf); setFps(await api.listFloorplans()); }

  if (!pf || !lib) return <div className="tabpane"><div className="loading">Loading Chip Studio…</div></div>;

  return (
    <div className="tabpane studio">
      {/* ── IP rail: hardened (placeable) IPs, grouped by category ── */}
      <aside className="studio-rail">
        <div className="raillabel">IP Library <em>· GDS macros</em></div>
        <p className="railhint">Every block here has a real GDS layout. 🏭 = tape-out sign-off clean · ✓ = testbench-verified. Drag one onto the chip →</p>
        <div className="railfolders">
          {allCats.map((cat) => {
            const items = hardened.filter((m) => m.category === cat);
            if (!items.length) return null;
            const isOpen = openCat[cat] ?? true;
            return (
              <div key={cat} className="railfolder">
                <div className="rf-head" onClick={() => setOpenCat((o) => ({ ...o, [cat]: !isOpen }))}>
                  <span>{isOpen ? "▾" : "▸"}</span> {iconOf(cat)} {labelOf(cat)} <span className="rf-n">{items.length}</span>
                </div>
                {isOpen && items.map((m) => (
                  <div key={m.id} className="raillip" draggable
                       onDragStart={(e) => e.dataTransfer.setData("ip", m.id)}
                       title={(m.tapeout_ready ? "tape-out sign-off clean · " : "") + (m.sim_status === "pass" ? "testbench verified" : "")}>
                    <span className="rl-name">{m.tapeout_ready && <span className="vtick" title="tape-out ready">🏭</span>}{m.sim_status === "pass" && <span className="vtick">✓</span>}{m.name}</span>
                    <span className="rl-ports">{m.ports.filter(p => p.dir === "input").length}in / {m.ports.filter(p => p.dir === "output").length}out</span>
                  </div>
                ))}
              </div>
            );
          })}
          {!hardened.length && <div className="placeholder">No GDS-ready, TB-verified IPs yet. An IP appears here once it has both a hardened GDS macro and a passing testbench.</div>}
        </div>
      </aside>

      {/* ── padframe canvas ── */}
      <section className="studio-canvas">
        <div className="canvastop">
          <select value={fp?.id} onChange={async (e) => setFp(await api.getFloorplan(e.target.value))}>
            {fps.map((f) => <option key={f.id} value={f.id}>{f.name} ({f.blocks})</option>)}
          </select>
          <input className="fpname" value={fp?.name || ""} onChange={(e) => fp && setFp({ ...fp, name: e.target.value })} />
          <button className="btn-ghost sm" onClick={newFp}>＋ New</button>
          <span className="spacer" />
          {sel && <button className="btn-ghost sm" onClick={removeSel}>Remove block</button>}
          <button className="btn-primary sm" onClick={save}>💾 Save floorplan</button>
        </div>
        <div className="canvasframe" onDragOver={(e) => e.preventDefault()} onDrop={onDrop}>
          <svg ref={svgRef} viewBox={`0 0 ${VB} ${VB}`} className="chipsvg"
               onPointerMove={onPointerMove} onPointerUp={onPointerUp} onClick={() => setSel(null)}>
            {pf.image_url && <image href={pf.image_url} x={0} y={0} width={VB} height={VB} opacity={0.5} />}
            <rect x={2} y={2} width={VB - 4} height={VB - 4} className="diearea" />
            {fp?.placed.map((b) => <Block key={b.uid} b={b} selected={b.uid === sel}
              onDown={(e) => onPointerDown(e, b)} />)}
          </svg>
        </div>
      </section>

      {/* ── pinout / placed blocks ── */}
      <aside className="studio-net">
        <div className="raillabel">Floorplan ({fp?.placed.length || 0} blocks)</div>
        <div className="netlist">
          {fp?.placed.map((b) => (
            <div key={b.uid} className={"netblk" + (b.uid === sel ? " on" : "")} onClick={() => setSel(b.uid)}>
              <div className="nb-name">{b.name}</div>
              <div className="nb-ports">
                {b.ports.map((p, i) => (
                  <span key={i} className={"portchip " + p.dir}>{p.dir === "input" ? "→" : p.dir === "output" ? "←" : "↔"} {p.name}</span>
                ))}
              </div>
            </div>
          ))}
          {!fp?.placed.length && <div className="placeholder">Drag IP blocks onto the padframe. Each block shows its input/output pins.</div>}
        </div>
        <div className="studio-foot">{pf.source}</div>
      </aside>
    </div>
  );
}

function Block({ b, selected, onDown }: { b: PlacedBlock; selected: boolean; onDown: (e: React.PointerEvent) => void }) {
  const ins = b.ports.filter((p) => p.dir !== "output");
  const outs = b.ports.filter((p) => p.dir === "output");
  const pinY = (i: number, n: number) => 22 + ((b.h - 30) * (i + 0.5)) / Math.max(1, n);
  return (
    <g transform={`translate(${b.x} ${b.y})`} className={"chipblk" + (selected ? " sel" : "")} onPointerDown={onDown}>
      <rect width={b.w} height={b.h} rx={7} className="blkrect" />
      <text x={b.w / 2} y={15} textAnchor="middle" className="blktitle">{b.name}</text>
      {ins.slice(0, 8).map((p, i) => (
        <g key={"i" + i} transform={`translate(0 ${pinY(i, Math.min(ins.length, 8))})`}>
          <circle cx={0} cy={0} r={3} className="pin in" />
          <text x={6} y={3} className="pinlbl in">{p.name}</text>
        </g>
      ))}
      {outs.slice(0, 8).map((p, i) => (
        <g key={"o" + i} transform={`translate(${b.w} ${pinY(i, Math.min(outs.length, 8))})`}>
          <circle cx={0} cy={0} r={3} className="pin out" />
          <text x={-6} y={3} textAnchor="end" className="pinlbl out">{p.name}</text>
        </g>
      ))}
    </g>
  );
}
