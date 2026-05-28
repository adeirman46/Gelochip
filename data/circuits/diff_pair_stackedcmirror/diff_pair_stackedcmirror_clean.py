from glayout.pdk.gf180_mapped import gf180_mapped_pdk as PDK
from glayout.primitives.fet import nmos, pmos
from glayout.routing.c_route import c_route
from glayout.routing.straight_route import straight_route
from glayout.util.comp_utils import evaluate_bbox
from gdsfactory.component import Component
# 5T OTA: NMOS diff pair (M1,M2) middle, PMOS mirror load (M3,M4) on top, NMOS
# tail (M5) below. Large vertical gaps keep the PMOS n-well clear of the NMOS.
top = Component(name="DP_STACKEDCM")
m1 = nmos(PDK, width=4, fingers=2, length=0.5); m2 = nmos(PDK, width=4, fingers=2, length=0.5)
m3 = pmos(PDK, width=8, fingers=2, length=0.5); m4 = pmos(PDK, width=8, fingers=2, length=0.5)
m5 = nmos(PDK, width=8, fingers=2, length=0.5)
r1 = top << m1; r2 = top << m2; r3 = top << m3; r4 = top << m4; r5 = top << m5
bw, bh = evaluate_bbox(m1)
r2.movex(bw + 8.0)
r3.movey(bh + 11.0); r4.movex(bw + 8.0); r4.movey(bh + 11.0)
r5.movex((bw + 8.0) / 2); r5.movey(-(bh + 11.0))
top << straight_route(PDK, r1.ports["multiplier_0_drain_N"], r3.ports["multiplier_0_drain_S"])   # VX
top << straight_route(PDK, r2.ports["multiplier_0_drain_N"], r4.ports["multiplier_0_drain_S"])   # VOUT
top << c_route(PDK, r3.ports["multiplier_0_gate_N"], r4.ports["multiplier_0_gate_N"])            # load gate tie
top << straight_route(PDK, r3.ports["multiplier_0_drain_W"], r3.ports["multiplier_0_gate_W"])    # M3 diode (VX)
top << c_route(PDK, r1.ports["multiplier_0_source_S"], r2.ports["multiplier_0_source_S"])        # VTAIL
top << straight_route(PDK, r5.ports["multiplier_0_drain_N"], r1.ports["multiplier_0_source_S"])  # tail->VTAIL
for i, r in enumerate((r1, r2, r3, r4, r5)):
    top.add_ports(r.get_ports_list(), prefix=f"M{i+1}_")
component = top
