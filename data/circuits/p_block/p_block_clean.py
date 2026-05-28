from glayout.pdk.gf180_mapped import gf180_mapped_pdk as PDK
from glayout.primitives.fet import pmos
from glayout.routing.c_route import c_route
from glayout.util.comp_utils import evaluate_bbox
from gdsfactory.component import Component
# PMOS FVF input block: M1 pass (g=VIN, s=VOUT, d=VX), M2 feedback common-source
# (g=VX, s=VDD, d=VOUT). Same DRC-clean composition pattern as the NMOS FVF.
top = Component(name="P_BLOCK")
m1 = pmos(PDK, width=6, fingers=2, length=0.5)
m2 = pmos(PDK, width=3, fingers=2, length=0.5)
r1 = top << m1; r2 = top << m2
r2.movex(evaluate_bbox(m1)[0] + 6 * PDK.util_max_metal_seperation())
top << c_route(PDK, r1.ports["multiplier_0_drain_N"],  r2.ports["multiplier_0_gate_N"])
top << c_route(PDK, r1.ports["multiplier_0_source_S"], r2.ports["multiplier_0_drain_S"])
top.add_ports(r1.get_ports_list(), prefix="M1_"); top.add_ports(r2.get_ports_list(), prefix="M2_")
component = top
