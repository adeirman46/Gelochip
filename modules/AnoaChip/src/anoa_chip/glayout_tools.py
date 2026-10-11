"""Pipeline-side wrapper around the Glayout subprocess harness + config files.

The pipeline (app.py) and the deep agents talk to Glayout ONLY through here:

  • run_build(design_dir, script, name, ...)  — build layout (+DRC/+LVS) in a
    fresh subprocess (glayout_harness.py), return the machine-readable dict.
  • load_config / save_config                 — the design's config/<name>.json
    parameter file (spec block + every sizing/placement/routing knob). The
    self-improve loop mutates THIS file, never the code.
  • config_note(cfg)                          — compact text form for prompts.
  • drc/lvs summaries                         — short LLM-readable verdicts.

Config file contract (config/<name>.json) — generated BEFORE any circuit:

{
  "name": "ota_5t",
  "pdk": "sky130",
  "spec": { "gain_db": {"min": 40}, "bw_hz": {"min": 1e6},
            "phase_margin_deg": {"min": 60}, "power_w": {"max": 1e-3} },
  "params": {
    "M1_M2": {"width": 4.0, "length": 1.0, "fingers": 2, "multipliers": 1},
    "M3_M4": {"width": 8.0, "length": 1.0, "fingers": 2, "multipliers": 1},
    "Mtail": {"width": 2.0, "length": 2.0, "fingers": 1, "multipliers": 1},
    "ibias_ua": 20, "cl_pf": 1.0, "vdd": 1.8
  },
  "placement": { "note": "movex/movey/center offsets if hand-tuned" },
  "routing":   { "style": "smart_route first; explicit c_route/L_route/straight_route where needed" },
  "finishing": { "with_tie": false, "with_substrate_tap": false,
                 "with_dummy": false, "guardring": false }
}

`finishing` starts ALL-FALSE: substrate ties, guardrings and dummies are added
LAST, only after routing is complete and LVS is clean on the bare circuit —
per the AnoaChip design rules.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Tuple

_LAYOUT_TIMEOUT = int(os.getenv("ANOA_LAYOUT_TIMEOUT_S", "900"))
_HARNESS = Path(__file__).with_name("glayout_harness.py")


# AnoaChip's OWN EDA-tools env, created by scripts/install.sh via micromamba
# (magic/netgen/ngspice/klayout from conda-forge) — so a fresh clone is fully
# self-contained and never depends on any sibling checkout's environment.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_ANOA_EDA_BIN = _REPO_ROOT / ".tools" / "eda" / "bin"


def _eda_bin_dir() -> str:
    """Directory holding AnoaChip's EDA binaries (magic/netgen), resolved INDEPENDENTLY
    so a clone works out of the box. Priority:
      1. ANOA_EDA_BIN (explicit override),
      2. AnoaChip/.tools/eda/bin — the env scripts/install.sh builds (micromamba),
      3. '' → fall back to whatever is on PATH (system install / user's shell),
    and, only as a last-resort DEV convenience, the sibling gLayout checkout's venv."""
    env = os.getenv("ANOA_EDA_BIN")
    if env and Path(env).is_dir():
        return env
    if (_ANOA_EDA_BIN / "magic").exists() or (_ANOA_EDA_BIN / "netgen").exists():
        return str(_ANOA_EDA_BIN)
    # last-resort dev fallback: a sibling gLayout checkout's bundled tools (a clone gets
    # .tools/eda/bin from install.sh instead, so this is never required).
    if os.getenv("ANOA_ALLOW_GLAYOUT_TOOLS", "1") not in ("0", "false", "no"):
        try:
            import glayout
            cand = Path(glayout.__file__).resolve().parents[2] / ".venv" / "bin"
            if (cand / "magic").exists() or (cand / "netgen").exists():
                return str(cand)
        except Exception:  # noqa: BLE001
            pass
    return ""


# back-compat alias (older call sites)
_glayout_bin_dir = _eda_bin_dir


# --------------------------------------------------------------------------- #
#  build / verify
# --------------------------------------------------------------------------- #
def run_build(design_dir: str | Path, script_rel: str, name: str,
              pdk: str | None = None, drc: bool = False, lvs: bool = False,
              timeout: int = 0) -> dict:
    """Run glayout_harness.py in a subprocess. Returns the verify dict
    (build/drc/lvs) — never raises; failures land in result['build']['error'].
    """
    design = Path(design_dir).resolve()
    pdk = pdk or os.getenv("PDK", "gf180mcuD")
    cmd = [sys.executable, str(_HARNESS), str(design), script_rel,
           "--name", name, "--pdk", pdk]
    if drc:
        cmd.append("--drc")
    if lvs:
        cmd.append("--lvs")
    env = dict(os.environ)
    env.setdefault("PDK_ROOT", str(Path.home() / "pdks"))
    # HEADLESS: clear DISPLAY so magic/netgen (built with Tk) can NEVER pop a GUI window
    # (the tkcon console) during DRC/LVS — they run purely in batch mode.
    env["DISPLAY"] = ""
    env["MAGIC_WISH"] = env.get("MAGIC_WISH", "")
    env["NETGEN_WISH"] = env.get("NETGEN_WISH", "")
    # AnoaChip's OWN EDA tools (magic/netgen/ngspice) come first on PATH
    gbin = _eda_bin_dir()
    if gbin:
        env["PATH"] = gbin + os.pathsep + env.get("PATH", "")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout or _LAYOUT_TIMEOUT,
                              cwd=str(design), env=env)
    except subprocess.TimeoutExpired:
        return {"name": name, "build": {"ok": False,
                "error": f"layout build timed out after {timeout or _LAYOUT_TIMEOUT}s"}}
    vjson = design / "layout" / f"verify_{name}.json"
    if vjson.exists():
        try:
            res = json.loads(vjson.read_text())
            res["log_tail"] = (proc.stdout + proc.stderr)[-3000:]
            return res
        except Exception:  # noqa: BLE001
            pass
    return {"name": name,
            "build": {"ok": False,
                      "error": (proc.stdout + "\n" + proc.stderr)[-4000:]
                      or f"harness exited {proc.returncode} with no output"}}


