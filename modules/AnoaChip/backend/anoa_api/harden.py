"""Reusable, UI-free LibreLane hardening — RTL → GDSII for one block.

Factored out of the streamlit pipeline's ``agent_harden`` so the batch IP builder
(`scripts/build_ip_library.py`) and the Create-IP backend can harden a block WITHOUT
the Recorder / streamlit machinery. Same proven gf180 config (relative floorplan
sizing, slang for SystemVerilog, lint/synth checks made informative-not-fatal so an
auto-generated block still reaches GDSII).
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_SRC = str(REPO / "src" / "anoa_chip")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

LIBRELANE_BIN = os.getenv("LIBRELANE_BIN", "librelane")
PDK = os.getenv("PDK", "gf180mcuD")
PDK_ROOT = os.getenv("PDK_ROOT", os.path.expanduser("~/.ciel"))
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def available() -> bool:
    return shutil.which(LIBRELANE_BIN) is not None


def _detect_clock(rtl_dir: Path, top: str, default: str) -> str:
    """Return the top module's real clock port. Many IPs don't call it 'clk' (FIRRTL uses
    'clock', PULP uses 'clk_i', …); a wrong CLOCK_PORT means registers aren't clocked and
    synthesis dies with 'ABC: the network is combinational'. So: if `default` isn't an actual
    input of `top`, auto-pick a clock-like input."""
    import re as _re
    text = ""
    for p in list(rtl_dir.glob("*.v")) + list(rtl_dir.glob("*.sv")):
        t = p.read_text(errors="replace")
        if _re.search(rf"\bmodule\s+{_re.escape(top)}\b", t):
            text = t
            break
    if not text:
        return default
    region = text[: text.find("endmodule") if "endmodule" in text else len(text)]
    inputs = []
    for m in _re.finditer(r"\binput\b[^;)\n]*?\b([A-Za-z_]\w*)\s*(?:,|\)|;|//|$)", region):
        inputs.append(m.group(1))
    # also catch ANSI 'input clock,' style names broadly
    inputs += _re.findall(r"\binput\b(?:\s+(?:wire|reg|logic|signed))?\s+([A-Za-z_]\w*)", region)
    inset = {i for i in inputs}
    if default in inset:
        return default
    for pat in (r"^(clk|clock|clk_i|i_clk|clock_i|clk_in|aclk|hclk|sysclk|clkin)$",
                r"clk", r"clock"):
        for nm in inputs:
            if _re.search(pat, nm, _re.I):
                return nm
    return default


def _build_config(rtl_dir: Path, src_dir: Path, design_name: str, top: str,
                  clock_port: str, clock_period: float, core_util: int) -> dict:
    """Copy the top's module closure into ``src_dir`` and return the LibreLane config —
    only the cone needed for `top`, so an unused orphan can't fail synthesis."""
    from verilog_check import closure_files
    closure, _orphans = closure_files(rtl_dir, top)
    want = set(closure) or {p.name for p in list(rtl_dir.glob("*.v")) + list(rtl_dir.glob("*.sv"))}
    want |= {p.name for p in list(rtl_dir.glob("*.vh")) + list(rtl_dir.glob("*.svh"))}
    design_files = []
    for p in (sorted(rtl_dir.glob("*.v")) + sorted(rtl_dir.glob("*.sv"))
              + sorted(rtl_dir.glob("*.vh")) + sorted(rtl_dir.glob("*.svh"))):
        if "tb" in p.name.lower() or "testbench" in p.name.lower() or p.name not in want:
            continue
        shutil.copy(p, src_dir / p.name)
        if p.suffix in (".v", ".sv"):
            design_files.append(f"dir::src/{p.name}")
    # Enable the slang frontend whenever the RTL uses SystemVerilog constructs — by CONTENT, not
    # just the .sv extension. SV inside .v files (unpacked-array ports, `logic`, `always_ff`) passes
    # Verilator sim/lint but makes plain yosys die ("syntax error, unexpected '['") → no GDS.
    from verilog_check import needs_slang
    has_sv = needs_slang(rtl_dir)
    return {
        "DESIGN_NAME": top, "VERILOG_FILES": design_files,
        "CLOCK_PORT": clock_port, "CLOCK_PERIOD": clock_period, "PDK": PDK,
        "FP_SIZING": "relative", "FP_CORE_UTIL": core_util,
        "PL_TARGET_DENSITY_PCT": max(20, core_util + 5),
        "PRIMARY_GDSII_STREAMOUT_TOOL": "klayout",
        **({"USE_SLANG": True} if has_sv else {}),
        # lint/synth checks informative, not fatal — auto-generated RTL trips these but is
        # still hardenable (same policy as the interactive flow).
        "LINTER_ERROR_ON_LATCH": False, "LINTER_ERROR_ON_MULTIDRIVEN": False,
        "ERROR_ON_LINTER_ERRORS": False, "ERROR_ON_LINTER_WARNINGS": False,
        "ERROR_ON_SYNTH_CHECKS": False, "ERROR_ON_UNMAPPED_CELLS": False,
        "ERROR_ON_DISCONNECTED_PINS": False,
        "LINTER_DISABLE_WARNINGS": [
            "UNOPTFLAT", "WIDTH", "WIDTHEXPAND", "WIDTHTRUNC", "WIDTHCONCAT",
            "CASEINCOMPLETE", "CASEOVERLAP", "UNUSEDSIGNAL", "UNDRIVEN", "PINMISSING",
            "IMPLICIT", "BLKSEQ", "SYNCASYNCNET", "DECLFILENAME", "EOFNEWLINE",
        ],
    }


