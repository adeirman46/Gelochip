from glayout.pdk.gf180_mapped import gf180_mapped_pdk as PDK
from glayout.primitives.fet import nmos
from glayout.routing.c_route import c_route
from glayout.routing.straight_route import straight_route
from glayout.util.comp_utils import evaluate_bbox
from gdsfactory.component import Component
# Cascode (stacked) current mirror from 4 DRC-clean nmos in a 2x2 grid. Bottom
# row = mirror devices, top row = cascode devices; all gates tied to VG. Vertical
# = straight_route (stack drain_N->source_S, gate_W<->gate_W); horizontal = c_route.
top = Component(name="STACKED_CM")
m = [nmos(PDK, width=4, fingers=2, length=0.5) for _ in range(4)]
r1, r2, r3, r4 = (top << x for x in m)
bw, bh = evaluate_bbox(m[0])
r2.movey(bh + 5.0); r3.movex(bw + 6.0); r4.movex(bw + 6.0); r4.movey(bh + 5.0)
top << straight_route(PDK, r1.ports["multiplier_0_drain_N"], r2.ports["multiplier_0_source_S"])  # ref stack n1
top << straight_route(PDK, r3.ports["multiplier_0_drain_N"], r4.ports["multiplier_0_source_S"])  # copy stack n2
top << c_route(PDK, r1.ports["multiplier_0_gate_S"], r3.ports["multiplier_0_gate_S"])            # bottom gate tie
top << c_route(PDK, r2.ports["multiplier_0_gate_N"], r4.ports["multiplier_0_gate_N"])            # top gate tie
top << straight_route(PDK, r1.ports["multiplier_0_gate_W"], r2.ports["multiplier_0_gate_W"])     # VG column
top.add_ports(r1.get_ports_list(), prefix="M1_"); top.add_ports(r2.get_ports_list(), prefix="M2_")
top.add_ports(r3.get_ports_list(), prefix="M3_"); top.add_ports(r4.get_ports_list(), prefix="M4_")
component = top
