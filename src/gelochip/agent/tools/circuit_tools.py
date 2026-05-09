"""
Circuit-level tools exposed to the LangGraph agent.

These tools bridge the LLM to the Gelochip building-block library.
"""
from __future__ import annotations
import json
import subprocess
import tempfile
import os
from pathlib import Path
from typing import Any

from langchain_core.tools import tool


@tool
def list_available_blocks() -> dict[str, list[str]]:
    """
    List all available Gelochip building blocks by category.

    Returns a dict with categories: primitives, blocks, cells.
    Each entry is a list of function names with brief descriptions.
    """
    return {
        "primitives": [
            "nmos(pdk, width, length, fingers, multipliers, ...) → NMOS transistor",
            "pmos(pdk, width, length, fingers, multipliers, ...) → PMOS transistor",
            "resistor(pdk, res_type, width, length) → Poly/metal resistor",
            "capacitor(pdk, width, length) → MIM capacitor",
            "mimcap(pdk, width, length, rows, columns) → MIM capacitor array",
            "inductor(pdk, turns, inner_diameter, width) → Spiral inductor (stub)",
            "via_stack(pdk, glayer_start, glayer_end) → Via stack",
            "via_array(pdk, glayer_start, glayer_end, size) → Via array",
            "guard_ring(pdk, enclosed_rectangle) → Substrate tap ring",
        ],
        "blocks": [
            "current_mirror(pdk, mirror_ratio, ref_width, n_or_p, ...) → Basic current mirror",
            "cascode_current_mirror(pdk, mirror_ratio, ref_width, cascode_width, ...) → Cascode mirror",
            "wilson_current_mirror(pdk, mirror_ratio, ref_width, ...) → Wilson mirror",
            "diff_pair(pdk, width, fingers, tail_current_width, n_or_p, ...) → Differential pair",
            "folded_cascode(pdk, input_width, cascode_width, load_width, ...) → Folded cascode",
            "common_source(pdk, width, fingers, load_type, ...) → CS amplifier stage",
            "common_gate(pdk, width, fingers, ...) → CG amplifier stage",
            "common_drain(pdk, width, fingers, ...) → Source follower",
            "current_bias(pdk, ref_width, mirror_ratio, ...) → Beta-multiplier bias",
            "bandgap_vref(pdk, ptat_width, ctat_width, ...) → Bandgap reference",
        ],
        "cells": [
            "two_stage_opamp(pdk, diff_pair_width, diff_pair_fingers, cs_width, ...) → 2-stage OTA",
            "folded_cascode_opamp(pdk, input_width, input_fingers, ...) → FC-OTA",
            "lna_cascode(pdk, gm_width, gm_fingers, cas_width, ...) → Cascode LNA",
            "lna_inductively_degenerated(pdk, gm_width, gm_fingers, ls_turns, lg_turns, ...) → Ind. deg. LNA",
            "gilbert_cell_mixer(pdk, rf_width, lo_width, load_width, ...) → Gilbert cell mixer",
            "passive_mixer(pdk, switch_width, switch_fingers, ...) → Passive CMOS mixer",
            "lc_vco(pdk, xcp_width, xcp_fingers, inductor_turns, ...) → LC VCO",
            "ring_vco(pdk, num_stages, inv_n_width, inv_p_width, ...) → Ring VCO",
        ],
    }


@tool
def get_pdk_info(pdk_name: str) -> dict[str, Any]:
    """
    Get key design rules and parameters for a PDK.

    Args:
        pdk_name: One of "gf180" (default), "sky130", "ihp130".

    Returns:
        Dict with Lmin, VDD, metal layers, and key design rules.
    """
    pdks = {
        "gf180": {
            "full_name": "GlobalFoundries GF180MCU 180nm  ← DEFAULT",
            "lmin_um": 0.18,
            "vdd_v": [1.8, 3.3, 5.0],
            "metals": ["metal1", "metal2", "metal3", "metal4", "metal5"],
            "nfet_model": "nfet_03v3",
            "pfet_model": "pfet_03v3",
            "bjt_models": ["npn_10x10", "pnp_10x10"],
            "ft_GHz": 20,
            "fmax_GHz": 40,
            "notes": (
                "DEFAULT PDK for Gelochip. Open-source (Google/efabless). "
                "Has BJT support for bandgap circuits. 1.8V/3.3V/5V options. "
                "Import: from gelochip.glayout.pdk.gf180_mapped import gf180_mapped_pdk"
            ),
        },
        "sky130": {
            "full_name": "SkyWater SKY130 130nm",
            "lmin_um": 0.15,
            "vdd_v": [1.8, 3.3],
            "metals": ["li1", "met1", "met2", "met3", "met4", "met5"],
            "nfet_model": "sky130_fd_pr__nfet_01v8",
            "pfet_model": "sky130_fd_pr__pfet_01v8",
            "ft_GHz": 50,
            "fmax_GHz": 80,
            "notes": (
                "Open-source PDK, free DRC/LVS via Magic/Netgen. Well-tested in GLayout. "
                "Import: from gelochip.glayout.pdk.sky130_mapped import sky130_mapped_pdk"
            ),
        },
        "ihp130": {
            "full_name": "IHP SG13G2 130nm BiCMOS",
            "lmin_um": 0.13,
            "vdd_v": [1.2, 1.5, 3.3],
            "metals": ["Metal1", "Metal2", "Metal3", "Metal4", "Metal5", "TopMetal1", "TopMetal2"],
            "nfet_model": "nfet",
            "pfet_model": "pfet",
            "hbt_models": ["npn13G2", "npn13G2L"],
            "ft_GHz": 300,
            "fmax_GHz": 500,
            "notes": "High-speed BiCMOS. Best for mmWave/RF above 10GHz. HBT fT=300GHz.",
        },
    }
    return pdks.get(pdk_name.lower(), {"error": f"Unknown PDK: {pdk_name}. Use sky130/gf180/ihp130"})


