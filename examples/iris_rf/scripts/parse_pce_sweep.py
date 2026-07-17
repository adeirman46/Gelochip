"""Parse whatever pce_sweep logs exist, print summary, save JSON."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SWEEP = ROOT / "results" / "pce_sweep"

def parse_log(path):
    txt = path.read_text(errors="ignore")
    def grab(name):
        m = re.search(rf"{name}\s*=\s*([-+0-9.eE]+)", txt)
        return float(m.group(1)) if m else None
    return grab("vout_avg"), grab("vrect_avg"), grab("vout_max")

rows = []
for log in sorted(SWEEP.glob("*.log")):
    if log.name.startswith("test"):
        continue
    m = re.match(r"f(\d+)mhz_R(\d+)\.log", log.name)
    if not m:
        continue
    fmhz = int(m.group(1))
    r = int(m.group(2))
    vout, vrect, vmax = parse_log(log)
    if vout is None:
        continue
    pin_w = 1e-3   # 0 dBm
    pce = vout*vout / r / pin_w
    rows.append({"freq_mhz": fmhz, "r_load": r, "vout_avg": vout, "vrect_avg": vrect, "vout_max": vmax, "pce": pce})

rows.sort(key=lambda x: (x["freq_mhz"], x["r_load"]))
print(f"{'FreqMHz':>8} {'R_load':>10} {'Vout(V)':>10} {'Vrect(V)':>10} {'PCE(%)':>10}")
for r in rows:
    print(f"{r['freq_mhz']:>8} {r['r_load']:>10} {r['vout_avg']:>10.4f} {r['vrect_avg']:>10.4f} {100*r['pce']:>10.4f}")

(ROOT / "results" / "pce_sweep_partial.json").write_text(json.dumps(rows, indent=2))
print(f"\nsaved {len(rows)} entries")

# Find best per-frequency
by_f = {}
for r in rows:
    f = r["freq_mhz"]
    if f not in by_f or r["pce"] > by_f[f]["pce"]:
        by_f[f] = r
print("\nBest per-frequency:")
for f, r in sorted(by_f.items()):
    print(f"  {f} MHz: R={r['r_load']:>8} Ω, Vout={r['vout_avg']:.3f} V, PCE={100*r['pce']:.4f}%")
