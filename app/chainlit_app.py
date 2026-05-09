"""
Gelochip Chainlit Web Interface.

Chainlit provides a production-grade React-based chat UI specifically designed
for AI/LLM applications — no Streamlit, full web application.

Run with:
    chainlit run app/chainlit_app.py --port 8080

Features:
  - Interactive chat with the Gelochip AI agent
  - Real-time streaming of agent steps
  - Display of GDS layout previews
  - SPICE performance estimate tables
  - Downloadable GDS files
"""
from __future__ import annotations
import os
import json
import base64
import tempfile
import asyncio
from pathlib import Path
from functools import partial

import chainlit as cl
from dotenv import load_dotenv

load_dotenv()

# ── LLM Setup ─────────────────────────────────────────────────────────────────

def _get_llm():
    if os.getenv("ANTHROPIC_API_KEY"):
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model="claude-sonnet-4-6", temperature=0.1, max_tokens=8192)
    elif os.getenv("GOOGLE_API_KEY"):
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model="gemini-2.5-pro", temperature=0.1)
    elif os.getenv("OPENAI_API_KEY"):
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model="gpt-4o", temperature=0.1)
    else:
        raise EnvironmentError(
            "Set ANTHROPIC_API_KEY, GOOGLE_API_KEY, or OPENAI_API_KEY in .env"
        )


# ── Chainlit Lifecycle ─────────────────────────────────────────────────────────

@cl.on_chat_start
async def on_chat_start():
    """Initialize the agent when a new chat session begins."""
    from gelochip.agent.graph import build_graph, create_initial_state

    try:
        llm = _get_llm()
        graph = build_graph(llm=llm)
        cl.user_session.set("graph", graph)
        cl.user_session.set("llm", llm)

        await cl.Message(
            content=(
                "## Gelochip – AI Analog/RF IC Layout Agent\n\n"
                "I can design and generate GDS layouts for:\n"
                "- **LNA** (Low Noise Amplifier) – cascode, inductively degenerated\n"
                "- **Op-Amp** – two-stage Miller, folded-cascode OTA\n"
                "- **Mixer** – Gilbert cell, passive CMOS\n"
                "- **VCO** – LC tank, ring oscillator\n"
                "- **Building blocks** – current mirrors, diff pairs, amplifier stages\n\n"
                "**Supported PDKs:** gf180 (default) | sky130 | ihp130\n\n"
                "Try: `Design a 5GHz cascode LNA in gf180 with NF < 2dB and gain > 15dB`"
            )
        ).send()
    except EnvironmentError as e:
        await cl.Message(content=f"⚠️ **Configuration error:** {e}\n\nSet your API key in `.env`.").send()


@cl.on_message
async def on_message(message: cl.Message):
    """Handle incoming user messages — run the full Gelochip agent pipeline."""
    graph = cl.user_session.get("graph")
    if graph is None:
        await cl.Message(content="Session expired. Please refresh the page.").send()
        return

    user_text = message.content.strip()

    # ── Step indicators ────────────────────────────────────────────────────────
    steps = {}

    async def send_step(name: str, content: str):
        """Stream a named step to the UI."""
        if name not in steps:
            steps[name] = cl.Step(name=name, type="tool")
        async with steps[name] as step:
            step.output = content

    # ── Build initial state ────────────────────────────────────────────────────
    from gelochip.agent.graph import create_initial_state
    state = create_initial_state(user_request=user_text, max_corrections=3)

    # ── Show thinking spinner ──────────────────────────────────────────────────
    thinking_msg = cl.Message(content="")
    await thinking_msg.send()

    try:
        # Run the agent (blocking, in executor to avoid blocking event loop)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, graph.invoke, state)

        # ── Display step results ───────────────────────────────────────────────
        if result.get("circuit_spec"):
            spec = result["circuit_spec"]
            await cl.Message(
                content=(
                    f"**Parsed Spec**\n"
                    f"```json\n{json.dumps(spec, indent=2)}\n```"
                ),
                author="SpecParser",
            ).send()

        if result.get("component_params"):
            params = result["component_params"]
            perf = params.pop("_performance_estimate", None)
            await cl.Message(
                content=(
                    f"**Component Parameters**\n"
                    f"```json\n{json.dumps(params, indent=2)}\n```"
                ),
                author="CircuitDesigner",
            ).send()
            if perf:
                rows = "\n".join(f"| {k} | {v} |" for k, v in perf.items())
                await cl.Message(
                    content=(
                        f"**Analytical Performance Estimate**\n\n"
                        f"| Metric | Value |\n|--------|-------|\n{rows}"
                    ),
                    author="Estimator",
                ).send()

        # ── Show generated code ────────────────────────────────────────────────
        layout = result.get("layout_result", {})
        if layout.get("python_code"):
            await cl.Message(
                content=f"**Generated GLayout Code**\n```python\n{layout['python_code'][:3000]}\n```",
                author="LayoutGenerator",
            ).send()

        # ── Attach GDS file if available ──────────────────────────────────────
        elements = []
        if layout.get("gds_path") and Path(layout["gds_path"]).exists():
            elements.append(
                cl.File(
                    name="layout.gds",
                    path=layout["gds_path"],
                    display="inline",
                )
            )

        # ── Final answer ───────────────────────────────────────────────────────
        final = result.get("final_answer", "Agent completed but produced no summary.")
        if result.get("errors"):
            final += f"\n\n⚠️ **Errors encountered:**\n" + "\n".join(
                f"- {e}" for e in result["errors"]
            )

        await cl.Message(content=final, elements=elements).send()

    except Exception as e:
        await cl.Message(content=f"❌ Agent error: {e}").send()
    finally:
        await thinking_msg.remove()


# ── Chainlit Settings Panel ────────────────────────────────────────────────────

@cl.on_settings_update
async def on_settings_update(settings: dict):
    """Update session settings when the user changes them in the UI."""
    cl.user_session.set("settings", settings)
    await cl.Message(content=f"Settings updated: {settings}").send()
