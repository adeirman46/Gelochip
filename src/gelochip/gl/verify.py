"""
SPICE simulation helper for gl circuits.
Reuses the ngspice flow from the dataset notebooks.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from typing import Optional

from gdsfactory.component import Component

_GF180_MODELS = os.path.join(
    os.path.dirname(__file__),
    "..", "glayout", "spice", "gf180_typical.spice",
)


# ─── netlist extraction ───────────────────────────────────────────────────────

class _NetlistProxy:
    def __init__(self, spice: str):
        self._spice = spice
        ms = list(re.finditer(r"\.subckt\s+(\w+)\s+(.*?)$", spice, re.I | re.M))
        if ms:
            m = ms[-1]
            self.circuit_name = m.group(1)
            self.nodes = [n for n in m.group(2).split() if "=" not in n]
        else:
            self.circuit_name = "UNKNOWN"
            self.nodes = []

    def generate_netlist(self) -> str:
        return self._spice


def _get_netlist(comp: Component) -> Optional[_NetlistProxy]:
    if not hasattr(comp, "info"):
        return None
    for key in ("netlist_obj", "netlist"):
        nl = comp.info.get(key)
        if nl is None:
            continue
        if hasattr(nl, "generate_netlist"):
            return nl
        if isinstance(nl, str) and nl.strip():
            return _NetlistProxy(nl)
    return None


# ─── SPICE text fixes ─────────────────────────────────────────────────────────

def _fix_spice(spice: str) -> str:
    spice = re.sub(r"m=\{(\d+)\}", lambda m: f"m={m.group(1)}", spice)
    spice = re.sub(r"\bl=\{[^}]+\}", "l=0.28", spice)
    spice = re.sub(r"\bw=\{[^}]+\}", "w=0.28", spice)

    def _clamp_l(m):
        try:
            return f"l={max(float(m.group(1)), 0.28)}"
        except Exception:
            return m.group(0)

    def _clamp_w(m):
        try:
            return f"w={max(float(m.group(1)), 0.22)}"
        except Exception:
            return m.group(0)

    spice = re.sub(r"\bl=([\d.]+)", _clamp_l, spice)
    spice = re.sub(r"\bw=([\d.]+)", _clamp_w, spice)
    spice = re.sub(r"^.*mimcap.*$", "* mimcap removed", spice, flags=re.M | re.I)
    return spice


# ─── testbench builder ────────────────────────────────────────────────────────

def _build_testbench(name: str, nodes: list, vdd: float = 3.3) -> str:
    nmap = {}
    for n in nodes:
        u = n.upper()
        if u in ("VDD", "AVDD", "VCC"):
            nmap[n] = "vdd"
        elif u in ("VSS", "GND", "AVSS"):
            nmap[n] = "0"
        elif u in ("VB", "VBULK", "BULK", "B"):
            nmap[n] = "0"
        else:
            nmap[n] = f"n_{n.lower()}"

    lines = [f"VDD vdd 0 DC {vdd}V"]
    for n in nodes:
        u, c = n.upper(), nmap[n]
        if c in ("vdd", "0"):
            continue
        if any(k in u for k in ("INP", "VINP", "VP")):
            lines.append(f"V_{n} {c} 0 DC {vdd * 0.55:.3f}")
        elif any(k in u for k in ("INM", "VINM", "VN")):
            lines.append(f"V_{n} {c} 0 DC {vdd * 0.45:.3f}")
        elif any(k in u for k in ("IBIAS", "NBC_", "BIAS", "DIFFPAIR_BIAS")):
            lines.append(f"I_{n} vdd {c} DC 10u")
        elif u == "VREF":
            lines.append(f"Iref_{n} vdd {c} DC 10u")
        elif u in ("VOUT", "OUTPUT", "OUT") or u.startswith("VOUT"):
            lines.append(f"RL_{n} {c} 0 100k")
        elif u == "VIN":
            lines.append(f"V_{n} {c} 0 DC {vdd * 0.5:.3f}")
        else:
            lines.append(f"V_{n} {c} 0 DC {vdd * 0.5:.3f}")

    inst = " ".join(nmap[n] for n in nodes)
    lines += [
        f"XDUT {inst} {name}",
        ".op",
        ".options GMIN=1e-12 RELTOL=1e-3 ITL1=500",
        ".save all",
    ]
    return "\n".join(lines)


# ─── public API ───────────────────────────────────────────────────────────────

def run_sim(comp: Component, label: str = "", vdd: float = 3.3) -> dict:
    """
    Run a DC operating-point simulation via ngspice + gf180 models.

    Returns a dict with keys: converged, nodes, voltages, raw.
    """
    nl = _get_netlist(comp)
    if nl is None:
        print(f"[gl.sim] No netlist found in component.info for '{label}'.")
        return {"converged": False, "error": "no netlist"}

    models = os.path.abspath(_GF180_MODELS)
    if not os.path.exists(models):
        print(f"[gl.sim] gf180 model file not found: {models}")
        return {"converged": False, "error": "models not found"}

    spice = _fix_spice(nl.generate_netlist())
    name = nl.circuit_name
    nodes = list(nl.nodes)
    tb = _build_testbench(name, nodes, vdd=vdd)
    deck = f"* {label or name}\n.include \"{models}\"\n\n{spice}\n\n{tb}\n.end\n"

    sp = out_f = ""
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sp", delete=False, dir="/tmp") as f:
            f.write(deck)
            sp = f.name
        out_f = sp + ".out"
        r = subprocess.run(
            ["ngspice", "-b", "-o", out_f, sp],
            capture_output=True, text=True, timeout=60,
        )
        raw = open(out_f).read() if os.path.exists(out_f) else r.stdout + r.stderr

        print(f"\n── DC OP: {label or name}  (VDD={vdd}V) ──")
        print(f"Circuit : {name}")
        print(f"Nodes   : {nodes}")

        in_tbl = False
        voltages = {}
        for line in raw.split("\n"):
            s = line.strip()
            if re.match(r"node\b.*voltage", s, re.I):
                in_tbl = True
                print(f"\n{line}")
            elif in_tbl and re.match(r"-{3,}", s):
                print(line)
            elif in_tbl and not s:
                in_tbl = False
            elif in_tbl:
                print(line)
                m = re.match(r"(\S+)\s+([\d.eE+\-]+)", s)
                if m:
                    voltages[m.group(1)] = float(m.group(2))

        no_conv = "no convergence" in raw.lower()
        converged = r.returncode == 0 and not no_conv
        if converged:
            print("\n✓ Converged – gf180 typical corner")
        elif no_conv:
            print("\n⚠ No convergence")
        else:
            errs = [l for l in raw.split("\n") if "error" in l.lower() and l.strip()]
            print(f"\n⚠ ngspice exit {r.returncode}")
            for e in errs[:3]:
                print(f"  {e}")

        return {"converged": converged, "nodes": nodes, "voltages": voltages, "raw": raw}

    except Exception as exc:
        print(f"[gl.sim] error: {exc}")
        return {"converged": False, "error": str(exc)}
    finally:
        for fn in (sp, out_f):
            try:
                if fn:
                    os.unlink(fn)
            except Exception:
                pass
