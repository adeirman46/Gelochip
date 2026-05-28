from glayout.pdk.gf180_mapped import gf180_mapped_pdk as PDK
from glayout.primitives.fet import nmos
from glayout.routing.c_route import c_route
from glayout.util.comp_utils import evaluate_bbox
from gdsfactory.component import Component
# FVF rebuilt from two DRC-clean nmos primitives (canonical FVF cell fails gf180
# M2/M3 spacing). Standard FVF: M1 = input/pass device (g=VIN, s=VOUT, d=VX);
# M2 = common-source feedback (g=VX, s=VSS, d=VOUT). Routes (facing E<->W only,
# DRC-clean): VX = M1.drain <-> M2.gate ;  VOUT = M1.source <-> M2.drain.
top = Component(name="FVF")
m1 = nmos(PDK, width=6, fingers=2, length=0.5)
m2 = nmos(PDK, width=3, fingers=2, length=0.5)
r1 = top << m1
r2 = top << m2
r2.movex(evaluate_bbox(m1)[0] + 6 * PDK.util_max_metal_seperation())
# c_route needs SAME-orientation ports; route different nets on N vs S to avoid
# collisions.  VX = M1.drain<->M2.gate (N side);  VOUT = M1.source<->M2.drain (S side).
top << c_route(PDK, r1.ports["multiplier_0_drain_N"],  r2.ports["multiplier_0_gate_N"])
top << c_route(PDK, r1.ports["multiplier_0_source_S"], r2.ports["multiplier_0_drain_S"])
top.add_ports(r1.get_ports_list(), prefix="M1_")
top.add_ports(r2.get_ports_list(), prefix="M2_")
component = top