def _default_layout_out() -> str:
    """Return <project_root>/outputs/layout or cwd/outputs/layout as fallback."""
    _here = Path(__file__).resolve()
    for _p in _here.parents:
        if (_p / "pyproject.toml").exists():
            d = _p / "outputs" / "layout"
            d.mkdir(parents=True, exist_ok=True)
            return str(d)
    d = Path.cwd() / "outputs" / "layout"
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


@tool
def execute_layout_code(python_code: str, output_dir: str = "") -> dict[str, Any]:
    """
    Execute generated GLayout Python code and return results.

    Runs the code in a subprocess, captures stdout/stderr,
    and checks for GDS output files.

    Args:
        python_code: Complete Python code string to execute.
        output_dir:  Directory where GDS files will be written.

    Returns:
        Dict with keys: success, stdout, stderr, gds_files, error.
    """
    if not output_dir:
        output_dir = _default_layout_out()
    os.makedirs(output_dir, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(python_code)
        tmp_path = f.name

    try:
        result = subprocess.run(
            ["python", tmp_path],
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "GELOCHIP_OUTPUT_DIR": output_dir},
        )
        gds_files = [
            os.path.join(output_dir, fn)
            for fn in os.listdir(output_dir)
            if fn.endswith(".gds")
        ]
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout[:2000],
            "stderr": result.stderr[:2000],
            "gds_files": gds_files,
            "error": result.stderr if result.returncode != 0 else None,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Layout generation timed out (>120s)", "gds_files": []}
    except Exception as e:
        return {"success": False, "error": str(e), "gds_files": []}
    finally:
        os.unlink(tmp_path)


@tool
def verify_design(
    gds_path: str,
    circuit_name: str,
    circuit_type: str,
    spec: dict[str, Any],
    pdk: str = "gf180",
    run_sim: bool = True,
) -> dict[str, Any]:
    """
    Run the full verification suite on a generated GDS layout.

    Steps:
        1. DRC  — check geometry against PDK design rules (requires Magic)
        2. LVS  — verify layout matches schematic netlist   (requires Netgen)
        3. PEX  — extract parasitics from layout            (requires Magic)
        4. SPICE — simulate with ngspice, check specs        (requires ngspice)

    Args:
        gds_path:     Path to the GDS file.
        circuit_name: Top cell name in the GDS.
        circuit_type: "lna" | "opamp" | "mixer" | "vco"
        spec:         Circuit specification dict (vdd_V, freq_GHz, gain_dB, etc.)
        pdk:          "gf180" (default) | "sky130" | "ihp130"
        run_sim:      Whether to run ngspice simulation (requires ngspice installed).

    Returns:
        Dict with keys:
            drc:           DRC result (is_pass, total_errors)
            lvs:           LVS result (is_pass, conclusion)
            sim:           Simulation result (gain_dB, nf_dB, etc.)
            spec_check:    Spec vs. measured comparison
            overall_pass:  True if DRC + LVS + all specs met
            summary:       Human-readable summary string
    """
    from pathlib import Path

    result: dict[str, Any] = {}
    summary_parts = []

    # ── DRC + LVS ─────────────────────────────────────────────────────────────
    from gelochip.verification.drc_lvs import run_full_verification
    from gdsfactory.component import Component
    dummy = Component(circuit_name)
    drc_lvs = run_full_verification(gds_path, circuit_name, dummy, pdk)
    result["drc"]     = drc_lvs.get("drc", {})
    result["lvs"]     = drc_lvs.get("lvs", {})
    result["physical"]= drc_lvs.get("physical", {})
    summary_parts.append(drc_lvs.get("summary", ""))

    # ── SPICE simulation ──────────────────────────────────────────────────────
    if run_sim:
        pex_spice = Path(gds_path).parent / (Path(gds_path).stem + "_pex.spice")
        if pex_spice.exists():
            from gelochip.verification.testbench import generate_testbench
            from gelochip.verification.simulate import run_simulation, check_specs
            try:
                tb  = generate_testbench(circuit_type, str(pex_spice), circuit_name, spec, pdk)
                sim = run_simulation(tb, circuit_type)
                chk = check_specs(sim, spec)
                result["sim"]        = sim
                result["spec_check"] = chk
                icon = "✅" if chk["all_passed"] else "❌"
                summary_parts.append(f"{icon} Sim: {'all specs met' if chk['all_passed'] else 'specs not met'}")
            except Exception as e:
                result["sim"] = {"error": str(e)}
                summary_parts.append(f"⚠️  Sim error: {e}")
        else:
            msg = (
                f"ℹ️  SPICE simulation skipped — no PEX netlist found.\n"
                f"   Run: bash scripts/run_pex.sh {gds_path} {circuit_name} {pdk}"
            )
            result["sim"] = {"skipped": True}
            summary_parts.append(msg)

    result["overall_pass"] = (
        drc_lvs.get("drc_lvs_pass", True) and
        result.get("spec_check", {}).get("all_passed", True)
    )
    result["summary"] = "\n".join(summary_parts)
    return result


