"""
Summarizer Node – assembles the final human-readable response.
"""
from __future__ import annotations
import json

from langchain_core.messages import AIMessage

from gelochip.agent.state import GelochipAgentState
from gelochip.agent.prompts import SUMMARIZER_PROMPT


def summarizer_node(state: GelochipAgentState, llm) -> GelochipAgentState:
    """Compose the final answer from the full agent state."""
    messages = [
        {"role": "system", "content": SUMMARIZER_PROMPT},
        {
            "role": "user",
            "content": (
                f"User request: {state.get('user_request', '')}\n\n"
                f"Circuit spec: {json.dumps(state.get('circuit_spec', {}), indent=2)}\n\n"
                f"Component params: {json.dumps(state.get('component_params', {}), indent=2)}\n\n"
                f"Layout result: {json.dumps(state.get('layout_result', {}), indent=2)}\n\n"
                f"Simulation result: {json.dumps(state.get('sim_result', {}), indent=2)}\n\n"
                f"Errors: {state.get('errors', [])}\n\n"
                "Write the final summary. Include: circuit type, topology, PDK, "
                "component parameters table, DRC/LVS status, "
                "simulated vs target performance, GDS path, and next steps."
            ),
        },
    ]
    response = llm.invoke(messages)
    final_answer = response.content if hasattr(response, "content") else str(response)

    return {
        **state,
        "final_answer": final_answer,
        "messages": state["messages"] + [AIMessage(content=final_answer)],
        "next_node": None,
    }
