# ipynb → DRC-clean `_clean.py` tooling

Regenerates each `data/circuits/<name>/<name>_clean.py` from the **canonical layout
in that circuit's `.ipynb`** (so the GDS matches the notebook image) and only promotes
it when Magic DRC = 0 errors.

- `mkclean.py` — extracts the notebook build (cells[0:2]), neutralizes the
  `__main__` guard, strips drc/lvs/write_gds/show_gds, prepends a module-proxy
  header so gdsfactory `@cell`/pydantic can resolve annotations outside Jupyter,
  and applies the universal label-pin fix (0.27→0.30 µm met2, gf180 M2.1).
- `patches.py` — per-circuit *faithful* DRC-heal string patches (nudge a via,
  set a route to min width, add a c_route extension). Must preserve the canonical
  topology/appearance.
- `promote.py` — `python promote.py <name> [ncells] [--write]`: build + Magic DRC,
  and on 0 errors write `<name>_clean.py`, `<name>_preview.png`, `eval_result_clean.json`.

Run from repo root with the venv:
    .venv/bin/python scripts/ipynb_clean/promote.py fvf 2 --write

DONE (0 DRC, faithful to ipynb): current_mirror, diff_pair, transmission_gate, fvf, p_block.
Library fix applied: `cells/elementary/FVF/fvf.py` (via-spread + min-width tie route) —
cascades to lvcm/n_block/ota importers.
IN PROGRESS: low_voltage_cmirror (20→6, central met2 sliver remains).
TODO: n_block 57, diff_pair_stackedcmirror 23, opamp 176, dse 304, stacked 397,
row_cs 537, opamp_twostage 848; build-fragile ota / diff_pair_cmirrorbias.
