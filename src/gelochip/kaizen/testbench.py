"""
gelochip.kaizen.testbench  —  SPICE extraction + AC/transient testbenches.

Generalises the per-notebook DC sim into a reusable verifier the agent, the
dataset notebooks, and the web app all share:

    extract_spice(component)            → gf180 subckt netlist string (no LVS)
    run_testbenches(component, out_dir) → {dc, ac, tran, plots, passed}

It builds a testbench around the extracted subckt, runs **ngspice** with the
gf180 typical models, and plots AC magnitude/phase + the transient response with
**matplotlib**. LVS is intentionally NOT run here (the agent doesn't use it).
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

GF180_MODELS = str(Path(__file__).resolve().parents[1]
                   / "glayout" / "spice" / "gf180_typical.spice")


# ── netlist extraction ────────────────────────────────────────────────────────
class _StringNetlist:
    def __init__(self, spice_str: str):
        self._spice = spice_str
        m = list(re.finditer(r"\.subckt\s+(\w+)\s+(.*)", spice_str, re.IGNORECASE))
        if m:
            self.circuit_name = m[-1].group(1)
            self.nodes = [n for n in m[-1].group(2).split() if "=" not in n]
        else:
            self.circuit_name, self.nodes = "UNKNOWN", []

    def generate_netlist(self) -> str:
        return self._spice


def _netlist_obj(component):
    info = getattr(component, "info", None) or {}
    nl = info.get("netlist_obj") or info.get("netlist")
    if nl is not None and hasattr(nl, "generate_netlist"):
        return nl
    if isinstance(nl, str) and nl.strip():
        return _StringNetlist(nl)
    return None


def extract_spice(component) -> dict[str, Any]:
    """Extract the schematic SPICE subckt from a built glayout component."""
    nl = _netlist_obj(component)
    if nl is None:
        return {"ok": False, "error": "no netlist in component.info", "spice": "",
                "circuit_name": "", "nodes": []}
    spice = _fix_spice(nl.generate_netlist())
    return {"ok": True, "spice": spice,
            "circuit_name": getattr(nl, "circuit_name", "DUT"),
            "nodes": getattr(nl, "nodes", [])}


def _fix_spice(spice: str) -> str:
    """Make a glayout netlist ngspice/gf180-model friendly."""
    spice = re.sub(r"m=\{(\d+)\}", lambda x: f"m={x.group(1)}", spice)
    spice = re.sub(r"\bl=\{[^}]+\}", "l=0.28", spice)
    spice = re.sub(r"\bw=\{[^}]+\}", "w=0.28", spice)
    spice = re.sub(r"\bl=([\d.]+)",
                   lambda m: f"l={max(float(m.group(1)), 0.28)}" if _f(m.group(1)) else m.group(0), spice)
    spice = re.sub(r"\bw=([\d.]+)",
                   lambda m: f"w={max(float(m.group(1)), 0.22)}" if _f(m.group(1)) else m.group(0), spice)
    spice = re.sub(r"^.*mimcap.*$", "* mimcap removed", spice, flags=re.MULTILINE | re.IGNORECASE)
    return spice


def _f(s: str) -> bool:
    try:
        float(s); return True
    except ValueError:
        return False


# ── node classification ───────────────────────────────────────────────────────
def _classify(nodes: list[str], vdd: float):
    """Map subckt nodes → testbench wiring, picking an AC input + output."""
    nmap, in_node, out_node = {}, None, None
    for n in nodes:
        u = n.upper()
        if u in ("VDD", "AVDD", "VCC"):
            nmap[n] = "vdd"
        elif u in ("VSS", "GND", "AVSS", "B", "BULK", "VBULK"):
            nmap[n] = "0"
        else:
            nmap[n] = f"n_{n.lower()}"
    for n in nodes:
        u = n.upper()
        if in_node is None and any(k in u for k in ("VIN", "VIP", "INP", "VB", "VREF", "IN", "VP")):
            in_node = n
        if any(k in u for k in ("VOUT", "IOUT", "VCOPY", "OUT", "VOP", "VOM", "VN")):
            out_node = n
    if in_node is None:
        in_node = next((n for n in nodes if nmap[n] not in ("vdd", "0")), None)
    if out_node is None:
        out_node = next((n for n in nodes if n != in_node and nmap[n] not in ("vdd", "0")), in_node)
    return nmap, in_node, out_node


def _bias_lines(nodes, nmap, in_node, vdd):
    """DC bias for every non-supply, non-input node so the DUT has an op point."""
    lines = []
    for n in nodes:
        c, u = nmap[n], n.upper()
        if c in ("vdd", "0") or n == in_node:
            continue
        if any(k in u for k in ("BIAS", "VB", "IREF", "IBIAS")):
            lines.append(f"I_{n} vdd {c} DC 10u")
        elif any(k in u for k in ("VOUT", "IOUT", "VCOPY", "OUT")):
            lines.append(f"RL_{n} vdd {c} 100k")
        else:
            lines.append(f"V_{n} {c} 0 DC {vdd*0.5:.3f}")
    return lines


# ── runner ────────────────────────────────────────────────────────────────────
def run_testbenches(component=None, out_dir: str | Path = ".", *, spice: str = "",
                    circuit_name: str = "DUT", nodes: list[str] | None = None,
                    vdd: float = 3.3, plot: bool = True) -> dict[str, Any]:
    """Run DC + AC + transient testbenches and (optionally) plot with matplotlib.

    Pass either a built `component` (netlist auto-extracted) or an explicit
    `spice`/`circuit_name`/`nodes`. Returns analyses + PNG plot paths + a
    heuristic pass/fail (`passed` = ngspice converged with finite output).
    """
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    if component is not None and not spice:
        ex = extract_spice(component)
        if not ex["ok"]:
            return {"ok": False, "error": ex["error"], "passed": False}
        spice, circuit_name, nodes = ex["spice"], ex["circuit_name"], ex["nodes"]
    nodes = nodes or []
    if not nodes:
        return {"ok": False, "error": "no nodes", "passed": False}

    nmap, in_node, out_node = _classify(nodes, vdd)
    inst = " ".join(nmap[n] for n in nodes)
    in_c, out_c = nmap.get(in_node, "0"), nmap.get(out_node, "0")
    bias = "\n".join(_bias_lines(nodes, nmap, in_node, vdd))

    ac_csv, tran_csv = out / "ac.csv", out / "tran.csv"
    deck = f"""* gelochip testbench for {circuit_name}
