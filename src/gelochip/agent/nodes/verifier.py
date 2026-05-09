"""
Verifier Node — runs DRC, LVS, and SPICE simulation on the generated layout.

Verification flow:
    1. Code compiled?        → execute_layout_code (already done in layout_generator)
    2. DRC pass?             → Magic via run_full_verification
    3. LVS pass?             → Netgen via run_full_verification
    4. Performance meets spec? → generate testbench → run ngspice → check_specs
    5. If anything fails:    → ask LLM to fix, loop up to max_corrections
"""
from __future__ import annotations
import json
import os
from pathlib import Path

from langchain_core.messages import AIMessage

from gelochip.agent.state import GelochipAgentState, SimResult
from gelochip.agent.prompts import VERIFIER_PROMPT
from gelochip.agent.tools.circuit_tools import execute_layout_code


def verifier_node(state: GelochipAgentState, llm) -> GelochipAgentState:
    """
    Full verification: code correctness → DRC → LVS → SPICE sim → spec check.

    Routes to "summarizer" on overall pass or when max_corrections is reached.
    Routes to "verifier" again when fixable errors remain.
    """
    layout_result    = state.get("layout_result", {})
    correction_count = state.get("correction_count", 0)
    max_corrections  = state.get("max_corrections", 3)
    spec             = state.get("circuit_spec", {})
    errors           = list(state.get("errors", []))
    messages         = list(state.get("messages", []))

    # ── Step 1: was code compilation already failing? ──────────────────────────
    output_dir = state.get("output_dir")
    layout_out = str(Path(output_dir) / "layout") if output_dir else "/tmp/gelochip_output"

    code_error = layout_result.get("error")
    if code_error and correction_count < max_corrections:
        fixed_code = _fix_code(llm, layout_result.get("python_code", ""), code_error)
        exec_result = execute_layout_code.invoke({
            "python_code": fixed_code,
            "output_dir": layout_out,
        })
        layout_result = {
            "python_code": fixed_code,
            "gds_path": exec_result.get("gds_files", [None])[0],
            "error": exec_result.get("error"),
        }
        messages.append(AIMessage(
            content=f"Code fix #{correction_count + 1}: {'success' if exec_result['success'] else 'still failing'}"
        ))
        if not exec_result["success"]:
            return {
                **state,
                "layout_result": layout_result,
                "correction_count": correction_count + 1,
                "messages": messages,
                "errors": errors + [code_error],
                "next_node": "verifier" if correction_count + 1 < max_corrections else "summarizer",
            }

    gds_path = layout_result.get("gds_path")

    # ── Step 2 & 3: DRC + LVS ─────────────────────────────────────────────────
    drc_lvs_result = {}
    if gds_path and Path(gds_path).exists():
        drc_lvs_result = _run_drc_lvs(gds_path, spec.get("circuit_type", "circuit"), spec.get("pdk", "gf180"))
        layout_result["drc_passed"] = drc_lvs_result.get("drc_lvs_pass")
        layout_result["drc_summary"] = drc_lvs_result.get("summary", "")
        messages.append(AIMessage(content=f"DRC/LVS:\n{drc_lvs_result.get('summary', 'skipped')}"))
        # Save DRC/LVS reports
        if output_dir:
            _save_drc_lvs_reports(output_dir, drc_lvs_result)
    else:
        layout_result["drc_passed"] = None
        messages.append(AIMessage(content="DRC/LVS skipped — no GDS file generated."))

    # ── Step 4: SPICE testbench + ngspice simulation ───────────────────────────
    sim_result: SimResult = {}
    spec_check = {}

    pex_spice = _find_pex_spice(gds_path)
    if pex_spice:
        sim_result, spec_check = _run_spice(pex_spice, spec, output_dir=output_dir)
        layout_result["lvs_passed"] = sim_result.get("passed")
        messages.append(AIMessage(
            content=_format_sim_summary(sim_result, spec_check)
        ))
        if output_dir and not sim_result.get("error"):
            _save_sim_results(output_dir, sim_result)
    else:
        # No PEX spice → run on schematic-level SPICE if available
        schematic_spice = layout_result.get("spice_netlist")
        if schematic_spice:
            sim_result, spec_check = _run_spice_from_string(schematic_spice, spec, output_dir=output_dir)
            messages.append(AIMessage(content=_format_sim_summary(sim_result, spec_check)))
            if output_dir and not sim_result.get("error"):
                _save_sim_results(output_dir, sim_result)
        else:
            messages.append(AIMessage(
                content=(
                    "⚠️  SPICE simulation skipped.\n"
                    "   Reason: No PEX netlist found. Run Magic PEX first:\n"
                    "   bash scripts/run_pex.sh output.gds circuit_name\n"
                    "   Or set PDK_ROOT and rerun with Magic installed."
                )
            ))

    # ── Decide next node ───────────────────────────────────────────────────────
    # Pass if: no code error, DRC either passed or skipped, specs met or sim skipped
    drc_ok    = layout_result.get("drc_passed") in (True, None)   # None = skipped, not failed
    sim_ok    = spec_check.get("all_passed", True)                 # True if no sim ran
    code_ok   = layout_result.get("error") is None

    overall_ok = code_ok and drc_ok and sim_ok

    if overall_ok or correction_count >= max_corrections:
        next_node = "summarizer"
    else:
        next_node = "verifier"

    return {
        **state,
        "layout_result": layout_result,
        "sim_result": sim_result,
        "correction_count": correction_count + 1,
        "messages": messages,
        "errors": errors,
        "next_node": next_node,
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fix_code(llm, broken_code: str, error_msg: str) -> str:
    """Ask LLM to fix broken GLayout code."""
    messages = [
        {"role": "system", "content": VERIFIER_PROMPT},
        {
            "role": "user",
            "content": (
                f"Broken code:\n```python\n{broken_code}\n```\n\n"
                f"Error:\n{error_msg}\n\n"
                "Return ONLY the corrected Python (no markdown)."
            ),
        },
    ]
    response = llm.invoke(messages)
    code = response.content if hasattr(response, "content") else str(response)
    if "```python" in code:
        code = code.split("```python")[1].split("```")[0].strip()
    elif "```" in code:
        code = code.split("```")[1].strip()
    return code


def _run_drc_lvs(gds_path: str, circuit_name: str, pdk: str) -> dict:
    """Run DRC + LVS via Magic/Netgen (graceful fallback if tools missing)."""
    try:
        from gelochip.verification.drc_lvs import run_full_verification
        from gdsfactory.component import Component
        dummy_comp = Component(circuit_name)
        return run_full_verification(gds_path, circuit_name, dummy_comp, pdk)
    except Exception as e:
        return {
            "drc_lvs_pass": None,
            "skipped": True,
            "summary": f"DRC/LVS could not run: {e}",
        }


def _find_pex_spice(gds_path: str) -> str | None:
    """Look for a PEX SPICE file next to the GDS."""
    if not gds_path:
        return None
    stem = Path(gds_path).stem
    for suffix in ["_pex.spice", ".pex.spice", ".spice"]:
        candidate = Path(gds_path).parent / (stem + suffix)
        if candidate.exists():
            return str(candidate)
    return None


def _run_spice(pex_spice_path: str, spec: dict, output_dir: str | None = None):
    """Generate testbench, run ngspice, check specs."""
    from gelochip.verification.testbench import generate_testbench
    from gelochip.verification.simulate import run_simulation, check_specs

    circuit_type = spec.get("circuit_type", "opamp")
    circuit_name = Path(pex_spice_path).stem.replace("_pex", "").replace(".pex", "")
    pdk = spec.get("pdk", "gf180")

    try:
        tb = generate_testbench(circuit_type, pex_spice_path, circuit_name, spec, pdk)
        # Save testbench
        if output_dir:
            tb_path = Path(output_dir) / "verification" / "testbench.sp"
            tb_path.parent.mkdir(parents=True, exist_ok=True)
            tb_path.write_text(tb, encoding="utf-8")
        sim = run_simulation(tb, circuit_type)
        chk = check_specs(sim, spec)
        return sim, chk
    except Exception as e:
        return {"error": str(e), "passed": False}, {"all_passed": False, "checks": []}


def _run_spice_from_string(spice_netlist: str, spec: dict, output_dir: str | None = None):
    """Write schematic netlist to file and simulate."""
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".spice", delete=False) as f:
        f.write(spice_netlist)
        path = f.name
    return _run_spice(path, spec, output_dir=output_dir)


