# What "hierarchical GDS" means, and why Mitch asked for one

## A GDS file is a library of cells, not a picture

A GDSII file holds a set of **cells**. A cell contains two kinds of things:

1. **shapes** — polygons and text drawn directly in that cell, each on a layer;
2. **references (SREF/AREF)** — "place cell *X* here, with this translation / rotation /
   mirror", optionally as an array.

A cell that no other cell references is a **top cell**. Reading a GDS means picking the top
cell and walking its references down to the leaves.

## Flat vs hierarchical

**Flat**: one single cell containing every polygon of the design, with no references. The
picture is identical, but all structure is gone.

**Hierarchical**: a top cell that references sub-cells (`RECTIFIER`, `PUMP_LADDER`, a
`via_stack`, a `mimcap` unit …), which reference their own sub-cells, and so on.

```
FLAT                              HIERARCHICAL
D05_Gelochip                      D05_Gelochip
  └── 82 036 polygons               ├── D05_RFEH_CORE_FULL
      (no structure at all)         │     ├── D05_RECTIFIER
                                    │     │     └── D05_two_trans_interdigitized ×2
                                    │     ├── D05_STARTUP_BIAS
                                    │     ├── D05_PUMP_LADDER
                                    │     │     └── D05_NDIODE ×3
                                    │     ├── D05_LOAD_DIODE
                                    │     ├── D05_mimcap_array ×5
                                    │     └── D05_tapring
                                    ├── D05_via_array   ×10   (referenced, not copied)
                                    └── boundary + router shapes
                                  1 top + 180 sub-cells
```

## Why it matters for a shared shuttle

* **File size and tool memory.** A `via_array` used 400 times is stored *once* and
  referenced 400 times. This design's 22 pF storage bank alone is ~34 700 via cuts; flat,
  every cut is written out again for every instance.
* **Reviewability.** The integrator can open the top cell, see five named blocks, and check
  that the floorplan matches the schematic. In a flat file there is nothing to look at but
  a soup of polygons.
* **Hierarchical LVS and extraction.** netgen and magic can compare or extract cell-by-cell
  and reuse the result for every instance. On a flat cell they must redo everything.
* **Debug.** A DRC error reported as "in cell `D05_PUMP_LADDER`, instance 2" is actionable.
  "at (x, y) in the flat top cell" is not.
* **Merging the shuttle.** The integrator merges ~20 projects into one reticle. If two
  projects both ship a cell called `nmos`, one silently overwrites the other and a block is
  quietly replaced by someone else's layout. This is why every sub-cell here is prefixed
  `D05_`.

## Why the previously shipped file was flat

`harvester_top_full.gds` had **exactly one cell**, `rf_energy_harvester$1`, with 82 036
polygons. That was not intentional — it came from GLayout's
`component_snap_to_grid()`, whose own docstring says:

```python
def component_snap_to_grid(comp: Component) -> Component:
    """snaps all polygons and ports in component to grid
    NOTE this function will flatten the component"""
    name = comp.name
    comp = comp.flatten().copy()      # <-- flattens the whole hierarchy
    comp.name = name
    return comp
```

`harvester_top()` calls it on the very last line. The `$1` suffix is the other half of the
same accident: `flatten()` registers a *new* component that wants the name
`rf_energy_harvester`, gdsfactory sees the name is taken and de-duplicates it to
`rf_energy_harvester$1`.

A `$` in a cell name is actively dangerous downstream — the notebook's own PEX recipe
contains `gds flatglob *\$\$*`, i.e. "flatten anything with a `$` in its name", so a tool
reading the shipped file may silently flatten or drop cells.

## What is shipped now

`component_snap_to_grid` is skipped at the top level (the GDS writer already quantises every
coordinate to the 5 nm database grid, so nothing is lost), and the result is post-processed
in KLayout to:

* set the top cell to exactly `D05_Gelochip`;
* rename every sub-cell to `D05_<name>`, replacing any character outside `[A-Za-z0-9_]`
  (so no `$` survives) and de-duplicating collisions;

giving **1 top cell + 180 sub-cells**, verified by the GDS audit.
