"""
Circuit Designer Node – sizes components using gm/ID methodology and topology knowledge.
"""
from __future__ import annotations
import json

from langchain_core.messages import AIMessage

from gelochip.agent.state import GelochipAgentState
from gelochip.agent.prompts import CIRCUIT_DESIGNER_PROMPT
from gelochip.agent.tools.circuit_tools import estimate_performance, get_pdk_info


def circuit_designer_node(state: GelochipAgentState, llm) -> GelochipAgentState:
    """
    Size the circuit components given the spec and selected topology.

    Uses the LLM + gm/ID heuristics to produce component_params that
    can be passed directly to Gelochip building-block functions.
    """
    spec     = state.get("circuit_spec", {})
    topology = state.get("selected_topology", spec.get("circuit_type", ""))
    pdk_name = spec.get("pdk", "gf180")

    pdk_info = get_pdk_info.invoke({"pdk_name": pdk_name})
    papers_summary = "\n".join(
        f"- {p.get('title', '')}: {p.get('summary', '')[:200]}"
        for p in state.get("retrieved_papers", [])[:3]
    )

    messages = [
        {"role": "system", "content": CIRCUIT_DESIGNER_PROMPT},
        {
            "role": "user",
            "content": (
                f"Circuit spec:\n{json.dumps(spec, indent=2)}\n\n"
                f"Selected topology: {topology}\n\n"
                f"PDK info:\n{json.dumps(pdk_info, indent=2)}\n\n"
                f"Relevant papers:\n{papers_summary}\n\n"
                "Produce the complete component_params JSON for Gelochip."
            ),
        },
    ]
    response = llm.invoke(messages)
    content = response.content if hasattr(response, "content") else str(response)

    try:
        clean = content.strip().lstrip("```json").rstrip("```").strip()
        component_params = json.loads(clean)
    except json.JSONDecodeError as e:
        return {
            **state,
            "errors": state.get("errors", []) + [f"CircuitDesigner JSON error: {e}"],
            "next_node": "summarizer",
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

    # Save params.json (strips _performance_estimate)
    if state.get("output_dir"):
        from gelochip.agent.output_manager import OutputManager
        from pathlib import Path
        om = OutputManager.__new__(OutputManager)
        om.root = Path(state["output_dir"])
        om._mkdir(om.root)
        om.save_params(component_params)

    return {
        **state,
        "component_params": component_params,
        "messages": state["messages"] + [
            AIMessage(content=f"Component sizing complete:\n{json.dumps(component_params, indent=2)}"),
        ],
        "next_node": "layout_generator",
    }
