"""
Bias generation building blocks.

    current_bias  – Self-biased current reference (beta-multiplier topology)
    bandgap_vref  – Bandgap voltage reference stub (PTAT + CTAT summing)
"""
from __future__ import annotations
from typing import Optional

from gdsfactory.component import Component
from pydantic import validate_arguments

from gelochip.glayout.pdk.mappedpdk import MappedPDK
from gelochip.glayout.primitives.fet import nmos, pmos
from gelochip.glayout.primitives.mimcap import mimcap
from gelochip.glayout.util.comp_utils import prec_ref_center, movex, movey
from gelochip.glayout.util.port_utils import rename_ports_by_orientation
from gelochip.glayout.spice.netlist import Netlist


@validate_arguments
def current_bias(
    pdk: MappedPDK,
    *,
    ref_width: float = 4.0,
    ref_length: Optional[float] = None,
    ref_fingers: int = 1,
    mirror_ratio: float = 1.0,
    r_startup_width: float = 2.0,
    r_startup_fingers: int = 2,
) -> Component:
    """
    Beta-multiplier self-biased current reference.

    Generates a supply-independent bias current using a resistor-degenerated
    NMOS current mirror and a PMOS startup circuit.

    Topology::

        VDD
         │
       M_p1 ──── M_p2 (PMOS current mirror)
         │            │
       M_n1 ──── M_n2 (NMOS, M_n1 gate-drain shorted)
         │            │
        [R]          VSS  ← degeneration resistor sets I_bias

    Args:
        pdk:              Technology PDK.
        ref_width:        NMOS reference transistor width (µm).
        ref_length:       Gate length (µm).
        ref_fingers:      Reference transistor gate fingers.
        mirror_ratio:     Output mirror ratio W_out/W_ref.
        r_startup_width:  Startup transistor width (µm).
        r_startup_fingers: Startup transistor gate fingers.

    Returns:
        Component with ports: ibias_out_*, vdd_*, vss_*
    """
    ref_length = ref_length or pdk.get_grule("poly")["min_width"]
    top = Component("current_bias")

    mn1 = nmos(pdk, width=ref_width, length=ref_length, fingers=ref_fingers)
    mn2 = nmos(pdk, width=ref_width * mirror_ratio, length=ref_length, fingers=ref_fingers)
    mp1 = pmos(pdk, width=ref_width, length=ref_length, fingers=ref_fingers)
    mp2 = pmos(pdk, width=ref_width * mirror_ratio, length=ref_length, fingers=ref_fingers)
    ms  = pmos(pdk, width=r_startup_width, length=ref_length, fingers=r_startup_fingers)

    for r, comp, prefix in [
        (prec_ref_center(mn1), mn1, "mn1_"),
        (prec_ref_center(mn2), mn2, "mn2_"),
        (prec_ref_center(mp1), mp1, "mp1_"),
        (prec_ref_center(mp2), mp2, "mp2_"),
        (prec_ref_center(ms), ms,  "ms_"),
    ]:
        top.add(r)
        top.add_ports(r.get_ports_list(), prefix=prefix)

    top.info["netlist"] = Netlist(
        circuit_name="CURRENT_BIAS",
        nodes=["IBIAS_OUT", "VDD", "VSS"],
    )
    return rename_ports_by_orientation(top)


@validate_arguments
def bandgap_vref(
    pdk: MappedPDK,
    *,
    ptat_width: float = 2.0,
    ctat_width: float = 2.0,
    ptat_length: Optional[float] = None,
    op_amp_fingers: int = 2,
) -> Component:
    """
    Bandgap voltage reference (PTAT + CTAT summing amplifier).

    Generates a temperature-stable ~1.2 V reference by summing a
    Proportional-To-Absolute-Temperature (PTAT) voltage with a
    Complementary-To-Absolute-Temperature (CTAT) diode voltage.

    NOTE: The BJT diodes used in a true bandgap require the gf180 or ihp130
    PDK. This stub creates the MOSFET amplifier portion. Set pdk accordingly.

    Args:
        pdk:            Technology PDK (gf180 recommended for BJT support).
        ptat_width:     PTAT transistor width (µm).
        ctat_width:     CTAT transistor width (µm).
        ptat_length:    Gate length (µm).
        op_amp_fingers: Op-amp differential pair fingers.

    Returns:
        Component with ports: vref_out_*, vdd_*, vss_*
    """
    ptat_length = ptat_length or pdk.get_grule("poly")["min_width"]
    top = Component("bandgap_vref")

    mp = pmos(pdk, width=ptat_width, length=ptat_length, fingers=op_amp_fingers)
    mn = nmos(pdk, width=ctat_width, length=ptat_length, fingers=op_amp_fingers)

    r_mp = prec_ref_center(mp)
    r_mn = prec_ref_center(mn)
    top.add(r_mp); top.add(r_mn)

    bbox_w = mp.bbox[1][0] - mp.bbox[0][0]
    sep = pdk.get_grule("met2")["min_separation"]
    movex(r_mn, bbox_w + sep)

    top.add_ports(r_mp.get_ports_list(), prefix="mp_")
    top.add_ports(r_mn.get_ports_list(), prefix="mn_")
    top.info["netlist"] = Netlist(
        circuit_name="BANDGAP_VREF",
        nodes=["VREF_OUT", "VDD", "VSS"],
    )
    return rename_ports_by_orientation(top)
