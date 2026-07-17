# ALIGN — SPICE netlist → GDS layout (sky130 + gf180)

Automatic analog place-&-route with [**ALIGN**](https://github.com/ALIGN-analoglayout/ALIGN-public):
give it a SPICE netlist, get a GDSII, rendered with the **KLayout** engine (clean distinct-color
theme + pin labels).

| notebook / file | what it does |
|---|---|
| [`sky130_examples.ipynb`](sky130_examples.ipynb) | 5 circuits → GDS → KLayout on the open **sky130** PDK |
| [`gf180_align.ipynb`](gf180_align.ipynb) | **every `examples/` topology** rewritten as gf180 → GDS → **gf180 DRC + LVS** → KLayout (`GF180_PDK`) |
| [`spice2gds.py`](spice2gds.py) | `spice2gds(design, netlist, pdk=...)` + `show_gds(gds)` |
| [`gf180_check.py`](gf180_check.py) | `gf180_drc(gds)` + `gf180_lvs(gds, netlist)` — **venv-only** (klayout module) |
| `pdks/GF180_PDK/` | GF180MCU PDK abstraction for ALIGN (committed) |

```python
import sys; sys.path.insert(0, ".")          # from notebooks/align
from spice2gds import spice2gds, show_gds
gds = spice2gds("five_transistor_ota", NETLIST, pdk="GF180_PDK")
show_gds(gds)                                 # clean KLayout render w/ pin labels
```

**gf180 DRC + LVS run in your venv** via [`gf180_check.py`](gf180_check.py) (the `klayout` Python
module — no Magic, no conda): `gf180_drc` checks width/space/enclosure against the real gf180 rules;
`gf180_lvs` extracts MOS devices (`klayout.db.LayoutToNetlist`) and compares to the netlist.

> ⚠️ The current `GF180_PDK` geometry is **sky130-scaled**, so `gf180_drc` reports violations — the
> layouts are **not gf180-DRC-clean yet**. Tapeout requires driving that count to **0** by tuning the
> `GF180_PDK` rule dimensions to gf180 minimums (the open follow-up). The local Magic 8.3.105 is too
> old for `gf180mcuD.tech` (segfaults), which is why DRC/LVS use the klayout module instead.

## ALIGN → gf180 (the extension)

ALIGN ships only a sky130 PDK. **`pdks/GF180_PDK`** extends it to GF180MCU: it reuses
ALIGN-pdk-sky130's (layers.json-driven) generators, remaps every layer to the **real GF180MCU GDS
number**, and takes geometry from the **real gf180 design rules** in your `gelochip`
`gf180_mapped_pdk` (`.layers`, `.get_grule`). It's committed (provenance in
[`pdks/GF180_PDK/README.md`](pdks/GF180_PDK/README.md)), so there's nothing to build.

Generator constraints (from ALIGN): device `W` must be a multiple of the PDK `Fin_pitch`, `NF` even,
models must be defined in the PDK (`pdks/GF180_PDK/models.sp`: sky130 names + `nfet_03v3`/`pfet_03v3`).

## Layout

```
notebooks/align/
├── sky130_examples.ipynb / gf180_align.ipynb   ← the notebooks
├── spice2gds.py            ← spice2gds() / show_gds()
├── src/align_flow.py       ← run_align() / view_klayout() / drc_report()
├── pdks/GF180_PDK/         ← GF180MCU ALIGN PDK            (committed)
├── setup_align.sh          ← one-time installer
├── _build_notebook.py      ← regenerates the .ipynb files
├── netlists/               ← .sp inputs (gallery/ = extra cells)        (tracked)
├── pdks/ (other) examples/ datasets/ runs/ .venv-align/                 (git-ignored)
```

## One-time setup

```bash
bash notebooks/align/setup_align.sh      # idempotent
```

Creates the isolated venv (`.venv-align` — ALIGN pins `pydantic<2`), builds ALIGN's C++ engine into
it, and extracts `pdks/` (mocks + `SKY130_PDK`), `examples/sky130/`, `datasets/`. `GF180_PDK` is
already committed.

## Rendering

`view_klayout` uses the `klayout` Python module with a **clean distinct-color theme** (saturated
color + hatch per layer on black — not the muddy PDK `.lyp`), crops ALIGN's outline marker, sizes
to the layout aspect, and overlays **pin/net labels** (VDD, VOUT, …) so pinouts are always visible.

## Gotchas

| symptom | cause / fix |
|---|---|
| **no GDS** | ALIGN's `--skipGDS` is `store_false` (default skips); the helpers always pass it. |
| `ALIGN exited 1` intermittently | routing is stochastic; `run_align` retries with escalating `nvariants`. Don't run two ALIGN jobs at once (contention). |
| `Width … multiple of fin pitch` | device `W` must be a multiple of the PDK `Fin_pitch`. |
| `Unmatched generator` | netlist uses a model the PDK doesn't define — use the PDK's models. |
