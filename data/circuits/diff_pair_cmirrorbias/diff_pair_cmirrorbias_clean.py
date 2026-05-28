from glayout.pdk.gf180_mapped import gf180_mapped_pdk as PDK
from glayout.primitives.fet import nmos
from glayout.routing.c_route import c_route
from glayout.routing.straight_route import straight_route
from glayout.util.comp_utils import evaluate_bbox
from gdsfactory.component import Component
# Differential pair (top row, M1/M2 sources tied = VTAIL) over a current-mirror
# tail bias (bottom row, M3 diode ref + M4 tail). VTAIL = M1/M2 sources = M4 drain.
top = Component(name="DP_CMBIAS")
m1 = nmos(PDK, width=4, fingers=2, length=0.5); m2 = nmos(PDK, width=4, fingers=2, length=0.5)
m3 = nmos(PDK, width=4, fingers=2, length=0.5); m4 = nmos(PDK, width=4, fingers=2, length=0.5)
r1 = top << m1; r2 = top << m2; r3 = top << m3; r4 = top << m4
bw, bh = evaluate_bbox(m1)
r2.movex(bw + 8.0)                       # diff pair: M1 | M2 (top row)
r3.movey(-(bh + 8.0))                    # mirror ref below M1
r4.movex(bw + 8.0); r4.movey(-(bh + 8.0))  # tail below M2
top << c_route(PDK, r1.ports["multiplier_0_source_S"], r2.ports["multiplier_0_source_S"])  # VTAIL tie (S, in gap)
top << c_route(PDK, r3.ports["multiplier_0_gate_S"], r4.ports["multiplier_0_gate_S"])       # mirror gate tie
top << straight_route(PDK, r4.ports["multiplier_0_drain_N"], r2.ports["multiplier_0_source_S"])  # tail->VTAIL
top << straight_route(PDK, r3.ports["multiplier_0_drain_W"], r3.ports["multiplier_0_gate_W"])    # diode ref
for i, r in enumerate((r1, r2, r3, r4)):
    top.add_ports(r.get_ports_list(), prefix=f"M{i+1}_")
component = top
