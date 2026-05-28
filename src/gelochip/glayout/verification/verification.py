# verification.py
import os
import re
import subprocess
import shutil
import tempfile
import sys
from pathlib import Path
from glayout import MappedPDK, sky130, gf180
from glayout.pdk.gf180_mapped import gf180_mapped_pdk as _gf180_pdk
from gdsfactory.typings import Component

def parse_drc_report(report_content: str) -> dict:
    """
    Parses a Magic DRC report into a machine-readable format.

    Magic DRC report format:
        cellname count: N
        ----------------------------------------
        Rule description (e.g. "N-well overlap < 0.43um (DF.7)")
        ----------------------------------------
         -0.890um  62.295um  -0.810um  62.680um   ← coordinate box (may be negative)
         0.810um   51.165um   0.890um  51.550um
        ...
    """
    errors = []
    current_rule = ""
    # coordinate line: optional leading whitespace, then optional minus, then digits
    _coord_re = re.compile(r"^-?\d+\.\d+")

    for line in report_content.strip().splitlines():
        stripped = line.strip()
        if not stripped or stripped == "----------------------------------------":
            continue
        # Rule header lines start with a letter (but NOT the "cellname count:" line)
        if re.match(r"^[a-zA-Z]", stripped) and "count:" not in stripped:
            current_rule = stripped
        # Coordinate box line — can start with '-' for negative coords
        elif _coord_re.match(stripped):
            errors.append({"rule": current_rule, "details": stripped})

    is_pass = len(errors) == 0

    return {
        "is_pass": is_pass,
        "total_errors": len(errors),
        "error_details": errors
    }

def parse_lvs_report(report_content: str) -> dict:
    """
    Parses the raw netgen LVS report and returns a summarized, machine-readable format.
    Focuses on parsing net and instance mismatches.
    """
    summary = {
        "is_pass": False,
        "conclusion": "LVS failed or report was inconclusive.",
        "total_mismatches": 0,
        "mismatch_details": {
            "nets": "Not found", 
            "devices": "Not found", 
            "unmatched_nets_parsed": [],
            "unmatched_instances_parsed": []
        }
    }
    
    # Primary check for LVS pass/fail
    if "Netlists match" in report_content or "Circuits match uniquely" in report_content:
        summary["is_pass"] = True
        summary["conclusion"] = "LVS Pass: Netlists match."
    elif "Netlist mismatch" in report_content or "Netlists do not match" in report_content:
        summary["conclusion"] = "LVS Fail: Netlist mismatch."

    for line in report_content.splitlines():
        line = line.strip()

        # Parse net mismatches
        net_mismatch_match = re.search(r"Net:\s*([^\|]+)\s*\|\s*\((no matching net)\)", line)
        if net_mismatch_match:
            name_left = net_mismatch_match.group(1).strip()
            # If name is on the left, it's in layout, missing in schematic
            summary["mismatch_details"]["unmatched_nets_parsed"].append({
                "type": "net",
                "name": name_left,
                "present_in": "layout",
                "missing_in": "schematic"
            })
            continue

        # Parse instance mismatches
        instance_mismatch_match = re.search(r"Instance:\s*([^\|]+)\s*\|\s*\((no matching instance)\)", line)
        if instance_mismatch_match:
            name_left = instance_mismatch_match.group(1).strip()
            # If name is on the left, it's in layout, missing in schematic
            summary["mismatch_details"]["unmatched_instances_parsed"].append({
                "type": "instance",
                "name": name_left,
                "present_in": "layout",
                "missing_in": "schematic"
            })
            continue

        # Also capture cases where something is present in schematic but missing in layout (right side of '|')
        net_mismatch_right_match = re.search(r"\s*\|\s*([^\|]+)\s*\((no matching net)\)", line)
        if net_mismatch_right_match:
            name_right = net_mismatch_right_match.group(1).strip()
            # If name is on the right, it's in schematic, missing in layout
            summary["mismatch_details"]["unmatched_nets_parsed"].append({
                "type": "net",
                "name": name_right,
                "present_in": "schematic",
                "missing_in": "layout"
            })
            continue

        instance_mismatch_right_match = re.search(r"\s*\|\s*([^\|]+)\s*\((no matching instance)\)", line)
        if instance_mismatch_right_match:
            name_right = instance_mismatch_right_match.group(1).strip()
            # If name is on the right, it's in schematic, missing in layout
            summary["mismatch_details"]["unmatched_instances_parsed"].append({
                "type": "instance",
                "name": name_right,
                "present_in": "schematic",
                "missing_in": "layout"
            })
            continue

        # Capture summary lines like "Number of devices:" and "Number of nets:"
        if "Number of devices:" in line:
            summary["mismatch_details"]["devices"] = line.split(":", 1)[1].strip() if ":" in line else line
        elif "Number of nets:" in line:
            summary["mismatch_details"]["nets"] = line.split(":", 1)[1].strip() if ":" in line else line

    # Calculate total mismatches
    summary["total_mismatches"] = len(summary["mismatch_details"]["unmatched_nets_parsed"]) + \
                                  len(summary["mismatch_details"]["unmatched_instances_parsed"])

    # If there are any mismatches found, then LVS fails, regardless of "Netlists match" string.
    if summary["total_mismatches"] > 0:
        summary["is_pass"] = False
        if "LVS Pass" in summary["conclusion"]: # If conclusion still says pass, update it
            summary["conclusion"] = "LVS Fail: Mismatches found."

    return summary

