# D05 — Gelochip RF Energy Harvester (GF180MCU)

Differential RF energy harvester: cross-coupled rectifier + injection-assisted startup bias
+ 3-stage Dickson charge pump + MOS-diode load.

## Slot and database

| | |
|---|---|
| Slot / variant | **D05 / EH** (west-edge pins, no Metal2 corner obstruction) |
| Slot origin on chip | (350, 1475) µm |
| Project area | **550 × 550 µm** |
| GDS file | **`gds/D05_Gelochip.gds`** |
| Top cell | **`D05_Gelochip`** |
| Hierarchy | hierarchical — 1 top cell + 180 sub-cells, every sub-cell prefixed `D05_` |
| Boundary marker | layer 0/0 rectangle at exactly (0,0)–(550,550) |
| Core size / placement | 287.07 × 290.71 µm, centred (≈131.5 µm E/W, ≈129.6 µm N/S margins) |

A **D**-variant build was also produced and checked against D's own keep-outs
`(529,548)-(550,550)` and `(0,0)-(2,21)` — **both CLEAR, 0.0000 µm²** — so the project can move
to slot D without re-verification (the GDS must be rebuilt for the chosen variant, since the
Metal2 landings follow that variant's pin plan).

## Pin plan

Five pins, all Metal2 on the west edge at x = 0…1 µm.

| Pin | Pad | Cell | Use | Landing y (µm) | Internal net |
|---|---|---|---|---|---|
| `VSS`  | W12 | `gf180mcu_fd_io__dvss`     | GROUND | 6.36 – 78.64   | VSS |
| `RFP`  | W13 | `gf180mcu_fd_io__asig_5p0` | SIGNAL | 120.34 – 164.66 | RFP |
| `RFN`  | W14 | `gf180mcu_fd_io__asig_5p0` | SIGNAL | 220.34 – 264.66 | RFN |
| `VOUT` | W15 | `gf180mcu_fd_io__asig_5p0` | SIGNAL | 320.34 – 364.66 | VOUT |
| `VCC`  | W16 | `gf180mcu_fd_io__dvdd`     | POWER  | 406.36 – 478.64 | **VRECT** |

`VCC` carries the harvester's own rectified rail, so the block powers its own pad-ring
segment: only 25 cells take `.DVDD(W16)` — our five pads plus their fillers — while the other
517 sit on `FLOAT_VDD_1`, confirming the `BRK_BEFORE_EH` / `BRK_AFTER_EH` cut is real. The
RFP/RFN/VOUT pads do reference `VCC` for ESD. `VMID1`, `VMID2`, `N1`, `N2` stay
internal. Details in `IO_AND_POWER.md`.

## Verification (on the exact submitted file and top cell)

| Check | Result |
|---|---|
| GF180 KLayout sign-off deck, `--variant=D` (5LM, `mim_option=B`), `--density --antenna` | **0 flagged items** |
| — MIM rules actually ran? | log: `MIM Option selected: B`, `fusetop has 34 polygons` |
| netgen LVS | **Circuits match uniquely**, all nine labelled ports |
| Per-IP (9 blocks, each individually) | foundry DRC clean; LVS match, or plate separation for caps |
| Capacitors | 34 FuseTop plates, 23.007 pF; **every plate pair a distinct net** |
| Net separation | 9 labelled core nets → 9 distinct; all 5 slot pins reach their core rail |
| Metal / poly density | met1 43.2 %, met2 43.7 %, met3 42.8 %, met4 45.6 %, met5 45.9 %, poly 43.2 % (floor 30 % / 14 %) |
| Metal2 corner obstruction | EH: none issued. D: both keep-outs clear on a D build |
| GDS audit | 1 top + 162 sub-cells, no `$`, bbox exactly (0,0)–(550,550), 0/0 boundary present |

## Two questions for the organisers

1. **Process variant.** The capacitors are drawn as **MIM-B** — Metal4 bottom plate, **FuseTop**
   top plate, Via4, both terminals on Metal5 — because `run_drc.py`'s variant table offers
   `mim_option=A` (the met2/met3 MIM) only for 3LM and 6LM, while this is a 5LM stack (variants
   C and D, both `mim_option=B`). Please confirm the shuttle runs a 5LM variant with the MIM
   module enabled. If the metal count differs, the capacitors move to a different metal pair and
   the floorplan moves with them.
2. **Dummy fill.** We have added our own fill inside the slot (honouring the Metal2 corner
   keep-outs and the pin landings). If the integrator fills the whole reticle instead, say so and
   we will ship without it.

## Fixed in this revision

* **MIM plate short** — `cap_block()` placed the bottom-plate `via_stack` at `by + 0.5` µm,
  but the Metal2 bottom plate overhangs the Metal3 top plate by only 0.6 µm (`met2/capmet
  min_enclosure`), so the via's met3 pad landed *on* the top plate. Every capacitor had its
  plates welded together, every bottom plate floated, and the storage cap dragged VOUT onto
  the VSS rail. The bottom plate now escapes on Metal2 and steps up to Metal3 only once it is
  a full `met3 min_separation` clear of the top plate.
* **Flat GDS** — the previous file was a single flat cell `rf_energy_harvester$1`
  (`component_snap_to_grid()` flattens). Now hierarchical and cleanly named.
* **No boundary pins** — the core's five met4 rail pads sat 137 µm inside the slot on the
  wrong layer; nothing reached the padring's Metal2 handover. Added a met4/met3 boundary
  router with Metal2 landings, pin shapes and labels.
