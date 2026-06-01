# Datasets

Circuit layout datasets used for retrieval/benchmarking. Each circuit is the **canonical
layout from its source notebook**, generated with GLayout on the **gf180** PDK and verified
with Magic DRC. **All 15 are now 0 DRC errors** (`eval_result_clean.json` per circuit).

## Verification Status — all DRC-clean ✅

| Circuit | DRC | DRC Errors | Area (µm²) |
|---------|-----|-----------|------------|
| current_mirror | ✅ pass | 0 | 300 |
| diff_pair | ✅ pass | 0 | 461 |
| transmission_gate | ✅ pass | 0 | 135 |
| fvf | ✅ pass | 0 | 573 |
| p_block | ✅ pass | 0 | 737 |
| low_voltage_cmirror | ✅ pass | 0 | 4 769 |
| differential_to_single_ended_converter | ✅ pass | 0 | 1 940 |
| diff_pair_stackedcmirror | ✅ pass | 0 | 7 075 |
| n_block | ✅ pass | 0 | 10 905 |
| opamp | ✅ pass | 0 | 82 786 |
| opamp_twostage | ✅ pass | 0 | 18 874 |
| row_csamplifier_dse | ✅ pass | 0 | 6 631 |
| stacked_current_mirror | ✅ pass | 0 | 417 |
| diff_pair_cmirrorbias | ✅ pass | 0 | 3 028 |
| ota | ✅ pass | 0 | 39 487 |

Areas are the bounding-box footprint of the current canonical layout. Last verified: 2026-05-31.

## Dataset Contents

Each circuit directory (`data/circuits/<name>/`) contains:

| File | Description |
|------|-------------|
| `<name>_clean.py` | the canonical, DRC-clean build (faithful to the `.ipynb`) |
| `<name>_preview.png` | layout thumbnail |
| `eval_result_clean.json` | DRC summary (`is_pass`, `total_errors`) + testbench metrics |
| `<name>.ipynb` | source generation notebook |

## Visual chain-of-thought dataset

`data/visual_dataset/dataset.jsonl` (+ `images/`) captures each of the 15 circuits as a
**step-by-step construction sequence** — every placement/route, with the layout re-rendered
after each step (893 steps total). This is collection 1 (`glayout_knowledge`) for the agent.

## Notes

- **All 15 are 0 DRC**, faithful to their source notebooks (not scattered re-implementations).
- LVS is **not run** in the clean-rebuild pipeline (it is geometry/DRC-focused); the SPICE
  netlist is best-effort and stubbed where the notebook's node-renaming is Jupyter-only (e.g. `ota`).
- The hardest fixes lived in the shared glayout library on gf180 (metal spacing, via enclosure,
  device legalization) — see the per-circuit `_clean.py` and the `scripts/ipynb_clean/` recipe.