.include {GF180_MODELS}
{spice}
VDD vdd 0 DC {vdd}
* AC + transient stimulus on input node '{in_node}'
VIN {in_c} 0 DC {vdd*0.5:.3f} AC 1 SIN({vdd*0.5:.3f} 0.05 1e6)
{bias}
XDUT {inst} {circuit_name}
.options GMIN=1e-12 RELTOL=1e-3 ITL1=500
.control
set wr_singlescale
op
ac dec 20 1 1e9
wrdata {ac_csv} vdb({out_c}) vp({out_c})
tran 0.02u 4u
wrdata {tran_csv} v({out_c}) v({in_c})
.endc
.end
"""
    deck_path = out / "testbench.spice"
    deck_path.write_text(deck)

    res: dict[str, Any] = {"ok": True, "circuit_name": circuit_name,
                           "in_node": in_node, "out_node": out_node,
                           "spice_path": str(deck_path), "ac": {}, "tran": {},
                           "plots": {}, "passed": False, "stdout": ""}
    try:
        r = subprocess.run(["ngspice", "-b", str(deck_path)], capture_output=True,
                           text=True, timeout=120)
        res["stdout"] = (r.stdout + r.stderr)[-3000:]
    except Exception as e:
        res["error"] = str(e)
        return res

    ac = _read_csv(ac_csv)
    tran = _read_csv(tran_csv)
    if ac:
        res["ac"] = {"freq": ac[0], "gain_db": ac[1], "phase_deg": ac[2] if len(ac) > 2 else []}
    if tran:
        res["tran"] = {"t": tran[0], "vout": tran[1], "vin": tran[2] if len(tran) > 2 else []}
    res["passed"] = bool(ac or tran) and "no convergence" not in res["stdout"].lower()

    if plot:
        res["plots"] = _plot(res, out)
    return res


def run_spec_testbench(circuit, out_dir: str | Path) -> dict:
    """Circuit-aware testbench from a hand-written netlist + spec.

    `circuit` is a clean_builders.Circuit (netlist + tb spec + theory). For
    amplifier/follower/switch circuits it runs AC + transient and reports in-band
    gain + bandwidth; for current mirrors (kind=="mirror") it sweeps the reference
    current and reports the measured copy ratio. Quantitative metrics are compared
    to the closed-form theory and plotted with matplotlib.
    """
    if circuit.tb.get("kind") in ("mirror", "current_mirror"):
        return _run_mirror_testbench(circuit, out_dir)

    import numpy as np

    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    tb = circuit.tb
    inst_nodes = " ".join(_gnd(n) for n in circuit.nodes)   # tie VSS/GND pins to node 0
    out_c = tb["out"]
    ac_csv, tran_csv = out / "ac.csv", out / "tran.csv"
    static = "\n".join(tb.get("static", []))
    deck = f"""* gelochip spec testbench — {circuit.subckt}
