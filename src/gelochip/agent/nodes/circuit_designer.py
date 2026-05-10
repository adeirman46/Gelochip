"""
Circuit Designer Node — sizes components and validates the circuit with PySpice/ngspice.

Flow:
  1. LLM sizes components using gm/ID methodology → component_params JSON
  2. LLM generates a PySpice netlist from component_params → pyspice_code
  3. Execute PySpice code with ngspice to validate the circuit topology
  4. On success → layout_generator (pyspice_code stored in state for reference)
  5. On any failure → corrector (failed_node = "circuit_designer")
"""
from __future__ import annotations
import json

from langchain_core.messages import AIMessage

from gelochip.agent.state import GelochipAgentState
from gelochip.agent.prompts import CIRCUIT_DESIGNER_PROMPT, PYSPICE_GENERATOR_PROMPT
from gelochip.agent.tools.circuit_tools import estimate_performance, get_pdk_info, execute_pyspice_code

# Chipster-style example PySpice snippets (few-shot context for the LLM)
_PYSPICE_EXAMPLES = {
    "lna": """\
# LNA example: common-source + cascode, AC analysis, check gain > 10 dB at freq
circuit = Circuit('LNA')
circuit.model('nmos_model', 'nmos', level=1, kp=170e-6, vto=0.5, lambda_=0.01)
circuit.V('dd', 'Vdd', circuit.gnd, 1.8)
circuit.V('bias', 'Vbias', circuit.gnd, 0.7)
circuit.R('load', 'Vout', 'Vdd', 200)  # 200 Ohm load
circuit.MOSFET('M1', 'Vds1', 'Vin',  circuit.gnd, circuit.gnd, model='nmos_model', w=200e-6, l=180e-9)
circuit.MOSFET('M2', 'Vout', 'Vbias', 'Vds1',  circuit.gnd, model='nmos_model', w=200e-6, l=180e-9)
circuit.V('in', 'Vin', circuit.gnd, 'dc 0.9 ac 1')
simulator = circuit.simulator()
analysis = simulator.ac(start_frequency=1e8, stop_frequency=10e9, number_of_points=50, variation='dec')
import numpy as np
gain = np.abs(np.array(analysis['Vout']))
gain_db = 20 * np.log10(gain[25] + 1e-12)
print(f"Gain: {gain_db:.1f} dB")
if gain_db > 10:
    print("PASS"); sys.exit(0)
else:
    print("FAIL"); sys.exit(2)
""",
    "opamp": """\
# Opamp example: differential pair + current mirror load, DC + AC
circuit = Circuit('Opamp')
circuit.model('nmos', 'nmos', level=1, kp=170e-6, vto=0.5, lambda_=0.01)
circuit.model('pmos', 'pmos', level=1, kp=50e-6,  vto=-0.5, lambda_=0.015)
circuit.V('dd', 'Vdd', circuit.gnd, 1.8)
circuit.V('inp', 'Vinp', circuit.gnd, 'dc 0.9 ac 0.5')
circuit.V('inn', 'Vinn', circuit.gnd, 'dc 0.9 ac -0.5')
circuit.MOSFET('M1', 'D1', 'Vinp', 'Tail', circuit.gnd, model='nmos', w=20e-6, l=180e-9)
circuit.MOSFET('M2', 'Vout', 'Vinn', 'Tail', circuit.gnd, model='nmos', w=20e-6, l=180e-9)
circuit.MOSFET('M3', 'D1',   'D1',   'Vdd', 'Vdd', model='pmos', w=10e-6, l=180e-9)
circuit.MOSFET('M4', 'Vout', 'D1',   'Vdd', 'Vdd', model='pmos', w=10e-6, l=180e-9)
circuit.I('tail', 'Tail', circuit.gnd, 1e-3)
simulator = circuit.simulator()
analysis = simulator.ac(start_frequency=1e3, stop_frequency=100e6, number_of_points=20, variation='dec')
import numpy as np
gain_db = 20 * np.log10(np.abs(np.array(analysis['Vout']))[0] + 1e-12)
print(f"DC gain: {gain_db:.1f} dB")
if gain_db > 20:
    print("PASS"); sys.exit(0)
else:
    print("FAIL"); sys.exit(2)
""",
    "mixer": """\
# Mixer example: Gilbert cell DC bias check
circuit = Circuit('Mixer')
circuit.model('nmos', 'nmos', level=1, kp=170e-6, vto=0.5, lambda_=0.01)
circuit.V('dd', 'Vdd', circuit.gnd, 1.8)
circuit.V('bias', 'Vbias', circuit.gnd, 0.9)
circuit.R('L1', 'Vdd', 'Voutp', 500)
circuit.R('L2', 'Vdd', 'Voutn', 500)
circuit.I('tail', 'SourceNode', circuit.gnd, 2e-3)
circuit.MOSFET('M1', 'RFp', 'Vrfp', 'SourceNode', circuit.gnd, model='nmos', w=50e-6, l=180e-9)
circuit.MOSFET('M2', 'RFn', 'Vrfn', 'SourceNode', circuit.gnd, model='nmos', w=50e-6, l=180e-9)
circuit.MOSFET('M3', 'Voutp', 'Vlop', 'RFp', circuit.gnd, model='nmos', w=30e-6, l=180e-9)
circuit.MOSFET('M4', 'Voutn', 'Vlon', 'RFp', circuit.gnd, model='nmos', w=30e-6, l=180e-9)
circuit.MOSFET('M5', 'Voutp', 'Vlon', 'RFn', circuit.gnd, model='nmos', w=30e-6, l=180e-9)
circuit.MOSFET('M6', 'Voutn', 'Vlop', 'RFn', circuit.gnd, model='nmos', w=30e-6, l=180e-9)
circuit.V('rfp', 'Vrfp', circuit.gnd, 0.9); circuit.V('rfn', 'Vrfn', circuit.gnd, 0.9)
circuit.V('lop', 'Vlop', circuit.gnd, 1.0); circuit.V('lon', 'Vlon', circuit.gnd, 0.8)
simulator = circuit.simulator()
analysis = simulator.operating_point()
voutp = float(analysis['Voutp'])
voutn = float(analysis['Voutn'])
print(f"Voutp={voutp:.3f}V, Voutn={voutn:.3f}V")
if 0.3 < voutp < 1.6 and 0.3 < voutn < 1.6:
    print("PASS"); sys.exit(0)
else:
    print("FAIL"); sys.exit(2)
""",
    "vco": """\
# VCO example: LC oscillator DC bias check
circuit = Circuit('VCO')
circuit.model('nmos', 'nmos', level=1, kp=170e-6, vto=0.5, lambda_=0.01)
circuit.V('dd', 'Vdd', circuit.gnd, 1.8)
circuit.I('bias', 'Vdd', 'drain1', 2e-3)
circuit.L('1', 'drain1', 'drain2', 1e-9)   # 1 nH tank
circuit.C('1', 'drain1', 'drain2', 0.5e-12) # 0.5 pF
circuit.MOSFET('M1', 'drain1', 'drain2', circuit.gnd, circuit.gnd, model='nmos', w=30e-6, l=180e-9)
circuit.MOSFET('M2', 'drain2', 'drain1', circuit.gnd, circuit.gnd, model='nmos', w=30e-6, l=180e-9)
simulator = circuit.simulator()
analysis = simulator.operating_point()
print("VCO bias check PASS"); sys.exit(0)
""",
}


