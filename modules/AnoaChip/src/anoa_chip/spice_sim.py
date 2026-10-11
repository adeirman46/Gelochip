"""ngspice testbench runner + analog spec extraction for AnoaChip.

This is the analog "simulation" stage (what iverilog+VCD was for GarudaChip):

  • run_ngspice(tb)          — batch ngspice with the PDK models on the path
  • parse_measures(log)      — every `.measure` result (`name = value`) as floats
  • ac_metrics(wrdata file)  — gain_db / f3db_hz / ugbw_hz / phase_margin_deg
                               computed with numpy from a `wrdata` AC export
  • plot_bode / plot_tran    — PNG plots (matplotlib Agg) the UI can show
  • check_specs(metrics, spec) — pass/fail table against the design's config
                               spec block (gain_db >= X, bw_hz >= Y, ...)

Testbench contract (what the agent is told to write in tb/<name>_tb.sp):
  - include the DUT netlist relative to the design dir:  .include ../netlist/<name>.sp
  - the PDK model .lib line is INJECTED automatically if missing
  - use `.measure` for point specs and `wrdata sim/<name>_ac.txt vdb(out) vp(out)`
    style exports for curves, then AnoaChip computes/plots the rest.
"""
from __future__ import annotations

import math
import os
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

_SIM_TIMEOUT = int(os.getenv("ANOA_SIM_TIMEOUT_S", "600"))

# AnoaChip's own EDA env (built by scripts/install.sh via micromamba) — used so a
# clone runs ngspice without depending on any system/sibling install.
_ANOA_EDA_BIN = Path(__file__).resolve().parents[2] / ".tools" / "eda" / "bin"


def _ngspice_bin() -> str:
    """Resolve ngspice independently: NGSPICE_BIN override, then AnoaChip's own
    .tools/eda/bin, else the bare name (whatever is on PATH)."""
    env = os.getenv("NGSPICE_BIN")
    if env:
        return env
    cand = _ANOA_EDA_BIN / "ngspice"
    return str(cand) if cand.exists() else "ngspice"


# --------------------------------------------------------------------------- #
#  PDK model library
# --------------------------------------------------------------------------- #
def pdk_lib_line(pdk: str | None = None) -> str:
    """Return the ngspice .lib line for the active PDK ('' if not found)."""
    pdk = (pdk or os.getenv("PDK", "gf180mcuD")).lower()
    pdk_root = Path(os.getenv("PDK_ROOT", str(Path.home() / "pdks")))
    if pdk.startswith("sky130"):
        lib = pdk_root / "sky130A" / "libs.tech" / "ngspice" / "sky130.lib.spice"
        if lib.exists():
            return f".lib {lib} tt"
    if pdk.startswith("gf180"):
        lib = pdk_root / "gf180mcuD" / "libs.tech" / "ngspice" / "sm141064.ngspice"
        if lib.exists():
            return f".lib {lib} typical"
    return ""


def _inject_lib(deck: str, pdk: str | None = None) -> str:
    """Ensure the PDK .lib is in the deck (idempotent) — plus the statistical switch
    params gf180's sm141064.ngspice REQUIRES before it is read: without
    `.param sw_stat_global=0 sw_stat_mismatch=0` ngspice dies with
    'Undefined parameter [sw_stat_mismatch]' (the v8 post-layout crash)."""
    pdk_l = (pdk or os.getenv("PDK", "gf180mcuD")).lower()
    extra: list = []
    if pdk_l.startswith("gf180"):
        # design.ngspice = GF's own "global switches + corner parameters" include — it
        # defines sw_stat_* AND the noise params (nfet_03v3_noia…) the models reference.
        # Without it ngspice dies on 'Undefined parameter'. Include it FIRST.
        dsn = Path(os.getenv("PDK_ROOT", str(Path.home() / "pdks"))) \
            / "gf180mcuD" / "libs.tech" / "ngspice" / "design.ngspice"
        if dsn.exists():
            if str(dsn) not in deck:
                extra.append(f".include {dsn}")
        else:                                   # fallback: at least the stat switches
            for prm in ("sw_stat_global", "sw_stat_mismatch"):
                if not re.search(rf"^\s*\.param\s+{prm}\b", deck, re.MULTILINE | re.IGNORECASE):
                    extra.append(f".param {prm} = 0")
    lines = deck.split("\n")
    if re.search(r"^\s*\.lib\s", deck, re.MULTILINE | re.IGNORECASE):
        if not extra:
            return deck
        # params must appear BEFORE the .lib that uses them — put them after the title
        return "\n".join([lines[0]] + extra + lines[1:]) if lines else deck
    lib = pdk_lib_line(pdk)
    if not lib:
        return deck
    # after the title line: params first, then the .lib
    return "\n".join([lines[0]] + extra + [lib] + lines[1:]) if lines \
        else "\n".join(extra + [lib, deck])


