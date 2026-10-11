# AnoaChip

**Toward the independence of chip design — now for analog.**

📦 Repository: <https://github.com/adeirman46/AnoaChip>

AnoaChip is a local-first, agentic flow that turns a **plain-language prompt into a
verified analog IC layout (GDSII)** — SPICE netlist generation, ngspice spec
verification (gain, bandwidth, phase margin, power…), and full netlist-to-GDS layout
with [Glayout](https://github.com/idea-fasoc/OpenFASOC), all driven by a **local LLM**
running on your own machine.

It is the analog sibling of [GarudaChip](https://github.com/adeirman46/GarudaChip)
(digital, LibreLane), re-architected to:

- 🧠 **Run on local models** via [Ollama](https://ollama.com) (default: `qwen3.5:9b`) —
  no API keys, no cloud, fully offline. Google Gemini remains an optional fallback.
- 📦 **Use [uv](https://docs.astral.sh/uv/)** for the Python environment (no conda).
- 🏭 **Lay out with Glayout** (gdsfactory-based, PDK-agnostic: sky130 / gf180) —
  DRC with **magic**, LVS with **netgen**, spec simulation with **ngspice**.
- 🔁 **Self-improve against the spec** — every circuit starts from a generated
  **config file** of parameters (W/L/fingers/multipliers, bias, placement, routing);
  an RLM deep-agent loop (deepagents + LangChain, autoresearch-style) re-tunes the
  config until the measured specs pass, and every improvement is written back to the
  knowledge DB.

---

## The unified flow

```
 Prompt ("a 5-transistor OTA, 40 dB gain, 1 MHz bandwidth")
   │
   ▼
 ┌────────────────────────── Circuit stage (local LLM) ─────────────────────────┐
 │  RAG recall  →  web research (SPICE netlists + glayout/gdsfactory code)      │
 │  →  CONFIG file (spec + all parameters)  →  SPICE netlist (.sp, with ports)  │
 │  →  ngspice testbench  →  simulate  →  spec check (gain dB, BW, PM, power)   │
 │  ⇄  self-correct: mutate config params until every spec passes               │
 └──────────────────────────────────────────────────────────────────────────────┘
   │  (spec-clean netlist + config)
   ▼
 ┌────────────────────────── Layout stage (Glayout) ────────────────────────────┐
 │  glayout script (nmos/pmos/mimcap sized FROM CONFIG — never defaults)        │
 │  →  place (movex/movey/center)  →  route EVERY port (c_route/L_route/        │
 │     straight_route + via_stack)  →  GDS  →  DRC (magic)  →  LVS (netgen)     │
 │  ⇄  self-correct: fix routes/params; ties, guardring & dummies added LAST    │
 └──────────────────────────────────────────────────────────────────────────────┘
   │
   ▼
 GDSII + reports (DRC, LVS, measured specs, Bode/transient plots, port table)
```

Web research is optional (uses `crawl4ai` + SearXNG) — the researcher hunts for
**SPICE netlists** (`.sp/.spice/.cir/.cdl`) and **glayout/gdsfactory generator code**,
not Verilog.

### The AnoaChip layout rules (enforced in the agent instructions)

1. **Never take the default `nmos()`/`pmos()` config blindly** — size every device
   from the design's config file, and generate the bare device first:
   `with_tie=False, with_substrate_tap=False, with_dummy=False`. Substrate ties,
   guard rings and dummies are **finishing steps**, added only after routing is
   complete and LVS is clean.
2. **Every circuit must expose ports**, and **every connection must be an explicit
   route**: `c_route`, `L_route` or `straight_route` (+ `via_stack` across layers).
   `straight_route` only works for inline parallel ports — if the geometry needs a
   C/L route, a straight route silently produces nothing and **LVS fails**; use
   `smart_route` or pick the right primitive.
3. **Placement is explicit** — `movex`, `movey`, `center` (component references),
   never overlapping devices and never unplaced references.
4. **Config first** — a `config/<name>.json` (spec block + every parameter) exists
   *before* any netlist or layout is generated; the self-improve loop mutates the
   config, re-runs, and records every improvement into the knowledge DB.

---

## Requirements

- Linux x86_64 (tested on Ubuntu)
- `git`, `curl`, `sudo` (only to `apt install` `tcl8.6-dev`/`build-essential` once, for the
  LVS-netgen build)
- An NVIDIA GPU is used automatically for embeddings if present (CPU works too)
- A local [gLayout checkout](https://github.com/idea-fasoc/OpenFASOC) as a **sibling
  folder** `../gLayout` (see `[tool.uv.sources]` in `pyproject.toml`)
- Open PDKs in `~/pdks` (`gf180mcuD` — via volare/open_pdks)

**Two dependency managers, one command** — `./scripts/install.sh` sets up everything:

| Manager | Manages | File |
|---|---|---|
| **[uv](https://docs.astral.sh/uv/)** | the Python env (glayout, torch, langchain, …) — pinned to **Python 3.12** so numpy 1.26 + scipy 1.13 + gdsfactory 7.7 all coexist | `pyproject.toml` + `uv.lock` |
| **[micromamba](https://mamba.readthedocs.io/)** (one static binary, bootstrapped by the script) | the **EDA binaries** magic + ngspice (conda-forge) into a private `.tools/eda/` env; the LVS **netgen** is built from source there | `.tools/` (git-ignored) |

Python can't install the EDA binaries and uv can't either, so the tools live in
AnoaChip's own `.tools/eda/` — **nothing piggybacks on a system install or the sibling
gLayout venv**, so a fresh clone is fully self-contained.

---

## Quick start

```bash
git clone https://github.com/adeirman46/AnoaChip.git && cd AnoaChip

# ONE command: uv Python env (+ glayout editable), micromamba .tools/eda
# (magic + ngspice + netgen-LVS built from source), Ollama + the local model.
./scripts/install.sh

# Bring up the durable knowledge store, then seed it from your gLayout checkout
docker compose up -d
uv run python scripts/build_knowledge_seed.py

# Launch the app (FastAPI :8011 + Vite :5173)
./scripts/run.sh
```

> The docker knowledge stack uses ports **5434 / 9102-9103 / 8890**, shifted so it
> can run side-by-side with GarudaChip's stack (5433 / 9100-9101 / 8888).

### Using the app

Open the Vite URL (`http://localhost:5173`). In the sidebar:

- pick the **chat model** from the dropdown (local Ollama models *and* Ollama **cloud**
  models like `glm-5.2:cloud` — the stronger pick for hard analog designs);
- open **⚙ Constraints** to optionally set a target **Gain (dB)** and **Bandwidth (Hz)**
  (leave blank to let the prompt/agent decide), tick which **simulations** to run
  (**DC / AC / TRAN**, any combination), and toggle **Layout (Glayout GDS · DRC · LVS)**;
- type a circuit (e.g. *"a cascode current mirror with a 10 µA reference"*) and watch it
  go prompt → config → SPICE netlist → ngspice → GDS → DRC/LVS → report.

### Durable knowledge store (the RLM's long-term memory)

AnoaChip remembers everything it sees and makes — netlists, configs, ngspice logs,
GDS, DRC/LVS reports, crawled references — in **Postgres (pgvector)** + **MinIO**,
so each new design can semantically **recall** prior designs, fixes and references.

```bash
docker compose up -d        # AnoaChip's own stack: Postgres 5434 + MinIO 9102/9103
```

The knowledge seed is **rebuilt from your local gLayout checkout** (every tutorial
`.ipynb` and every cell generator `.py` under `src/glayout/cells//blocks/`):

```bash
uv run python scripts/build_knowledge_seed.py          # wipe + re-ingest + export
```

It is config-driven and optional — if the stack is down the app falls back to the
pure-local flow (`ANOA_MEMORY=0` to disable). Manage it with:

```bash
cd src/anoa_chip
uv run python memory_store.py stats     # what's in the store
uv run python memory_store.py export    # refresh the committed seed
```

---

## Manual setup

`./scripts/install.sh` does all of this; the steps, if you prefer them by hand:

```bash
# 1. Python env (uv), pinned to Python 3.12 — glayout comes from ../gLayout, editable
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync --python 3.12         # core deps
uv sync --extra web           # + crawl4ai web-research agent (recommended)
uv run crawl4ai-setup         # one-time Playwright browser setup

# 2. EDA binaries into AnoaChip's OWN env (no system/sibling dependency)
mkdir -p .tools/bin
curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xj -C .tools bin/micromamba
MAMBA_ROOT_PREFIX=$PWD/.tools/mamba .tools/bin/micromamba create -y -p .tools/eda -c conda-forge magic ngspice
# LVS netgen from source (conda-forge 'netgen' is the unrelated 3D-mesh tool)
sudo apt install -y tcl8.6-dev tk8.6-dev build-essential
git clone --depth 1 https://github.com/RTimothyEdwards/netgen .tools/src/netgen
( cd .tools/src/netgen && ./configure --prefix=$PWD/../../eda --with-tcl=/usr/lib/tcl8.6 --with-tk=/usr/lib/tk8.6 && make -j"$(nproc)" && make install )

# 3. Local model (Ollama). For a cloud model: `ollama pull glm-5.2:cloud`
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen3.5:9b

# 4. PDK (if ~/pdks/gf180mcuD isn't already there)
uv run volare enable --pdk gf180mcu <version>   # or use your existing ~/pdks

# 5. Config
cp .env.example .env
```

---

## Configuration

All configuration is in `.env` (copied from `.env.example`). Highlights:

| Variable | Default | Notes |
|---|---|---|
| `LLM_PROVIDER` | `ollama` | `ollama` (local) or `google` (cloud) |
| `OLLAMA_MODEL` | `glm-5.2:cloud` | any tag from `ollama list` (local or `*:cloud`) |
| `PDK` | `gf180mcuD` | glayout mapped PDK (3.3 V, `gf180mcu_fd_pr__nfet_03v3`) |
| `PDK_ROOT` | `~/pdks` | open_pdks layout with `gf180mcuD` |
| `NGSPICE_BIN` / `MAGIC_BIN` / `NETGEN_BIN` | *(auto)* | resolved from `.tools/eda/bin` first, then PATH |
| `ANOA_MEMORY` | `1` | durable knowledge store on/off |
| `SEARXNG_URL` | `http://localhost:8890` | self-hosted metasearch for research |

The EDA tools are resolved automatically (`.tools/eda/bin` → `$ANOA_EDA_BIN` → PATH),
so you normally don't set the `*_BIN` variables.

---

## Project structure

```
AnoaChip/
├── scripts/
│   ├── install.sh                # one command: uv env + .tools/eda (micromamba) + Ollama
│   ├── run.sh                    # launch backend + frontend (puts .tools/eda on PATH)
│   └── build_knowledge_seed.py   # (re)build the knowledge DB from ../gLayout
├── src/anoa_chip/
│   ├── app.py                    # the unified prompt→config→netlist→sim→GDS pipeline
│   ├── deep_agent.py             # RLM deep agents (deepagents + Ollama)
│   ├── netlist_check.py          # SPICE lint + ngspice parse check
│   ├── spice_sim.py              # ngspice runner, spec metrics, Bode/tran plots
│   ├── glayout_harness.py        # subprocess: build(pdk) → GDS + DRC + LVS (headless)
│   ├── glayout_tools.py          # config files + build/verify + independent tool resolution
│   ├── passives.py               # on-chip inductor (spiral + Mohan L) / active-inductor +
│   │                             #   mimcap integration guidance (glayout has no inductor)
│   ├── memory_store.py           # Postgres(pgvector)+MinIO knowledge store
│   └── llm.py                    # model/embeddings factory (Ollama ⇄ Google)
├── backend/anoa_api/             # FastAPI (runs the pipeline headlessly, SSE)
├── frontend/                     # Vite + React UI (teal theme; Gain/BW + DC/AC/TRAN controls)
├── .tools/                       # AnoaChip's own EDA env (magic/netgen/ngspice) — git-ignored
├── pyproject.toml + uv.lock      # uv-managed (Python 3.12); glayout = ../gLayout (editable)
└── .env.example                  # configuration template
```

Design runs land in `output/<design>/` with:

```
config/<name>.json          # spec + the COMPLETE parameter table (see below)
config/<name>_history.jsonl  # every iteration's parameters + measured performance
netlist/<name>.sp           # SPICE netlist with ports
tb/<name>_tb.sp             # ngspice testbench (.measure + wrdata)
sim/                        # logs, wrdata exports, bode.png / tran.png
layout/<name>.py            # glayout generator: build(pdk) -> Component
layout/<name>.gds|.svg      # the layout + preview
layout/verify_<name>.json   # build + DRC + LVS machine-readable verdicts
```

### The config is the full parameter record (and the only tuning knob)

`config/<name>.json` holds a `params` block listing **every** component value with none
omitted — per MOSFET W/L/fingers/multipliers, every R/C/L, every bias current and
reference, the supply — plus the target `spec`. The netlist *and* the layout size
themselves from it, and every simulation appends `{parameters, measured metrics}` to
`config/<name>_history.jsonl`. So to hit a different spec you change these values and
re-run; the self-improve loop does exactly that automatically, and any past
parameter set (and the performance it produced) can be recalled and tuned from.

---

## How it works

**Circuit stage** — A deep agent (RLM-style: peek at slices, delegate sub-queries,
build up in files) recalls similar designs from the knowledge DB, researches the web
(SearXNG + crawl4ai) for reference **netlists** and **glayout code**, then writes the
config (full parameter table) and a ported SPICE netlist. A self-checking ngspice
testbench runs the chosen analyses (**DC / AC / TRAN**) and measures the spec table
(gain dB, bandwidth, UGBW, phase margin, power…). While any spec fails, the loop
mutates the config parameters (W/L/fingers, R, C, bias, compensation…), regenerates,
re-simulates — and stores each improvement as a lesson.

**Layout stage** — The spec-clean netlist is turned into a glayout generator script
sized from the config. Devices are generated bare (no tie/tap/dummy), placed with
`movex/movey/center`, and **every** connection is routed with
`c_route`/`L_route`/`straight_route`/`smart_route` + `via_stack`; every pin gets a
**port and a text label** (LVS matches by label). Capacitors use glayout's **mimcap**;
inductors — which glayout has no primitive for — come from `passives.py` (a sized
planar spiral, or the guidance to prefer a compact **gyrator-C active inductor**). The
harness writes the GDS and reference netlist, then runs **DRC (magic)** and
**LVS (netgen)**, headless. Failures loop back with parsed, actionable errors (e.g.
"net only in schematic → a route or a pin label is missing"). Once LVS/DRC are clean,
ties, guard rings and dummies are added and verification re-runs.

---

## Credits

AnoaChip is built on top of [GarudaChip](https://github.com/adeirman46/GarudaChip)
by Ade Irman. Analog layout backend by
[Glayout / OpenFASOC](https://github.com/idea-fasoc/OpenFASOC) (University of
Michigan). EDA tools: magic, netgen, ngspice, KLayout, gdsfactory.

## License

MIT — see [LICENSE](LICENSE).
