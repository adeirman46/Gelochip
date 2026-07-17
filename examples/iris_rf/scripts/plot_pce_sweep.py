"""Plot PCE vs R_load from the partial sweep, save PNG."""
import json
from pathlib import Path
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
data = json.loads((ROOT / "results" / "pce_sweep_partial.json").read_text())

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.6), dpi=170)

for f in [30, 60, 100]:
    rows = [r for r in data if r["freq_mhz"] == f]
    rows.sort(key=lambda r: r["r_load"])
    if not rows: continue
    Rs = [r["r_load"] for r in rows]
    Vs = [r["vout_avg"] for r in rows]
    Ps = [100*r["pce"] for r in rows]
    ax1.plot(Rs, Ps, "o-", label=f"{f} MHz", lw=1.8)
    ax2.plot(Rs, Vs, "o-", label=f"{f} MHz", lw=1.8)

for ax, ylabel, title in [(ax1, "PCE (%)", "PCE vs Load Resistance (Pin = 0 dBm)"),
                          (ax2, "V_out (V)", "V_out vs Load Resistance (Pin = 0 dBm)")]:
    ax.set_xscale("log")
    ax.set_xlabel("R_load (Ω)")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(True, which="both", alpha=0.3)
    ax.legend()

ax2.axhline(1.2, color="red", ls="--", lw=1, alpha=0.7)
ax2.text(1e3, 1.22, "V_out target = 1.2 V", color="red", fontsize=9)

fig.tight_layout()
out = ROOT / "results" / "pce_sweep_summary.png"
fig.savefig(out)
print("wrote", out)
