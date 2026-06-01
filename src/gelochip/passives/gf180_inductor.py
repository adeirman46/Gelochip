"""gf180 RF passives via RapidPassives — spiral inductors / transformers on the
gf180 top-metal stack (windings on met5, underpass/crossings on met4, vias on
via4, patterned ground shield on met1). Exports DRC-targeted GDS."""
from pathlib import Path
from .rapidpassives.stack import ProcessStack, StackLayer
from .rapidpassives import build_spiral_inductor, build_symmetric_inductor, to_gds


def gf180_stack() -> ProcessStack:
    """gf180 inductor stack: thick met5 windings, met4 underpass, via4, met1 PGS."""
    return ProcessStack(name="gf180", layers=(
        StackLayer(id="34_0", type="metal", z=0.0, thickness=0.53,           # met1 (PGS)
                   gds_layers=("pgs",)),
        StackLayer(id="40_0", type="via",   z=2.0, thickness=0.50,           # via3
                   gds_layers=("vias2",)),
        StackLayer(id="46_0", type="metal", z=2.5, thickness=0.90,           # met4 (underpass)
                   gds_layers=("crossings", "windings_m2", "crossings_m1",
                               "guard_ring", "centertap")),
        StackLayer(id="41_0", type="via",   z=3.4, thickness=0.50,           # via4
                   gds_layers=("vias", "vias1")),
        StackLayer(id="81_0", type="metal", z=3.9, thickness=2.80,           # met5 (windings)
                   gds_layers=("windings",)),
    ))


def spiral(out_gds: str, Dout=160.0, N=3, width=9.0, spacing=4.0, sides=8) -> dict:
    res = build_spiral_inductor({"Dout": Dout, "N": N, "sides": sides, "width": width,
                                 "spacing": spacing, "via_spacing": 1.0, "via_width": 1.0,
                                 "via_in_metal": 0.4})
    to_gds(res, gf180_stack(), out_gds, cell_name="GF180_SPIRAL_IND")
    return {"Dout": Dout, "N": N, "width": width, "spacing": spacing, "gds": out_gds}