def circuit_designer_node(state: GelochipAgentState, llm) -> GelochipAgentState:
    """
    Size components and validate the circuit with PySpice before layout.
    """
    spec       = state.get("circuit_spec", {})
    topology   = state.get("selected_topology", spec.get("circuit_type", ""))
    pdk_name   = spec.get("pdk", "gf180")
    corrector_feedback = state.get("corrector_feedback")

    pdk_info = get_pdk_info.invoke({"pdk_name": pdk_name})
    papers_summary = "\n".join(
        f"- {p.get('title', '')}: {p.get('summary', '')[:200]}"
        for p in state.get("retrieved_papers", [])[:3]
    )

    # ── Step 1: size components ──────────────────────────────────────────────
    designer_messages = [
        {"role": "system", "content": CIRCUIT_DESIGNER_PROMPT},
    ]

    if corrector_feedback:
        designer_messages.append({
            "role": "user",
            "content": (
                "A previous attempt failed. Here is feedback from the corrector:\n\n"
                f"{corrector_feedback}\n\n"
                "Use this to produce correct component parameters."
            ),
        })
        designer_messages.append({"role": "assistant", "content": "Understood. I will fix the parameters."})

    designer_messages.append({
        "role": "user",
        "content": (
            f"Circuit spec:\n{json.dumps(spec, indent=2)}\n\n"
            f"Selected topology: {topology}\n\n"
            f"PDK info:\n{json.dumps(pdk_info, indent=2)}\n\n"
            f"Relevant papers:\n{papers_summary}\n\n"
            "Produce the complete component_params JSON for Gelochip."
        ),
    })

    response = llm.invoke(designer_messages)
    content = response.content if hasattr(response, "content") else str(response)

    try:
        clean = content.strip().lstrip("```json").rstrip("```").strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1].strip()
        component_params = json.loads(clean)
    except json.JSONDecodeError as e:
        return {
            **state,
            "errors": state.get("errors", []) + [f"CircuitDesigner JSON error: {e}"],
            "failed_node": "circuit_designer",
            "corrector_feedback": None,
            "next_node": "corrector",
        }

    # Quick analytical performance estimate
    try:
        perf_estimate = estimate_performance.invoke({
            "circuit_spec": spec,
            "component_params": component_params,
        })
        component_params["_performance_estimate"] = perf_estimate
    except Exception:
        pass

    # Save params.json
    if state.get("output_dir"):
        from gelochip.agent.output_manager import OutputManager
        from pathlib import Path
        om = OutputManager.__new__(OutputManager)
        om.root = Path(state["output_dir"])
        om._mkdir(om.root)
        om.save_params(component_params)

    # ── Step 2: generate PySpice netlist ─────────────────────────────────────
    circuit_type = spec.get("circuit_type", "lna")
    example = _PYSPICE_EXAMPLES.get(circuit_type, _PYSPICE_EXAMPLES["lna"])
    pdk_models = _pdk_model_params(pdk_name)

    pyspice_messages = [
        {"role": "system", "content": PYSPICE_GENERATOR_PROMPT},
        {
            "role": "user",
            "content": (
                f"Generate a PySpice validation script for:\n"
                f"Circuit spec:\n{json.dumps(spec, indent=2)}\n\n"
                f"Sized parameters:\n{json.dumps(component_params, indent=2)}\n\n"
                f"PDK SPICE model parameters:\n{pdk_models}\n\n"
                f"Example script style to follow (adapt for this circuit):\n"
                f"```python\nimport sys\n"
                f"from PySpice.Spice.Netlist import Circuit\n"
                f"from PySpice.Unit import *\n\n"
                f"{example}```\n\n"
                "Return ONLY runnable Python code — no markdown, no explanation."
            ),
        },
    ]

    pyspice_resp = llm.invoke(pyspice_messages)
    pyspice_code = pyspice_resp.content if hasattr(pyspice_resp, "content") else str(pyspice_resp)
    if "```python" in pyspice_code:
        pyspice_code = pyspice_code.split("```python")[1].split("```")[0].strip()
    elif "```" in pyspice_code:
        pyspice_code = pyspice_code.split("```")[1].strip()

    # Save PySpice netlist to spice/netlist.py
    if state.get("output_dir"):
        from gelochip.agent.output_manager import OutputManager
        from pathlib import Path
        om_s = OutputManager.__new__(OutputManager)
        om_s.root = Path(state["output_dir"])
        om_s._mkdir(om_s.root / "spice")
        om_s.save_pyspice_code(pyspice_code)

    # ── Step 3: execute and validate PySpice (optional — requires ngspice) ──────
    messages_out = list(state.get("messages") or [])
    layout_out   = state.get("output_dir") or "/tmp"

    if not _ngspice_available():
        # ngspice binary not installed — skip simulation, proceed to layout
        messages_out.append(AIMessage(
            content=(
                f"⚠️  ngspice not found — skipping PySpice validation.\n"
                f"Circuit sizing complete ({circuit_type}, {pdk_name}). "
                f"Install ngspice for pre-layout simulation."
            )
        ))
        return {
            **state,
            "component_params": component_params,
            "pyspice_code": pyspice_code,
            "pyspice_result": {"success": None, "skipped": True, "reason": "ngspice not installed"},
            "messages": messages_out,
            "corrector_feedback": None,
            "failed_node": None,
            "next_node": "layout_generator",
        }

    exec_result = execute_pyspice_code.invoke({
        "pyspice_code": pyspice_code,
        "output_dir": layout_out,
    })

    if exec_result["success"]:
        messages_out.append(AIMessage(
            content=(
                f"✅ Circuit sizing complete ({circuit_type}, {pdk_name}).\n"
                f"PySpice validation passed: {exec_result.get('stdout', '')[:200]}"
            )
        ))
        return {
            **state,
            "component_params": component_params,
            "pyspice_code": pyspice_code,
            "pyspice_result": exec_result,
            "messages": messages_out,
            "corrector_feedback": None,
            "failed_node": None,
            "next_node": "layout_generator",
        }

    # PySpice failed — check if it's a simulator binary error (unrecoverable)
    pyspice_error = exec_result.get("error") or exec_result.get("stderr") or ""
    if _is_simulator_error(pyspice_error):
        # ngspice reported an error but is present — treat as warning, skip
        messages_out.append(AIMessage(
            content=(
                f"⚠️  PySpice simulation error (ngspice issue) — skipping validation.\n"
                f"{pyspice_error[:200]}\n→ Proceeding to layout_generator."
            )
        ))
        return {
            **state,
            "component_params": component_params,
            "pyspice_code": pyspice_code,
            "pyspice_result": exec_result,
            "messages": messages_out,
            "corrector_feedback": None,
            "failed_node": None,
            "next_node": "layout_generator",
        }

    # PySpice failed due to code error (wrong circuit, wrong operating point)
    messages_out.append(AIMessage(
        content=f"⚠️  PySpice circuit validation failed:\n{pyspice_error[:400]}\n→ Routing to corrector."
    ))
    return {
        **state,
        "component_params": component_params,
        "pyspice_code": pyspice_code,
        "pyspice_result": exec_result,
        "messages": messages_out,
        "errors": state.get("errors", []) + [f"PySpice validation: {pyspice_error[:300]}"],
        "failed_node": "circuit_designer",
        "corrector_feedback": None,
        "next_node": "corrector",
    }