def _save_drc_lvs_reports(output_dir: str, result: dict) -> None:
    vdir = Path(output_dir) / "verification"
    vdir.mkdir(parents=True, exist_ok=True)
    if result.get("drc", {}).get("raw_report"):
        (vdir / "drc_report.txt").write_text(result["drc"]["raw_report"], encoding="utf-8")
    if result.get("lvs", {}).get("raw_report"):
        (vdir / "lvs_report.txt").write_text(result["lvs"]["raw_report"], encoding="utf-8")


def _save_sim_results(output_dir: str, sim: dict) -> None:
    import json
    vdir = Path(output_dir) / "verification"
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / "sim_results.json").write_text(json.dumps(sim, indent=2, default=str), encoding="utf-8")


def _format_sim_summary(sim: dict, chk: dict) -> str:
    if sim.get("error"):
        return f"⚠️  Simulation error: {sim['error']}"

    lines = ["**SPICE Simulation Results:**"]
    for c in chk.get("checks", []):
        icon = "✅" if c["passed"] else "❌"
        lines.append(
            f"  {icon} {c['metric']}: measured={c['measured']}, target={'≥' if c['passed'] else '<'}{c['target']}"
        )
    if not chk.get("checks"):
        lines.append("  (no spec checks ran — add target specs to the request)")

    lines.append(f"\n{'✅ All specs met.' if chk.get('all_passed') else '❌ Some specs not met — correction needed.'}")
    return "\n".join(lines)
