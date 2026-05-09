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

    try:
        from gelochip.glayout.verification.verification import run_verification
        result = run_verification(gds_path, component_name, component)
        return result.get("drc", {
            "is_pass": False,
            "total_errors": -1,
            "error_details": [],
            "raw_report": "run_verification returned unexpected format",
        })
    except Exception as e:
        return {
            "is_pass": False,
            "total_errors": -1,
            "error_details": [],
            "raw_report": "",
            "error": str(e),
        }


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
