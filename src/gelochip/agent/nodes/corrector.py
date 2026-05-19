"""
Universal Corrector Node — fixes errors from any agent in the pipeline.

Handles errors from:
  - circuit_designer: JSON parse errors or PySpice simulation failures
  - layout_generator: GLayout code execution errors (imports, API mismatches, etc.)

Behaviour
---------
For layout errors (two layers):
  Layer 1 — Deterministic import sanitisation (no LLM, instant).
             If this fixes execution → routes to verifier.
  Layer 2 — LLM-guided full code regeneration with error context.
             If this fixes execution → routes to verifier.
             If still failing + budget → routes back to layout_generator with feedback.

For circuit_designer errors:
  LLM fixes the JSON params or PySpice code.
  On success → routes back to layout_generator (or circuit_designer for PySpice).
  On budget exhausted → routes to summarizer.

Custom block creation:
  When a required building block is missing, the LLM implements it manually.
  The block is saved to core/custom_blocks/ for future reuse.

Graph edges required
--------------------
circuit_designer  → corrector   (on JSON/PySpice error)
layout_generator  → corrector   (on code execution error)
corrector         → verifier    (layout fixed)
corrector         → layout_generator  (layout retry with feedback)
corrector         → circuit_designer  (params retry with feedback)
corrector         → summarizer  (budget exhausted)
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from langchain_core.messages import AIMessage

from gelochip.agent.state import GelochipAgentState
from gelochip.agent.prompts import CORRECTOR_PROMPT
from gelochip.agent.tools.circuit_tools import execute_layout_code, execute_pyspice_code


# ---------------------------------------------------------------------------
# Import sanitation tables (for layout errors)
# ---------------------------------------------------------------------------

_GLAYOUT_PRIMITIVES = {
    'nmos', 'pmos', 'multiplier',
    'c_route', 'L_route', 'straight_route', 'smart_route',
    'via_stack', 'via_array',
    'mimcap', 'mimcap_array',
    'resistor',
    'move', 'movex', 'movey', 'align_comp_to_port',
    'tapring',
}

_CELL_MODULE: dict[str, str] = {
    'lna_cascode':                 'core.cells.lna',
    'lna_inductively_degenerated': 'core.cells.lna',
    'two_stage_opamp':             'core.cells.opamp',
    'folded_cascode_opamp':        'core.cells.opamp',
    'gilbert_cell_mixer':          'core.cells.mixer',
    'passive_mixer':               'core.cells.mixer',
    'lc_vco':                      'core.cells.vco',
    'ring_vco':                    'core.cells.vco',
}

_PDK_OBJ = {
    'gf180':  'gf180_mapped_pdk',
    'sky130': 'sky130_mapped_pdk',
    'ihp130': 'ihp130_mapped_pdk',
}

_CANONICAL_HEADER = """\
import gdsfactory as gf
from glayout import (
    nmos, pmos, multiplier,
    c_route, L_route, straight_route, smart_route,
    via_stack, via_array,
    mimcap, mimcap_array,
    resistor,
    move, movex, movey, align_comp_to_port,
)
from core.primitives.passive import inductor
from core.cells.lna import lna_cascode, lna_inductively_degenerated
from core.cells.opamp import two_stage_opamp, folded_cascode_opamp
from core.cells.mixer import gilbert_cell_mixer, passive_mixer
from core.cells.vco import lc_vco, ring_vco
from glayout.pdk.gf180_mapped import gf180_mapped_pdk
from glayout.pdk.sky130_mapped import sky130_mapped_pdk
from glayout.pdk.ihp130_mapped import ihp130_mapped_pdk
"""


# ---------------------------------------------------------------------------
# Main node
# ---------------------------------------------------------------------------

def corrector_node(state: GelochipAgentState, llm) -> GelochipAgentState:
    """
    Universal error corrector — routes based on which node failed.

    Routing:
      failed_node == "layout_generator" → layout import fix + LLM regen
      failed_node == "circuit_designer" → JSON fix or PySpice fix
      budget exhausted                   → summarizer
    """
    failed_node      = state.get("failed_node", "layout_generator")
    correction_count = state.get("correction_count", 0)
    max_corrections  = state.get("max_corrections", 3)
    messages         = list(state.get("messages") or [])
    errors           = list(state.get("errors") or [])
    spec             = state.get("circuit_spec") or {}
    component_params = state.get("component_params") or {}

    messages.append(AIMessage(
        content=f"🔧 Corrector activated (attempt {correction_count + 1}/{max_corrections}) "
                f"— fixing '{failed_node}' error."
    ))

    if correction_count >= max_corrections:
        messages.append(AIMessage(content="❌ Max corrections reached → summarizer."))
        return {
            **state,
            "correction_count": correction_count + 1,
            "messages": messages,
            "errors": errors,
            "next_node": "summarizer",
        }

    if failed_node == "layout_generator":
        return _fix_layout(state, llm, messages, errors, spec, component_params, correction_count)
    else:
        return _fix_circuit_designer(state, llm, messages, errors, spec, component_params, correction_count)


# ---------------------------------------------------------------------------
# Layout correction (two-layer)
# ---------------------------------------------------------------------------

def _fix_layout(state, llm, messages, errors, spec, component_params, correction_count):
    layout_result = state.get("layout_result") or {}
    broken_code   = layout_result.get("python_code", "")
    error_msg     = layout_result.get("error") or ""
    pdk           = spec.get("pdk", "gf180")
    circuit_type  = spec.get("circuit_type", "lna")
    layout_out    = _resolve_layout_dir(state)

    # ── Layer 1: deterministic import sanitisation ───────────────────────────
    fixed_code = _sanitise(broken_code)
    fixed_code = _ensure_pdk_var(fixed_code, pdk)

    exec1 = execute_layout_code.invoke({"python_code": fixed_code, "output_dir": layout_out})

    if exec1["success"]:
        gds = (exec1.get("gds_files") or [None])[0]
        messages.append(AIMessage(
            content=f"✅ Corrector (import fix): code executes. GDS: {gds}"
        ))
        _maybe_save_custom_block(fixed_code, circuit_type, state)
        return {
            **state,
            "layout_result": {**layout_result, "python_code": fixed_code, "gds_path": gds, "error": None},
            "correction_count": correction_count + 1,
            "messages": messages,
            "corrector_feedback": None,
            "failed_node": None,
            "next_node": "verifier",
        }

    sanitised_error = exec1.get("error") or ""
    errors.append(sanitised_error)
    messages.append(AIMessage(content=f"⚠️  Import fix still failing:\n{sanitised_error[:400]}"))

    # ── Layer 2: LLM full regeneration ───────────────────────────────────────
    regen_code = _llm_fix_code(
        llm=llm,
        broken_code=fixed_code,
        error_msg=sanitised_error,
        spec=spec,
        component_params=component_params,
        failed_node="layout_generator",
        canonical_header=_CANONICAL_HEADER,
    )
    regen_code = _sanitise(regen_code)
    regen_code = _ensure_pdk_var(regen_code, pdk)

    exec2 = execute_layout_code.invoke({"python_code": regen_code, "output_dir": layout_out})

    if exec2["success"]:
        gds = (exec2.get("gds_files") or [None])[0]
        messages.append(AIMessage(
            content=f"✅ Corrector (LLM regen): code executes. GDS: {gds}"
        ))
        _maybe_save_custom_block(regen_code, circuit_type, state)
        return {
            **state,
            "layout_result": {**layout_result, "python_code": regen_code, "gds_path": gds, "error": None},
            "correction_count": correction_count + 1,
            "messages": messages,
            "errors": errors,
            "corrector_feedback": None,
            "failed_node": None,
            "next_node": "verifier",
        }

    regen_error = exec2.get("error") or ""
    errors.append(regen_error)

    # Route back to layout_generator with structured feedback
    feedback = _build_layout_feedback(circuit_type, regen_error, regen_code)
    messages.append(AIMessage(
        content=f"❌ LLM regen still failing. Sending feedback to layout_generator for retry."
    ))

    return {
        **state,
        "layout_result": {**layout_result, "python_code": regen_code, "gds_path": None, "error": regen_error},
        "correction_count": correction_count + 1,
        "messages": messages,
        "errors": errors,
        "corrector_feedback": feedback,
        "failed_node": "layout_generator",
        "next_node": "layout_generator",
    }


# ---------------------------------------------------------------------------
# Circuit designer correction (JSON params or PySpice)
# ---------------------------------------------------------------------------

_SIMULATOR_ERROR_PATTERNS = (
    "ngspice", "no such file", "simulator", "circuitsimulator",
    "spice program", "executable", "command not found", "factory",
    "netlist.py", "simulation.py",
)

def _is_simulator_error(error: str) -> bool:
    low = error.lower()
    return any(p in low for p in _SIMULATOR_ERROR_PATTERNS)


def _fix_circuit_designer(state, llm, messages, errors, spec, component_params, correction_count):
    pyspice_result   = state.get("pyspice_result") or {}
    pyspice_code     = state.get("pyspice_code") or ""
    error_msg        = pyspice_result.get("error") or (state.get("errors") or ["unknown error"])[-1]
    circuit_type     = spec.get("circuit_type", "circuit")

    # If the error is an ngspice/simulator infrastructure error, skip validation
    if _is_simulator_error(error_msg):
        messages.append(AIMessage(
            content="⚠️  PySpice error is from ngspice infrastructure (not circuit design). "
                    "Skipping simulation — proceeding to layout_generator."
        ))
        return {
            **state,
            "correction_count": correction_count + 1,
            "messages": messages,
            "errors": errors,
            "corrector_feedback": None,
            "failed_node": None,
            "next_node": "layout_generator",
        }

    # Determine if this is a JSON params error or PySpice circuit-logic error
    last_error = (state.get("errors") or [""])[-1]
    is_json_error = not component_params or "JSON error" in last_error or "json" in last_error.lower()

    if is_json_error or not pyspice_code:
        # Fix JSON params
        fixed_content = _llm_fix_code(
            llm=llm,
            broken_code=json.dumps(component_params, indent=2) if component_params else "{}",
            error_msg=error_msg,
            spec=spec,
            component_params=component_params,
            failed_node="circuit_designer_json",
            canonical_header="",
        )
        try:
            clean = fixed_content.strip().lstrip("```json").rstrip("```").strip()
            new_params = json.loads(clean)
            messages.append(AIMessage(content=f"✅ Corrector: fixed circuit params JSON."))
            return {
                **state,
                "component_params": new_params,
                "correction_count": correction_count + 1,
                "messages": messages,
                "errors": errors,
                "corrector_feedback": None,
                "failed_node": None,
                "next_node": "layout_generator",
            }
        except json.JSONDecodeError as e:
            errors.append(f"Corrector JSON fix failed: {e}")
            messages.append(AIMessage(content=f"❌ Corrector: JSON fix failed → summarizer."))
            return {
                **state,
                "correction_count": correction_count + 1,
                "messages": messages,
                "errors": errors,
                "next_node": "summarizer",
            }
    else:
        # Fix PySpice code
        fixed_pyspice = _llm_fix_code(
            llm=llm,
            broken_code=pyspice_code,
            error_msg=error_msg,
            spec=spec,
            component_params=component_params,
            failed_node="circuit_designer_pyspice",
            canonical_header="",
        )
        pyspice_out = _resolve_layout_dir(state)
        exec_result = execute_pyspice_code.invoke({
            "pyspice_code": fixed_pyspice,
            "output_dir": pyspice_out,
        })

        if exec_result["success"]:
            messages.append(AIMessage(
                content=f"✅ Corrector: PySpice fixed. Proceeding to layout_generator."
            ))
            if state.get("output_dir"):
                from gelochip.agent.output_manager import OutputManager
                _om = OutputManager.__new__(OutputManager)
                _om.root = Path(state["output_dir"])
                _om._mkdir(_om.root / "spice")
                _om.save_pyspice_code(fixed_pyspice)
            return {
                **state,
                "pyspice_code": fixed_pyspice,
                "pyspice_result": exec_result,
                "correction_count": correction_count + 1,
                "messages": messages,
                "errors": errors,
                "corrector_feedback": None,
                "failed_node": None,
                "next_node": "layout_generator",
            }

        pyspice_error = exec_result.get("error") or ""
        errors.append(pyspice_error)
        feedback = (
            f"## Corrector Feedback — PySpice Fix Failed\n\n"
            f"### Error\n```\n{pyspice_error[:600]}\n```\n\n"
            f"### Guidance\n"
            f"- Check MOSFET operating points (all must be in saturation)\n"
            f"- Verify supply voltages match PDK spec ({spec.get('pdk','gf180')})\n"
            f"- Ensure ngspice-compatible syntax\n"
        )
        messages.append(AIMessage(
            content=f"❌ PySpice fix failed. Sending feedback to circuit_designer for retry."
        ))
        return {
            **state,
            "pyspice_code": fixed_pyspice,
            "pyspice_result": exec_result,
            "correction_count": correction_count + 1,
            "messages": messages,
            "errors": errors,
            "corrector_feedback": feedback,
            "failed_node": "circuit_designer",
            "next_node": "circuit_designer",
        }


# ---------------------------------------------------------------------------
# LLM fix helper
# ---------------------------------------------------------------------------

def _llm_fix_code(
    llm,
    broken_code: str,
    error_msg: str,
    spec: dict,
    component_params: dict,
    failed_node: str,
    canonical_header: str,
) -> str:
    """Ask the LLM to fix the failing code, with full error context as input."""
    context_parts = [
        f"## Failed node: {failed_node}",
        f"\n## Error\n```\n{error_msg}\n```",
        f"\n## Broken code\n```\n{broken_code}\n```",
        f"\n## Circuit spec\n{json.dumps(spec, indent=2)}",
    ]
    if component_params:
        context_parts.append(f"\n## Component params\n{json.dumps(component_params, indent=2)}")
    if canonical_header:
        context_parts.append(f"\n## Canonical import header (use verbatim)\n```python\n{canonical_header}```")

    context_parts.append(
        "\nFix the code so it runs without errors. "
        "Return ONLY the corrected code — no markdown fences, no explanation."
    )

    prompt_msgs = [
        {"role": "system", "content": CORRECTOR_PROMPT},
        {"role": "user", "content": "\n".join(context_parts)},
    ]

    resp = llm.invoke(prompt_msgs)
    code = resp.content if hasattr(resp, "content") else str(resp)
    if "```python" in code:
        code = code.split("```python")[1].split("```")[0].strip()
    elif "```json" in code:
        code = code.split("```json")[1].split("```")[0].strip()
    elif "```" in code:
        code = code.split("```")[1].strip()
    return code


# ---------------------------------------------------------------------------
# Custom block saving
# ---------------------------------------------------------------------------

def _maybe_save_custom_block(code: str, circuit_type: str, state: GelochipAgentState) -> None:
    """
    If the corrected code contains manually-implemented functions (not in the
    canonical cells), save them to core/custom_blocks/ for future reuse.
    """
    try:
        _save_custom_block_file(code, circuit_type)
    except Exception:
        pass  # Saving is best-effort; never block the pipeline


def _save_custom_block_file(code: str, circuit_type: str) -> None:
    """Extract top-level functions from code and save them to custom_blocks/."""
    # Find custom_blocks dir
    here = Path(__file__).resolve()
    custom_dir: Path | None = None
    for p in here.parents:
        cb = p / "core" / "custom_blocks"
        if cb.is_dir():
            custom_dir = cb
            break
    if not custom_dir:
        return

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return

    known_imports = set(_CELL_MODULE.keys()) | _GLAYOUT_PRIMITIVES | {
        "inductor", "gf180_mapped_pdk", "sky130_mapped_pdk", "ihp130_mapped_pdk"
    }

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        name = node.name
        if name.startswith("_") or name in known_imports or name in (
            "generate_" + circuit_type, circuit_type
        ):
            continue

        # Extract function source
        lines = code.splitlines()
        start = node.lineno - 1
        end = getattr(node, "end_lineno", start + 20)
        func_source = "\n".join(lines[start:end])

        # Only save functions that look like layout pcells (return Component)
        if "gf.Component" not in func_source and "Component" not in func_source:
            continue

        out_file = custom_dir / f"{name}.py"
        if out_file.exists():
            continue  # Don't overwrite existing blocks

        header = (
            f'"""Auto-generated custom block: {name}."""\n'
            f"from __future__ import annotations\n"
            f"import gdsfactory as gf\n"
            f"from glayout import (\n"
            f"    nmos, pmos, multiplier,\n"
            f"    c_route, L_route, straight_route, smart_route,\n"
            f"    via_stack, via_array, mimcap, mimcap_array, resistor,\n"
            f"    move, movex, movey, align_comp_to_port,\n"
            f")\n\n"
        )
        out_file.write_text(header + func_source + "\n")


# ---------------------------------------------------------------------------
# Import sanitisation (for layout errors — identical to old layout_corrector)
# ---------------------------------------------------------------------------

def _sanitise(code: str) -> str:
    out: list[str] = []
    gf_injected = False

    for raw_line in code.splitlines():
        line = raw_line

        line = re.sub(r'\bgelochip\.glayout\b', 'glayout', line)
        line = re.sub(r'\bgelochip\.core\b',    'core',    line)

        stripped = line.strip()

        if re.search(
            r'from\s+(?:glayout|gelochip\S*)\s+import\s+[^#\n]*\bComponent\b',
            stripped,
        ):
            if not gf_injected:
                out.append('import gdsfactory as gf')
                gf_injected = True
            rest = re.sub(r'\bComponent\b\s*,?\s*', '', stripped)
            rest = re.sub(r',\s*$', '', rest).strip()
            if rest and not rest.rstrip().endswith('import'):
                out.append(_rerout_import(rest))
            continue

        if re.search(r'\bComponent\b', stripped) and not stripped.startswith('#'):
            if not gf_injected and not re.search(r'import\s+gdsfactory', stripped):
                out.insert(0, 'import gdsfactory as gf')
                gf_injected = True

        if re.match(r'from\s+glayout\s+import\b', stripped):
            out.extend(_split_glayout_import(stripped))
            continue

        if re.match(r'from\s+gelochip\s+import\b', stripped):
            names = [n.strip() for n in stripped.split('import', 1)[1].split(',')]
            out.extend(_route_names(names))
            continue

        for pdk_name, pdk_obj in _PDK_OBJ.items():
            line = re.sub(
                rf'from\s+glayout\s+import\s+({re.escape(pdk_obj)})',
                rf'from glayout.pdk.{pdk_name}_mapped import \1',
                line,
            )

        out.append(line)

    result = '\n'.join(out)
    result = re.sub(r'(?<!gf\.)(?<!\w)Component\s*\(', 'gf.Component(', result)
    return result


def _split_glayout_import(stmt: str) -> list[str]:
    names_raw = stmt.split('import', 1)[1]
    names = [n.strip().strip('()') for n in names_raw.split(',') if n.strip()]

    cell_names  = [n for n in names if n in _CELL_MODULE]
    prim_names  = [n for n in names if n in _GLAYOUT_PRIMITIVES]
    pdk_names   = [n for n in names if n in set(_PDK_OBJ.values())]
    other_names = [n for n in names if n not in _CELL_MODULE
                   and n not in _GLAYOUT_PRIMITIVES
                   and n not in set(_PDK_OBJ.values())
                   and n != 'Component']

    lines = []
    by_mod: dict[str, list[str]] = {}
    for n in cell_names:
        by_mod.setdefault(_CELL_MODULE[n], []).append(n)
    for mod, fns in by_mod.items():
        lines.append(f"from {mod} import {', '.join(fns)}")
    if prim_names:
        lines.append(f"from glayout import {', '.join(prim_names)}")
    for pdk_obj in pdk_names:
        pdk_key = next(k for k, v in _PDK_OBJ.items() if v == pdk_obj)
        lines.append(f"from glayout.pdk.{pdk_key}_mapped import {pdk_obj}")
    if other_names:
        lines.append(f"from glayout import {', '.join(other_names)}")
    return lines or [stmt]


def _rerout_import(stmt: str) -> str:
    if not re.match(r'from\s+\w', stmt):
        return stmt
    names = [n.strip() for n in stmt.split('import', 1)[1].split(',') if n.strip()]
    lines = _route_names(names)
    return '\n'.join(lines) if lines else stmt


def _route_names(names: list[str]) -> list[str]:
    lines = []
    by_mod: dict[str, list[str]] = {}
    prims, others = [], []
    for n in names:
        n = n.strip()
        if not n:
            continue
        if n in _CELL_MODULE:
            by_mod.setdefault(_CELL_MODULE[n], []).append(n)
        elif n in _GLAYOUT_PRIMITIVES:
            prims.append(n)
        elif n == 'inductor':
            by_mod.setdefault('core.primitives.passive', []).append(n)
        else:
            others.append(n)
    for mod, fns in by_mod.items():
        lines.append(f"from {mod} import {', '.join(fns)}")
    if prims:
        lines.append(f"from glayout import {', '.join(prims)}")
    if others:
        lines.append(f"from glayout import {', '.join(others)}")
    return lines


def _ensure_pdk_var(code: str, pdk: str) -> str:
    pdk_obj = _PDK_OBJ.get(pdk, 'gf180_mapped_pdk')
    if re.search(r'\bpdk\s*=\s*\w+_mapped_pdk\b', code):
        return code
    return f'pdk = {pdk_obj}\n' + code


# ---------------------------------------------------------------------------
# Feedback builder
# ---------------------------------------------------------------------------

def _build_layout_feedback(circuit_type: str, error: str, code: str) -> str:
    lines = [
        f"## Corrector Feedback — {circuit_type}",
        "",
        "### What was tried",
        "1. Deterministic import sanitisation",
        "2. LLM-guided full code regeneration",
        "",
        "### Remaining error",
        f"```\n{error[:600]}\n```",
        "",
        "### Guidance for next attempt",
    ]

    if "cannot import name" in error or "ImportError" in error:
        bad = re.search(r"cannot import name '(\w+)'", error)
        name = bad.group(1) if bad else "unknown"
        mod = _CELL_MODULE.get(name)
        if mod:
            lines.append(f"- `{name}` must be imported from `{mod}`, NOT from glayout.")
        else:
            lines.append(f"- `{name}` is not in any module — implement it manually from nmos/pmos primitives.")
    elif "NameError" in error:
        name = re.search(r"name '(\w+)' is not defined", error)
        if name:
            lines.append(f"- `{name.group(1)}` is used but never defined — add it.")
    elif "TypeError" in error:
        lines.append("- Wrong function arguments — check parameter names in the building block signature.")
    elif "AttributeError" in error:
        lines.append("- Missing port/attribute — verify Component ports exist before routing.")
    else:
        lines.append("- Try a completely different code structure using only glayout primitives.")

    lines += [
        "",
        "### Always use this import header",
        "```python",
        _CANONICAL_HEADER.strip(),
        "```",
    ]
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _resolve_layout_dir(state: GelochipAgentState) -> str:
    output_dir = state.get("output_dir")
    if output_dir:
        path = Path(output_dir) / "layout"
    else:
        pkg = Path(__file__).resolve()
        for p in pkg.parents:
            if (p / "pyproject.toml").exists():
                path = p / "outputs" / "layout"
                break
        else:
            path = Path.cwd() / "outputs" / "layout"
    path.mkdir(parents=True, exist_ok=True)
    return str(path)
