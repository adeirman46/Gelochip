import csv
import json
import math
import re
import subprocess
from pathlib import Path

try:
    import matplotlib.pyplot as plt
except Exception as exc:
    raise SystemExit(f"matplotlib is required to generate plots: {exc}")

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config" / "iris_config.json").read_text())
RESULTS = ROOT / "results"
PRE = RESULTS / "prelayout"
PRE.mkdir(parents=True, exist_ok=True)


def cap_side_um(cap_pf: float) -> float:
    cap_f = cap_pf * 1e-12
    density_f_per_um2 = 2.0e-15
    return math.sqrt(cap_f / density_f_per_um2)


def render_template(pin_dbm: float, freq_hz: float, wave_csv: Path, rawfile: Path) -> str:
    template = (ROOT / "netlist" / "iris_pre_template.spice").read_text()
    pdk_root = (ROOT.parent / CONFIG["pdk_root"] / CONFIG["process"] / "libs.tech" / "ngspice").resolve()
    replacements = {
        "{PIN_DBM}": str(pin_dbm),
        "{FREQ_HZ}": f"{freq_hz}",
        "{LOAD_RES}": f"{CONFIG['load_res_ohm']}",
        "{LMATCH}": f"{CONFIG['matching_network']['series_inductor_h']}",
        "{CMATCH}": f"{CONFIG['matching_network']['shunt_cap_f']}",
        "{RDAMP}": f"{CONFIG['matching_network']['damping_res_ohm']}",
        "{MATCH_GAIN}": f"{CONFIG['matching_network']['effective_voltage_gain']}",
        "{DESIGN_INCLUDE}": str((pdk_root / "design.ngspice").resolve()),
        "{MODEL_LIB}": str((pdk_root / "sm141064.ngspice").resolve()),
        "{WAVE_CSV}": str(wave_csv.resolve()),
        "{RAWFILE}": str(rawfile.resolve()),
        "{CINJ_PF}": f"{CONFIG['rectifier']['inject_cap_pf']}",
        "{CSTAGE_PF}": f"{CONFIG['charge_pump']['stage_cap_pf']}",
        "{CSTORE_PF}": f"{CONFIG['charge_pump']['storage_cap_pf']}",
        "{BIAS_PMOS_W}": f"{CONFIG['rectifier']['bias_pmos_w_um']}",
        "{BIAS_PMOS_L}": f"{CONFIG['rectifier']['bias_pmos_l_um']}",
        "{BIAS_NMOS_W}": f"{CONFIG['rectifier']['bias_nmos_w_um']}",
        "{BIAS_NMOS_L}": f"{CONFIG['rectifier']['bias_nmos_l_um']}",
        "{RECT_PMOS_W}": f"{CONFIG['rectifier']['pmos_w_um']}",
        "{RECT_PMOS_L}": f"{CONFIG['rectifier']['pmos_l_um']}",
        "{RECT_PMOS_NF}": str(CONFIG['rectifier']['pmos_nf']),
        "{RECT_NMOS_W}": f"{CONFIG['rectifier']['nmos_w_um']}",
        "{RECT_NMOS_L}": f"{CONFIG['rectifier']['nmos_l_um']}",
        "{RECT_NMOS_NF}": str(CONFIG['rectifier']['nmos_nf']),
        "{CP_DIODE_W}": f"{CONFIG['charge_pump']['diode_w_um']}",
        "{CP_DIODE_L}": f"{CONFIG['charge_pump']['diode_l_um']}",
        "{CP_DIODE_NF}": str(CONFIG['charge_pump']['diode_nf']),
    }
    for key, value in replacements.items():
        template = template.replace(key, value)
    return template


def parse_measurements(log_text: str) -> dict:
    measures = {}
    for match in re.finditer(r"(^|\n)\s*([a-zA-Z0-9_]+)\s*=\s*([-+0-9.eE]+)", log_text):
        measures[match.group(2)] = float(match.group(3))
    return measures