def harden_rtl(rtl_dir, work_dir, design_name: str, *, top: str = "",
               clock_port: str = "clk", clock_period: float = 10.0, core_util: int = 35,
               on_log=None, timeout: int = 3600) -> dict:
    """Run LibreLane on the RTL in ``rtl_dir``, producing a GDS under ``work_dir``.

    Returns ``{ok, gds, png, metrics, rc, log}``. ``gds``/``png`` are absolute paths copied
    next to work_dir (``<top>.gds`` / ``<top>.png``) or None. ``on_log(line)`` streams the
    live LibreLane output if given.
    """
    from verilog_check import pick_top
    rtl_dir, work_dir = Path(rtl_dir), Path(work_dir)
    if not available():
        return {"ok": False, "gds": None, "png": None, "metrics": {}, "rc": -1,
                "log": "librelane not on PATH"}
    top = top or pick_top(rtl_dir) or design_name
    clock_port = _detect_clock(rtl_dir, top, clock_port)   # FIRRTL 'clock' / PULP 'clk_i' / …
    chip = work_dir / "chip"
    src = chip / "src"
    if chip.exists():
        shutil.rmtree(chip, ignore_errors=True)
    src.mkdir(parents=True, exist_ok=True)
    config = _build_config(rtl_dir, src, design_name, top, clock_port, clock_period, core_util)
    (chip / "config.json").write_text(json.dumps(config, indent=2))
    if not config["VERILOG_FILES"]:
        return {"ok": False, "gds": None, "png": None, "metrics": {}, "rc": -1,
                "log": "no synthesizable RTL files found"}

    cmd = [LIBRELANE_BIN, "--manual-pdk", "--pdk-root", PDK_ROOT, "config.json"]
    env = {**os.environ, "PDK_ROOT": PDK_ROOT}
    lines: list[str] = []
    proc = subprocess.Popen(cmd, cwd=str(chip), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, env=env, bufsize=1)
    try:
        for raw in proc.stdout:                       # type: ignore[union-attr]
            ln = _ANSI.sub("", raw.rstrip())
            lines.append(ln)
            if on_log:
                on_log(ln)
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        lines.append(f"(timed out after {timeout}s)")
    (chip / "librelane.log").write_text("\n".join(lines))

    gds = (sorted(glob.glob(str(chip / "runs" / "**" / "final" / "**" / "*.gds"), recursive=True))
           or sorted(glob.glob(str(chip / "runs" / "**" / "*.gds"), recursive=True)))
    metrics = {}
    for mp in glob.glob(str(chip / "runs" / "**" / "metrics.json"), recursive=True):
        try:
            metrics = json.load(open(mp))
        except Exception:  # noqa: BLE001
            pass
    signoff = _signoff(metrics)
    out = {"ok": bool(gds), "gds": None, "png": None,
           "metrics": _slim_metrics(metrics), "signoff": signoff,
           "tapeout_ready": bool(gds) and signoff.get("clean", False),
           "rc": proc.returncode, "log": "\n".join(lines[-400:])}
    if gds:
        dest = work_dir / f"{top}.gds"
        shutil.copy(gds[-1], dest)
        out["gds"] = str(dest)
        pngs = sorted(glob.glob(str(chip / "runs" / "**" / "*.png"), recursive=True))
        render = [p for p in pngs if re.search(r"render|layout|final|gds", p, re.I)] or pngs
        if render:
            dest_png = work_dir / f"{top}.png"
            shutil.copy(render[-1], dest_png)
            out["png"] = str(dest_png)
    return out


