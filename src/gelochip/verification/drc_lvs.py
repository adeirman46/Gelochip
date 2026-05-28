"""
DRC and LVS wrappers that call the glayout verification module.

Requires:
    - Magic VLSI tool (sudo apt install magic)
    - Netgen LVS tool  (sudo apt install netgen-lvs)
    - PDK_ROOT environment variable pointing to the PDK installation

These tools are part of the open-source EDA stack for gf180/sky130.
The easiest way to get them all: IIC-OSIC-TOOLS Docker image.

Usage::

    from gelochip.verification.drc_lvs import run_drc, run_lvs, run_full_verification
    from gdsfactory.component import Component

    comp: Component = ...          # your layout component
    gds_path = "/tmp/my_lna.gds"
    comp.write_gds(gds_path)

    drc = run_drc(gds_path, "lna_cascode", comp, pdk="gf180")
    print(drc["is_pass"], drc["total_errors"])

    lvs = run_lvs(gds_path, "lna_cascode", comp, pdk="gf180")
    print(lvs["is_pass"], lvs["conclusion"])
"""
from __future__ import annotations
import os
import shutil
from pathlib import Path
from typing import Any

from gdsfactory.component import Component


def run_drc(
    gds_path: str,
    component_name: str,
    component: Component,
    pdk: str = "gf180",
) -> dict[str, Any]:
    """
    Run Design Rule Check (DRC) via Magic VLSI.

    Checks that all geometries in the layout respect the PDK's minimum spacing,
    width, enclosure, and overlap rules.

    Args:
        gds_path:       Path to the GDS file to check.
        component_name: Top cell name in the GDS.
        component:      gdsfactory Component (used by glayout's verifier for reference).
        pdk:            "gf180" | "sky130"

    Returns:
        Dict with:
            is_pass:      True if no DRC violations
            total_errors: Number of DRC violations
            error_details: List of {rule, details} dicts
            raw_report:   Full Magic DRC output string

    Requires: Magic VLSI installed + PDK_ROOT set.
    Install:  sudo apt install magic  (or via IIC-OSIC-TOOLS Docker)
    """
    if not shutil.which("magic"):
        return {
            "is_pass": None,
            "total_errors": None,
            "error_details": [],
            "raw_report": "",
            "error": "magic not found. Install: sudo apt install magic",
            "skipped": True,
        }

    pdk_root = os.environ.get("PDK_ROOT", "")
    if not pdk_root:
        return {
            "is_pass": None,
            "total_errors": None,
            "error_details": [],
            "raw_report": "",
            "error": "PDK_ROOT not set. Export PDK_ROOT=/path/to/pdks",
            "skipped": True,
        }

    # Prefer the venv's magic (rev 644) over any system magic.
    # sys.executable is e.g. /path/to/.venv/bin/python — its directory has magic.
    import sys as _sys
    _venv_bin = os.path.dirname(_sys.executable)
    _orig_path = os.environ.get("PATH", "")
    _orig_pdk_root = os.environ.get("PDK_ROOT", "")
    if os.path.isfile(os.path.join(_venv_bin, "magic")):
        os.environ["PATH"] = _venv_bin + os.pathsep + _orig_path

    try:
        from gelochip.glayout.verification.verification import run_verification
        result = run_verification(gds_path, component_name, component)
        raw = result.get("drc", {})
        # Flatten summary sub-dict into top level so callers get
        # total_errors, is_pass, error_details directly.
        summary = raw.pop("summary", {})
        raw.update(summary)
        # Guarantee these keys always exist
        raw.setdefault("total_errors", 0)
        raw.setdefault("error_details", [])
        raw.setdefault("is_pass", raw.get("total_errors", 0) == 0)
        # Add per-category error counts for RL observation
        raw.update(_categorise_errors(raw.get("error_details", [])))
        return raw
    except Exception as e:
        return {
            "is_pass": False,
            "total_errors": 0,
            "error_details": [],
            "NW": 0, "CO": 0, "PL": 0, "DF": 0, "other": 0,
            "error": str(e),
        }
    finally:
        os.environ["PATH"] = _orig_path
        # glayout's drc_magic overwrites PDK_ROOT with str(None) when pdk_root
        # is not set on the PDK object — restore it so subsequent DRC calls work.
        if _orig_pdk_root:
            os.environ["PDK_ROOT"] = _orig_pdk_root
        elif "PDK_ROOT" in os.environ:
            del os.environ["PDK_ROOT"]