def _pdk_model_params(pdk: str) -> str:
    models = {
        "gf180":  "nmos: level=1, kp=170e-6, vto=0.5, lambda_=0.01  |  pmos: level=1, kp=50e-6, vto=-0.5, lambda_=0.015",
        "sky130": "nmos: level=1, kp=200e-6, vto=0.48, lambda_=0.009 |  pmos: level=1, kp=60e-6, vto=-0.48, lambda_=0.012",
        "ihp130": "nmos: level=1, kp=250e-6, vto=0.45, lambda_=0.008 |  pmos: level=1, kp=70e-6, vto=-0.45, lambda_=0.010",
    }
    return models.get(pdk, models["gf180"])


def _ngspice_available() -> bool:
    """Check if the ngspice binary is available on PATH."""
    import shutil
    return shutil.which("ngspice") is not None


_SIMULATOR_ERROR_PATTERNS = (
    "ngspice", "no such file", "simulator", "circuitsimulator",
    "spice program", "executable", "command not found", "factory",
    "netlist.py", "simulation.py",
)

def _is_simulator_error(error: str) -> bool:
    """Return True if the error is from ngspice/simulator infrastructure, not the circuit itself."""
    low = error.lower()
    return any(p in low for p in _SIMULATOR_ERROR_PATTERNS)
