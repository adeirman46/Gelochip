"""Quick PCE optimization sweep for IRIS rectifier.

Approach: keep circuit topology from iris_pre_template.spice but sweep
load resistance (100 Ω to 10 MΩ) at each frequency (30/60/100 MHz) and 0 dBm
input, to find the R_load that maximizes PCE.

Writes: results/pce_sweep_summary.json + .csv + .png
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
NGSPICE = ROOT.parent / CONFIG["ngspice_bin"] if not Path(CONFIG["ngspice_bin"]).is_absolute() else Path(CONFIG["ngspice_bin"])
if not NGSPICE.exists():
    # fallback to system
    NGSPICE = Path("ngspice")

TEMPLATE = (ROOT / "netlist" / "iris_pre_template.spice").read_text()
PDKS = ROOT.parent / CONFIG["pdk_root"]
NGSPICE_DIR = PDKS / CONFIG["process"] / "libs.tech" / "ngspice"
MODELS_LIB = NGSPICE_DIR / "sm141064.ngspice"
DESIGN_INC = NGSPICE_DIR / "design.ngspice"

OUT = ROOT / "results" / "pce_sweep"
OUT.mkdir(parents=True, exist_ok=True)

# design params from config
match = CONFIG["matching_network"]
rect = CONFIG["rectifier"]
pump = CONFIG["charge_pump"]


def render(freq_hz, pin_dbm, r_load, tag):
    d = {
        "PIN_DBM": f"{pin_dbm}",
        "FREQ_HZ": f"{freq_hz:.6g}",
        "LOAD_RES": f"{r_load:.6g}",
        "LMATCH": f"{match['series_inductor_h']:.6g}",
        "CMATCH": f"{match['shunt_cap_f']:.6g}",
        "RDAMP": f"{match['damping_res_ohm']:.6g}",
        "MATCH_GAIN": f"{match['effective_voltage_gain']:.6g}",
        "DESIGN_INCLUDE": str(DESIGN_INC),
        "MODEL_LIB": str(MODELS_LIB),
        "WAVE_CSV": str(OUT / f"{tag}_wave.csv"),
        "RAWFILE": str(OUT / f"{tag}.raw"),
        "CINJ_PF": f"{rect['inject_cap_pf']:.6g}",
        "BIAS_PMOS_W": f"{rect['bias_pmos_w_um']:.6g}",
        "BIAS_PMOS_L": f"{rect['bias_pmos_l_um']:.6g}",
        "BIAS_NMOS_W": f"{rect['bias_nmos_w_um']:.6g}",
        "BIAS_NMOS_L": f"{rect['bias_nmos_l_um']:.6g}",
        "RECT_PMOS_W": f"{rect['pmos_w_um']:.6g}",
        "RECT_PMOS_L": f"{rect['pmos_l_um']:.6g}",
        "RECT_PMOS_NF": f"{rect['pmos_nf']}",
        "RECT_NMOS_W": f"{rect['nmos_w_um']:.6g}",
        "RECT_NMOS_L": f"{rect['nmos_l_um']:.6g}",
        "RECT_NMOS_NF": f"{rect['nmos_nf']}",
        "CP_DIODE_W": f"{pump['diode_w_um']:.6g}",
        "CP_DIODE_L": f"{pump['diode_l_um']:.6g}",
        "CP_DIODE_NF": f"{pump['diode_nf']}",
        "CSTAGE_PF": f"{pump['stage_cap_pf']:.6g}",
        "CSTORE_PF": f"{pump['storage_cap_pf']:.6g}",
    }
    out = TEMPLATE
    for k, v in d.items():
        out = out.replace("{" + k + "}", v)
    return out


def run_one(freq_hz, pin_dbm, r_load, tag):
    deck = render(freq_hz, pin_dbm, r_load, tag)
    deck_path = OUT / f"{tag}.spice"
    log_path = OUT / f"{tag}.log"
    deck_path.write_text(deck)
    with log_path.open("w") as lf:
        rc = subprocess.run([str(NGSPICE), "-b", "-o", str(log_path), str(deck_path)],
                            stdout=lf, stderr=subprocess.STDOUT).returncode
    text = log_path.read_text(errors="ignore")

    def grab(name):
        m = re.search(rf"{name}\s*=\s*([-+0-9.eE]+)", text)
        return float(m.group(1)) if m else None

    vout_avg = grab("vout_avg")
    vrect_avg = grab("vrect_avg")
    vout_max = grab("vout_max")
    pin_w = 1e-3 * 10 ** (pin_dbm / 10)
    pce = None
    if vout_avg is not None and pin_w > 0:
        pce = (vout_avg ** 2) / r_load / pin_w
    return {
        "freq_hz": freq_hz,
        "pin_dbm": pin_dbm,
        "r_load": r_load,
        "vrect_avg": vrect_avg,
        "vout_avg": vout_avg,
        "vout_max": vout_max,
        "pin_w": pin_w,
        "pce": pce,
        "rc": rc,
        "log": str(log_path),
    }


def main():
    freqs = [30e6, 45e6, 60e6]
    r_loads = [1e3, 3e3, 1e4, 3e4, 1e5, 3e5, 1e6, 3e6, 1e7]
    results = []
    for f in freqs:
        for R in r_loads:
            tag = f"f{int(f/1e6):03d}mhz_R{int(R)}"
            row = run_one(f, 0, R, tag)
            print(tag, "Vout=", row["vout_avg"], "PCE=", row["pce"])
            results.append(row)

    (ROOT / "results" / "pce_sweep_summary.json").write_text(json.dumps({"results": results}, indent=2))

    # csv
    with (ROOT / "results" / "pce_sweep_summary.csv").open("w", newline="") as fp:
        w = csv.writer(fp)
        w.writerow(["freq_hz", "pin_dbm", "r_load", "vrect_avg", "vout_avg", "pce"])
        for r in results:
            w.writerow([r["freq_hz"], r["pin_dbm"], r["r_load"], r["vrect_avg"], r["vout_avg"], r["pce"]])

    # plot
    fig, ax = plt.subplots(figsize=(9, 5), dpi=160)
    for f in freqs:
        xs = [r["r_load"] for r in results if r["freq_hz"] == f and r["pce"] is not None]
        ys = [100 * r["pce"] for r in results if r["freq_hz"] == f and r["pce"] is not None]
        ax.plot(xs, ys, "o-", label=f"{f/1e6:.0f} MHz")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("R_load (Ω)")
    ax.set_ylabel("PCE (%)")
    ax.set_title("PCE vs Load Resistance @ 0 dBm")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(ROOT / "results" / "pce_sweep_summary.png")
    print("done")


if __name__ == "__main__":
    main()
