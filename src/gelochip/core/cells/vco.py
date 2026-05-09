"""
Voltage-Controlled Oscillator (VCO) cells.

    lc_vco    – LC tank VCO with cross-coupled NMOS pair
    ring_vco  – N-stage CMOS ring oscillator
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
from gelochip.core.blocks.current_mirror import current_mirror
from gelochip.core.primitives.passive import inductor as spiral_inductor


@validate_arguments
def lc_vco(
    pdk: MappedPDK,
    *,
    # Cross-coupled NMOS pair
    xcp_width: float = 8.0,
    xcp_length: Optional[float] = None,
    xcp_fingers: int = 4,
    # PMOS current source (tail)
    tail_width: float = 8.0,
    tail_fingers: int = 4,
    # LC tank
    inductor_turns: int = 3,
    inductor_inner_diameter: float = 60.0,
    inductor_width: float = 6.0,
    varactor_width: float = 4.0,
    varactor_fingers: int = 8,
    # MIM capacitor for extra tank capacitance
    tank_cap_size: tuple[float, float] = (10.0, 10.0),
    sd_rmult: int = 2,
) -> Component:
    """
    LC-tank VCO with cross-coupled NMOS negative-resistance pair.

    The negative transconductance −2/gm cancels tank losses, sustaining
    oscillation at f0 = 1 / (2π √(LC)).  A varactor (voltage-tunable
    capacitor) provides frequency tuning via Vtune.

    Topology::

        VDD
         │
       M_tail (PMOS current source, Ibias)
         ├─────────────────────┤
        [L/2]              [L/2]    ← differential spiral inductor
         │                   │
       VOUTP              VOUTN
         │                   │
       M_xcpn+            M_xcpn-  ← cross-coupled NMOS pair
         │                   │
        VSS                 VSS
         │
       [Cvar] (varactor, Vtune → 0..VDD)

    Args:
        pdk:                    Technology PDK.
        xcp_width:              Cross-coupled NMOS width per finger (µm).
        xcp_length:             Gate length (µm).
        xcp_fingers:            Cross-coupled NMOS fingers.
        tail_width:             PMOS tail current transistor width (µm).
        tail_fingers:           PMOS tail transistor fingers.
        inductor_turns:         LC tank inductor turns.
        inductor_inner_diameter: Inductor inner diameter (µm).
        inductor_width:         Inductor metal trace width (µm).
        varactor_width:         Varactor MOSFET width per finger (µm).
        varactor_fingers:       Varactor MOSFET gate fingers.
        tank_cap_size:          Extra MIM capacitor (w, h) in µm.
        sd_rmult:               S/D via multiplier.

    Returns:
        Component with ports:
            outp_*   – Differential output (+)
            outn_*   – Differential output (−)
            vtune_*  – Varactor tuning voltage input
            vbias_*  – Tail current mirror bias
            vdd_*, vss_*
    """
    xcp_length = xcp_length or pdk.get_grule("poly")["min_width"]
    top = Component("lc_vco")

    m_xcpp = nmos(pdk, width=xcp_width, length=xcp_length, fingers=xcp_fingers, sd_rmult=sd_rmult)
    m_xcpn = nmos(pdk, width=xcp_width, length=xcp_length, fingers=xcp_fingers, sd_rmult=sd_rmult)
    m_tail = pmos(pdk, width=tail_width, length=xcp_length, fingers=tail_fingers, sd_rmult=sd_rmult)
    m_var  = nmos(pdk, width=varactor_width, length=xcp_length, fingers=varactor_fingers)
    c_tank = mimcap(pdk, size=tank_cap_size)
    tank_l = spiral_inductor(pdk, turns=inductor_turns,
                             inner_diameter=inductor_inner_diameter,
                             width=inductor_width)

    sep = pdk.get_grule("met2")["min_separation"]
    bbox_w = m_xcpp.bbox[1][0] - m_xcpp.bbox[0][0]
    bbox_h = m_xcpp.bbox[1][1] - m_xcpp.bbox[0][1]

    r_xcpp = prec_ref_center(m_xcpp); top.add(r_xcpp)
    r_xcpn = prec_ref_center(m_xcpn); top.add(r_xcpn); movex(r_xcpn, bbox_w + sep)
    r_tail = prec_ref_center(m_tail); top.add(r_tail); movey(r_tail, bbox_h + sep)
    movex(r_tail, bbox_w / 2)
    r_var  = prec_ref_center(m_var);  top.add(r_var);  movey(r_var, -(bbox_h + sep))
    movex(r_var, bbox_w / 2)
    r_ctank = prec_ref_center(c_tank); top.add(r_ctank)
    movex(r_ctank, 2 * (bbox_w + sep))
    r_lc = prec_ref_center(tank_l); top.add(r_lc)
    movex(r_lc, -inductor_inner_diameter - sep)

    for ref, prefix in [
        (r_xcpp, "xcpp_"), (r_xcpn, "xcpn_"),
        (r_tail, "tail_"), (r_var, "var_"), (r_ctank, "ctank_"),
    ]:
        top.add_ports(ref.get_ports_list(), prefix=prefix)

    top.info["specs"] = {
        "topology": "lc_vco_cross_coupled",
        "reference": "Hajimiri & Lee, JSSC 1999",
        "inductor_turns": inductor_turns,
        "varactor_fingers": varactor_fingers,
    }
    top.info["netlist"] = Netlist(
        circuit_name="LC_VCO",
        nodes=["OUTP", "OUTN", "VTUNE", "VBIAS", "VDD", "VSS"],
    )
    return rename_ports_by_orientation(top)


@validate_arguments
def ring_vco(
    pdk: MappedPDK,
    *,
    num_stages: int = 3,
    inv_n_width: float = 2.0,
    inv_p_width: float = 4.0,
    inv_length: Optional[float] = None,
    inv_fingers: int = 1,
    sd_rmult: int = 1,
) -> Component:
    """
    N-stage CMOS ring oscillator.

    Frequency f0 ≈ 1 / (2 × N × τ_pd) where τ_pd is the inverter propagation delay.
    Widely used for on-chip clock generation and PLL reference.

    Args:
        pdk:          Technology PDK.
        num_stages:   Number of inverter stages (must be odd, typically 3, 5, 7).
        inv_n_width:  NMOS inverter transistor width per finger (µm).
        inv_p_width:  PMOS inverter transistor width per finger (µm).
        inv_length:   Gate length (µm).
        inv_fingers:  Gate fingers per inverter transistor.
        sd_rmult:     S/D via multiplier.

    Returns:
        Component with ports: out_*, vdd_*, vss_*
    """
    if num_stages % 2 == 0:
        raise ValueError(f"Ring VCO requires odd number of stages, got {num_stages}")
    inv_length = inv_length or pdk.get_grule("poly")["min_width"]
    top = Component(f"ring_vco_{num_stages}stage")

    sep = pdk.get_grule("met2")["min_separation"]
    x_cursor = 0.0

    for i in range(num_stages):
        mn = nmos(pdk, width=inv_n_width, length=inv_length, fingers=inv_fingers, sd_rmult=sd_rmult)
        mp = pmos(pdk, width=inv_p_width, length=inv_length, fingers=inv_fingers, sd_rmult=sd_rmult)

        r_mn = prec_ref_center(mn); top.add(r_mn)
        r_mp = prec_ref_center(mp); top.add(r_mp)

        bbox_w = mn.bbox[1][0] - mn.bbox[0][0]
        bbox_h = mn.bbox[1][1] - mn.bbox[0][1]

        movex(r_mn, x_cursor)
        movex(r_mp, x_cursor)
        movey(r_mp, bbox_h + sep)

        top.add_ports(r_mn.get_ports_list(), prefix=f"inv{i}_n_")
        top.add_ports(r_mp.get_ports_list(), prefix=f"inv{i}_p_")

        x_cursor += bbox_w + sep

    top.info["specs"] = {
        "topology": "ring_vco",
        "num_stages": num_stages,
        "target_freq": "PDK-dependent",
    }
    top.info["netlist"] = Netlist(
        circuit_name=f"RING_VCO_{num_stages}STAGE",
        nodes=["OUT", "VDD", "VSS"],
    )
    return rename_ports_by_orientation(top)