def run_verification(layout_path: str, component_name: str, top_level: Component) -> dict:
    """
    Runs DRC and LVS checks and returns a structured result dictionary.
    Note: PDK functions create directory structures:
      - DRC: {output_dir}/drc/{design_name}/{design_name}.rpt
      - LVS: {output_dir}/lvs/{design_name}/{design_name}_lvs.rpt
    """
    # Sanitize component name: strip gdsfactory $N suffix and special chars
    safe_name = re.sub(r'[\$\s].*$', '', component_name).upper()
    if not safe_name:
        safe_name = component_name.upper()

    # Always write a fresh GDS and rename the top cell via gdstk so the name
    # inside the file matches what Magic will be asked to load.
    # gdsfactory appends $N for uniqueness; setting .name alone doesn't rename
    # the underlying gdstk cell, causing Magic to find an empty cell and report
    # "No errors" — a false CLEAN.
    new_gds = os.path.abspath(f"./{safe_name}.gds")
    top_level.write_gds(new_gds)
    try:
        import gdstk as _gdstk
        _lib = _gdstk.read_gds(new_gds)
        _tops = _lib.top_level()
        if _tops and _tops[0].name != safe_name:
            _tops[0].name = safe_name
            _lib.write_gds(new_gds)
    except Exception:
        pass
    layout_path = new_gds
    component_name = safe_name

    verification_results = {
        "drc": {"status": "not run", "is_pass": False, "report_path": None, "summary": {}},
        "lvs": {"status": "not run", "is_pass": False, "report_path": None, "summary": {}}
    }

    # DRC Check
    # PDK creates: {drc_output_dir}/drc/{component_name}/{component_name}.rpt
    drc_output_dir = os.path.abspath(f"./{component_name}_drc_out")
    drc_actual_report = os.path.join(drc_output_dir, "drc", component_name, f"{component_name}.rpt")
    verification_results["drc"]["report_path"] = drc_actual_report
    try:
        # Clean up existing directory if present
        if os.path.exists(drc_output_dir):
            shutil.rmtree(drc_output_dir)
        # Pass pdk_root explicitly so drc_magic doesn't overwrite PDK_ROOT with
        # str(None) when self.pdk_root is unset (corrupts env for later calls).
        _pdk_root = os.environ.get("PDK_ROOT") or None
        _gf180_pdk.drc_magic(layout_path, component_name, output_file=drc_output_dir,
                             pdk_root=_pdk_root)
        report_content = ""
        if os.path.exists(drc_actual_report):
            with open(drc_actual_report, 'r') as f:
                report_content = f.read()
        summary = parse_drc_report(report_content)
        verification_results["drc"].update({"summary": summary, "is_pass": summary["is_pass"], "status": "pass" if summary["is_pass"] else "fail"})
    except Exception as e:
        verification_results["drc"]["status"] = f"error: {e}"

    # LVS Check
    # PDK creates: {lvs_output_dir}/lvs/{component_name}/{component_name}_lvs.rpt
    lvs_output_dir = os.path.abspath(f"./{component_name}_lvs_out")
    lvs_actual_report = os.path.join(lvs_output_dir, "lvs", component_name, f"{component_name}_lvs.rpt")
    verification_results["lvs"]["report_path"] = lvs_actual_report
    try:
        # Clean up existing directory if present
        if os.path.exists(lvs_output_dir):
            shutil.rmtree(lvs_output_dir)
        _gf180_pdk.lvs_netgen(layout=top_level, design_name=component_name, output_file_path=lvs_output_dir)
        report_content = ""
        if os.path.exists(lvs_actual_report):
            with open(lvs_actual_report, 'r') as report_file:
                report_content = report_file.read()
        lvs_summary = parse_lvs_report(report_content)
        verification_results["lvs"].update({"summary": lvs_summary, "is_pass": lvs_summary["is_pass"], "status": "pass" if lvs_summary["is_pass"] else "fail"})
    except Exception as e:
        verification_results["lvs"]["status"] = f"error: {e}"
        
    return verification_results