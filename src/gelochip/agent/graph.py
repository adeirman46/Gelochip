"""
Gelochip LangGraph multi-agent pipeline.

Graph topology:

    START
      │
    spec_parser      – natural language → structured CircuitSpec
      │
    researcher       – ArXiv + web search → topology recommendations
      │
    circuit_designer – gm/ID sizing + PySpice validation → component_params
      │ success                    │ JSON/PySpice error
      ▼                            ▼
    layout_generator           corrector ──→ circuit_designer (retry)
      │ success   │ failure         │ success (layout fixed)
      ▼           ▼                 ▼
    summarizer  corrector ──→   verifier (DRC/LVS/SPICE)
                    │                │
                    └──→ layout_generator (retry with feedback)
                    └──→ summarizer (budget exhausted)
                                     │
                                  summarizer
                                     │
                                    END

Usage::

    from gelochip.agent.graph import build_graph
    graph = build_graph()

    result = graph.invoke({
        "user_request": "Design a 5GHz LNA in sky130 with NF < 2dB and gain > 15dB",
        "messages": [],
        "circuit_spec": None,
        "retrieved_papers": [],
        "selected_topology": None,
        "component_params": {},
        "pyspice_code": None,
        "pyspice_result": None,
        "layout_result": None,
        "sim_result": None,
        "correction_count": 0,
        "max_corrections": 3,
        "final_answer": None,
        "next_node": None,
        "errors": [],
        "failed_node": None,
    })
    print(result["final_answer"])
"""
from __future__ import annotations
import os
from functools import partial
from typing import Literal

from langgraph.graph import StateGraph, START, END

from gelochip.agent.state import GelochipAgentState
from gelochip.agent.nodes import (
    spec_parser_node,
    researcher_node,
    circuit_designer_node,
    layout_generator_node,
    corrector_node,
    verifier_node,
    summarizer_node,
)


def _route_after_spec_parser(state: GelochipAgentState) -> Literal["researcher", "summarizer"]:
    return state.get("next_node", "researcher")


def _route_after_circuit_designer(
    state: GelochipAgentState,
) -> Literal["layout_generator", "corrector"]:
    return state.get("next_node", "layout_generator")


def _route_after_layout(
    state: GelochipAgentState,
) -> Literal["corrector", "summarizer"]:
    return state.get("next_node", "summarizer")


def _route_after_corrector(
    state: GelochipAgentState,
) -> Literal["verifier", "layout_generator", "circuit_designer", "summarizer"]:
    return state.get("next_node", "summarizer")


def _route_after_verifier(state: GelochipAgentState) -> Literal["verifier", "summarizer"]:
    return state.get("next_node", "summarizer")