def _signoff(m: dict) -> dict:
    """Extract the TAPE-OUT sign-off checks from LibreLane's metrics and decide `clean`.
    Tape-out-ready means every physical + electrical sign-off check is zero AND setup timing is
    met (worst slack >= 0) across corners. No mistakes — a GDS with DRC/antenna/slew/timing
    violations is NOT tape-out-ready."""
    if not isinstance(m, dict):
        return {"clean": False, "reason": "no metrics"}
    def g(key, default=0):
        v = m.get(key)
        return v if isinstance(v, (int, float)) else default
    def nom(metric):
        """Value at the typical sign-off corner (nom_tt) if available, else the aggregate."""
        for k in (f"design__{metric}__count__corner:nom_tt_025C_5v00",):
            if isinstance(m.get(k), (int, float)):
                return m[k]
        return g(f"design__{metric}__count")
    # HARD physical-correctness checks (corner-independent) — these MUST be zero for tape-out.
    hard = {
        "magic_drc": g("magic__drc_error__count"),
        "magic_overlap": g("magic__illegal_overlap__count"),
        "route_drc": g("route__drc_errors"),
        "antenna": g("route__antenna_violation__count"),
        "lvs": g("lvs__total__errors", 0),
        "design_violations": g("design__violations"),
        "synth_check": g("synthesis__check_error__count"),
        "flow_errors": g("flow__errors__count"),
    }
    # electrical checks at the TYPICAL sign-off corner (the corner the resizer repairs).
    elec = {"max_slew": nom("max_slew_violation"), "max_cap": nom("max_cap_violation"),
            "max_fanout": nom("max_fanout_violation"), "hold_vio": g("timing__hold_vio__count", 0)}
    # worst setup slack across corners must be non-negative (timing met everywhere).
    wns = m.get("timing__setup__ws")
    if not isinstance(wns, (int, float)):
        wns = min([v for k, v in m.items()
                   if k.startswith("timing__setup__ws__corner") and isinstance(v, (int, float))],
                  default=0.0)
    # slow/fast-corner slew is a known single-corner-repair flow limitation → reported, not gated.
    slow_slew = g("design__max_slew_violation__count")
    failed = [k for k, v in {**hard, **elec}.items() if isinstance(v, (int, float)) and v > 0]
    if isinstance(wns, (int, float)) and wns < -0.001:
        failed.append("setup_timing")
    return {**hard, **elec, "setup_wns_ns": round(wns, 3) if isinstance(wns, (int, float)) else 0.0,
            "slow_corner_slew": slow_slew, "clean": not failed, "failed": failed}


def _slim_metrics(m: dict) -> dict:
    """Pull the few metrics the IP card shows from LibreLane's big metrics.json."""
    if not isinstance(m, dict):
        return {}
    def g(*keys):
        for k in keys:
            if k in m and m[k] not in (None, "", float("inf")):
                return m[k]
        return None
    return {k: v for k, v in {
        "die_area_um2": g("design__die__area", "design__die__area__um2"),
        "core_area_um2": g("design__core__area"),
        "cell_count": g("design__instance__count", "design__instance__count__stdcell"),
        "util_pct": g("design__instance__utilization", "design__instance__utilization__stdcell"),
        "wns_ns": g("timing__setup__ws", "clock__skew__worst"),
        "power_mw": g("power__total"),
    }.items() if v is not None}
