"""
Gelochip MCP Server.

Exposes Gelochip's IC layout agent as MCP (Model Context Protocol) tools
so that Claude Desktop, Claude Code, and other MCP clients can invoke it.

Usage — add to Claude Desktop config (~/.config/claude/claude_desktop_config.json):

    {
      "mcpServers": {
        "gelochip": {
          "command": "uv",
          "args": ["run", "python", "app/mcp_server.py"],
          "cwd": "/path/to/Gelochip"
        }
      }
    }

Then restart Claude Desktop and use the Gelochip tools from any conversation.

Requirements:
    pip install mcp  (or add to pyproject.toml)
    Set ANTHROPIC_API_KEY / OLLAMA_MODEL / GOOGLE_API_KEY / OPENAI_API_KEY in env.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

mcp = FastMCP(
    name="gelochip",
    instructions=(
        "Gelochip is an AI-assisted analog/RF IC layout tool. "
        "Use design_circuit to generate a full GDS layout from a natural-language description. "
        "Use list_building_blocks to see available primitives/cells, "
        "get_pdk_info for PDK details, and execute_layout_code to run Python layout code directly."
    ),
)

# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_llm():
    """Build the best available LLM from environment variables."""
    if os.getenv("OLLAMA_MODEL"):
        from langchain_ollama import ChatOllama
        return ChatOllama(
            model=os.getenv("OLLAMA_MODEL", "qwen3.5:9b"),
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
        return ChatGoogleGenerativeAI(model="gemini-2.5-pro", temperature=0.1)
    elif os.getenv("OPENAI_API_KEY"):
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model="gpt-4o", temperature=0.1)
    else:
        raise EnvironmentError(
            "No LLM configured. Set OLLAMA_MODEL, ANTHROPIC_API_KEY, "
            "GOOGLE_API_KEY, or OPENAI_API_KEY."
        )


# ── MCP Tools ──────────────────────────────────────────────────────────────────

@mcp.tool()
def design_circuit(description: str, pdk: str = "gf180") -> str:
    """
    Run the full Gelochip LangGraph agent pipeline to design and generate a GDS layout.

    The agent performs the following steps:
        1. SpecParser      — parses natural language into structured CircuitSpec
        2. Researcher      — searches ArXiv for relevant circuit topologies
        3. CircuitDesigner — sizes components using gm/ID methodology
        4. LayoutGenerator — generates and executes GLayout Python code → GDS
        5. Verifier        — DRC / LVS / SPICE simulation with auto-correction
        6. Summarizer      — assembles the final human-readable design report

    Args:
        description: Natural-language circuit design request.
                     Examples:
                       "5GHz cascode LNA in gf180 with NF < 2dB and gain > 15dB"
                       "Two-stage Miller opamp with 60dB gain and 10MHz GBW"
                       "Gilbert cell mixer at 2.4GHz in sky130"
        pdk:         Target PDK. One of "gf180" (default), "sky130", "ihp130".

    Returns:
        Final design report as a markdown string, including:
        - Chosen topology and component parameters
        - Analytical performance estimate
        - DRC/LVS result
        - SPICE simulation results (if ngspice available)
        - GDS file path
        - Next steps
    """
    from gelochip.agent.graph import build_graph, create_initial_state

    try:
        llm   = _get_llm()
        graph = build_graph(llm=llm)

        user_request = f"{description} (PDK: {pdk})"
        state = create_initial_state(user_request=user_request, max_corrections=3)

        # LangGraph invoke is sync; use asyncio if needed in an async context
        result = graph.invoke(state)

        final_answer = result.get("final_answer") or "Agent completed but produced no summary."
        errors = result.get("errors") or []

        output_parts = [final_answer]

        if errors:
            output_parts.append("\n\n## Errors Encountered\n" + "\n".join(f"- {e}" for e in errors))

        layout = result.get("layout_result") or {}
        if layout.get("gds_path"):
            output_parts.append(f"\n\n## Output Files\n- GDS: `{layout['gds_path']}`")

        return "\n".join(output_parts)

    except EnvironmentError as exc:
        return f"Configuration error: {exc}"
    except Exception as exc:
        return f"Agent error: {exc}"


@mcp.tool()
def list_building_blocks() -> str:
    """
    List all available Gelochip building blocks organized by category.

    Categories:
        - primitives: NMOS/PMOS transistors, resistors, capacitors, inductors, vias, guard rings
        - blocks:     Current mirrors, diff pairs, cascode stages, bias circuits
        - cells:      Complete circuits (LNA, op-amp, mixer, VCO)

    Returns:
        JSON string with all available building block function signatures.
    """
    from gelochip.agent.tools.circuit_tools import list_available_blocks

    result = list_available_blocks.invoke({})
    return json.dumps(result, indent=2)


@mcp.tool()
def get_pdk_info(pdk: str) -> str:
    """
    Get design rules, device models, and key parameters for a supported PDK.

    Supported PDKs:
        - gf180   — GlobalFoundries GF180MCU 180nm (default, open-source)
        - sky130  — SkyWater SKY130 130nm (open-source, free DRC/LVS)
        - ihp130  — IHP SG13G2 130nm BiCMOS (300GHz HBT, mmWave)

    Args:
        pdk: PDK name. One of "gf180", "sky130", "ihp130".

    Returns:
        JSON string with:
        - full_name, lmin_um, vdd_v
        - nfet_model, pfet_model
        - metal layer stack
        - fT / fmax (GHz)
        - usage notes and import path
    """
    from gelochip.agent.tools.circuit_tools import get_pdk_info as _get_pdk_info

    result = _get_pdk_info.invoke({"pdk_name": pdk})
    return json.dumps(result, indent=2)


@mcp.tool()
def execute_layout_code(python_code: str) -> str:
    """
    Execute GLayout Python code and return the result.

    The code is run in a sandboxed subprocess. GDS output files are
    written to /tmp/gelochip_output/.

    Use this tool to:
        - Test individual building-block calls
        - Iterate on layout code without re-running the full agent
        - Debug GDS generation issues

    Args:
        python_code: Complete Python code string. It should import and call
                     Gelochip building blocks and save the GDS, e.g.::

                         from gelochip.glayout.pdk.gf180_mapped import gf180_mapped_pdk
                         from gelochip.core.blocks.amplifier import common_source
                         comp = common_source(gf180_mapped_pdk, width=4.0, fingers=4)
                         comp.write_gds("/tmp/gelochip_output/cs_amp.gds")

    Returns:
        JSON string with:
        - success (bool)
        - stdout, stderr (truncated)
        - gds_files (list of generated GDS file paths)
        - error (str or null)
    """
    from gelochip.agent.tools.circuit_tools import execute_layout_code as _exec

    result = _exec.invoke({
        "python_code": python_code,
        "output_dir":  "/tmp/gelochip_output",
    })
    return json.dumps(result, indent=2, default=str)


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run(transport="stdio")