def _categorise_errors(error_details: list) -> dict:
    """Count DRC errors per rule category for RL observation."""
    cats = {"NW": 0, "CO": 0, "PL": 0, "DF": 0, "other": 0}
    for err in error_details:
        rule = err.get("rule", "").upper()
        if any(k in rule for k in ("NW", "N-WELL", "NWELL")):
            cats["NW"] += 1
        elif any(k in rule for k in ("CO", "CONTACT", "VIA")):
            cats["CO"] += 1
        elif any(k in rule for k in ("PL", "POLY")):
            cats["PL"] += 1
        elif any(k in rule for k in ("DF", "DIFF", "ACTIVE", "OVERLAP")):
            cats["DF"] += 1
        else:
            cats["other"] += 1
    return cats


def run_lvs(
    gds_path: str,
    component_name: str,
    component: Component,
    pdk: str = "gf180",
) -> dict[str, Any]:
    """
    Run Layout vs. Schematic (LVS) check via Netgen.

    Extracts a SPICE netlist from the layout (via Magic) and compares it
    against the schematic netlist stored in component.info["netlist"].

    Args:
        gds_path:       Path to the GDS file.
        component_name: Top cell name.
        component:      gdsfactory Component with info["netlist"] set.
        pdk:            "gf180" | "sky130"

    Returns:
        Dict with:
            is_pass:     True if layout matches schematic
            conclusion:  Human-readable LVS verdict
            total_mismatches: Number of mismatched nets/devices
            raw_report:  Full Netgen LVS output string

    Requires: Magic + Netgen installed + PDK_ROOT set.
    Install:  sudo apt install netgen-lvs
    """
    if not shutil.which("netgen"):
        return {
            "is_pass": None,
            "conclusion": "Netgen not found. Install: sudo apt install netgen-lvs",
            "total_mismatches": None,
            "skipped": True,
        }

    pdk_root = os.environ.get("PDK_ROOT", "")
    if not pdk_root:
        return {
            "is_pass": None,
            "conclusion": "PDK_ROOT not set.",
            "total_mismatches": None,
            "skipped": True,
        }

    try:
        from gelochip.glayout.verification.verification import run_verification
        result = run_verification(gds_path, component_name, component)
        return result.get("lvs", {
            "is_pass": False,
            "conclusion": "run_verification returned unexpected format",
            "total_mismatches": -1,
        })
    except Exception as e:
        return {
            "is_pass": False,
            "conclusion": str(e),
            "total_mismatches": -1,
        }


def run_full_verification(
    gds_path: str,
    component_name: str,
    component: Component,
    pdk: str = "gf180",
) -> dict[str, Any]:
    """
    Run DRC + LVS + physical feature extraction in one call.

    This is the main verification entry point used by the Gelochip agent.

    Returns:
        Dict with keys: drc, lvs, physical, drc_lvs_pass, summary
    """
    drc = run_drc(gds_path, component_name, component, pdk)
    lvs = run_lvs(gds_path, component_name, component, pdk)

    drc_pass = drc.get("is_pass")
    lvs_pass = lvs.get("is_pass")

    # Physical features (area, symmetry) — uses glayout's extractor
    physical = {}
    try:
        from gelochip.glayout.verification.physical_features import run_physical_feature_extraction
        physical = run_physical_feature_extraction(gds_path, component_name, component)
    except Exception as e:
        physical = {"error": str(e)}

    skipped = drc.get("skipped") or lvs.get("skipped")

    summary_lines = []
    if skipped:
        summary_lines.append(
            "⚠️  DRC/LVS skipped — Magic/Netgen not installed or PDK_ROOT not set.\n"
            "   Install tools: sudo apt install magic netgen-lvs\n"
            "   Set PDK:       export PDK_ROOT=/path/to/pdks\n"
            "   Easiest:       use IIC-OSIC-TOOLS Docker image."
        )
    else:
        drc_icon = "✅" if drc_pass else "❌"
        lvs_icon = "✅" if lvs_pass else "❌"
        drc_errors = drc.get("total_errors", "?")
        drc_status = "PASS" if drc_pass else f"FAIL ({drc_errors} errors)"
        summary_lines.append(f"{drc_icon} DRC: {drc_status}")
        summary_lines.append(f"{lvs_icon} LVS: {lvs.get('conclusion', 'unknown')}")
        if physical.get("area_um2"):
            summary_lines.append(f"📐 Area: {physical['area_um2']:.1f} µm²")

    return {
        "drc": drc,
        "lvs": lvs,
        "physical": physical,
        "drc_lvs_pass": bool(drc_pass and lvs_pass),
        "skipped": skipped,
        "summary": "\n".join(summary_lines),
    }
