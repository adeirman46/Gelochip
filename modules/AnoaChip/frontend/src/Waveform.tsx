import type { Waveform as Wave, WaveSignal } from "./types";

// Render a parsed VCD as digital traces — 1-bit signals as high/low step lines, multi-bit
// buses as hex-labelled bus shapes. Pure SVG (no GTKWave); scales to the time window.
const ROW = 34;          // px per signal row
const LABEL_W = 150;     // left label gutter
const PAD = 8;

function bitTrace(sig: WaveSignal, x: (t: number) => number, tmax: number): string {
  const top = PAD + 4, bot = ROW - PAD;
  let d = "";
  let prev = sig.wave[0]?.[1] ?? 0;
  let py = prev ? top : bot;
  d += `M ${x(0)} ${py}`;
  for (const [t, v] of sig.wave) {
    const y = v ? top : bot;
    d += ` L ${x(t)} ${py} L ${x(t)} ${y}`;
    py = y;
  }
  d += ` L ${x(tmax)} ${py}`;
  return d;
}

function BusTrace({ sig, x, tmax }: { sig: WaveSignal; x: (t: number) => number; tmax: number }) {
  const top = PAD + 2, mid = ROW / 2, bot = ROW - PAD;
  const segs: JSX.Element[] = [];
  const labels: JSX.Element[] = [];
  for (let i = 0; i < sig.wave.length; i++) {
    const [t, v] = sig.wave[i];
    const t2 = i + 1 < sig.wave.length ? sig.wave[i + 1][0] : tmax;
    if (t2 <= t) continue;
    const x1 = x(t), x2 = x(t2);
    segs.push(<polygon key={i} className="busseg"
      points={`${x1 + 3},${mid} ${x1 + 6},${top} ${x2 - 6},${top} ${x2 - 3},${mid} ${x2 - 6},${bot} ${x1 + 6},${bot}`} />);
    if (x2 - x1 > 26) labels.push(
      <text key={"l" + i} className="buslbl" x={(x1 + x2) / 2} y={mid + 3.5} textAnchor="middle">
        {v == null ? "x" : v.toString(16)}
      </text>);
  }
  return <>{segs}{labels}</>;
}

export function WaveformView({ wave }: { wave: Wave }) {
  if (!wave.signals.length) return <div className="placeholder">No signals dumped.</div>;
  const tmax = wave.tmax || 1;
  const W = 900;
  const plotW = W - LABEL_W - 16;
  const x = (t: number) => LABEL_W + 8 + (t / tmax) * plotW;
  const H = wave.signals.length * ROW + 24;

  return (
    <div className="waveform">
      <svg viewBox={`0 0 ${W} ${H}`} className="wavesvg" preserveAspectRatio="xMinYMin meet">
        {wave.signals.map((s, i) => {
          const y = i * ROW;
          return (
            <g key={i} transform={`translate(0 ${y})`}>
              {i % 2 === 0 && <rect className="waverow" x={0} y={0} width={W} height={ROW} />}
              <line className="wavegrid" x1={LABEL_W} y1={0} x2={LABEL_W} y2={ROW} />
              <text className="wavelabel" x={LABEL_W - 8} y={ROW / 2 + 4} textAnchor="end">
                {s.name}{s.width > 1 ? `[${s.width - 1}:0]` : ""}
              </text>
              {s.width > 1 ? <BusTrace sig={s} x={x} tmax={tmax} /> :
                <path className="wavebit" d={bitTrace(s, x, tmax)} />}
            </g>
          );
        })}
        <text className="waveaxis" x={LABEL_W + 8} y={H - 6}>0</text>
        <text className="waveaxis" x={W - 8} y={H - 6} textAnchor="end">{tmax} ns</text>
      </svg>
    </div>
  );
}
