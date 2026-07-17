# GF180_PDK — GF180MCU PDK abstraction for ALIGN

Extends [ALIGN](https://github.com/ALIGN-analoglayout/ALIGN-public) (which ships only sky130) to
**GF180MCU**. Derived from [ALIGN-pdk-sky130](https://github.com/ALIGN-analoglayout/ALIGN-pdk-sky130)
(BSD-3, generators reused) by:

- remapping every layer to the real **GF180MCU GDS number**, and
- taking geometry from the real gf180 design rules in gelochip's `gf180_mapped_pdk`
  (`.layers`, `.get_grule`).

Use: `schematic2layout.py <netlist_dir> -p <this dir>` (device `W` must be a multiple of `Fin_pitch`).
**Run gf180 DRC + LVS sign-off before tapeout** (`gf180_mapped_pdk.drc_magic` / `.lvs_netgen`).
