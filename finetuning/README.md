# Gelochip — RF-Expert Qwen Post-Training

Post-train Qwen to be a world-class RF chip / antenna / satellite IC designer.

> **Separate from** `src/gelochip/agent/finetuning/` which fine-tunes CodeLlama on code-fix tasks.
> This folder focuses on injecting **RF domain knowledge** into Qwen via LoRA + PINN.

## Why post-training (not pre-training)?
Qwen already understands language and general science. We only need to inject
RF domain expertise via Supervised Fine-Tuning (SFT) + LoRA. This is 100×
cheaper and reaches expert-level performance faster than pre-training from scratch.

## Pipeline overview

```
Raw Sources            Data Prep               Fine-Tuning            Eval
────────────────       ──────────────────────  ──────────────────     ──────────────────
RF Books (PDF)    →    01_pdf_extract §1-2     03_qwen_sft_lora  →    06_rf_benchmark
arXiv Papers      →    01_pdf_extract §2       04_dpo_refine     →    06_rf_benchmark
GLayout Code      →    01_pdf_extract §3            │
AICircuit Dataset →    01_pdf_extract §5  ──→  02_dataset_build §3 ──┘
Chipster (PySpice)→    01_pdf_extract §7  ──→  02_dataset_build §8
AnalogCoder AAAI  →    01_pdf_extract §7  ──→  02_dataset_build §8
HuggingFace EE DS →    02_dataset_build §4
Synthetic RF QA   →    02_dataset_build §5     PINN (runs parallel)
Antenna Sim Data  →    02_dataset_build §7  →  05_pinn_maxwell   →    07_pinn_verify
```

## Analog PySpice Sources

| Source | Repo | Type | Circuits |
|--------|------|------|----------|
| **Chipster** | `adeirman46/chipster` | Your own PySpice generator + notebooks | Analog blocks, standard cells |
| **AnalogCoder** | `laiyao1/AnalogCoder` | AAAI 2025 Oral benchmark | 24 problems: opamp, oscillator, PLL, VCO, current mirror, inverter, diff pair… |

Both are extracted in `01_pdf_extract.ipynb §7` → `data/raw/analog_pyspice/`:
- `corpus.py` — all PySpice code concatenated (pre-training)
- `sft_pairs.jsonl` — instruction → PySpice code pairs (SFT)

Then merged into `data/processed/sft_rf_domain.jsonl` by `02_dataset_build.ipynb §8`.

## Folder structure

```
finetuning/
├── data_prep/          # Notebooks: collect sources, build SFT/PINN datasets
├── sft/                # Notebooks: LoRA fine-tune Qwen, DPO preference tuning
├── pinn/               # Notebooks: Physics-Informed NN for Maxwell/EM simulation
├── eval/               # Notebooks: RF design Q&A benchmark + PINN accuracy metrics
└── data/
    ├── raw/            # PDFs, repos, GDS files (gitignored — download locally)
    ├── processed/      # Cleaned JSONL ready for training
    └── synthetic/      # LLM-generated synthetic RF Q&A pairs
```

## Quick start

```bash
# 1. Collect all data sources
jupyter notebook finetuning/data_prep/01_pdf_extract.ipynb

# 2. Build SFT + PINN datasets
jupyter notebook finetuning/data_prep/02_dataset_build.ipynb

# 3. Fine-tune Qwen with LoRA/QLoRA (needs GPU)
jupyter notebook finetuning/sft/03_qwen_sft_lora.ipynb

# 4. (Optional) DPO preference refinement
jupyter notebook finetuning/sft/04_dpo_refine.ipynb

# 5. Train PINN EM solver (can run in parallel with step 3)
jupyter notebook finetuning/pinn/05_pinn_maxwell.ipynb

# 6. Evaluate
jupyter notebook finetuning/eval/06_rf_benchmark.ipynb
jupyter notebook finetuning/eval/07_pinn_verify.ipynb
```

## Key data sources (verified open-access)

| Source | Type | URL |
|--------|------|-----|
| Steer RF Design (5 vols) | Textbook | https://www.lib.ncsu.edu/projects/microwave-and-rf-design-open-textbook |
| AICircuit (NeurIPS 2024) | Circuit dataset | https://github.com/AvestimehrResearchGroup/AICircuit |
| Mendeley Antenna Dataset | EM sim (55K) | https://data.mendeley.com/datasets/3gxr2vvd9n/2 |
| ReaLLMASIC/gLayout | Layout code | https://github.com/ReaLLMASIC/gLayout |
| OpenFASOC | Layout code | https://github.com/idea-fasoc/OpenFASOC |
| ALIGN (DARPA) | Layout code | https://github.com/ALIGN-analoglayout/ALIGN-public |
| gLayout-IHP130 (BiCMOS) | Layout code | https://github.com/amisapta15/gLayout-IHP130 |
| EEE-Bench (2860 Q&A) | HuggingFace | https://huggingface.co/datasets/afdsafas/EEE-Bench |
| STEM-AI EE Q&A | HuggingFace | https://huggingface.co/datasets/STEM-AI-mtl/Electrical-engineering |
| Ka-band CMOS 256-elem (ISSCC 2025) | Paper | https://ieeexplore.ieee.org/document/10904607 |
| PMC Ka-band beamforming | Paper (CC BY) | https://pmc.ncbi.nlm.nih.gov/articles/PMC12349506 |
