# Architecture

## Agent Pipeline

```
┌──────────────────────────────────────────────────────────────────┐
│  Web UI  (app/web_app.py — FastAPI + SSE)                        │
│  "Design a 5GHz LNA in gf180 with NF < 2dB"                     │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────────┐
│  LangGraph Agent  (src/gelochip/agent/graph.py)                  │
│                                                                   │
│  SpecParser → Researcher → CircuitDesigner ──────────────────┐   │
│                                 │ PySpice/ngspice validation  │   │
│                                 ↓ (pass)       (fail) ───→   │   │
│                           LayoutGenerator   Corrector ←───────┘  │
│                                 │ (fail) ──→   │                  │
│                                 │       ←───────┘ (retry/fixed)  │
│                                 ↓                                 │
│                              Verifier (DRC/LVS/SPICE)            │
│                                 ↓                                 │
│                             Summarizer → final answer            │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────────┐
│  Gelochip Building Blocks  (src/gelochip/core/)                  │
│  nmos / pmos / current_mirror / diff_pair / lna_cascode / …     │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────────┐
│  GLayout  (src/gelochip/glayout/)                                │
│  gdsfactory + klayout → GDS output + DRC/LVS                    │
└──────────────────────────────────────────────────────────────────┘
```

## Agent Nodes

| Node | File | Purpose |
|------|------|---------|
| SpecParser | `nodes/spec_parser.py` | Natural language → `CircuitSpec` JSON |
| Researcher | `nodes/researcher.py` | ArXiv RAG + PDF figure extraction |
| CircuitDesigner | `nodes/circuit_designer.py` | Component sizing + PySpice validation |
| LayoutGenerator | `nodes/layout_generator.py` | GLayout code generation + GDS execution |
| Corrector | `nodes/corrector.py` | Universal error fixer (JSON/PySpice/layout) |
| Verifier | `nodes/verifier.py` | DRC / LVS / SPICE spec check |
| Summarizer | `nodes/summarizer.py` | Final answer synthesis |

## PixelatedRF Inverse Design Pipeline

```
Dataset (540k layouts × S₁₁) → 01_dataset.ipynb
         ↓
Forward Surrogate (Layout→S₁₁)  ← 02_train.ipynb Phase A
  ForwardSurrogateNet v4: CoordConv + SE-ResNet + multi-scale MLP
  val MSE = 0.093 (z-scored) after 200 epochs
         ↓
Inverse Design (S₁₁→Layout) ← 02_train.ipynb Phase B
  ConditionalGenerator v5b: Product-Gated cVAE
  val best-of-8 tandem MSE = 0.301 after 120 epochs
         ↓
GF180 GDSII export ← 03_layout_gds.ipynb
         ↓
OpenEMS FDTD validation ← 04_simulate.ipynb
```

## Project Structure

```
Gelochip/
├── src/gelochip/
│   ├── agent/          # LangGraph pipeline + nodes + tools
│   ├── core/           # primitives / blocks / cells / pdk
│   ├── glayout/        # GLayout framework (gdsfactory-based)
│   ├── verification/   # DRC/LVS runner, testbench generator
│   └── api/            # FastAPI REST backend
├── app/
│   ├── web_app.py      # FastAPI + SSE web UI (port 8080)
│   ├── mcp_server.py   # MCP server for Claude Desktop
│   └── static/
├── notebooks/
│   ├── pixelatedRF/    # EM inverse design pipeline (4 notebooks)
│   └── datasets/       # Circuit layout datasets for fine-tuning
├── finetuning/         # Qwen3 SFT + DPO notebooks
├── docs/               # Extended documentation
└── outputs/            # Per-job run artifacts (git-ignored)
```
