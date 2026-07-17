"""spice2gds — SPICE netlist -> GDS (via ALIGN) + a KLayout viewer.

Importable module:

    from spice2gds import spice2gds, show_gds
    gds = spice2gds("five_transistor_ota", NETLIST)   # SPICE string -> GDS (Path)
    show_gds(gds)                                      # render it with the KLayout engine

`spice2gds()` runs ALIGN's place-&-route. PDKs:
  * "SKY130_PDK"  — open-source sky130 (ALIGN-pdk-sky130). The default.
  * "GF180_PDK"   — GF180MCU (committed in pdks/GF180_PDK): real GF180MCU layer numbers + design
                    rules from gelochip's gf180_mapped_pdk; gf180 models nfet_03v3/pfet_03v3.
                    See gf180_align.ipynb.

As with any layout, run gf180/sky130 DRC + LVS sign-off (gf180_mapped_pdk.drc_magic / .lvs_netgen)
before tapeout.

`show_gds(gds, colors=...)` renders any GDS with the KLayout engine ("sky130" / "gf180" / .lyp path).
"""
import sys
from pathlib import Path

# make src/align_flow importable regardless of caller cwd
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from align_flow import (  # noqa: E402
    run_align, view_klayout, drc_report,
    PDKS, available_pdks, example_netlist,
)


def spice2gds(design, netlist, pdk="SKY130_PDK", nvariants=4, drc=True):
    """Place & route a SPICE netlist into a GDS and return its path.

    design   : top sub-circuit name (must match the `.subckt` in `netlist`)
    netlist  : SPICE netlist as a string
    pdk      : ALIGN PDK name (default sky130); `available_pdks()` lists the rest
    nvariants: layout candidates to attempt (retried with more on failure)
    drc      : print ALIGN's built-in DRC / connectivity check
    """
    gds = run_align(design, netlist, pdk=pdk, nvariants=nvariants, verbose=False)[0]
    if drc:
        drc_report(gds)
    return gds


def show_gds(gds, colors="sky130"):
    """Render a GDS with the KLayout engine (returns an inline IPython.Image).

    colors: "sky130" / "gf180" (PDK layer colors), an explicit .lyp path, or None.
    """
    return view_klayout(gds, colors=colors)


__all__ = ["spice2gds", "show_gds", "available_pdks", "example_netlist", "PDKS"]
