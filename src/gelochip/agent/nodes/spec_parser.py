"""
Spec Parser Node – extracts structured CircuitSpec from natural language.
"""
from __future__ import annotations
import json

from langchain_core.messages import AIMessage, HumanMessage

from gelochip.agent.state import GelochipAgentState
from gelochip.agent.prompts import SPEC_PARSER_PROMPT


def spec_parser_node(state: GelochipAgentState, llm) -> GelochipAgentState:
    """
    Parse the user's natural-language request into a structured CircuitSpec.

    Calls the LLM with SPEC_PARSER_PROMPT and returns a JSON spec.
    If parsing fails, the error is appended to state["errors"].
    """
    messages = [
        {"role": "system", "content": SPEC_PARSER_PROMPT},
        {"role": "user",   "content": state["user_request"]},
    ]
    response = llm.invoke(messages)
    content = response.content if hasattr(response, "content") else str(response)

    try:
        clean = content.strip().lstrip("```json").rstrip("```").strip()
        spec = json.loads(clean)
    except json.JSONDecodeError as e:
        return {
            **state,
            "errors": state.get("errors", []) + [f"SpecParser JSON error: {e}\nRaw: {content[:200]}"],
            "next_node": "summarizer",
        }

    return {
        **state,
        "circuit_spec": spec,
        "messages": state["messages"] + [
            HumanMessage(content=state["user_request"]),
            AIMessage(content=f"Parsed spec: {json.dumps(spec, indent=2)}"),
        ],
        "next_node": "researcher",
    }