def run_case(pin_dbm: float, freq_hz: float) -> dict:
    tag = f"f{int(freq_hz/1e6):03d}mhz_p{pin_dbm:+03.0f}dbm".replace("+", "p").replace("-", "m")
    deck = PRE / f"{tag}.spice"
    log = PRE / f"{tag}.log"
    wave_csv = PRE / f"{tag}_wave.csv"
    rawfile = PRE / f"{tag}.raw"
    deck.write_text(render_template(pin_dbm, freq_hz, wave_csv, rawfile))
    ngspice_bin = (ROOT.parent / CONFIG["ngspice_bin"]).resolve()
    proc = subprocess.run(
        [str(ngspice_bin), "-b", "-o", str(log), str(deck)],
        cwd=PRE,
        capture_output=True,
        text=True,
        check=False,
    )
    log_text = ""
    if log.exists():
        log_text += log.read_text(errors="ignore")
    log_text += proc.stdout + proc.stderr
    if proc.returncode != 0:
        raise RuntimeError(f"ngspice failed for {tag}\n{log_text}")
    measures = parse_measurements(log_text)
    pin_w = 1e-3 * (10 ** (pin_dbm / 10.0))
    vout = measures.get("vout_avg", float("nan"))
    pce = (vout * vout / CONFIG["load_res_ohm"] / pin_w) if pin_w > 0 and not math.isnan(vout) else float("nan")
    return {
        "case": tag,
        "freq_hz": freq_hz,
        "pin_dbm": pin_dbm,
        "pin_w": pin_w,
        "vrect_avg": measures.get("vrect_avg"),
        "vout_avg": vout,
        "vout_max": measures.get("vout_max"),
        "pce": pce,
        "deck": str(deck.relative_to(ROOT)),
        "log": str(log.relative_to(ROOT)),
        "wave_csv": str(wave_csv.relative_to(ROOT)),
        "rawfile": str(rawfile.relative_to(ROOT)),
    }


def write_summary(rows: list[dict]) -> None:
    csv_path = RESULTS / "prelayout_summary.csv"
    json_path = RESULTS / "prelayout_summary.json"
    fieldnames = [
        "case", "freq_hz", "pin_dbm", "pin_w", "vrect_avg", "vout_avg", "vout_max", "pce", "deck", "log", "wave_csv", "rawfile"
    ]
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    thresholds = {}
    for freq_hz in CONFIG["frequency_sweep_hz"]:
        qualifying = [row for row in rows if row["freq_hz"] == freq_hz and (row["vout_avg"] or 0) >= 1.2]
        thresholds[str(int(freq_hz))] = min((row["pin_dbm"] for row in qualifying), default=None)
    json_path.write_text(json.dumps({"results": rows, "thresholds_dbm": thresholds}, indent=2))


def plot(rows: list[dict]) -> None:
    freqs = CONFIG["frequency_sweep_hz"]
    fig, axes = plt.subplots(2, 1, figsize=(8, 10), dpi=150)
    for freq_hz in freqs:
        freq_rows = sorted((row for row in rows if row["freq_hz"] == freq_hz), key=lambda row: row["pin_dbm"])
        x = [row["pin_dbm"] for row in freq_rows]
        axes[0].plot(x, [row["vout_avg"] for row in freq_rows], marker="o", label=f"{freq_hz/1e6:.0f} MHz")
        axes[1].plot(x, [100 * row["pce"] for row in freq_rows], marker="o", label=f"{freq_hz/1e6:.0f} MHz")
    axes[0].axhline(1.2, color="tab:red", linestyle="--", linewidth=1.0, label="1.2 V target")
    axes[0].set_xlabel("Input power (dBm)")
    axes[0].set_ylabel("Average output voltage (V)")
    axes[0].grid(True, alpha=0.3)
    axes[0].legend()
    axes[1].set_xlabel("Input power (dBm)")
    axes[1].set_ylabel("Estimated PCE (%)")
    axes[1].grid(True, alpha=0.3)
    axes[1].legend()
    fig.tight_layout()
    fig.savefig(RESULTS / "prelayout_summary.png")
    plt.close(fig)

    target = sorted(rows, key=lambda row: (abs(row["freq_hz"] - CONFIG["target_frequency_hz"]), abs(row["pin_dbm"])))
    if not target:
        return
    best = target[0]
    wave_path = ROOT / best["wave_csv"]
    time_s = []
    vout = []
    with wave_path.open() as handle:
        for line in handle:
            parts = [part for part in line.strip().split() if part]
            if len(parts) >= 4:
                try:
                    time_s.append(float(parts[0]))
                    vout.append(float(parts[3]))
                except ValueError:
                    continue
    if not time_s:
        return
    window = [(t, v) for t, v in zip(time_s, vout) if t >= max(time_s) - 5e-6]
    fig, ax = plt.subplots(figsize=(8, 4), dpi=150)
    ax.plot([item[0] * 1e6 for item in window], [item[1] for item in window], color="tab:blue")
    ax.set_xlabel("Time (us)")
    ax.set_ylabel("Vout (V)")
    ax.set_title(f"IRIS output waveform at {best['freq_hz']/1e6:.0f} MHz, {best['pin_dbm']} dBm")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(RESULTS / "prelayout_waveform.png")
    plt.close(fig)


if __name__ == "__main__":
    rows = []
    for freq_hz in CONFIG["frequency_sweep_hz"]:
        for pin_dbm in CONFIG["power_sweep_dbm"]:
            rows.append(run_case(pin_dbm, freq_hz))
    write_summary(rows)
    plot(rows)
    print(json.dumps(rows, indent=2))
