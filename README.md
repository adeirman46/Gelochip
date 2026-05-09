# Gelochip

**AI-Assisted Analog/RF IC Layout Automation** — powered by [GLayout](https://github.com/ALIGN-analoglayout/ALIGN-public) and [LangGraph](https://github.com/langchain-ai/langgraph).

Describe the circuit you want in plain English. Gelochip designs, sizes, and generates a GDSII layout automatically.

> Inspired by [Chipster](https://github.com/adeirman46/Chipster) (digital flow via OpenLane) — Gelochip is its analog/RF counterpart.

---

## Features

| Feature | Details |
|---------|---------|
| **Agentic AI Pipeline** | LangGraph multi-agent: SpecParser → Researcher → CircuitDesigner → LayoutGenerator → Verifier |
| **Building Blocks** | Function-based library: `nmos`, `pmos`, `current_mirror`, `diff_pair`, `lna_cascode`, `gilbert_cell_mixer`, `lc_vco`, … |
| **RF/Analog Cells** | LNA, Op-Amp, Mixer, VCO with proper port wiring |
| **PDK Support** | **gf180** (default), sky130, ihp130 |
| **Web Interface** | Chainlit — React-based chat UI (not Streamlit) |
| **REST API** | FastAPI backend with async job queue |
| **Paper RAG** | ArXiv search for topology knowledge |
| **LLM Support** | Claude (Anthropic), Gemini (Google), GPT-4o (OpenAI) |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  Chainlit Web UI  (app/chainlit_app.py)                          │
│  "Design a 5GHz LNA in gf180 with NF < 2dB"                     │
└──────────────────────────┬───────────────────────────────────────┘
                           │  in-process
┌──────────────────────────▼───────────────────────────────────────┐
│  LangGraph Agent  (src/gelochip/agent/graph.py)                  │
│                                                                   │
│  SpecParser → Researcher → CircuitDesigner → LayoutGenerator     │
│                                     ↕  (up to 3 corrections)     │
│                                Verifier ← failed code            │
│                                     ↓                            │
│                                Summarizer → final answer         │
└──────────────────────────┬───────────────────────────────────────┘
                           │  calls
┌──────────────────────────▼───────────────────────────────────────┐
│  Gelochip Building Blocks  (src/gelochip/core/)                  │
│                                                                   │
│  Primitives:  nmos / pmos / resistor / capacitor / via_stack     │
│  Blocks:      current_mirror / diff_pair / common_source / …     │
│  Cells:       lna_cascode / two_stage_opamp / gilbert_cell / …   │
└──────────────────────────┬───────────────────────────────────────┘
                           │  wraps
┌──────────────────────────▼───────────────────────────────────────┐
│  GLayout  (src/gelochip/glayout/)                                │
│  gdsfactory + klayout → GDS output + DRC/LVS                    │
└──────────────────────────────────────────────────────────────────┘
```

---

## Installation

### Prerequisites

| Tool | Install |
|------|---------|
| Python 3.10+ | `sudo apt install python3.10` or pyenv |
| `uv` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| KLayout | `sudo apt install klayout` or [klayout.de](https://www.klayout.de) |
| ngspice (optional) | `sudo apt install ngspice` |
| Magic + Netgen (optional) | [opencircuitdesign.com/magic](http://opencircuitdesign.com/magic/) |

---

### Step 1 — Clone

```bash
git clone https://github.com/adeirman46/Gelochip.git
cd Gelochip
```

### Step 2 — Install `uv`

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env    # add uv to PATH
```

### Step 3 — Create venv and install

```bash
uv sync --extra ml --extra notebooks
```

Installs everything (EDA core, AI agent, web UI, ML fine-tuning, Jupyter).

### Step 4 — Configure API keys

```bash
cp .env.example .env
nano .env        # or code .env
```

```dotenv
# .env — at least ONE key required
ANTHROPIC_API_KEY=sk-ant-...      # Claude claude-sonnet-4-6 (recommended)
GOOGLE_API_KEY=AIza...            # Gemini 2.5 Pro
OPENAI_API_KEY=sk-...             # GPT-4o
```

### Step 5 — Set up gf180 PDK

```bash
# Option A: via volare (recommended, lightweight)
uv run pip install volare
uv run volare enable --pdk gf180mcu --version 0.0.1

# Option B: IIC-OSIC-TOOLS Docker (all PDKs + Magic + Netgen pre-installed)
# docker pull hpretl/iic-osic-tools
# docker run -it -p 8888:8888 hpretl/iic-osic-tools
```

> sky130 is also supported: `uv run volare enable --pdk sky130 --version bdc9412`

---

## Running

> **Which one do I use?**
>
> | | Chainlit (Web UI) | REST API |
> |--|--|--|
> | **Who** | You, as a user | Another program / script |
> | **How** | Chat in a browser | HTTP requests (`curl`, Python `requests`, Postman) |
> | **Use when** | Interactive design sessions | Batch automation, CI pipelines, custom frontends |
>
> **→ If you just want to design circuits: use Chainlit. That's the main interface.**
> The REST API is optional and only needed if you want to call Gelochip programmatically from another system.

### Start Gelochip (Chainlit Web UI)

```bash
uv run chainlit run app/chainlit_app.py --port 8080
```

Open `http://localhost:8080` in your browser. Type a design request like:

```
Design a 5GHz cascode LNA in gf180 with NF < 2dB and gain > 15dB
```

Chainlit is a React-based web application built for AI agents — real-time step streaming, downloadable GDS files, dark mode. Not Streamlit.

### REST API (optional — for programmatic use)

```bash
uv run uvicorn gelochip.api.main:app --reload --port 8000
# Swagger UI at http://localhost:8000/docs
```

```bash
# Example: submit a design job via curl
curl -X POST http://localhost:8000/design/run_sync \
  -H "Content-Type: application/json" \
  -d '{"request": "Design a two-stage opamp in gf180 with 60dB gain", "pdk": "gf180"}'
```

### Python script (optional — for automation)

```python
from gelochip.agent.graph import build_graph, create_initial_state

graph = build_graph()   # auto-detects API key from .env
result = graph.invoke(create_initial_state(
    "Design a 5GHz cascode LNA in gf180 with NF < 2dB and gain > 15dB"
))
print(result["final_answer"])
```

### Use building blocks directly

```python
from gelochip.glayout.pdk.gf180_mapped import gf180_mapped_pdk as pdk

# ── Primitives ────────────────────────────────────────────────────
from gelochip.core.primitives import nmos, pmos, capacitor, via_stack

m1 = nmos(pdk, width=2.0, fingers=4)
m2 = pmos(pdk, width=4.0, fingers=4)
c1 = capacitor(pdk, width=5.0, length=5.0)

# ── Building blocks ───────────────────────────────────────────────
from gelochip.core.blocks import current_mirror, diff_pair, common_source

cm  = current_mirror(pdk, mirror_ratio=2.0, ref_width=4.0, n_or_p="nfet")
dp  = diff_pair(pdk, width=6.0, fingers=4, n_or_p="nfet")
cs  = common_source(pdk, width=4.0, fingers=2, load_type="pmos_diode")

# ── RF Cells ──────────────────────────────────────────────────────
from gelochip.core.cells import lna_cascode, gilbert_cell_mixer, two_stage_opamp, lc_vco

lna  = lna_cascode(pdk, gm_width=40.0, gm_fingers=10, cas_width=40.0, cas_fingers=10)  # gf180 Lmin=0.18µm
mix  = gilbert_cell_mixer(pdk, rf_width=10.0, rf_fingers=4)
oa   = two_stage_opamp(pdk, diff_pair_width=6.0, diff_pair_fingers=4)
vco  = lc_vco(pdk, xcp_width=8.0, xcp_fingers=4, inductor_turns=3)

# Write GDS
lna.write_gds("lna.gds")
lna.show()   # open in KLayout
```

---

## AI Agent — "Current Methods"

Gelochip uses a **LangGraph multi-agent state machine**, the same architecture powering Claude Code, LangChain agents, and modern agentic RAG systems.

| Pattern | Implementation |
|---------|---------------|
| **ReAct** | Each node reasons before calling tools |
| **RAG** | ArXiv full-text search for topology papers |
| **Tool Use** | `arxiv_search`, `execute_layout_code`, `estimate_performance` |
| **Self-correction** | Verifier loops on compile/DRC errors (up to N times) |
| **State machine** | LangGraph `StateGraph` with typed `GelochipAgentState` |
| **Streaming** | Chainlit displays each step live |

**PINN (Physics-Informed Neural Networks)** — planned: train a PINN on SPICE sweeps to predict MOSFET I-V curves across PDK corners, replacing hand-analysis approximations in sizing.

---

## GLayout Roadmap

- [x] Function-based primitives: `nmos`, `pmos`, `resistor`, `capacitor`, `via_stack`
- [x] Building blocks: `current_mirror` (basic, cascode, Wilson), `diff_pair`, `folded_cascode`, `common_source/gate/drain`, `bias`
- [x] RF cells: `lna_cascode`, `lna_inductively_degenerated`, `gilbert_cell_mixer`, `passive_mixer`, `lc_vco`, `ring_vco`
- [x] Op-amp cells: `two_stage_opamp`, `folded_cascode_opamp`
- [x] LangGraph agent pipeline
- [x] ArXiv search tool
- [ ] Full EM-simulated spiral inductor
- [ ] PINN device model
- [ ] Post-layout SPICE via ngspice
- [ ] Bayesian / RL parameter optimizer
- [ ] GF180 BJT-based bandgap reference (primary PDK — npn_10x10 model)

---

## Project Structure

```
Gelochip/
├── src/gelochip/
│   ├── glayout/            # GLayout framework source
│   ├── core/
│   │   ├── primitives/     # nmos, pmos, resistor, capacitor, via, guard_ring
│   │   ├── blocks/         # current_mirror, diff_pair, amplifier, bias
│   │   └── cells/          # opamp, lna, mixer, vco
│   ├── agent/
│   │   ├── graph.py        # LangGraph pipeline
│   │   ├── nodes/          # 6 agent nodes
│   │   ├── tools/          # circuit_tools, search_tools
│   │   ├── prompts/        # system prompts
│   │   └── finetuning/     # LLM SFT scripts
│   └── api/
│       ├── main.py         # FastAPI app
│       └── routes/         # REST endpoints
├── app/
│   └── chainlit_app.py     # Chainlit web UI
├── tests/
├── notebooks/
│   └── tutorials/          # GLayout tutorial notebooks
├── pyproject.toml          # uv project config
├── requirements.txt
├── environment.yml
└── .env.example
```

---

## License

Apache-2.0 — see [LICENSE](LICENSE).