def _magicrc(pdk: str) -> Path | None:
    """The PDK's magicrc (magic tech setup) for extraction/DRC."""
    root = Path(os.getenv("PDK_ROOT", str(Path.home() / "pdks")))
    if pdk.lower().startswith("gf180"):
        p = root / "gf180mcuD" / "libs.tech" / "magic" / "gf180mcuD.magicrc"
    else:
        p = root / "sky130A" / "libs.tech" / "magic" / "sky130A.magicrc"
    return p if p.exists() else None


def run_pex(design_dir: str | Path, name: str, pdk: str | None = None,
            timeout: int = 0) -> dict:
    """POST-LAYOUT PARASITIC EXTRACTION: run magic's extractor on the signed-off GDS to
    produce a SPICE netlist WITH parasitic R/C — the netlist ngspice then simulates for the
    real DC/AC/transient response (the user's flow: 'spice extraction si glayout/PEX itu yg
    dipake buat simulasi ngspice'). Returns {ok, pex_netlist, error}."""
    import tempfile
    design = Path(design_dir).resolve()
    pdk = pdk or os.getenv("PDK", "gf180mcuD")
    gds = design / "layout" / f"{name}.gds"
    if not gds.exists():
        return {"ok": False, "error": f"no GDS at {gds} — build the layout first"}
    rc = _magicrc(pdk)
    if not rc:
        return {"ok": False, "error": f"no magicrc for {pdk} under PDK_ROOT"}
    magic = None
    gbin = _eda_bin_dir()
    if gbin and (Path(gbin) / "magic").exists():
        magic = str(Path(gbin) / "magic")
    magic = os.getenv("MAGIC_BIN", magic or "magic")
    out = design / "layout" / f"{name}_pex.spice"
    with tempfile.TemporaryDirectory(prefix="anoa_pex_") as td:
        script = Path(td) / "pex.tcl"
        # `port makeall` PROMOTES the layout's text labels to real magic PORTS before
        # extraction — without it ext2spice emitted `.subckt <top>` with NO port list
        # (labels stayed internal nets), so the post-layout testbench could never
        # X-instantiate the circuit and the sim always crashed.
        script.write_text(
            f"gds read {gds}\nload {name}\nselect top cell\n"
            "port makeall\n"
            "extract do local\nextract all\n"
            "ext2spice lvs\next2spice cthresh 0\next2spice rthresh 0\n"
            f"ext2spice -o {out}\nquit -noprompt\n")
        env = dict(os.environ)
        env["DISPLAY"] = ""; env["PDK_ROOT"] = str(Path(os.getenv("PDK_ROOT", str(Path.home() / "pdks"))))
        if gbin:
            env["PATH"] = gbin + os.pathsep + env.get("PATH", "")
        try:
            proc = subprocess.run(
                [magic, "-rcfile", str(rc), "-noconsole", "-dnull", str(script)],
                cwd=td, capture_output=True, text=True, env=env,
                timeout=timeout or 300)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"magic PEX failed: {e}"}
    if out.exists() and out.stat().st_size > 40:
        return {"ok": True, "pex_netlist": str(out)}
    return {"ok": False,
            "error": (proc.stdout + proc.stderr)[-1500:] or "PEX produced no netlist"}