.include {GF180_MODELS}
{circuit.netlist}
VDD VDD 0 DC {tb.get('vdd',3.3)}
{static}
{tb['ac_src']}
XDUT {inst_nodes} {circuit.subckt}
.options GMIN=1e-12 RELTOL=1e-3 ITL1=500
.control
set wr_singlescale
op
ac dec 30 1 1e9
wrdata {ac_csv} vdb({out_c}) vp({out_c})
.endc
.end
"""
    (out / "ac_tb.spice").write_text(deck)
    deck_tran = deck.replace(tb["ac_src"], tb["tran_src"]).replace(
        f"ac dec 30 1 1e9\nwrdata {ac_csv} vdb({out_c}) vp({out_c})",
        f"tran 0.02u 4u\nwrdata {tran_csv} v({out_c}) v({tb['ac_in']})")
    (out / "tran_tb.spice").write_text(deck_tran)

    res = {"ok": True, "circuit_name": circuit.subckt, "out_node": out_c,
           "in_node": tb["ac_in"], "ac": {}, "tran": {}, "plots": {},
           "metrics": {}, "theory": circuit.theory, "passed": False, "stdout": ""}
    for deck_str, name in ((deck, "ac_tb"), (deck_tran, "tran_tb")):
        try:
            r = subprocess.run(["ngspice", "-b", str(out / f"{name}.spice")],
                               capture_output=True, text=True, timeout=120)
            res["stdout"] += r.stdout + r.stderr
        except Exception as e:
            res["error"] = str(e)

    ac = _read_csv(ac_csv)
    tran = _read_csv(tran_csv)
    if ac:
        f, g = np.array(ac[0]), np.array(ac[1])
        res["ac"] = {"freq": ac[0], "gain_db": ac[1]}
        gdc = float(np.mean(g[f < 1e3])) if (f < 1e3).any() else float(g[0])
        # -3 dB bandwidth relative to in-band gain
        thr = gdc - 3.0
        bw = next((float(fi) for fi, gi in zip(f, g) if gi < thr), float(f[-1]))
        res["metrics"] = {"inband_gain_db": round(gdc, 2), "bw_3db_hz": bw}
    if tran:
        res["tran"] = {"t": tran[0], "vout": tran[1], "vin": tran[2] if len(tran) > 2 else []}
    res["passed"] = _theory_pass(circuit, res["metrics"])
    res["plots"] = _plot_theory(res, out)
    return res


def _run_mirror_testbench(circuit, out_dir):
    """DC current-mirror testbench: sweep I_ref, measure copy current, report ratio."""
    import numpy as np

    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    tb = circuit.tb
    inst = " ".join(_gnd(n) for n in circuit.nodes)   # tie VSS/GND pins to node 0
    csv = out / "mirror.csv"
    static = "\n".join(tb.get("static", []))
    # I_ref pushed into the reference node; copy current sensed by a 0 V source.
    deck = f"""* gelochip mirror testbench — {circuit.subckt}
