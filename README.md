# Gelochip

**Describe an analog/RF circuit in plain English → get a DRC-clean gf180 GDSII layout.**
A local, self-correcting RAG agent (no cloud, no fine-tuning) that designs, verifies
(Magic DRC + AC/transient vs. theory), and learns from every run.

![Gelochip Kaizen](docs/img/kaizen_showcase.png)

> Inspired by [Chipster](https://github.com/adeirman46/Chipster) (digital flow via OpenLane) — Gelochip is its analog/RF counterpart.

---

## ▶ Run an app

```bash
git clone https://github.com/adeirman46/Gelochip.git && cd Gelochip
./scripts/run.sh                 # Gelochip Studio  → http://localhost:8090
```

`run.sh` sets up the `.venv` (via `uv`), pulls the local model, and launches.
Pick any of the three apps (optionally pass a port):

| Command | App | Port | What it is |
|---|---|---|---|
| `./scripts/run.sh kaizen`  | **Gelochip Studio** | 8090 | RAG agent · IP library · padframe · pin-connect *(default)* |
| `./scripts/run.sh pixelrf` | **PixelatedRF Designer** | 8001 | Draw an S₁₁ target → inverse-designed GDS layout |
| `./scripts/run.sh web`     | Legacy LangGraph UI | 8080 | Original spec→layout pipeline |

**Requirements:** `ollama` (`ollama pull qwen3.5:9b` — auto-pulled by the script) ·
`magic`, `netgen`, `ngspice` + `PDK_ROOT` → gf180 PDK · `numpy<2.0` (gdsfactory<8 needs it).

### Large assets (download)

Model weights (`models/pixelatedrf/`) and EM datasets (`data/pixelatedrf/`) are **not
in git** (kept under GitHub's file-size limit). The **Kaizen Studio** app needs none of
them — it auto-builds its ChromaDB from the in-repo datasets. Only the **PixelatedRF**
app/notebooks need them:

```bash
# 1. set your Drive link in scripts/fetch_assets.sh   2. run:
./scripts/fetch_assets.sh
```

> Drive link: _TODO — add your Google Drive share link in `scripts/fetch_assets.sh`._

**Where each file goes** (download from Drive, then place exactly here):

| File | Put in | Used by |
|---|---|---|
| `forward_model.pt` | `models/pixelatedrf/` | PixelatedRF forward surrogate |
| `inverse_model.pt` | `models/pixelatedrf/` | PixelatedRF inverse (MCL) net |
| `forward_model_resume.pt`, `inverse_resume.pt`, `_resume.pt` | `models/pixelatedrf/` | training resume (optional) |
| `antenna_dataset.mat` | `data/pixelatedrf/` | raw EM dataset (notebook 01) |
| `data_split.npz` | `data/pixelatedrf/` | train/val/test split (notebooks 02–04) |
| `y_norm_stats.npz` | `data/pixelatedrf/` | S₁₁ normalisation stats |

The `drc_corrector_ppo.pt` (layoutRL) is small and ships in git at `models/layoutrl/`.

---

## Gelochip Studio (the main app)

A self-correcting **Retrieval-Augmented Generation** agent. A local `qwen3.5:9b`
(Ollama) is grounded on **three local ChromaDB collections** and corrects itself
against real Magic DRC + ngspice — corrections are injected as in-context feedback,
never gradients. The 3 collections **auto-build on first launch** (instant after that).

| # | Collection | Contents |
|---|---|---|
| 1 | `glayout_knowledge` | glayout layout/code knowledge + 15 DRC-clean circuit blocks |
| 2 | `rf_theory` | RF/mmWave books, papers, EE-QA, PySpice corpus |
| 3 | `error_feedback` | error→fix memory (starts empty, grows at runtime) |

**Four tools** in the web UI:
1. **Prompt → GDSII (RF)** — live `plan → research → retrieve → generate → DRC → fix → persist`
   with GDS preview, extracted SPICE, AC/transient plots, and code. A **Researcher** agent
   (arXiv / web / GitHub via crawl4ai → temporary RAG) and the retrieved knowledge are shown
   in a **Knowledge & Research** panel so you can verify the agent's sources *before* it
   generates. On a DRC-clean result the research + verified code are persisted into ChromaDB.
   A **left history sidebar** saves every run — click to restore its full state.
2. **IP Library** — 15 DRC-clean blocks (with real µm² area), drag-n-drop onto the chip.
3. **Padframe** — gf180 pad ring (sscs-chipathon-2025 / caravel-gf180mcu compatible).
4. **Pin-Connect agent** — proposes pin↔pin nets + pinout names, draws the wires.

The [architecture notebook](notebooks/kaizen_architecture/) is the spec the web app
follows. All 15 circuits in `data/circuits/` are **DRC-clean + theory-verified**:

| class | circuits | theory check |
|---|---|---|
| switch | transmission_gate | ~0 dB pass-through |
| follower | fvf, n_block, p_block | gain ≈ unity |
| current mirror | current_mirror, stacked_current_mirror, low_voltage_cmirror | DC copy ratio |
| amplifier | diff_pair, diff_pair_cmirrorbias, ota, opamp, differential_to_single_ended_converter, diff_pair_stackedcmirror, row_csamplifier | DC gain / GBW |
| 2-stage | opamp_twostage | ~43 dB (> single stage) |

---

## Repository layout

```
Gelochip/
├── data/                  # all datasets
│   ├── circuits/          #   15 DRC-clean circuit blocks (IP library)
│   ├── glayout_code/      #   human→glayout-code JSONL  (collection 1)
│   ├── rf_theory/         #   RF/mmWave corpus           (collection 2)
│   └── pixelatedrf/       #   antenna_dataset.mat, data_split.npz
├── models/                # all model weights
│   ├── pixelatedrf/       #   forward / inverse EM models
│   └── layoutrl/          #   DRC-corrector PPO policy
├── src/gelochip/
│   ├── kaizen/            # RAG agent: config, collections, executor, testbench, agent, studio
│   ├── pixelrf/           # PixelatedRF inverse-design app + inference
│   ├── glayout/  gl/  verification/   # gdsfactory layout + DRC/LVS/PEX
├── app/                   # kaizen_app.py (Studio) · web_app.py · mcp_server.py · static/
├── scripts/               # run.sh (launcher) · kaizen_ingest.py · build_clean_datasets.py · …
├── notebooks/             # kaizen_architecture/ · pixelatedRF/ · …
└── docs/
```

---

## More

<details>
<summary>Python API · building blocks · MCP server</summary>

```python
# Build a block directly
from gelochip.glayout.pdk.gf180_mapped import gf180_mapped_pdk as pdk
from gelochip.core.cells import lna_cascode
lna_cascode(pdk, gm_width=40.0, gm_fingers=10, cas_width=40.0, cas_fingers=10).write_gds("lna.gds")
```

```bash
# MCP server for Claude Desktop
uv run python app/mcp_server.py
```

**Verification flow:** code exec → DRC (Magic) → LVS (Netgen) → PEX + SPICE (ngspice).
Missing tools are skipped gracefully; fastest setup is [IIC-OSIC-TOOLS Docker](https://github.com/iic-jku/iic-osic-tools).

**PixelatedRF:** retrain in `notebooks/pixelatedRF/02_train.ipynb` (needs `data/pixelatedrf/data_split.npz` from `01_dataset.ipynb`); weights in `models/pixelatedrf/`.

</details>

---

## Documentation

- [Kaizen architecture](notebooks/kaizen_architecture/README.md) — the RAG agent, collections, 15 circuits
- [Installation](docs/installation.md) · [Architecture](docs/architecture.md) · [PixelatedRF](docs/pixelated-rf.md) · [Datasets](docs/datasets.md)

## License

MIT — see [LICENSE](LICENSE).