def build_summary(res: dict) -> str:
    """One-paragraph LLM/human-readable verdict of a run_build result."""
    b = res.get("build", {})
    if not b.get("ok"):
        return "LAYOUT BUILD FAILED:\n" + (b.get("error") or "unknown error")[-2500:]
    nlab = b.get("n_labels", -1)
    lab_note = (f"{nlab} labels" if nlab and nlab > 0 else
                "NO LABELS (LVS will fail — add a text label on every pin's metal)")
    lines = [f"layout OK — {b.get('n_ports', 0)} ports, {lab_note}, bbox {b.get('bbox_um')} µm,"
             f" ref-netlist {'yes' if b.get('has_ref_netlist') else 'NO (LVS will fail)'}"]
    drc, lvs = res.get("drc", {}), res.get("lvs", {})
    if drc.get("status") not in (None, "not run"):
        if drc.get("status") == "pass":
            lines.append("DRC: PASS ✓")
        elif drc.get("status") == "fail":
            det = "; ".join(f"{e.get('rule','?')}" for e in drc.get("error_details", [])[:6])
            lines.append(f"DRC: FAIL ✗ ({drc.get('total_errors')} errors — {det})")
        else:
            lines.append(f"DRC: ERROR — {str(drc.get('error'))[:600]}")
    if lvs.get("status") not in (None, "not run"):
        if lvs.get("status") == "pass":
            lines.append("LVS: PASS ✓ (layout matches netlist)")
        elif lvs.get("status") == "fail":
            um = "; ".join(f"{u['type']} {u['name']} only in {u['present_in']}"
                           for u in lvs.get("unmatched", [])[:8])
            lines.append(f"LVS: FAIL ✗ — {lvs.get('conclusion')} {um}")
            lines.append("Hint: an 'only in schematic' net usually means a route "
                         "was NOT generated — check that every connection uses "
                         "c_route/L_route/straight_route (straight_route only "
                         "works for inline parallel ports; use c_route/L_route "
                         "otherwise) and that via_stack bridges layer changes.")
        else:
            lines.append(f"LVS: ERROR — {str(lvs.get('error'))[:600]}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
#  config files (the self-improve loop's substrate)
# --------------------------------------------------------------------------- #
def config_path(design_dir: str | Path, name: str) -> Path:
    return Path(design_dir) / "config" / f"{name}.json"


def load_config(design_dir: str | Path, name: str) -> dict:
    p = config_path(design_dir, name)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:  # noqa: BLE001
            return {}
    return {}


def save_config(design_dir: str | Path, name: str, cfg: dict) -> Path:
    p = config_path(design_dir, name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2))
    return p


def config_note(cfg: dict, max_chars: int = 1800) -> str:
    """Compact JSON for prompts."""
    if not cfg:
        return "(no config yet)"
    return json.dumps(cfg, indent=1)[:max_chars]


def bump_iteration(design_dir: str | Path, name: str, cfg: dict,
                   metrics: dict | None = None, note: str = "") -> None:
    """Append this config + measured metrics to config/<name>_history.jsonl so
    the self-improve loop (and the knowledge DB) can see the trajectory."""
    p = Path(design_dir) / "config" / f"{name}_history.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = {"config": cfg, "metrics": metrics or {}, "note": note}
    with p.open("a") as f:
        f.write(json.dumps(rec, default=str) + "\n")


# --------------------------------------------------------------------------- #
#  quick env sanity (used by the UI banner, like librelane_available was)
# --------------------------------------------------------------------------- #
def glayout_available() -> Tuple[bool, str]:
    try:
        import glayout  # noqa: F401
        import gdsfactory  # noqa: F401
        return True, f"glayout @ {Path(glayout.__file__).parent}"
    except Exception as e:  # noqa: BLE001
        return False, f"glayout not importable: {e}"


def tools_available() -> dict:
    import shutil
    gbin = _glayout_bin_dir()

    def _have(name: str, env_var: str) -> bool:
        if gbin and (Path(gbin) / name).exists():
            return True
        return bool(shutil.which(os.getenv(env_var, name)))
    return {"magic": _have("magic", "MAGIC_BIN"),
            "netgen": _have("netgen", "NETGEN_BIN"),
            "ngspice": _have("ngspice", "NGSPICE_BIN")}
