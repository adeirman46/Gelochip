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
    spec   = state.get("circuit_spec", {})
    params = state.get("component_params", {})
    blocks = list_available_blocks.invoke({})

    messages = [
        {"role": "system", "content": LAYOUT_GENERATOR_PROMPT},
        {
            "role": "user",
            "content": (
                f"Circuit spec:\n{json.dumps(spec, indent=2)}\n\n"
                f"Component params:\n{json.dumps(params, indent=2)}\n\n"
                f"Available Gelochip functions:\n{json.dumps(blocks, indent=2)}\n\n"
                "Write complete runnable Python code to generate the GDS layout. "
                "Save the GDS to '/tmp/gelochip_output/output.gds'. "
                "Return ONLY Python code, no markdown."
            ),
        },
    ]
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
        "output_dir": "/tmp/gelochip_output",
    })

    layout_result = {
        "python_code": python_code,
        "gds_path": exec_result.get("gds_files", [None])[0],
        "error": exec_result.get("error"),
    }

    next_node = "verifier" if not exec_result["success"] else "summarizer"

    return {
        **state,
        "layout_result": layout_result,
        "messages": state["messages"] + [
            AIMessage(content=(
                f"Layout generation {'succeeded' if exec_result['success'] else 'failed'}. "
                f"GDS: {layout_result.get('gds_path', 'N/A')}"
            )),
        ],
        "next_node": next_node,
    }
