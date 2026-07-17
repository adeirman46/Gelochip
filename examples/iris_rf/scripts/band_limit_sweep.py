"""v3: Frequency-vs-Vout rolloff sweep to find the true upper operating limit
(highest frequency at Pin=0 dBm where Vout >= 1.2 V is still achieved).

Sweep list is taken from CONFIG['band_limit_sweep_hz']; simulation uses the
same pre-layout SPICE template so results are directly comparable to the
prelayout summary already in the report.
"""
import csv
import json
import math
import re
import subprocess
from pathlib import Path

import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config" / "iris_config.json").read_text())
RESULTS = ROOT / "results"
BLIM = RESULTS / "band_limit"
BLIM.mkdir(parents=True, exist_ok=True)

# reuse render_template from run_prelayout without importing (paths differ)
import importlib.util
spec = importlib.util.spec_from_file_location("run_prelayout", ROOT / "scripts" / "run_prelayout.py")
run_prelayout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_prelayout)


def parse(log_text: str):
    measures = {}
    for match in re.finditer(r"(^|\n)\s*([a-zA-Z0-9_]+)\s*=\s*([-+0-9.eE]+)", log_text):
        measures[match.group(2)] = float(match.group(3))
    return measures


def run_case(freq_hz: float, pin_dbm: float = 0.0) -> dict:
    tag = f"bl_f{int(freq_hz/1e6):03d}mhz_p{pin_dbm:+03.0f}dbm".replace("+", "p").replace("-", "m")
    deck = BLIM / f"{tag}.spice"
    log_path = BLIM / f"{tag}.log"
    wave_csv = BLIM / f"{tag}_wave.csv"
    raw = BLIM / f"{tag}.raw"
    deck.write_text(run_prelayout.render_template(pin_dbm, freq_hz, wave_csv, raw))
    ngspice = (ROOT.parent / CONFIG["ngspice_bin"]).resolve()
    proc = subprocess.run([str(ngspice), "-b", "-o", str(log_path), str(deck)],
                          cwd=BLIM, capture_output=True, text=True, check=False)
    log_text = log_path.read_text(errors="ignore") if log_path.exists() else ""
    log_text += proc.stdout + proc.stderr
    if proc.returncode != 0:
        raise RuntimeError(f"ngspice failed for {tag}: {log_text[-2000:]}")
    m = parse(log_text)
    pin_w = 1e-3 * 10 ** (pin_dbm / 10.0)
    vout = m.get("vout_avg", float("nan"))
    pce = vout * vout / CONFIG["load_res_ohm"] / pin_w if pin_w > 0 and not math.isnan(vout) else float("nan")
    return {
        "case": tag,
        "freq_hz": freq_hz,
        "pin_dbm": pin_dbm,
        "vrect_avg": m.get("vrect_avg"),
        "vout_avg": vout,
        "vout_max": m.get("vout_max"),
        "pce": pce,
    }


def main():
    freqs = CONFIG.get("band_limit_sweep_hz", [])
    if not freqs:
        raise SystemExit("band_limit_sweep_hz not set in config")
    rows = [run_case(f, 0.0) for f in freqs]
    csv_path = RESULTS / "band_limit_summary.csv"
    json_path = RESULTS / "band_limit_summary.json"
    with csv_path.open("w", newline="") as h:
        w = csv.DictWriter(h, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    passed = [r for r in rows if (r["vout_avg"] or 0) >= 1.2]
    upper = max((r["freq_hz"] for r in passed), default=None)
    summary = {"results": rows, "upper_operating_hz": upper}
    json_path.write_text(json.dumps(summary, indent=2))
    # plot
    xs = [r["freq_hz"] / 1e6 for r in rows]
    ys = [r["vout_avg"] for r in rows]
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=150)
    ax.plot(xs, ys, marker="o", color="tab:blue", linewidth=2)
    ax.axhline(1.2, color="tab:red", linestyle="--", linewidth=1.0, label="1.2 V spec")
    if upper is not None:
        ax.axvline(upper / 1e6, color="tab:green", linestyle=":", linewidth=1.5,
                   label=f"Upper limit ~ {upper/1e6:.0f} MHz")
    ax.set_xlabel("Frequency (MHz)")
    ax.set_ylabel("Vout (V) @ 0 dBm")
    ax.set_title("IRIS Vout rolloff vs frequency (Pin = 0 dBm, pre-layout)")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(RESULTS / "band_limit_rolloff.png")
    plt.close(fig)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
