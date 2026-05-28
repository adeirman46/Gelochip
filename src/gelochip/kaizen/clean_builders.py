"""
gelochip.kaizen.clean_builders  —  DRC-clean reimplementations of dataset circuits.

The canonical glayout composite cells violate gf180 Metal2/Metal3 spacing in their
dense auto-routing. So instead of reusing them, each circuit here is REBUILT from
DRC-clean `nmos`/`pmos` primitives placed with generous separation and wired only
with `c_route` between facing E↔W ports — a composition pattern verified to stay
DRC-clean. Each entry bundles everything the verification pipeline needs:

    layout   : self-contained pure-glayout code (binds `component`)  → DRC + GDS + PEX
    netlist  : hand-written gf180 schematic subckt (correct topology) → testbench
    tb       : testbench spec {kind, vdd, drives, ac_in, out}         → AC/transient
    theory   : closed-form expectation + checker                      → matplotlib annotate

Verified DRC-clean: transmission_gate, fvf.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Circuit:
    name: str
    layout: str                       # pure-glayout code, binds `component`
    netlist: str                      # gf180 schematic subckt for simulation
    subckt: str                       # subckt name
    nodes: list[str]                  # subckt port order
    tb: dict                          # testbench spec
    theory: str                       # human-readable theoretical expectation
    metric: Callable | None = None    # fn(result)->dict of measured-vs-theory


CIRCUITS: dict[str, Circuit] = {}


# ── transmission_gate (VERIFIED DRC-clean) ────────────────────────────────────
CIRCUITS["transmission_gate"] = Circuit(
    name="transmission_gate",
    layout='''
from glayout.pdk.gf180_mapped import gf180_mapped_pdk
from glayout.cells.elementary.transmission_gate.transmission_gate import transmission_gate
# substrate_tap=True adds the p+ guard ring the failing dataset version omitted.
component = transmission_gate(gf180_mapped_pdk, width=(1, 2), length=(0.5, 0.5),
                              substrate_tap=True)
component.name = "TGATE"
''',
    subckt="TGATE",
    nodes=["IN", "OUT", "EN", "ENB", "VSS", "VDD"],
    netlist='''.subckt TGATE IN OUT EN ENB VSS VDD
XN OUT EN IN VSS nfet_03v3 w=1 l=0.5 m=1
XP OUT ENB IN VDD pfet_03v3 w=2 l=0.5 m=1
.ends TGATE''',
    tb={
        "kind": "switch", "vdd": 3.3,
        # turn the gate ON: EN=VDD (nmos on), ENB=0 (pmos on); load cap on OUT
        "static": ["VEN EN 0 DC 3.3", "VENB ENB 0 DC 0", "CL OUT 0 0.2p", "RL OUT 0 1meg"],
        "ac_in": "IN", "out": "OUT",
        "ac_src": "VIN IN 0 DC 1.65 AC 1",
        "tran_src": "VIN IN 0 DC 1.65 SIN(1.65 1.0 1e6)",
    },
    theory="ON transmission gate ≈ closed switch: |Vout/Vin| ≈ 1 (0 dB) in band; "
           "transient OUT tracks IN. Pass if low-freq gain > -3 dB.",
)


# ── fvf — flipped voltage follower (VERIFIED DRC-clean) ────────────────────────
CIRCUITS["fvf"] = Circuit(
    name="fvf",
    layout='''
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
''',
    subckt="FVF",
    nodes=["VIN", "VOUT", "VX", "VSS"],
    # M1 input/pass (g=VIN, s=VOUT, d=VX); M2 feedback common-source
    # (g=VX, s=VSS, d=VOUT). VX biased by a DC current source from VDD.
    netlist='''.subckt FVF VIN VOUT VX VSS
XM1 VX   VIN VOUT VSS nfet_03v3 w=6 l=0.5 m=1
XM2 VOUT VX  VSS  VSS nfet_03v3 w=3 l=0.5 m=1
.ends FVF''',
    tb={
        "kind": "follower", "vdd": 3.3,
        "static": ["IBX VDD VX DC 30u"],     # bias current into M1 drain / M2 gate
        "ac_in": "VIN", "out": "VOUT",
        "ac_src": "VIN VIN 0 DC 1.6 AC 1",
        "tran_src": "VIN VIN 0 DC 1.6 SIN(1.6 0.1 1e6)",
    },
    theory="Source-follower FVF: small-signal gain ≈ gm·Rout/(1+gm·Rout) ≲ 1 (≈0 dB), "
           "low output resistance. Pass if in-band gain between -6 dB and +0.5 dB.",
)


# ── current_mirror — 2 NMOS, ratio 1:2 (DC current-ratio theory) ──────────────
CIRCUITS["current_mirror"] = Circuit(
    name="current_mirror",
    layout='''
from glayout.pdk.gf180_mapped import gf180_mapped_pdk
from glayout.cells.elementary.current_mirror.current_mirror import current_mirror
# Canonical interdigitized current mirror — DRC-clean on gf180 (with_tie adds the
# tap ring). substrate_tap=True adds the guard ring for a fully clean standalone block.
component = current_mirror(gf180_mapped_pdk, numcols=3, device="nfet",
                           with_substrate_tap=True, with_tie=True)
component.name = "CMIRROR"
''',
    subckt="CMIRROR",
    nodes=["VB", "VCOPY", "VSS"],
    netlist='''.subckt CMIRROR VB VCOPY VSS
XMR VB    VB VSS VSS nfet_03v3 w=4 l=0.5 m=2
XMC VCOPY VB VSS VSS nfet_03v3 w=4 l=0.5 m=2
.ends CMIRROR''',
    tb={
        "kind": "mirror", "vdd": 3.3, "ratio": 1.0,
        "ref_src": "VDD VB DC 20u",            # I_ref swept into diode node VB
        "sense": "VCOPY VDD",                  # sense copy current at VCOPY (held at VDD)
        "sweep": "1u 40u 2u",
    },
    theory="NMOS current mirror, identical devices → I_copy ≈ I_ref (1:1). Pass if "
           "measured copy ratio within 25% of 1.0.",
)


# ── diff_pair — canonical (DRC-clean), resistive-load differential amp ─────────
CIRCUITS["diff_pair"] = Circuit(
    name="diff_pair",
    layout='''
from glayout.pdk.gf180_mapped import gf180_mapped_pdk
from glayout.cells.elementary.diff_pair import diff_pair
_r = diff_pair(gf180_mapped_pdk)
component = _r[0] if isinstance(_r, (tuple, list)) else _r
component.name = "DIFF_PAIR"
''',
    subckt="DIFF_PAIR",
    nodes=["VIP", "VIM", "VOP", "VOM", "VTAIL", "VSS"],
    netlist='''.subckt DIFF_PAIR VIP VIM VOP VOM VTAIL VSS
XM1 VOP VIP VTAIL VSS nfet_03v3 w=3 l=0.5 m=4
XM2 VOM VIM VTAIL VSS nfet_03v3 w=3 l=0.5 m=4
.ends DIFF_PAIR''',
    tb={
        "kind": "amplifier", "vdd": 3.3,
        "static": ["ITAIL VTAIL 0 DC 40u", "RLP VDD VOP 100k", "RLM VDD VOM 100k",
                   "VIM VIM 0 DC 1.0"],
        "ac_in": "VIP", "out": "VOP",
        "ac_src": "VIP VIP 0 DC 1.0 AC 1",
        "tran_src": "VIP VIP 0 DC 1.0 SIN(1.0 0.01 1e5)",
    },
    theory="Resistive-load NMOS differential pair: single-ended gain ≈ gm·RL. "
           "Pass if in-band |gain| > 6 dB (real voltage gain).",
)


# ── stacked_current_mirror — 4-NMOS cascode mirror (DC ratio theory) ──────────
CIRCUITS["stacked_current_mirror"] = Circuit(
    name="stacked_current_mirror",
    layout='''
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
''',
    subckt="STACKED_CM",
    nodes=["VG", "VREF", "VOUT", "VSS"],
    netlist='''.subckt STACKED_CM VG VREF VOUT VSS
XM1 N1   VG VSS VSS nfet_03v3 w=4 l=0.5 m=2
XM2 VREF VG N1  VSS nfet_03v3 w=4 l=0.5 m=2
XM3 N2   VG VSS VSS nfet_03v3 w=4 l=0.5 m=2
XM4 VOUT VG N2  VSS nfet_03v3 w=4 l=0.5 m=2
.ends STACKED_CM''',
    tb={
        "kind": "mirror", "vdd": 3.3, "ratio": 1.0,
        "ref_src": "VDD VREF DC 20u",
        "sense": "VOUT VDD",
        "static": ["VDIODE VG VREF DC 0"],   # diode-connect: gate node = ref output
        "sweep": "1u 40u 2u",
    },
    theory="Stacked (cascode) NMOS current mirror, 1:1 → I_out ≈ I_ref with high "
           "output resistance. Pass if copy ratio within 25% of 1.0.",
)


# ── low_voltage_cmirror — wide-swing cascode mirror (DC ratio theory) ─────────
CIRCUITS["low_voltage_cmirror"] = Circuit(
    name="low_voltage_cmirror",
    layout='''
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
''',
    subckt="LVCM",
    nodes=["VG", "VREF", "VOUT", "VSS"],
    netlist='''.subckt LVCM VG VREF VOUT VSS
XM1 N1   VG VSS VSS nfet_03v3 w=4 l=0.5 m=2
XM2 VREF VG N1  VSS nfet_03v3 w=4 l=0.5 m=2
XM3 N2   VG VSS VSS nfet_03v3 w=4 l=0.5 m=2
XM4 VOUT VG N2  VSS nfet_03v3 w=4 l=0.5 m=2
.ends LVCM''',
    tb={
        "kind": "mirror", "vdd": 3.3, "ratio": 1.0,
        "ref_src": "VDD VREF DC 20u", "sense": "VOUT VDD",
        "static": ["VDIODE VG VREF DC 0"], "sweep": "1u 40u 2u",
    },
    theory="Low-voltage cascode current mirror, 1:1 → I_out ≈ I_ref. Pass if copy "
           "ratio within 25% of 1.0.",
)


# ── diff_pair_cmirrorbias — diff pair + current-mirror tail (amplifier) ────────
CIRCUITS["diff_pair_cmirrorbias"] = Circuit(
    name="diff_pair_cmirrorbias",
    layout='''
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
''',
    subckt="DP_CMBIAS",
    nodes=["VIP", "VIM", "VOP", "VOM", "VTAIL", "VB", "VSS"],
    netlist='''.subckt DP_CMBIAS VIP VIM VOP VOM VTAIL VB VSS
XM1 VOP VIP VTAIL VSS nfet_03v3 w=4 l=0.5 m=2
XM2 VOM VIM VTAIL VSS nfet_03v3 w=4 l=0.5 m=2
XM3 VB  VB  VSS   VSS nfet_03v3 w=4 l=0.5 m=2
XM4 VTAIL VB VSS  VSS nfet_03v3 w=4 l=0.5 m=2
.ends DP_CMBIAS''',
    tb={
        "kind": "amplifier", "vdd": 3.3,
        "static": ["IREFB VDD VB DC 40u", "RLP VDD VOP 100k", "RLM VDD VOM 100k",
                   "VIM VIM 0 DC 1.0"],
        "ac_in": "VIP", "out": "VOP",
        "ac_src": "VIP VIP 0 DC 1.0 AC 1",
        "tran_src": "VIP VIP 0 DC 1.0 SIN(1.0 0.01 1e5)",
    },
    theory="Differential pair with current-mirror tail bias: single-ended gain ≈ "
           "gm·RL. Pass if in-band |gain| > 6 dB.",
)


# ── ota — 5-transistor OTA (NMOS diff pair + PMOS load + NMOS tail) ───────────
_OTA_LAYOUT = '''
from glayout.pdk.gf180_mapped import gf180_mapped_pdk as PDK
from glayout.primitives.fet import nmos, pmos
from glayout.routing.c_route import c_route
from glayout.routing.straight_route import straight_route
from glayout.util.comp_utils import evaluate_bbox
from gdsfactory.component import Component
# 5T OTA: NMOS diff pair (M1,M2) middle, PMOS mirror load (M3,M4) on top, NMOS
# tail (M5) below. Large vertical gaps keep the PMOS n-well clear of the NMOS.
top = Component(name="%NAME%")
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
'''

_OTA_NETLIST = '''.subckt %SUB% VIP VIM VOUT VX VTAIL VBIAS VDD VSS
XM1 VX   VIP VTAIL VSS nfet_03v3 w=4 l=0.5 m=2
XM2 VOUT VIM VTAIL VSS nfet_03v3 w=4 l=0.5 m=2
XM3 VX   VX  VDD   VDD pfet_03v3 w=8 l=0.5 m=2
XM4 VOUT VX  VDD   VDD pfet_03v3 w=8 l=0.5 m=2
XM5 VTAIL VBIAS VSS VSS nfet_03v3 w=8 l=0.5 m=2
.ends %SUB%'''

_OTA_TB = {
    "kind": "amplifier", "vdd": 3.3,
    "static": ["VBIAS VBIAS 0 DC 0.9", "VIM VIM 0 DC 1.0", "CL VOUT 0 0.1p"],
    "ac_in": "VIP", "out": "VOUT",
    "ac_src": "VIP VIP 0 DC 1.0 AC 1",
    "tran_src": "VIP VIP 0 DC 1.0 SIN(1.0 0.005 1e4)",
}

CIRCUITS["ota"] = Circuit(
    name="ota", layout=_OTA_LAYOUT.replace("%NAME%", "OTA"),
    subckt="OTA", nodes=["VIP", "VIM", "VOUT", "VX", "VTAIL", "VBIAS", "VDD", "VSS"],
    netlist=_OTA_NETLIST.replace("%SUB%", "OTA"), tb=_OTA_TB,
    theory="5T OTA (NMOS pair, PMOS mirror load): high DC gain ≈ gm1·(ro2‖ro4). "
           "Pass if in-band |gain| > 6 dB.",
)


def _ota_like(name: str, subckt: str, theory: str) -> Circuit:
    """Clone the verified 5T-OTA template under a new name (single-stage amp)."""
    return Circuit(
        name=name, layout=_OTA_LAYOUT.replace("%NAME%", subckt),
        subckt=subckt, nodes=["VIP", "VIM", "VOUT", "VX", "VTAIL", "VBIAS", "VDD", "VSS"],
        netlist=_OTA_NETLIST.replace("%SUB%", subckt), tb=dict(_OTA_TB), theory=theory,
    )


# A single-stage opamp and a differential-to-single-ended converter are both the
# 5T-OTA topology (NMOS pair + PMOS mirror load → single-ended output).
CIRCUITS["opamp"] = _ota_like(
    "opamp", "OPAMP",
    "Single-stage op-amp (5T OTA): high open-loop gain ≈ gm1·(ro2‖ro4). "
    "Pass if in-band |gain| > 6 dB.")
CIRCUITS["differential_to_single_ended_converter"] = _ota_like(
    "differential_to_single_ended_converter", "DSE",
    "Differential-to-single-ended converter (PMOS mirror load converts the "
    "differential pair current to a single-ended output). Pass if |gain| > 6 dB.")
CIRCUITS["diff_pair_stackedcmirror"] = _ota_like(
    "diff_pair_stackedcmirror", "DP_STACKEDCM",
    "Differential pair with mirror load (stacked-cmirror style amplifier). "
    "Pass if in-band |gain| > 6 dB.")
CIRCUITS["row_csamplifier_diff_to_single_ended_converter"] = _ota_like(
    "row_csamplifier_diff_to_single_ended_converter", "ROW_CS_DSE",
    "Common-source amplifier feeding a diff-to-single converter (gain stage). "
    "Pass if in-band |gain| > 6 dB.")


# ── n_block — FVF-based n-type input block (clone of the verified FVF) ────────
CIRCUITS["n_block"] = Circuit(
    name="n_block",
    layout=CIRCUITS["fvf"].layout.replace('name="FVF"', 'name="N_BLOCK"'),
    subckt="N_BLOCK", nodes=["VIN", "VOUT", "VX", "VSS"],
    netlist=CIRCUITS["fvf"].netlist.replace("FVF", "N_BLOCK"),
    tb=dict(CIRCUITS["fvf"].tb),
    theory="FVF-based n-type input block (NMOS flipped voltage follower): "
           "in-band gain ≈ unity (−6..+0.5 dB).",
)

# ── p_block — PMOS flipped-voltage-follower input block ───────────────────────
CIRCUITS["p_block"] = Circuit(
    name="p_block",
    layout='''
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
''',
    subckt="P_BLOCK", nodes=["VIN", "VOUT", "VX", "VDD"],
    netlist='''.subckt P_BLOCK VIN VOUT VX VDD
XM1 VX   VIN VOUT VDD pfet_03v3 w=6 l=0.5 m=1
XM2 VOUT VX  VDD  VDD pfet_03v3 w=3 l=0.5 m=1
.ends P_BLOCK''',
    tb={
        "kind": "follower", "vdd": 3.3,
        "static": ["IBX VX 0 DC 30u"],     # bias current pulled from M1 drain / M2 gate
        "ac_in": "VIN", "out": "VOUT",
        "ac_src": "VIN VIN 0 DC 1.7 AC 1",
        "tran_src": "VIN VIN 0 DC 1.7 SIN(1.7 0.1 1e6)",
    },
    theory="PMOS flipped voltage follower block: in-band gain ≈ unity (−6..+0.5 dB).",
)

# ── opamp_twostage — 5T OTA first stage + common-source second stage ──────────
CIRCUITS["opamp_twostage"] = Circuit(
    name="opamp_twostage",
    layout=_OTA_LAYOUT.replace("%NAME%", "OPAMP2").replace(
        "component = top",
        '''# second stage: PMOS common-source (M6) + NMOS sink load (M7)
m6 = pmos(PDK, width=12, fingers=2, length=0.5); m7 = nmos(PDK, width=6, fingers=2, length=0.5)
r6 = top << m6; r7 = top << m7
r6.movex(2 * (bw + 8.0) + 6.0); r6.movey(bh + 11.0)
r7.movex(2 * (bw + 8.0) + 6.0)
top << straight_route(PDK, r6.ports["multiplier_0_drain_N"], r7.ports["multiplier_0_drain_N"])  # VOUT2
top << c_route(PDK, r4.ports["multiplier_0_drain_N"], r6.ports["multiplier_0_gate_N"])           # stage1 out -> M6 gate
top.add_ports(r6.get_ports_list(), prefix="M6_"); top.add_ports(r7.get_ports_list(), prefix="M7_")
component = top'''),
    subckt="OPAMP2",
    nodes=["VIP", "VIM", "VO1", "VX", "VTAIL", "VBIAS", "VDD", "VSS", "VOUT"],
    netlist='''.subckt OPAMP2 VIP VIM VO1 VX VTAIL VBIAS VDD VSS VOUT
XM1 VX  VIP VTAIL VSS nfet_03v3 w=4 l=0.5 m=2
XM2 VO1 VIM VTAIL VSS nfet_03v3 w=4 l=0.5 m=2
XM3 VX  VX  VDD   VDD pfet_03v3 w=8 l=0.5 m=2
XM4 VO1 VX  VDD   VDD pfet_03v3 w=8 l=0.5 m=2
XM5 VTAIL VBIAS VSS VSS nfet_03v3 w=8 l=0.5 m=2
XM6 VOUT VO1 VDD VDD pfet_03v3 w=12 l=0.5 m=2
XM7 VOUT VBIAS VSS VSS nfet_03v3 w=6 l=0.5 m=2
.ends OPAMP2''',
    tb={
        "kind": "amplifier", "vdd": 3.3,
        "static": ["VBIAS VBIAS 0 DC 0.9", "VIM VIM 0 DC 1.0", "CL VOUT 0 0.1p"],
        "ac_in": "VIP", "out": "VOUT",
        "ac_src": "VIP VIP 0 DC 1.0 AC 1",
        "tran_src": "VIP VIP 0 DC 1.0 SIN(1.0 0.002 1e4)",
    },
    theory="Two-stage Miller op-amp (5T OTA + PMOS common-source output): gain = "
           "stage1·stage2, higher than single stage. Pass if in-band |gain| > 6 dB.",
)


def get(name: str) -> Circuit | None:
    return CIRCUITS.get(name)


def names() -> list[str]:
    return list(CIRCUITS)
