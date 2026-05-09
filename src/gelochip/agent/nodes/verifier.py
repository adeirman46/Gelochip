"""
Verifier Node – debugs failed layout code and routes to retry or give up.
"""
from __future__ import annotations
import json

from langchain_core.messages import AIMessage

from gelochip.agent.state import GelochipAgentState
from gelochip.agent.prompts import VERIFIER_PROMPT
from gelochip.agent.tools.circuit_tools import execute_layout_code


def verifier_node(state: GelochipAgentState, llm) -> GelochipAgentState:
    """
    Attempt to fix layout code that failed compilation or DRC/LVS.

    Loops up to state["max_corrections"] times before routing to summarizer.
    """
    layout_result = state.get("layout_result", {})
    correction_count = state.get("correction_count", 0)
    max_corrections = state.get("max_corrections", 3)

    if correction_count >= max_corrections:
        return {
            **state,
            "errors": state.get("errors", []) + ["Max correction attempts reached."],
            "next_node": "summarizer",
        }

    broken_code = layout_result.get("python_code", "")
    error_msg   = layout_result.get("error", "Unknown error")

    messages = [
        {"role": "system", "content": VERIFIER_PROMPT},
        {
            "role": "user",
            "content": (
                f"Broken code:\n```python\n{broken_code}\n```\n\n"
                f"Error:\n{error_msg}\n\n"
                "Fix the code and return ONLY the corrected Python (no markdown)."
            ),
        },
    ]
    response = llm.invoke(messages)
    fixed_code = response.content if hasattr(response, "content") else str(response)

    if "```python" in fixed_code:
        fixed_code = fixed_code.split("```python")[1].split("```")[0].strip()
    elif "```" in fixed_code:
        fixed_code = fixed_code.split("```")[1].strip()

    exec_result = execute_layout_code.invoke({
        "python_code": fixed_code,
        "output_dir": "/tmp/gelochip_output",
    })

    new_layout = {
        "python_code": fixed_code,
        "gds_path": exec_result.get("gds_files", [None])[0],
        "error": exec_result.get("error"),
    }

    next_node = "summarizer" if exec_result["success"] else "verifier"

    return {
        **state,
        "layout_result": new_layout,
        "correction_count": correction_count + 1,
        "messages": state["messages"] + [
            AIMessage(content=(
                f"Correction #{correction_count + 1}: "
                f"{'fixed successfully' if exec_result['success'] else 'still failing'}."
            )),
        ],
        "next_node": next_node,
    }
