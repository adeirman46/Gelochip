# Datasets

Circuit layout datasets used for fine-tuning and benchmarking. Each circuit is generated with GLayout on the **gf180** PDK and verified with Magic (DRC) + Netgen (LVS).

## Verification Status

| Circuit | DRC | DRC Errors | LVS | Area (µm²) | H-Symmetry |
|---------|-----|-----------|-----|------------|------------|
| current_mirror | ✅ pass | 0 | ✅ pass | 1 026 | 1.000 |
| diff_pair | ✅ pass | 0 | ✅ pass | 1 430 | 1.000 |
| transmission_gate | ⚠️ fail | 2 | ✅ pass | 359 | 1.000 |
| low_voltage_cmirror | ⚠️ fail | 12 | ✅ pass | 4 119 | 0.976 |
| p_block | ✅ pass | 0 | ⚠️ fail | 2 797 | 1.000 |
| opamp_twostage | ✅ pass | 0 | ⚠️ fail | 40 230 | 0.926 |
| diff_pair_stackedcmirror | ✅ pass | 0 | ⚠️ fail | 23 434 | 0.997 |
| row_csamplifier_dse | ✅ pass | 0 | ⚠️ fail | 20 848 | 1.000 |
| fvf | ⚠️ fail | 3 | ⚠️ fail | 1 250 | 0.692 |
| diff_pair_cmirrorbias | ⚠️ fail | 5 | ⚠️ fail | 8 810 | 0.999 |
| n_block | ⚠️ fail | 29 | ⚠️ fail | 9 228 | 0.986 |
| ota | ⚠️ fail | 53 | ⚠️ fail | 19 242 | 0.908 |
| opamp | ⚠️ fail | 111 | ⚠️ fail | 137 897 | 0.963 |
| stacked_current_mirror | ⚠️ fail | 193 | ⚠️ fail | 1 012 | 1.000 |
| differential_to_single_ended_converter | ⚠️ fail | 165 | ⚠️ fail | 3 071 | 0.945 |

Last verified: 2026-05-18.

## Dataset Contents

Each circuit directory (`data/circuits/<name>/`) contains:

| File | Description |
|------|-------------|
| `*.gds` | GDS layout file |
| `*_preview.png` | Layout thumbnail |
| `eval_result.json` | Full DRC/LVS/PEX/geometric metrics |
| `*.ipynb` | Generation notebook |
| `*_pex.spice` | Post-extraction SPICE netlist (where available) |

## Notes

- **DRC clean**: `current_mirror`, `diff_pair`, `opamp_twostage`, `diff_pair_stackedcmirror`, `row_csamplifier_dse`, `p_block`
- **Full pass (DRC + LVS)**: `current_mirror`, `diff_pair`
- **LVS failures** on most circuits are due to unmatched subcircuit ports from the GLayout hierarchical netlisting — a known issue tracked in the universal corrector pipeline
- PEX (parasitic extraction) available for `n_block` and `ota` only
- For fine-tuning notebooks see `notebooks/gelo_dataset_optimized/`