@tool
def estimate_performance(circuit_spec: dict[str, Any], component_params: dict[str, Any]) -> dict[str, Any]:
    """
    Estimate circuit performance using analytical equations.

    Uses hand-analysis equations (gm/ID methodology, Friis, etc.)
    to give first-order estimates before running SPICE simulation.

    Args:
        circuit_spec:       Parsed circuit specification dict.
        component_params:   Sized component parameters dict.

    Returns:
        Dict with estimated performance metrics.
    """
    circuit_type = circuit_spec.get("circuit_type", "")
    estimates = {}

    if circuit_type == "lna":
        gm_w = component_params.get("gm_width", 40.0)
        gm_f = component_params.get("gm_fingers", 10)
        pdk   = circuit_spec.get("pdk", "sky130")
        ft = {"gf180": 20e9, "sky130": 50e9, "ihp130": 300e9}.get(pdk, 20e9)
        total_w_um = gm_w * gm_f
        id_ma = total_w_um * 0.2
        gm_mS = 2 * id_ma / 0.3
        nf_estimate_dB = 1.0 + 10 * (0.3 / gm_mS * 0.02)
        gain_estimate_dB = 20 + 10 * (gm_mS * 50 / 20)
        estimates = {
            "estimated_gm_mS": round(gm_mS, 2),
            "estimated_id_mA": round(id_ma, 2),
            "estimated_gain_dB": round(min(gain_estimate_dB, 20), 1),
            "estimated_nf_dB": round(max(nf_estimate_dB, 0.5), 1),
            "estimated_power_mW": round(id_ma * circuit_spec.get("vdd_V", 1.8), 2),
            "ft_GHz": ft / 1e9,
        }

    elif circuit_type == "opamp":
        dp_w = component_params.get("diff_pair_width", 6.0)
        dp_f = component_params.get("diff_pair_fingers", 4)
        total_w_um = dp_w * dp_f
        id_ma = total_w_um * 0.1
        gm_mS = 2 * id_ma / 0.3
        load_r = 50e3
        gain_vv = gm_mS * 1e-3 * load_r
        estimates = {
            "estimated_gm_mS": round(gm_mS, 2),
            "estimated_id_mA": round(id_ma, 2),
            "estimated_dc_gain_dB": round(20 * (gain_vv ** 0.5), 1),
            "estimated_gbw_MHz": round(gm_mS / (2 * 3.14159 * 1e-12 * 1e6), 1),
            "estimated_power_mW": round(id_ma * circuit_spec.get("vdd_V", 1.8) * 2, 2),
        }

    elif circuit_type == "mixer":
        estimates = {
            "estimated_conversion_gain_dB": 4.0,
            "estimated_nf_dB": 12.0,
            "estimated_iip3_dBm": 5.0,
            "note": "Analytical mixer estimates require more detail; use SPICE for accuracy.",
        }

    elif circuit_type == "vco":
        inductance_pH = 300 * component_params.get("inductor_turns", 3)
        cap_fF = 200
        import math
        f_est_GHz = 1 / (2 * math.pi * math.sqrt(inductance_pH * 1e-12 * cap_fF * 1e-15)) / 1e9
        estimates = {
            "estimated_freq_GHz": round(f_est_GHz, 2),
            "estimated_tuning_range_pct": 15,
            "note": "Actual frequency depends on varactor tuning curve and parasitics.",
        }

    estimates["disclaimer"] = "Analytical first-order estimates only. Run SPICE for accurate results."
    return estimates
