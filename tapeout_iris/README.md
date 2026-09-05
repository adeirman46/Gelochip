# D05 — IRIS RF Energy Harvester, tapeout package

GF180MCU, Chipathon 2026 project slot **D05**, variant **EH** (west-edge pins, no Metal2
corner keep-out). Everything needed to review or submit the design is in this folder.

## Submit this

| | |
|---|---|
| **GDS** | `gds/D05_Gelochip.gds` |
| **Top cell** | `D05_Gelochip` |
| **Area** | exactly 550 × 550 µm, bbox (0,0)–(550,550) |
| **Hierarchy** | 163 cells, every sub-cell prefixed `D05_`, no `$` in any name |

`gds/D05_Gelochip_nofill.gds` and `gds/D05_Gelochip_FET.gds` are **review aids only** — the
first fails metal density (it is the pre-fill topology, easier to read the routing from), the
second has no capacitors and exists so LVS and PEX can run.

## Contents

```
gds/       D05_Gelochip.gds          <- THE TAPEOUT FILE (with dummy fill)
           D05_Gelochip_nofill.gds   <- same topology, no fill (review)
           D05_Gelochip_FET.gds      <- capacitor-free view (LVS / PEX)
netlist/   D05_Gelochip_source.spice        LVS source netlist
           D05_Gelochip_FET_source.spice    LVS source, FET view
           RFEH_PEX_pex.spice               extracted netlist (2293 R, 439 C)
doc/       D05_module_and_rule_report.pdf   modules, rules, pass/fail, outputs
           D05_module_and_rule_report.tex   LaTeX source
           info.yaml                        project metadata + verification record
           lvs_config.json                  LVS configuration
           ISSUE_BODY.md                    text for the submission issue
           IO_AND_POWER.md                  pin table and VDD/VSS routing
           HIERARCHICAL_GDS.md              what hierarchical GDS means and why
img/       all figures (matplotlib + KLayout renders)
src/       the Python modules that build and verify the design
logs/      LVS logs, per-IP validation, flow report
D05.def.tgz                                 the organiser's slot definition
GLayout_RF_EnergyHarvester_Complete.ipynb   the full notebook
```

## Pins

Five pins, all Metal2 on the **west** edge of the slot at x = 0…1 µm.

| Pin | Pad | Cell | Type | Landing y (µm) | Internal net |
|---|---|---|---|---|---|
| `VSS`  | W12 | `dvss`     | ground | 6.36 – 78.64    | VSS |
| `RFP`  | W13 | `asig_5p0` | signal | 120.34 – 164.66 | RFP |
| `RFN`  | W14 | `asig_5p0` | signal | 220.34 – 264.66 | RFN |
| `VOUT` | W15 | `asig_5p0` | signal | 320.34 – 364.66 | VOUT |
| `VCC`  | W16 | `dvdd`     | power  | 406.36 – 478.64 | **VRECT** |

`VMID1`, `VMID2`, `N1`, `N2` are labelled for probing but are not bonded out.

`VCC` carries the harvester's own rectified rail, so the block powers its own padring segment:
only 25 cells take `.DVDD(W16)` — our five pads plus their fillers — while the other 517 sit on
`FLOAT_VDD_1`. The RFP/RFN/VOUT pads reference `VCC` for ESD; see `doc/IO_AND_POWER.md`.

## Verification status

| Check | Result |
|---|---|
| Foundry KLayout deck, `--variant=D --density --antenna` | **0 flagged items** |
| — MIM rules actually ran | log: `MIM Option selected: B`, `fusetop has 34 polygons` |
| netgen LVS, exact file and top cell | **circuits match uniquely**, 9 ports |
| Per-module DRC + LVS (9 modules) | all clean |
| Split nets | 9 names → 9 nets, one name each |
| Dangling metal | 0.00 µm² |
| Capacitors | 34 FuseTop plates, 23.007 pF, all on their intended net pairs |
| Metal / poly density | 42.8–45.9 % metal, 43.2 % poly (floor 30 % / 14 %) |
| Metal2 corner keep-out | none issued for EH; a D build is clear on both |
| Post-layout | VRECT 0.817 V, VOUT 1.578 V; sensitivity +3.7 dBm unmatched / −7.2 dBm matched |

DRC is the **foundry KLayout deck**, not magic — magic's `gf180mcuD` tech has no MIM device and
a much thinner rule set, which is what let the previous shorted capacitors pass.

## Two open questions for the organisers

1. **Process variant.** The capacitors are **MIM-B** (Metal4 bottom plate, FuseTop top plate,
   Via4, both terminals on Metal5) because `run_drc.py`'s variant table offers the Metal2/Metal3
   MIM only for 3LM and 6LM, while this is a 5LM stack (variants C and D, both `mim_option=B`).
   Please confirm the shuttle runs a 5LM variant with the MIM module enabled.
2. **Dummy fill.** We added our own fill inside the slot, honouring the Metal2 corner keep-outs
   and the pin landings. If the integrator fills the whole reticle instead, say so and we will
   ship without it.

## Reproducing

Requires the `glayout_env` conda environment with `PYTHONPATH=<repo>/src`, `PDK_ROOT` set to
the volare gf180mcu tree, and — for the ngspice parts — the PandaChip container running
(`docker start pandachip-eda`), because the system ngspice-36 lacks `mulu0` and cannot run the
gf180 BSIM4 cards.

```
python src/run_tapeout_v2.py     # build core -> slot routing -> fill -> LVS
python src/validate_ips.py       # per-module DRC + LVS
python src/dangling_check.py     # split nets and dangling metal
python src/cap_net_check.py      # every capacitor on its intended nets
python src/padring_check.py      # padring handover + route widths
```