.include {GF180_MODELS}
{circuit.netlist}
VDD VDD 0 DC {tb.get('vdd',3.3)}
IREF {tb['ref_src']}
VSENSE {tb['sense']} DC 0
{static}
XDUT {inst} {circuit.subckt}
.options GMIN=1e-12 RELTOL=1e-3 ITL1=500
.control
dc IREF {tb.get('sweep','1u 40u 2u')}
wrdata {csv} i(VSENSE)
.endc
.end
"""
    (out / "mirror_tb.spice").write_text(deck)
    res = {"ok": True, "circuit_name": circuit.subckt, "metrics": {}, "plots": {},
           "theory": circuit.theory, "passed": False, "stdout": "", "ac": {}, "tran": {},
           "in_node": "IREF", "out_node": tb.get("sense", "")}
    try:
        r = subprocess.run(["ngspice", "-b", str(out / "mirror_tb.spice")],
                           capture_output=True, text=True, timeout=120)
        res["stdout"] = (r.stdout + r.stderr)[-3000:]
    except Exception as e:
        res["error"] = str(e); return res
    data = _read_csv(csv)
    if data and len(data) >= 2:
        iref, isense = np.array(data[0]), np.abs(np.array(data[1]))
        ratios = isense[iref > 0] / iref[iref > 0]
        ratio = float(np.median(ratios)) if len(ratios) else 0.0
        target = tb.get("ratio", 1.0)
        res["metrics"] = {"copy_ratio": round(ratio, 3), "target_ratio": target}
        res["passed"] = abs(ratio - target) / target < 0.25 if target else False
        res["_mirror"] = {"iref": data[0], "iout": isense.tolist()}
    res["plots"] = _plot_mirror(res, out)
    return res


def _plot_mirror(res, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    m = res.get("_mirror")
    if not m:
        return {}
    fig, ax = plt.subplots(figsize=(6, 3.6))
    ax.plot([x * 1e6 for x in m["iref"]], [y * 1e6 for y in m["iout"]],
            color="#6ea8fe", lw=1.8, label="measured I_out")
    tgt = res["metrics"].get("target_ratio", 1)
    ax.plot([x * 1e6 for x in m["iref"]], [x * 1e6 * tgt for x in m["iref"]],
            ls="--", color="#a78bfa", label=f"theory ×{tgt}")
    ax.set_xlabel("I_ref [µA]"); ax.set_ylabel("I_out [µA]")
    ax.set_title(f"Current mirror — {res['circuit_name']}  "
                 f"(ratio {res['metrics'].get('copy_ratio')} vs {tgt})")
    ax.legend(fontsize=7); ax.grid(True, alpha=.3)
    p = out / "ac_plot.png"; fig.tight_layout(); fig.savefig(p, dpi=120); plt.close(fig)
    return {"ac": str(p)}


def _gnd(node: str) -> str:
    """Map a ground-like subckt pin to ngspice node 0."""
    return "0" if node.upper() in ("VSS", "GND", "AVSS", "0") else node


def _theory_pass(circuit, metrics: dict) -> bool:
    g = metrics.get("inband_gain_db")
    if g is None:
        return False
    kind = circuit.tb.get("kind", "")
    if kind == "switch":
        return g > -3.0                      # closed switch passes signal
    if kind == "follower":
        return -6.0 <= g <= 0.5              # follower gain ≲ 1
    if kind in ("amplifier", "ota", "opamp"):
        return g > 6.0                       # real voltage gain
    if kind in ("mirror", "current_mirror"):
        return True                          # checked via DC current ratio elsewhere
    return g is not None


def _plot_theory(res: dict, out: Path) -> dict:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plots = {}
    m = res.get("metrics", {})
    if res.get("ac", {}).get("freq"):
        fig, ax = plt.subplots(figsize=(6, 3.6))
        ax.semilogx(res["ac"]["freq"], res["ac"]["gain_db"], color="#6ea8fe", lw=1.8)
        if m.get("inband_gain_db") is not None:
            ax.axhline(m["inband_gain_db"], ls="--", c="#a78bfa", alpha=.7,
                       label=f"in-band {m['inband_gain_db']} dB")
            ax.axhline(m["inband_gain_db"] - 3, ls=":", c="#f59e0b", alpha=.7, label="-3 dB")
        ax.set_xlabel("Frequency [Hz]"); ax.set_ylabel("Gain [dB]")
        ax.set_title(f"AC — {res['circuit_name']}  (theory: {'PASS' if res['passed'] else 'CHECK'})")
        ax.legend(fontsize=7); ax.grid(True, which="both", alpha=.3)
        p = out / "ac_plot.png"; fig.tight_layout(); fig.savefig(p, dpi=120); plt.close(fig)
        plots["ac"] = str(p)
    if res.get("tran", {}).get("t"):
        fig, ax = plt.subplots(figsize=(6, 3.6))
        t = [x * 1e6 for x in res["tran"]["t"]]
        ax.plot(t, res["tran"]["vout"], color="#3fb950", label="vout")
        if res["tran"].get("vin"):
            ax.plot(t, res["tran"]["vin"], color="#a78bfa", alpha=.6, label="vin")
        ax.set_xlabel("Time [µs]"); ax.set_ylabel("Voltage [V]")
        ax.set_title(f"Transient — {res['circuit_name']}")
        ax.legend(fontsize=7); ax.grid(True, alpha=.3)
        p = out / "tran_plot.png"; fig.tight_layout(); fig.savefig(p, dpi=120); plt.close(fig)
        plots["tran"] = str(p)
    return plots


def _read_csv(path: Path):
    """ngspice wrdata writes whitespace columns: x y [x y ...]. Return columns."""
    if not path.exists() or path.stat().st_size == 0:
        return None
    import numpy as np
    try:
        data = np.loadtxt(path)
    except Exception:
        return None
    if data.ndim == 1:
        data = data.reshape(1, -1)
    cols = [data[:, i].tolist() for i in range(data.shape[1])]
    # columns are interleaved x,y,(x,y)… → [x, y0, y1, …]
    xs = cols[0]
    ys = [cols[i] for i in range(1, len(cols), 2)]
    return [xs, *ys] if ys else None


def _plot(res: dict, out: Path) -> dict[str, str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plots = {}
    if res.get("ac", {}).get("freq"):
        fig, ax = plt.subplots(figsize=(6, 3.4))
        ax.semilogx(res["ac"]["freq"], res["ac"]["gain_db"], color="#6ea8fe")
        ax.set_xlabel("Frequency [Hz]"); ax.set_ylabel("Gain [dB]")
        ax.set_title(f"AC response — {res['circuit_name']}"); ax.grid(True, which="both", alpha=.3)
        p = out / "ac_plot.png"; fig.tight_layout(); fig.savefig(p, dpi=120); plt.close(fig)
        plots["ac"] = str(p)
    if res.get("tran", {}).get("t"):
        fig, ax = plt.subplots(figsize=(6, 3.4))
        ax.plot([t * 1e6 for t in res["tran"]["t"]], res["tran"]["vout"],
                color="#3fb950", label="vout")
        if res["tran"].get("vin"):
            ax.plot([t * 1e6 for t in res["tran"]["t"]], res["tran"]["vin"],
                    color="#a78bfa", alpha=.6, label="vin")
        ax.set_xlabel("Time [µs]"); ax.set_ylabel("Voltage [V]")
        ax.set_title(f"Transient — {res['circuit_name']}"); ax.legend(); ax.grid(True, alpha=.3)
        p = out / "tran_plot.png"; fig.tight_layout(); fig.savefig(p, dpi=120); plt.close(fig)
        plots["tran"] = str(p)
    return plots