# --------------------------------------------------------------------------- #
#  run
# --------------------------------------------------------------------------- #
def run_ngspice(tb_path: str | Path, workdir: str | Path | None = None,
                timeout: int = 0, pdk: str | None = None) -> Tuple[bool, str]:
    """Run one testbench in batch mode. Returns (ok, combined_log).

    ok = process exited 0 AND the log has no fatal 'Error:' lines. The tb runs
    with cwd = its design dir so relative .include/.wrdata paths resolve there.
    """
    tb = Path(tb_path).resolve()
    cwd = Path(workdir).resolve() if workdir else tb.parent.parent  # design dir
    timeout = timeout or _SIM_TIMEOUT
    ngspice = _ngspice_bin()

    deck = tb.read_text()
    fixed = _inject_lib(deck, pdk)
    if fixed != deck:
        tb.write_text(fixed)

    (cwd / "sim").mkdir(parents=True, exist_ok=True)
    before = set(p.name for p in cwd.iterdir()) if cwd.exists() else set()
    try:
        proc = subprocess.run([ngspice, "-b", str(tb)], capture_output=True,
                              text=True, timeout=timeout, cwd=str(cwd))
    except FileNotFoundError:
        return False, "ngspice not found — install it (sudo apt install ngspice)"
    except subprocess.TimeoutExpired:
        return False, f"ngspice timed out after {timeout}s"
    # DEFENSIVE CLEANUP: a testbench with a stray `>`/`<`/`->` in an echo makes ngspice
    # redirect output to junk files named after the value (=40, 1M, FAIL, …). Delete any
    # value-shaped file the run created in the design dir so it never pollutes the output.
    _junk = re.compile(r"^([=<>].*|-?[0-9][0-9.eE+\-]*[a-zA-Z%]*|PASS|FAIL|->)$")
    try:
        for name in set(p.name for p in cwd.iterdir()) - before:
            if _junk.match(name):
                (cwd / name).unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass
    log = (proc.stdout or "") + ("\n[stderr]\n" + proc.stderr if proc.stderr else "")
    fatal = [ln for ln in log.splitlines()
             if re.match(r"\s*Error", ln, re.IGNORECASE)
             and "analysis not" not in ln.lower()]
    ok = proc.returncode == 0 and not fatal
    return ok, log[-24000:]


# --------------------------------------------------------------------------- #
#  measurements
# --------------------------------------------------------------------------- #
_MEAS_RE = re.compile(r"^\s*([a-zA-Z_][\w]*)\s*=\s*([-+0-9.eE]+)", re.MULTILINE)


def parse_measures(log: str) -> Dict[str, float]:
    """Every `.measure` result printed by ngspice as {name: float}."""
    out: Dict[str, float] = {}
    for m in _MEAS_RE.finditer(log or ""):
        name, val = m.group(1).lower(), m.group(2)
        try:
            out[name] = float(val)
        except ValueError:
            continue
    return out


def _read_wrdata(path: str | Path) -> np.ndarray:
    """Load an ngspice `wrdata` export (whitespace columns) as a 2-D array."""
    return np.loadtxt(str(path), ndmin=2)


def ac_metrics(wrdata_path: str | Path) -> Dict[str, float]:
    """Compute the classic AC specs from a wrdata export.

    Expected columns (ngspice writes x-value before each vector):
      freq vdb(out) [freq vp(out)]      →  gain, bandwidth, UGBW, phase margin
    Falls back gracefully if only magnitude was exported.
    """
    d = _read_wrdata(wrdata_path)
    f = d[:, 0]
    gdb = d[:, 1]
    metrics: Dict[str, float] = {}
    if len(f) < 3:
        return metrics
    dc_gain = float(gdb[0])
    metrics["gain_db"] = dc_gain
    # -3 dB bandwidth
    below = np.where(gdb <= dc_gain - 3.0)[0]
    if below.size:
        i = below[0]
        if i > 0:   # log-interpolate the crossing
            x = np.interp(dc_gain - 3.0, [gdb[i], gdb[i - 1]],
                          [math.log10(f[i]), math.log10(f[i - 1])])
            metrics["bw_hz"] = float(10 ** x)
        else:
            metrics["bw_hz"] = float(f[i])
    # unity-gain frequency
    zero = np.where(gdb <= 0.0)[0]
    if zero.size and zero[0] > 0:
        i = zero[0]
        x = np.interp(0.0, [gdb[i], gdb[i - 1]],
                      [math.log10(f[i]), math.log10(f[i - 1])])
        metrics["ugbw_hz"] = float(10 ** x)
    # phase margin if a phase column is present (deg or rad; wrdata repeats x)
    if d.shape[1] >= 4:
        ph = d[:, 3]
        if np.nanmax(np.abs(ph)) < 7:      # radians → degrees
            ph = np.degrees(ph)
        if "ugbw_hz" in metrics:
            phase_at_ug = float(np.interp(math.log10(metrics["ugbw_hz"]),
                                          np.log10(f), ph))
            metrics["phase_margin_deg"] = 180.0 + phase_at_ug if phase_at_ug < 0 \
                else phase_at_ug
    return metrics


