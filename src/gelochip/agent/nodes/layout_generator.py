"""
Layout Generator Node – generates and executes GLayout Python code.
"""
from __future__ import annotations
import json

from langchain_core.messages import AIMessage

from gelochip.agent.state import GelochipAgentState
from gelochip.agent.prompts import LAYOUT_GENERATOR_PROMPT
from gelochip.agent.tools.circuit_tools import execute_layout_code, list_available_blocks


def layout_generator_node(state: GelochipAgentState, llm) -> GelochipAgentState:
    """
    Generate Python code that calls Gelochip building blocks, then execute it.

    If execution fails, routes to the verifier node for correction.
    """
    from pathlib import Path

    spec              = state.get("circuit_spec", {})
    params            = state.get("component_params", {})
    blocks            = list_available_blocks.invoke({})
    corrector_feedback = state.get("corrector_feedback")

    # Resolve output directory BEFORE building the prompt so the correct path
    # is injected into the LLM instruction (not a hardcoded /tmp path).
    output_dir = state.get("output_dir")
    if output_dir:
        layout_out = str(Path(output_dir) / "layout")
        Path(layout_out).mkdir(parents=True, exist_ok=True)
    else:
        # Fallback: project outputs/ next to this package
        _pkg = Path(__file__).resolve()
        for _p in _pkg.parents:
            if (_p / "pyproject.toml").exists():
                layout_out = str(_p / "outputs" / "layout")
                break
        else:
            layout_out = str(Path.cwd() / "outputs" / "layout")
        Path(layout_out).mkdir(parents=True, exist_ok=True)

    pyspice_code = state.get("pyspice_code") or ""
    pyspice_ref = (
        f"\nReference PySpice netlist (circuit topology validated, use same sizing):\n"
        f"```python\n{pyspice_code[:1200]}\n```\n"
        if pyspice_code else ""
    )

    user_content = (
        f"Circuit spec:\n{json.dumps(spec, indent=2)}\n\n"
        f"Component params:\n{json.dumps(params, indent=2)}\n\n"
        f"{pyspice_ref}"
        f"Available Gelochip functions:\n{json.dumps(blocks, indent=2)}\n\n"
        "Write complete runnable Python code to generate the GDS layout. "
        f"Save the GDS to '{layout_out}/output.gds'. "
        "Return ONLY Python code, no markdown."
    )

    messages = [{"role": "system", "content": LAYOUT_GENERATOR_PROMPT}]

    # If the corrector sent back structured feedback, inject it before the
    # main user request so the LLM knows what went wrong in the last attempt.
    if corrector_feedback:
        messages.append({
            "role": "user",
            "content": (
                "A previous layout attempt failed. Here is the corrector's analysis:\n\n"
                f"{corrector_feedback}\n\n"
                "Use this to avoid the same mistakes in your new code."
            ),
        })
        messages.append({"role": "assistant", "content": "Understood. I will avoid those mistakes."})

    messages.append({"role": "user", "content": user_content})
    response = llm.invoke(messages)
    python_code = response.content if hasattr(response, "content") else str(response)

    # Strip accidental markdown fences
    if "```python" in python_code:
        python_code = python_code.split("```python")[1].split("```")[0].strip()
    elif "```" in python_code:
        python_code = python_code.split("```")[1].strip()

    # Execute the generated code
    exec_result = execute_layout_code.invoke({
        "python_code": python_code,
        "output_dir": layout_out,
    })

    gds_file = (exec_result.get("gds_files") or [None])[0]

    # Save layout code
    if output_dir:
        from gelochip.agent.output_manager import OutputManager
        from pathlib import Path
        om = OutputManager.__new__(OutputManager)
        om.root = Path(output_dir)
        om._mkdir(om.root / "layout")
        om.save_layout_code(python_code)

    layout_result = {
        "python_code": python_code,
        "gds_path": gds_file,
        "error": exec_result.get("error"),
    }

    next_node = "corrector" if not exec_result["success"] else "summarizer"

    return {
        **state,
        "layout_result": layout_result,
        "failed_node": "layout_generator" if not exec_result["success"] else None,
        "messages": state["messages"] + [
            AIMessage(content=(
                f"Layout generation {'succeeded' if exec_result['success'] else 'failed'}. "
                f"GDS: {layout_result.get('gds_path', 'N/A')}"
            )),
        ],
        "next_node": next_node,
    }
