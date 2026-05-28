# Gelochip Kaizen — RAG (not SFT) for gf180 RF/mmWave chip generation

A self-correcting **Retrieval-Augmented Generation** agent that designs gf180
analog/RF layouts, verifies them with real **Magic DRC**, runs **AC + transient**
testbenches checked against closed-form **theory**, and learns from every failure
— **without fine-tuning** the model. Knowledge is external and hot-swappable;
the model stays a general reasoner.

![Gelochip Kaizen showcase](../../docs/img/kaizen_showcase.png)

> Full design rationale + diagrams: [`01_kaizen_architecture.ipynb`](01_kaizen_architecture.ipynb).

## Architecture

```
Gelochip Studio (web)              Kaizen LangGraph agent            Knowledge (local ChromaDB)
─────────────────────              ──────────────────────            ──────────────────────────
Prompt → GDSII (RF)   ┐    plan → retrieve → generate → test ──┐     1. glayout_knowledge
IP Library (drag-drop)├──▶  ▲ (DRC + AC/tran vs theory)        │     2. rf_theory
Padframe (chipathon)  │     └──── error_feedback ◀── critic ◀──┘     3. error_feedback (empty→grows)
Pin-Connect agent     ┘    LLM: qwen3.5:9b (Ollama) · embeddings: all-MiniLM-L6-v2 (local)
```

## The three ChromaDB collections

| # | Collection | Contents | Source |
|---|---|---|---|
| 1 | **`glayout_knowledge`** | glayout layout/code knowledge incl. 15 DRC-clean circuit blocks | `data/glayout_code/*.jsonl` + `data/circuits/*/*_clean.py` |
| 2 | **`rf_theory`** | RF/mmWave books, papers, EE-QA, PySpice corpus | `data/rf_theory/**` |
| 3 | **`error_feedback`** | error → root-cause → fix memory — **starts EMPTY**, written by the Kaizen loop at runtime | runtime (`collections.add_lesson`) |

## Repository layout (after cleanup)

```
Gelochip/
├── data/                     # all datasets (moved here, clean & readable)
│   ├── circuits/             #   15 DRC-clean circuit blocks (IP library)
│   ├── glayout_code/         #   human→glayout-code JSONL (collection 1)
│   ├── rf_theory/            #   RF/mmWave theory corpus (collection 2)
│   └── pixelatedrf/          #   antenna_dataset.mat, data_split.npz
├── models/
│   └── qwen35_4b_gds_lora/   # SFT model weights (moved out of notebooks/)
├── src/gelochip/kaizen/      # config, embeddings, collections, executor,
│                             # testbench, clean_builders, agent, studio
├── app/kaizen_app.py + app/static/kaizen/   # FastAPI + SSE web Studio
├── scripts/                  # kaizen_ingest.py, build_clean_datasets.py, …
└── notebooks/kaizen_architecture/  # 01_kaizen_architecture.ipynb + chroma_db/
```

## Quick start

```bash
VIRTUAL_ENV=$PWD/.venv uv pip install -r requirements.txt   # keep numpy<2.0
ollama pull qwen3.5:9b
.venv/bin/python scripts/kaizen_ingest.py                   # build the 3 collections
.venv/bin/python -m uvicorn app.kaizen_app:app --port 8090  # → http://localhost:8090
```

## The 15 DRC-clean circuits (verified)

All under `data/circuits/<name>/<name>_clean.py`, each verified at **0 Magic DRC
errors** and with an AC/transient (or DC-sweep) testbench matched to theory,
plotted in `tb_clean/`, and ingested into `glayout_knowledge`.

| class | circuits | theory check |
|---|---|---|
| switch | transmission_gate | ~0 dB pass-through |
| follower | fvf, n_block, p_block | gain ≈ unity |
| current mirror | current_mirror, stacked_current_mirror, low_voltage_cmirror | DC copy ratio |
| amplifier | diff_pair, diff_pair_cmirrorbias, ota, opamp, differential_to_single_ended_converter, diff_pair_stackedcmirror, row_csamplifier_diff_to_single_ended_converter | DC gain / GBW |
| 2-stage | opamp_twostage | ~43 dB (> single stage) |

Re-verify any circuit: `.venv/bin/python scripts/build_clean_datasets.py <name>`
(refuses to promote unless Magic confirms 0 DRC errors).

## Gelochip Studio (web) — four tools

1. **Prompt → GDSII (RF)** — live `plan→retrieve→generate→DRC→error_feedback`,
   GDS preview, extracted SPICE, AC + transient matplotlib plots, code.
2. **IP Library** — the 15 DRC-clean blocks, drag-n-drop onto the chip.
3. **Padframe** — gf180 pad ring (sscs-chipathon-2025 / caravel-gf180mcu compatible).
4. **Pin-Connect agent** — proposes pin↔pin nets + pinout names, draws wires.
