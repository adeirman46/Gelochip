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
from pathlib import Path

import chainlit as cl
from dotenv import load_dotenv

load_dotenv()

# ── LLM Setup ─────────────────────────────────────────────────────────────────

def _get_llm():
    # Local Ollama — set OLLAMA_MODEL in .env to use (no API key needed)
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
        return ChatAnthropic(model="claude-sonnet-4-6", temperature=0.1, max_tokens=8192)
    elif os.getenv("GOOGLE_API_KEY"):
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model="gemini-2.5-pro", temperature=0.1)
    elif os.getenv("OPENAI_API_KEY"):
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model="gpt-4o", temperature=0.1)
    else:
        raise EnvironmentError(
            "No LLM configured. Options:\n"
            "  Local (free): set OLLAMA_MODEL=qwen3.5:9b in .env\n"
            "  Cloud:        set ANTHROPIC_API_KEY, GOOGLE_API_KEY, or OPENAI_API_KEY"
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
    """
    Handle incoming user messages.

    Uses graph.astream_events(version="v2") so we get three levels of live updates:
      1. Node steps    — a collapsible Step opens when each agent node starts
      2. Tool calls    — nested Steps for arxiv_search, execute_layout_code, etc.
      3. Thinking      — Qwen3.5 / DeepSeek-R1 <think> blocks shown as sub-steps
    """
    graph = cl.user_session.get("graph")
    if graph is None:
        await cl.Message(content="Session expired. Please refresh the page.").send()
        return

    user_text = message.content.strip()

    from gelochip.agent.graph import create_initial_state
    state = create_initial_state(user_request=user_text, max_corrections=3)

    accumulated: dict = {}

    # Live-step trackers keyed by run_id or node name
    node_steps:  dict[str, cl.Step] = {}   # graph node name  → Step
    tool_steps:  dict[str, cl.Step] = {}   # event run_id     → Step
    think_steps: dict[str, cl.Step] = {}   # llm run_id       → Step
    think_bufs:  dict[str, str]     = {}   # llm run_id       → accumulated thinking text
    think_toks:  dict[str, int]     = {}   # llm run_id       → token counter (for batched updates)
    in_think:    set[str]           = set()
    current_node: str | None = None

    try:
        async for event in graph.astream_events(state, version="v2"):
            kind    = event["event"]
            name    = event.get("name", "")
            run_id  = event.get("run_id", "")

            # ── Graph node started ────────────────────────────────────────────
            if kind == "on_chain_start" and name in _NODE_LABELS:
                step = cl.Step(name=_NODE_LABELS[name], type="run")
                await step.send()
                node_steps[name] = step
                current_node = name

            # ── Graph node finished ───────────────────────────────────────────
            elif kind == "on_chain_end" and name in _NODE_LABELS:
                output = event["data"].get("output") or {}
                if isinstance(output, dict):
                    accumulated.update(output)
                if name in node_steps:
                    node_steps[name].output = _node_step_content(
                        name, output if isinstance(output, dict) else {}
                    )
                    await node_steps[name].update()

            # ── Tool call started ─────────────────────────────────────────────
            elif kind == "on_tool_start":
                parent_id = node_steps[current_node].id if current_node in node_steps else None
                tool_input = event["data"].get("input") or {}
                step = cl.Step(name=f"🔧 {name}", type="tool", parent_id=parent_id)
                step.input = _trim(json.dumps(tool_input, default=str), 400)
                await step.send()
                tool_steps[run_id] = step

            # ── Tool call finished ────────────────────────────────────────────
            elif kind == "on_tool_end":
                if run_id in tool_steps:
                    out = event["data"].get("output") or ""
                    tool_steps[run_id].output = _trim(str(out), 800)
                    await tool_steps[run_id].update()

            # ── LLM token stream — detect <think> blocks ───────────────────────
            elif kind == "on_chat_model_stream":
                chunk = event["data"].get("chunk")
                if not (chunk and hasattr(chunk, "content") and chunk.content):
                    continue
                token: str = chunk.content if isinstance(chunk.content, str) else ""
                if not token:
                    continue

                # ─ thinking starts ─
                if "<think>" in token and run_id not in in_think:
                    in_think.add(run_id)
                    after_tag = token.split("<think>", 1)[1]
                    think_bufs[run_id] = after_tag
                    think_toks[run_id] = 0
                    parent_id = node_steps[current_node].id if current_node in node_steps else None
                    ts = cl.Step(name="💭 Thinking...", type="run", parent_id=parent_id)
                    ts.output = after_tag
                    await ts.send()
                    think_steps[run_id] = ts

                # ─ thinking ends ─
                elif "</think>" in token and run_id in in_think:
                    in_think.discard(run_id)
                    before_tag = token.split("</think>", 1)[0]
                    think_bufs[run_id] = think_bufs.get(run_id, "") + before_tag
                    if run_id in think_steps:
                        think_steps[run_id].output = think_bufs[run_id]
                        await think_steps[run_id].update()

                # ─ inside thinking: batch-update every 30 tokens ─
                elif run_id in in_think:
                    think_bufs[run_id] = think_bufs.get(run_id, "") + token
                    think_toks[run_id] = think_toks.get(run_id, 0) + 1
                    if think_toks[run_id] % 30 == 0 and run_id in think_steps:
                        think_steps[run_id].output = think_bufs[run_id]
                        await think_steps[run_id].update()

        result = accumulated

        # ── Post-stream: send detail cards ────────────────────────────────────

        if result.get("component_params"):
            params = dict(result["component_params"])
            perf = params.pop("_performance_estimate", None)
            if perf:
                rows = "\n".join(f"| {k} | {v} |" for k, v in perf.items())
                await cl.Message(
                    content="**Analytical Performance Estimate**\n\n"
                            f"| Metric | Value |\n|--------|-------|\n{rows}",
                    author="Estimator",
                ).send()

        layout = result.get("layout_result") or {}
        if layout.get("python_code"):
            await cl.Message(
                content=f"**Generated GLayout Code**\n```python\n{layout['python_code'][:3000]}\n```",
                author="LayoutGenerator",
            ).send()

        sim = result.get("sim_result") or {}
        if sim and not sim.get("skipped") and not sim.get("error"):
            meas_rows = "\n".join(
                f"| {k} | {round(v, 3) if isinstance(v, float) else v} |"
                for k, v in sim.items()
                if k not in ("raw_measurements", "sim_stdout", "returncode", "passed", "error")
                and v is not None
            )
            if meas_rows:
                await cl.Message(
                    content=f"**SPICE Simulation Results**\n\n| Metric | Value |\n|--------|-------|\n{meas_rows}",
                    author="ngspice",
                ).send()
        elif sim.get("error"):
            await cl.Message(
                content=(
                    f"⚠️ **Simulation note:** {sim['error']}\n\n"
                    "To enable SPICE simulation:\n"
                    "1. `sudo apt install ngspice magic`\n"
                    "2. Set `PDK_ROOT` and run: `bash scripts/run_pex.sh output.gds cell_name gf180`"
                ),
                author="ngspice",
            ).send()

        elements = []
        if layout.get("gds_path") and Path(layout["gds_path"]).exists():
            elements.append(cl.File(name="layout.gds", path=layout["gds_path"], display="inline"))

        final = result.get("final_answer") or "Agent completed but produced no summary."
        errors = result.get("errors") or []
        if errors:
            final += "\n\n⚠️ **Errors encountered:**\n" + "\n".join(f"- {e}" for e in errors)

        await cl.Message(content=final, elements=elements).send()

    except Exception as e:
        await cl.Message(content=f"❌ Agent error: {e}").send()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _trim(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


# ── Node label map ─────────────────────────────────────────────────────────────

_NODE_LABELS = {
    "spec_parser":      "📋 SpecParser — parsing request",
    "researcher":       "🔍 Researcher — searching papers",
    "circuit_designer": "⚡ CircuitDesigner — sizing components",
    "layout_generator": "🏗️ LayoutGenerator — generating GDS",
    "verifier":         "🔬 Verifier — DRC / LVS / SPICE",
    "summarizer":       "✍️ Summarizer — writing answer",
}


def _node_step_content(node_name: str, output: dict) -> str:
    """Summary shown inside each node's collapsible Step card."""
    if node_name == "spec_parser":
        spec = output.get("circuit_spec") or {}
        return f"```json\n{json.dumps(spec, indent=2)}\n```" if spec else "Spec parsed."

    if node_name == "researcher":
        papers = output.get("retrieved_papers") or []
        if papers:
            lines = [f"Found {len(papers)} papers:"]
            for p in papers[:5]:
                lines.append(f"- {p.get('title', 'Unknown')}")
            return "\n".join(lines)
        return "Paper search complete."

    if node_name == "circuit_designer":
        params = dict(output.get("component_params") or {})
        params.pop("_performance_estimate", None)
        if params:
            lines = ["**Component Parameters:**"]
            for k, v in list(params.items())[:10]:
                lines.append(f"- `{k}`: {v}")
            return "\n".join(lines)
        return "Circuit sizing complete."

    if node_name == "layout_generator":
        lr = output.get("layout_result") or {}
        gds = lr.get("gds_path", "")
        status = "✅ GDS generated" if gds else "⏳ Generating..."
        code = lr.get("python_code", "")
        preview = f"\n\n```python\n{code[:400]}...\n```" if code else ""
        return f"{status}{(' — ' + gds) if gds else ''}{preview}"

    if node_name == "verifier":
        lr = output.get("layout_result") or {}
        drc = lr.get("drc_summary", "")
        sim = output.get("sim_result") or {}
        parts = []
        if drc:
            parts.append(drc)
        if sim and not sim.get("skipped"):
            parts.append(f"Simulation: {'✅ pass' if sim.get('passed') else '❌ fail'}")
        return "\n\n".join(parts) if parts else "Verification complete."

    if node_name == "summarizer":
        answer = output.get("final_answer", "")
        return _trim(answer, 600)

    return _trim(json.dumps(output, indent=2, default=str), 600)


# ── Chainlit Settings Panel ────────────────────────────────────────────────────

@cl.on_settings_update
async def on_settings_update(settings: dict):
    """Update session settings when the user changes them in the UI."""
    cl.user_session.set("settings", settings)
    await cl.Message(content=f"Settings updated: {settings}").send()
