"""
LangGraph agent state definition for Gelochip.

The state flows through all agent nodes in the graph.
"""
from __future__ import annotations
from typing import Annotated, Optional, Any
from typing_extensions import TypedDict

from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage


class CircuitSpec(TypedDict, total=False):
    """Structured circuit specification extracted from natural language."""
    circuit_type: str          # e.g. "lna", "opamp", "mixer", "vco"
    topology: str              # e.g. "cascode", "folded_cascode", "gilbert_cell"
    pdk: str                   # e.g. "sky130", "gf180", "ihp130"
    freq_GHz: Optional[float]  # Target operating frequency
    gain_dB: Optional[float]   # Target voltage/power gain
    nf_dB: Optional[float]     # Target noise figure (RF)
    iip3_dBm: Optional[float]  # Target input-referred IP3
    s11_dB: Optional[float]    # Target input return loss
    vdd_V: Optional[float]     # Supply voltage
    ibias_uA: Optional[float]  # Bias current budget
    area_um2: Optional[float]  # Area budget
    extra_specs: dict[str, Any]


class LayoutResult(TypedDict, total=False):
    """Result of layout generation."""
    python_code: str           # Generated GLayout Python code
    gds_path: Optional[str]    # Path to generated GDS file
    drc_passed: Optional[bool] # DRC result
    lvs_passed: Optional[bool] # LVS result
    spice_netlist: Optional[str]
    error: Optional[str]


class SimResult(TypedDict, total=False):
    """SPICE simulation result."""
    gain_dB: Optional[float]
    nf_dB: Optional[float]
    bw_GHz: Optional[float]
    iip3_dBm: Optional[float]
    phase_margin_deg: Optional[float]
    power_mW: Optional[float]
    error: Optional[str]


class GelochipAgentState(TypedDict):
    """Full agent state passed between all LangGraph nodes."""

    # Conversation history (appended, never overwritten)
    messages: Annotated[list[BaseMessage], add_messages]

    # Raw natural-language request from the user
    user_request: str

    # Structured specification after parsing
    circuit_spec: Optional[CircuitSpec]

    # Retrieved papers / design knowledge
    retrieved_papers: list[dict[str, Any]]

    # Topology selected by circuit_designer node
    selected_topology: Optional[str]

    # Component parameters proposed by circuit_designer
    component_params: dict[str, Any]

    # Generated layout code and result
    layout_result: Optional[LayoutResult]

    # SPICE simulation result
    sim_result: Optional[SimResult]

    # How many correction loops have been tried
    correction_count: int

    # Maximum allowed corrections before giving up
    max_corrections: int

    # Final answer assembled by the summarizer node
    final_answer: Optional[str]

    # Which node should run next (for conditional routing)
    next_node: Optional[str]

    # Error accumulation
    errors: list[str]
