# Gelochip

**AI-Assisted Analog/RF IC Layout Automation** — powered by [GLayout](https://github.com/ALIGN-analoglayout/ALIGN-public) and [LangGraph](https://github.com/langchain-ai/langgraph).

Describe the circuit you want in plain English. Gelochip designs, sizes, and generates a GDSII layout automatically.

> Inspired by [Chipster](https://github.com/adeirman46/Chipster) (digital flow via OpenLane) — Gelochip is its analog/RF counterpart.

---

## Features

| Feature | Details |
|---------|---------|
| **Agentic AI Pipeline** | LangGraph multi-agent: SpecParser → Researcher → CircuitDesigner → LayoutGenerator → **Corrector** → Verifier |
| **PySpice Validation** | Circuit designer generates and validates a SPICE netlist with ngspice before layout |
| **Universal Corrector** | Fixes errors from any node — JSON params, PySpice failures, layout import/API errors |
| **Building Blocks** | Function-based library: `nmos`, `pmos`, `current_mirror`, `diff_pair`, `lna_cascode`, `gilbert_cell_mixer`, `lc_vco`, … |
| **Custom Blocks** | Auto-saves manually-implemented cells to `core/custom_blocks/` for future reuse |
| **RF/Analog Cells** | LNA, Op-Amp, Mixer, VCO with proper port wiring |
| **Satellite RF Cells** | `rf_buffer`, `switched_cap_ps` (MTPS), `rf_combiner_8to1`, `rf_amp`, `rx_element` — full Ka-band phased array RX strip |
| **PDK Support** | **gf180** (default), sky130, ihp130 |
| **Web Interface** | FastAPI + SSE — real-time pipeline streaming with stage-by-stage cards |
| **REST API** | FastAPI backend with async job queue |
| **MCP Server** | Claude Desktop integration via MCP tool |
| **Paper RAG** | ArXiv search for topology knowledge |
| **LLM Fine-tuning** | Domain-specific Qwen3 SFT + DPO on analog/RF circuit datasets |
| **LLM Support** | **Local:** Ollama (qwen3:8b, fits 8 GB VRAM) · **Cloud:** Claude, Gemini, GPT-4o |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  Web UI  (app/web_app.py  —  FastAPI + SSE)                      │
│  "Design a 5GHz LNA in gf180 with NF < 2dB"                     │
└──────────────────────────┬───────────────────────────────────────┘
                           │  in-process
┌──────────────────────────▼───────────────────────────────────────┐
│  LangGraph Agent  (src/gelochip/agent/graph.py)                  │
│                                                                   │
│  SpecParser → Researcher → CircuitDesigner ──────────────────┐   │
│                                 │ PySpice/ngspice validation  │   │
│                                 ↓ (pass)        (fail) ───→  │   │
│                           LayoutGenerator    Corrector ←──────┘  │
│                                 │ (fail) ──→    │                 │
│                                 │        ←──────┘ (retry/fixed)  │
│                                 ↓                                 │
│                              Verifier (DRC/LVS/SPICE)            │
│                                 ↓                                 │
│                             Summarizer → final answer            │
└──────────────────────────┬───────────────────────────────────────┘
                           │  calls
┌──────────────────────────▼───────────────────────────────────────┐
│  Gelochip Building Blocks  (src/gelochip/core/)                  │
│                                                                   │
│  Primitives:  nmos / pmos / resistor / capacitor / via_stack     │
│  Blocks:      current_mirror / diff_pair / common_source / …     │
│  Cells:       lna_cascode / two_stage_opamp / gilbert_cell / …   │
│  Custom:      core/custom_blocks/  (auto-saved new cells)        │
└──────────────────────────┬───────────────────────────────────────┘
                           │  wraps
┌──────────────────────────▼───────────────────────────────────────┐
│  GLayout  (src/gelochip/glayout/)                                │
│  primitives / routing / placement / cells / pdk / spice          │
│  gdsfactory + klayout → GDS output + DRC/LVS                    │
└──────────────────────────────────────────────────────────────────┘
```

---

## Installation

### Prerequisites

| Tool | Required | Install |
|------|----------|---------|
| Python 3.10+ | ✅ | `sudo apt install python3.10` or pyenv |
| `uv` | ✅ | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| **ngspice** | ✅ | `sudo apt update && sudo apt install -y ngspice` |
| KLayout | ✅ | `sudo apt install klayout` or [klayout.de](https://www.klayout.de) |
| Magic + Netgen | optional | [opencircuitdesign.com/magic](http://opencircuitdesign.com/magic/) |

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

### Step 4 — Configure LLM

```bash
cp .env.example .env
nano .env        # or code .env
```

Pick **one** option:

#### Option A — Local with Ollama (free, no internet, 8 GB VRAM)

```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Pull the model (~5 GB download)
ollama pull qwen3:8b
```

Then in `.env`:
```dotenv
OLLAMA_MODEL=qwen3:8b          # or qwen3:4b for <6 GB VRAM
# OLLAMA_HOST=http://localhost:11434  # default, change if needed
```

#### Option B — Cloud API

```dotenv
ANTHROPIC_API_KEY=sk-ant-...      # Claude claude-sonnet-4-6
# GOOGLE_API_KEY=AIza...          # Gemini 2.5 Pro
# OPENAI_API_KEY=sk-...           # GPT-4o
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

### Start Gelochip Web UI

```bash
uv run uvicorn app.web_app:app --port 8080 --reload
```

Open `http://localhost:8080` in your browser.

```
Design a 5GHz cascode LNA in gf180 with NF < 2dB and gain > 15dB
```

The web UI shows the full agent pipeline live:

| What you see | When it appears |
|---|---|
| 📋 **SpecParser** — structured spec JSON | Immediately after submit |
| 🔍 **Researcher** + paper cards | While ArXiv papers are fetched |
| 💭 **Thinking...** block | Qwen3/DeepSeek-R1 reasoning streamed live |
| ⚡ **CircuitDesigner** — param table + PySpice ✅/❌ | After topology sizing |
| 🔧 **Corrector** — error + feedback (if any failure) | On JSON/PySpice/layout error |
| 🏗️ **LayoutGenerator** + GLayout Python code | GDS being generated |
| 🔬 **Verifier** — DRC/LVS/SPICE results | After GDS is ready |
| Layout preview image | Right panel, after GDS completes |
| ✍️ **Summarizer** final answer | Markdown-rendered at the end |

Each run saves all artifacts to `outputs/{job_id}/` — see [Output Directory](#output-directory).

### REST API (optional — for programmatic use)

```bash
uv run uvicorn gelochip.api.main:app --reload --port 8000
# Swagger UI at http://localhost:8000/docs
```

```bash
curl -X POST http://localhost:8000/design/run_sync \
  -H "Content-Type: application/json" \
  -d '{"request": "Design a two-stage opamp in gf180 with 60dB gain", "pdk": "gf180"}'
```

### MCP Server (Claude Desktop integration)

Expose Gelochip as an MCP tool so Claude Desktop (or any MCP client) can design circuits directly.

```bash
uv run python app/mcp_server.py
```

Add to Claude Desktop `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "gelochip": {
      "command": "uv",
      "args": ["run", "python", "app/mcp_server.py"],
      "cwd": "/path/to/Gelochip"
    }
  }
}
```

Then in Claude Desktop: *"Design a 5GHz LNA in gf180"* — Claude will call the `design_circuit` MCP tool automatically.

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

## Verification Flow

The agent runs 4 verification stages automatically after generating the layout:

```
GLayout code
     │
     ▼
① Code execution  ── Python compiles + GDS generated?  ──→ fix & retry (up to 3×)
     │
     ▼
② DRC             ── Design rules pass?                 ──→ report violations
     │  (Magic VLSI)
     ▼
③ LVS             ── Layout matches schematic netlist?  ──→ report mismatches
     │  (Netgen)
     ▼
④ PEX + SPICE     ── Performance meets spec?            ──→ fix sizing & retry
        (Magic + ngspice)
```

| Stage | Tool | What it checks | Required |
|-------|------|---------------|---------|
| Code | Python | GLayout compiles, GDS produced | Always |
| DRC | Magic VLSI | Min spacing, width, enclosure | `sudo apt install magic` + `PDK_ROOT` |
| LVS | Netgen | Layout netlist == schematic | `sudo apt install netgen-lvs` + `PDK_ROOT` |
| SPICE | ngspice | Gain, NF, phase margin, IIP3, etc. | `sudo apt install ngspice` |

**If Magic/Netgen/ngspice are not installed**, the agent skips those stages gracefully and tells you what to install. The fastest way to get all tools: use the [IIC-OSIC-TOOLS Docker image](https://github.com/iic-jku/iic-osic-tools).

### Running PEX manually

```bash
# After the agent generates output.gds:
export PDK_ROOT=/path/to/pdks
bash scripts/run_pex.sh /tmp/gelochip_output/lna_cascode.gds lna_cascode gf180
# → produces lna_cascode_pex.spice (with R/C parasitics)
```

### Running SPICE manually

```python
from gelochip.verification import generate_testbench, run_simulation, check_specs

tb = generate_testbench(
    circuit_type="lna",
    spice_path="lna_cascode_pex.spice",
    circuit_name="lna_cascode",
    spec={"vdd_V": 1.8, "freq_GHz": 5.0, "gain_dB": 15.0, "nf_dB": 2.0},
    pdk="gf180",
)
sim    = run_simulation(tb, circuit_type="lna")
result = check_specs(sim, spec={"gain_dB": 15.0, "nf_dB": 2.0})
print(result)
# {'all_passed': True, 'checks': [{'metric': 'gain_dB', 'target': 15.0, 'measured': 16.3, 'passed': True}, ...]}
```

---

## Output Directory

Every pipeline run saves all artifacts under `outputs/{job_id}/`:

```
outputs/{job_id}/
├── spec.json               – parsed CircuitSpec
├── params.json             – sized component parameters
├── summary.md              – final answer from Summarizer
├── spice/
│   ├── netlist.py          – PySpice validation script (from CircuitDesigner)
│   └── testbench.sp        – ngspice testbench (from Verifier)
├── papers/
│   ├── papers.json         – metadata for all retrieved ArXiv papers
│   └── {arxiv_id}/
│       ├── paper.pdf
│       └── fig_0.png …
├── layout/
│   ├── layout.py           – generated GLayout Python code
│   ├── output.gds          – GDSII layout
│   └── output_preview.png
└── verification/
    ├── drc_report.txt      – Magic DRC output
    ├── lvs_report.txt      – Netgen LVS output
    ├── testbench.sp        – ngspice testbench (mirror copy)
    ├── output_pex.spice    – post-layout PEX netlist (if Magic ran)
    └── sim_results.json    – ngspice simulation results
```

Override the root directory with `GELOCHIP_OUTPUT_DIR=/your/path` in `.env`.

---

## AI Agent — "Current Methods"

Gelochip uses a **LangGraph multi-agent state machine**, the same architecture powering Claude Code, LangChain agents, and modern agentic RAG systems.

| Pattern | Implementation |
|---------|---------------|
| **ReAct** | Each node reasons before calling tools |
| **RAG** | ArXiv full-text search for topology papers |
| **Tool Use** | `arxiv_search`, `execute_layout_code`, `execute_pyspice_code`, `estimate_performance` |
| **PySpice Validation** | CircuitDesigner validates netlist with ngspice before layout; skips gracefully if absent |
| **Universal Corrector** | Single corrector node handles JSON, PySpice, and layout errors from any upstream node |
| **Self-correction** | Verifier loops on compile/DRC errors (up to N times) |
| **State machine** | LangGraph `StateGraph` with typed `GelochipAgentState` |
| **Streaming** | FastAPI SSE displays each pipeline step live in the browser |

**PINN (Physics-Informed Neural Networks)** — in progress: train a PINN on SPICE sweeps to predict MOSFET I-V curves across PDK corners, replacing hand-analysis approximations in sizing (`finetuning/pinn/`).

---

## Fine-tuning

The `finetuning/` directory contains notebooks for training a domain-expert Qwen3 model on analog/RF circuit design:

| Notebook | Purpose |
|----------|---------|
| `data_prep/01_pdf_extract.ipynb` | Extract circuits and specs from analog IC design papers (PDFs) |
| `data_prep/02_dataset_build.ipynb` | Build instruction-tuning dataset (spec → params → GLayout code) |
| `sft/03_qwen_sft_lora.ipynb` | Supervised fine-tuning with LoRA on Qwen3 |
| `sft/04_dpo_refine.ipynb` | DPO refinement: correct vs incorrect layout pairs |
| `pinn/05_pinn_maxwell.ipynb` | Physics-Informed Neural Network for MOSFET I-V modeling |
| `eval/06_rf_benchmark.ipynb` | Benchmark fine-tuned model on RF circuit tasks |
| `eval/07_pinn_verify.ipynb` | Verify PINN predictions against ngspice sweeps |

Raw training datasets are in `finetuning/data/raw/` (LNA, Mixer, VCO, Opamp specs from aicircuit).

---

## GLayout Roadmap

- [x] Function-based primitives: `nmos`, `pmos`, `resistor`, `capacitor`, `via_stack`, `mimcap`, `bjt`
- [x] Building blocks: `current_mirror` (basic, cascode, Wilson), `diff_pair`, `folded_cascode`, `common_source/gate/drain`, `bias`
- [x] RF cells: `lna_cascode`, `lna_inductively_degenerated`, `gilbert_cell_mixer`, `passive_mixer`, `lc_vco`, `ring_vco`
- [x] Op-amp cells: `two_stage_opamp`, `folded_cascode_opamp`
- [x] LangGraph agent pipeline with 7 nodes
- [x] ArXiv search tool + PDF figure extraction
- [x] PySpice pre-layout circuit validation with ngspice
- [x] Universal Corrector node (JSON / PySpice / layout errors)
- [x] Custom blocks auto-save to `core/custom_blocks/`
- [x] Per-job output directory (spec, params, spice, layout, verification)
- [x] MCP server (Claude Desktop integration)
- [x] Satellite RF cells: `rf_buffer`, `switched_cap_ps` (MTPS), `rf_combiner_8to1`, `rf_amp`, `rx_element`
- [ ] Full EM-simulated spiral inductor
- [ ] PINN device model (in progress — `finetuning/pinn/`)
- [ ] Ka-band phased array top-level chip (8× `rx_element` + `rf_combiner_8to1`)
- [ ] MTP (Multi-Time Programmable) calibration memory cell
- [ ] Bayesian / RL parameter optimizer

---

## Project Structure

```
Gelochip/
├── src/gelochip/
│   ├── agent/
│   │   ├── graph.py              # LangGraph pipeline + conditional routing
│   │   ├── state.py              # GelochipAgentState (typed TypedDict)
│   │   ├── output_manager.py     # Per-job artifact saver (outputs/{job_id}/)
│   │   ├── nodes/
│   │   │   ├── spec_parser.py    # Parse natural-language request → CircuitSpec
│   │   │   ├── researcher.py     # ArXiv RAG + PDF figure extraction
│   │   │   ├── circuit_designer.py  # Component sizing + PySpice validation
│   │   │   ├── layout_generator.py  # GLayout code generation + GDS execution
│   │   │   ├── corrector.py      # Universal error fixer (any upstream node)
│   │   │   ├── verifier.py       # DRC / LVS / SPICE spec check
│   │   │   └── summarizer.py     # Final answer synthesis
│   │   ├── prompts/
│   │   │   └── system_prompts.py # All LLM system prompts (incl. PYSPICE_GENERATOR, CORRECTOR)
│   │   └── tools/
│   │       ├── circuit_tools.py  # execute_layout_code, execute_pyspice_code, estimate_performance
│   │       └── search_tools.py   # arxiv_search, crawl4ai web fetch
│   ├── core/
│   │   ├── primitives/           # nmos, pmos, resistor, capacitor, via, guard_ring
│   │   ├── blocks/               # current_mirror, diff_pair, amplifier, bias
│   │   ├── cells/                # lna, opamp, mixer, vco, satellite_rf
│   │   │   └── satellite_rf.py   # rf_buffer, switched_cap_ps (MTPS), rf_combiner_8to1, rf_amp, rx_element
│   │   ├── custom_blocks/        # auto-saved manually-implemented cells (agent output)
│   │   └── pdk/
│   │       ├── gf180_mapped/     # GF180MCU PDK rules + layer map
│   │       ├── sky130_mapped/    # SkyWater 130nm PDK
│   │       └── ihp130_mapped/    # IHP 130nm PDK
│   ├── glayout/                  # GLayout framework (gdsfactory-based)
│   │   ├── primitives/           # fet, mimcap, resistor, via_gen, guardring, bjt
│   │   ├── cells/
│   │   │   ├── elementary/       # current_mirror, diff_pair, FVF, transmission_gate
│   │   │   └── composite/        # opamp, diffpair_cmirror_bias, fvf_ota, stacked_cmirror, …
│   │   ├── routing/              # c_route, L_route, smart_route, straight_route
│   │   ├── placement/            # two_transistor, four_transistor, common_centroid
│   │   ├── pdk/
│   │   │   ├── gf180_mapped/
│   │   │   ├── sky130_mapped/
│   │   │   └── ihp130_mapped/
│   │   ├── spice/                # netlist extraction helpers
│   │   ├── util/                 # geometry, port_utils, snap_to_grid, comp_utils
│   │   └── verification/         # DRC evaluator wrapper, physical feature checks
│   ├── verification/
│   │   ├── drc_lvs.py            # Magic DRC + Netgen LVS runner
│   │   ├── testbench.py          # ngspice testbench generator (LNA/Opamp/Mixer/VCO)
│   │   └── simulate.py           # run_simulation + check_specs
│   └── api/
│       ├── main.py               # FastAPI app (REST)
│       ├── schemas.py            # Pydantic request/response models
│       └── routes/
│           └── design.py         # POST /design/run_sync + /design/run_async
├── app/
│   ├── web_app.py                # FastAPI + SSE web UI (port 8080)
│   ├── mcp_server.py             # MCP server for Claude Desktop
│   └── static/
│       └── index.html            # Single-page pipeline viewer
├── finetuning/                   # Domain fine-tuning for analog/RF expertise
│   ├── data_prep/
│   │   ├── 01_pdf_extract.ipynb  # Extract specs from IC design papers
│   │   └── 02_dataset_build.ipynb
│   ├── sft/
│   │   ├── 03_qwen_sft_lora.ipynb   # Qwen3 LoRA supervised fine-tuning
│   │   └── 04_dpo_refine.ipynb      # DPO on correct/incorrect layout pairs
│   ├── pinn/
│   │   └── 05_pinn_maxwell.ipynb    # PINN for MOSFET I-V modeling
│   ├── eval/
│   │   ├── 06_rf_benchmark.ipynb
│   │   └── 07_pinn_verify.ipynb
│   └── data/
│       └── raw/                  # aicircuit datasets (LNA, Mixer, VCO, PA, …)
├── tests/
│   ├── test_agent/               # test_state.py
│   └── test_core/                # test_primitives.py, test_blocks.py
├── scripts/
│   ├── run_pex.sh                # Post-layout PEX extraction via Magic
│   └── setup_pdk.sh              # PDK setup helper
├── outputs/                      # Per-job run artifacts (git-ignored)
│   └── {job_id}/
│       ├── spec.json / params.json / summary.md
│       ├── spice/                # netlist.py (PySpice) + testbench.sp
│       ├── layout/               # layout.py + output.gds
│       └── verification/         # drc_report, lvs_report, sim_results
├── pyproject.toml                # uv project config + optional extras
├── requirements.txt              # pip-compatible mirror of pyproject.toml
├── environment.yml               # Conda environment (includes ngspice)
└── .env.example
```

---

## License

Apache-2.0 — see [LICENSE](LICENSE).
