from glayout.pdk.gf180_mapped import gf180_mapped_pdk as PDK
from glayout.primitives.fet import nmos
from glayout.routing.c_route import c_route
from glayout.routing.straight_route import straight_route
from glayout.util.comp_utils import evaluate_bbox
from gdsfactory.component import Component
# Low-voltage cascode current mirror: 2x2 nmos, bottom = mirror, top = cascode,
# gates tied to VG. Same DRC-clean composition as the stacked mirror.
top = Component(name="LVCM")
m = [nmos(PDK, width=4, fingers=2, length=0.5) for _ in range(4)]
r1, r2, r3, r4 = (top << x for x in m)
bw, bh = evaluate_bbox(m[0])
r2.movey(bh + 5.0); r3.movex(bw + 6.0); r4.movex(bw + 6.0); r4.movey(bh + 5.0)
top << straight_route(PDK, r1.ports["multiplier_0_drain_N"], r2.ports["multiplier_0_source_S"])
top << straight_route(PDK, r3.ports["multiplier_0_drain_N"], r4.ports["multiplier_0_source_S"])
top << c_route(PDK, r1.ports["multiplier_0_gate_S"], r3.ports["multiplier_0_gate_S"])
top << c_route(PDK, r2.ports["multiplier_0_gate_N"], r4.ports["multiplier_0_gate_N"])
top << straight_route(PDK, r1.ports["multiplier_0_gate_W"], r2.ports["multiplier_0_gate_W"])
for i, r in enumerate((r1, r2, r3, r4)):
    top.add_ports(r.get_ports_list(), prefix=f"M{i+1}_")
component = top