# --------------------------------------------------------------------------- #
#  plots (the analog "waveform viewer")
# --------------------------------------------------------------------------- #
def plot_bode(wrdata_path: str | Path, out_png: str | Path,
              title: str = "AC response") -> str | None:
    """Gain(+phase) Bode PNG from a wrdata AC export. Returns the png path."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        d = _read_wrdata(wrdata_path)
        f, gdb = d[:, 0], d[:, 1]
        has_ph = d.shape[1] >= 4
        fig, axes = plt.subplots(2 if has_ph else 1, 1, figsize=(7, 5.5 if has_ph else 3.4),
                                 sharex=True)
        ax0 = axes[0] if has_ph else axes
        ax0.semilogx(f, gdb, lw=1.6)
        ax0.axhline(0, color="gray", lw=0.6, ls="--")
        ax0.set_ylabel("Gain (dB)")
        ax0.grid(True, which="both", alpha=0.3)
        ax0.set_title(title)
        if has_ph:
            ph = d[:, 3]
            if np.nanmax(np.abs(ph)) < 7:
                ph = np.degrees(ph)
            axes[1].semilogx(f, ph, lw=1.4, color="tab:orange")
            axes[1].set_ylabel("Phase (°)")
            axes[1].set_xlabel("Frequency (Hz)")
            axes[1].grid(True, which="both", alpha=0.3)
        else:
            ax0.set_xlabel("Frequency (Hz)")
        fig.tight_layout()
        fig.savefig(out_png, dpi=110)
        plt.close(fig)
        return str(out_png)
    except Exception:  # noqa: BLE001
        return None


def plot_tran(wrdata_path: str | Path, out_png: str | Path,
              title: str = "Transient") -> str | None:
    """Time-domain PNG from a wrdata tran export (t v1 [t v2 ...])."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        d = _read_wrdata(wrdata_path)
        fig, ax = plt.subplots(figsize=(7, 3.4))
        n = d.shape[1]
        for k in range(0, n - 1, 2):
            ax.plot(d[:, k], d[:, k + 1], lw=1.3, label=f"v{k // 2 + 1}")
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("V")
        ax.grid(True, alpha=0.3)
        ax.set_title(title)
        if n > 2:
            ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(out_png, dpi=110)
        plt.close(fig)
        return str(out_png)
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------------------- #
#  spec verdict
# --------------------------------------------------------------------------- #
_SPEC_OPS = {
    ">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b, "<": lambda a, b: a < b,
    "==": lambda a, b: abs(a - b) <= 0.05 * max(abs(b), 1e-30),
}


def check_specs(metrics: Dict[str, float], spec: dict) -> List[dict]:
    """Compare measured metrics against the config's spec block.

    spec entries look like {"gain_db": {"min": 40}, "bw_hz": {"min": 1e6},
    "power_w": {"max": 1e-3}, "phase_margin_deg": {"min": 60}} or the compact
    string form {"gain_db": ">= 40"}. Returns one row per spec:
    {name, target, measured, pass}.
    """
    rows: List[dict] = []
    for name, want in (spec or {}).items():
        got = metrics.get(name.lower())
        # UNMEASURED spec → pass=None (rendered '–', NOT counted as FAIL): a spec the tb
        # didn't measure — or that doesn't apply to this topology (gain_db on a current
        # mirror) — must not paint the whole verdict table red.
        row = {"name": name, "measured": got, "target": want, "pass": None}
        if got is None:
            row["target"] = _spec_str(want)
            rows.append(row)
            continue
        ok = True
        judged = False
        if isinstance(want, dict):
            if "min" in want:
                ok &= got >= float(want["min"])
                judged = True
            if "max" in want:
                ok &= got <= float(want["max"])
                judged = True
            row["target"] = _spec_str(want)
        elif isinstance(want, str):
            m = re.match(r"\s*(>=|<=|==|>|<)\s*([-+0-9.eE]+)", want)
            if m:
                ok = _SPEC_OPS[m.group(1)](got, float(m.group(2)))
                judged = True
        else:  # bare number = minimum
            try:
                ok = got >= float(want)
                judged = True
            except (TypeError, ValueError):
                pass
        row["pass"] = bool(ok) if judged else None   # descriptive text row → '–'
        rows.append(row)
    return rows


def _spec_str(want) -> str:
    if isinstance(want, dict):
        parts = []
        if "min" in want:
            parts.append(f">= {want['min']}")
        if "max" in want:
            parts.append(f"<= {want['max']}")
        return " and ".join(parts) or str(want)
    return str(want)


def specs_pass(rows: List[dict]) -> bool:
    """PASS = every JUDGED spec passed (pass=None rows are unmeasured/descriptive — they
    don't fail the run) and at least one spec was actually judged."""
    judged = [r for r in rows if r.get("pass") is not None]
    return bool(judged) and all(r["pass"] for r in judged)


def spec_table(rows: List[dict]) -> str:
    """Human/LLM-readable verdict table ('–' = not measured / not applicable)."""
    if not rows:
        return "(no specs defined in config)"
    out = ["spec              target            measured        verdict"]
    for r in rows:
        meas = "-" if r["measured"] is None else f"{r['measured']:.6g}"
        verdict = "-" if r.get("pass") is None else ("PASS ✓" if r["pass"] else "FAIL ✗")
        out.append(f"{r['name']:<17} {str(r['target']):<17} {meas:<15} {verdict}")
    return "\n".join(out)