def build_graph(llm=None, checkpointer=None, interrupt_after: list[str] | None = None) -> StateGraph:
    """
    Build and compile the Gelochip LangGraph agent.

    Args:
        llm: LangChain chat model instance. If None, builds from env vars:
             - ANTHROPIC_API_KEY  → Claude claude-sonnet-4-6 (recommended)
             - GOOGLE_API_KEY     → Gemini 2.5 Pro
             - OPENAI_API_KEY     → GPT-4o

    Returns:
        Compiled LangGraph StateGraph.
    """
    if llm is None:
        llm = _auto_llm()

    _spec_parser      = partial(spec_parser_node,      llm=llm)
    _researcher       = partial(researcher_node,       llm=llm)
    _circuit_designer = partial(circuit_designer_node, llm=llm)
    _layout_generator = partial(layout_generator_node, llm=llm)
    _corrector        = partial(corrector_node,        llm=llm)
    _verifier         = partial(verifier_node,         llm=llm)
    _summarizer       = partial(summarizer_node,       llm=llm)

    graph = StateGraph(GelochipAgentState)

    graph.add_node("spec_parser",      _spec_parser)
    graph.add_node("researcher",       _researcher)
    graph.add_node("circuit_designer", _circuit_designer)
    graph.add_node("layout_generator", _layout_generator)
    graph.add_node("corrector",        _corrector)
    graph.add_node("verifier",         _verifier)
    graph.add_node("summarizer",       _summarizer)

    graph.add_edge(START, "spec_parser")

    graph.add_conditional_edges(
        "spec_parser",
        _route_after_spec_parser,
        {"researcher": "researcher", "summarizer": "summarizer"},
    )
    graph.add_edge("researcher", "circuit_designer")

    # circuit_designer → layout_generator (success) or corrector (JSON/PySpice error)
    graph.add_conditional_edges(
        "circuit_designer",
        _route_after_circuit_designer,
        {"layout_generator": "layout_generator", "corrector": "corrector"},
    )

    # layout_generator → corrector (failure) or summarizer (success)
    graph.add_conditional_edges(
        "layout_generator",
        _route_after_layout,
        {"corrector": "corrector", "summarizer": "summarizer"},
    )

    # corrector → verifier (layout fixed), layout_generator (layout retry),
    #             circuit_designer (params retry), summarizer (budget exhausted)
    graph.add_conditional_edges(
        "corrector",
        _route_after_corrector,
        {
            "verifier":         "verifier",
            "layout_generator": "layout_generator",
            "circuit_designer": "circuit_designer",
            "summarizer":       "summarizer",
        },
    )

    graph.add_conditional_edges(
        "verifier",
        _route_after_verifier,
        {"verifier": "verifier", "summarizer": "summarizer"},
    )
    graph.add_edge("summarizer", END)

    compile_kwargs: dict = {}
    if checkpointer is not None:
        compile_kwargs["checkpointer"] = checkpointer
    if interrupt_after:
        compile_kwargs["interrupt_after"] = interrupt_after
    return graph.compile(**compile_kwargs)


def _auto_llm():
    """
    Pick LLM based on environment variables.

    Priority:
        1. OLLAMA_MODEL      → local Ollama (free, no API key, needs GPU/CPU)
        2. ANTHROPIC_API_KEY → Claude claude-sonnet-4-6 (best code quality)
        3. GOOGLE_API_KEY    → Gemini 2.5 Pro
        4. OPENAI_API_KEY    → GPT-4o

    Local setup (8 GB VRAM, e.g. RTX 4060):
        ollama pull qwen3:8b
        echo 'OLLAMA_MODEL=qwen3:8b' >> .env
    """
    if os.getenv("OLLAMA_MODEL"):
        from langchain_ollama import ChatOllama
        return ChatOllama(
            model=os.getenv("OLLAMA_MODEL", "qwen3:8b"),
            base_url=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
            temperature=0.1,
            num_ctx=8192,
        )
    elif os.getenv("ANTHROPIC_API_KEY"):
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model="claude-sonnet-4-6",
            temperature=0.1,
            max_tokens=8192,
        )
    elif os.getenv("GOOGLE_API_KEY"):
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model="gemini-2.5-pro",
            temperature=0.1,
        )
    elif os.getenv("OPENAI_API_KEY"):
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model="gpt-4o", temperature=0.1)
    else:
        raise EnvironmentError(
            "No LLM configured. Options:\n"
            "  Local (free): set OLLAMA_MODEL=qwen3:8b in .env (requires Ollama)\n"
            "  Cloud:        set ANTHROPIC_API_KEY, GOOGLE_API_KEY, or OPENAI_API_KEY"
        )


def create_initial_state(
    user_request: str,
    max_corrections: int = 3,
    output_dir: str | None = None,
) -> GelochipAgentState:
    """Helper to create a properly initialized agent state."""
    return {
        "user_request": user_request,
        "messages": [],
        "circuit_spec": None,
        "retrieved_papers": [],
        "selected_topology": None,
        "component_params": {},
        "pyspice_code": None,
        "pyspice_result": None,
        "layout_result": None,
        "sim_result": None,
        "correction_count": 0,
        "max_corrections": max_corrections,
        "final_answer": None,
        "next_node": None,
        "errors": [],
        "output_dir": output_dir,
        "corrector_feedback": None,
        "failed_node": None,
    }
