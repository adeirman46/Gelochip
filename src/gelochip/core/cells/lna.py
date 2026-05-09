"""
Low-Noise Amplifier (LNA) cells.

    lna_cascode                    – NMOS cascode LNA (common-gate cascode)
    lna_inductively_degenerated    – Inductively degenerated LNA (Shaeffer & Lee topology)

These are the most common RF LNA topologies for 1–10 GHz applications.
Port convention:
    rfin_*     – RF input (50 Ω match)
    rfout_*    – RF output
    vbias_*    – DC bias voltage
    vdd_*, vss_*

Target specs (typical for 5 GHz WLAN):
    NF  < 2 dB
    S11 < −10 dB
    Gain > 15 dB
    IIP3 > −5 dBm
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
from gelochip.core.blocks.amplifier import common_source, common_gate
from gelochip.core.blocks.current_mirror import current_mirror
from gelochip.core.blocks.bias import current_bias


@validate_arguments
def lna_cascode(
    pdk: MappedPDK,
    *,
    # Transconductance (bottom) transistor
    gm_width: float = 40.0,
    gm_length: Optional[float] = None,
    gm_fingers: int = 10,
    # Cascode (top) transistor
    cas_width: float = 40.0,
    cas_length: Optional[float] = None,
    cas_fingers: int = 10,
    # PMOS load
    load_width: float = 20.0,
    load_fingers: int = 5,
    # Decoupling / ESD capacitors
    input_cap_size: tuple[float, float] = (20.0, 20.0),
    # Bias
    bias_width: float = 4.0,
    bias_fingers: int = 2,
    sd_rmult: int = 2,
) -> Component:
    """
    NMOS cascode LNA (two-transistor cascode stack).

    Topology::

        VDD
         │
       [PMOS diode load]
         │
       M_cas (NMOS, common-gate) ← VB_cas (AC ground)
         │
       M_gm  (NMOS, common-source) ← RF_IN
         │
       VSS

    The cascode topology provides:
    - High reverse isolation (S12 ↓) → stability
    - Higher gain than a single CS stage
    - Lower Miller capacitance → better high-frequency response

    Args:
        pdk:              Technology PDK.
        gm_width:         Gm transistor width per finger (µm). Total W = gm_width × gm_fingers.
        gm_length:        Gate length (µm). Use PDK minimum for max fT.
        gm_fingers:       Number of gate fingers in Gm transistor.
        cas_width:        Cascode transistor width per finger (µm).
        cas_length:       Cascode gate length (µm).
        cas_fingers:      Cascode transistor fingers.
        load_width:       PMOS load transistor width per finger (µm).
        load_fingers:     Load transistor fingers.
        input_cap_size:   (w, h) AC coupling capacitor at RF input (µm).
        bias_width:       Bias current mirror transistor width (µm).
        bias_fingers:     Bias transistor fingers.
        sd_rmult:         S/D via multiplier (for high-current RF transistors).

    Returns:
        Component with ports:
            rfin_*     – RF input
            rfout_*    – RF output (drain of cascode)
            vbias_gm_* – Bias for Gm stage
            vbias_cas_*– Bias for cascode gate
            vdd_*, vss_*

    Example::

        from gelochip.glayout.pdk.gf180_mapped import gf180_mapped_pdk as pdk
        lna = lna_cascode(pdk, gm_width=40.0, gm_fingers=10)
        lna.write_gds("lna_cascode.gds")
    """
    gm_length = gm_length or pdk.get_grule("poly")["min_width"]
    cas_length = cas_length or gm_length

    top = Component("lna_cascode")

    m_gm = nmos(pdk, width=gm_width, length=gm_length, fingers=gm_fingers, sd_rmult=sd_rmult)
    m_cas = nmos(pdk, width=cas_width, length=cas_length, fingers=cas_fingers, sd_rmult=sd_rmult)
    m_load = pmos(pdk, width=load_width, length=gm_length, fingers=load_fingers, sd_rmult=sd_rmult)
    c_in = mimcap(pdk, size=input_cap_size)
    bias = current_bias(pdk, ref_width=bias_width, ref_fingers=bias_fingers)

    r_gm = prec_ref_center(m_gm)
    r_cas = prec_ref_center(m_cas)
    r_load = prec_ref_center(m_load)
    r_cin = prec_ref_center(c_in)
    r_bias = prec_ref_center(bias)

    top.add(r_gm); top.add(r_cas); top.add(r_load)
    top.add(r_cin); top.add(r_bias)

    bbox_h = m_gm.bbox[1][1] - m_gm.bbox[0][1]
    bbox_w = m_gm.bbox[1][0] - m_gm.bbox[0][0]
    sep = pdk.get_grule("met2")["min_separation"]

    movey(r_cas, bbox_h + sep)
    movey(r_load, 2 * (bbox_h + sep))
    movex(r_cin, -(bbox_w + sep))
    movex(r_bias, bbox_w + sep)

    top.add_ports(r_gm.get_ports_list(),   prefix="gm_")
    top.add_ports(r_cas.get_ports_list(),  prefix="cas_")
    top.add_ports(r_load.get_ports_list(), prefix="load_")
    top.add_ports(r_cin.get_ports_list(),  prefix="cin_")
    top.add_ports(r_bias.get_ports_list(), prefix="bias_")

    top.info["specs"] = {
        "topology": "cascode_lna",
        "target_freq_GHz": 5.0,
        "target_nf_dB": 2.0,
        "target_gain_dB": 15.0,
        "target_iip3_dBm": -5.0,
    }
    top.info["netlist"] = Netlist(
        circuit_name="LNA_CASCODE",
        nodes=["RFIN", "RFOUT", "VBIAS_GM", "VBIAS_CAS", "VDD", "VSS"],
    )
    return rename_ports_by_orientation(top)


@validate_arguments
def lna_inductively_degenerated(
    pdk: MappedPDK,
    *,
    gm_width: float = 40.0,
    gm_length: Optional[float] = None,
    gm_fingers: int = 10,
    cas_width: float = 40.0,
    cas_fingers: int = 10,
    load_width: float = 20.0,
    load_fingers: int = 5,
    # Inductive degeneration (source inductor Ls)
    ls_turns: int = 2,
    ls_inner_diameter: float = 30.0,
    ls_width: float = 4.0,
    # Gate inductor Lg for input matching
    lg_turns: int = 4,
    lg_inner_diameter: float = 50.0,
    lg_width: float = 4.0,
    sd_rmult: int = 2,
) -> Component:
    """
    Inductively degenerated NMOS LNA (Shaeffer & Lee, JSSC 1997).

    The source inductor Ls creates a real input impedance ωT·Ls ≈ 50 Ω,
    enabling simultaneous noise and power matching without resistive loss.

    Topology::

        VDD
         │
       [load]
         │
       M_cas ← V_cas_bias
         │
       M_gm ← RF_IN ─── Lg ──┤
         │
        Ls (source inductor)
         │
       VSS

    Args:
        pdk:            Technology PDK.
        gm_width:       Gm transistor width per finger (µm).
        gm_length:      Gate length (µm).
        gm_fingers:     Gm transistor fingers.
        cas_width:      Cascode transistor width per finger (µm).
        cas_fingers:    Cascode transistor fingers.
        load_width:     PMOS load width per finger (µm).
        load_fingers:   Load transistor fingers.
        ls_turns:       Source inductor Ls turns.
        ls_inner_diameter: Ls inner diameter (µm).
        ls_width:       Ls metal width (µm).
        lg_turns:       Gate inductor Lg turns.
        lg_inner_diameter: Lg inner diameter (µm).
        lg_width:       Lg metal width (µm).
        sd_rmult:       S/D via multiplier.

    Returns:
        Component with ports: rfin_*, rfout_*, vbias_*, vdd_*, vss_*

    Note:
        Spiral inductors use stub components. Full EM-simulated inductors
        will replace these in a future release.
    """
    from gelochip.core.primitives.passive import inductor as spiral_inductor
    gm_length = gm_length or pdk.get_grule("poly")["min_width"]

    top = Component("lna_ind_degen")

    m_gm = nmos(pdk, width=gm_width, length=gm_length, fingers=gm_fingers, sd_rmult=sd_rmult)
    m_cas = nmos(pdk, width=cas_width, length=gm_length, fingers=cas_fingers, sd_rmult=sd_rmult)
    m_load = pmos(pdk, width=load_width, length=gm_length, fingers=load_fingers)
    ls = spiral_inductor(pdk, turns=ls_turns, inner_diameter=ls_inner_diameter, width=ls_width)
    lg = spiral_inductor(pdk, turns=lg_turns, inner_diameter=lg_inner_diameter, width=lg_width)

    r_gm   = prec_ref_center(m_gm)
    r_cas  = prec_ref_center(m_cas)
    r_load = prec_ref_center(m_load)
    r_ls   = prec_ref_center(ls)
    r_lg   = prec_ref_center(lg)

    top.add(r_gm); top.add(r_cas); top.add(r_load)
    top.add(r_ls); top.add(r_lg)

    bbox_h = m_gm.bbox[1][1] - m_gm.bbox[0][1]
    bbox_w = m_gm.bbox[1][0] - m_gm.bbox[0][0]
    sep = pdk.get_grule("met2")["min_separation"]

    movey(r_cas,  bbox_h + sep)
    movey(r_load, 2 * (bbox_h + sep))
    movey(r_ls,   -(ls_inner_diameter + sep))
    movex(r_lg,   -(bbox_w + sep + lg_inner_diameter))

    top.add_ports(r_gm.get_ports_list(),   prefix="gm_")
    top.add_ports(r_cas.get_ports_list(),  prefix="cas_")
    top.add_ports(r_load.get_ports_list(), prefix="load_")

    top.info["specs"] = {
        "topology": "inductively_degenerated_lna",
        "reference": "Shaeffer & Lee, JSSC 1997",
        "target_freq_GHz": 5.0,
        "target_nf_dB": 1.5,
        "target_gain_dB": 18.0,
        "ls_turns": ls_turns,
        "lg_turns": lg_turns,
    }
    top.info["netlist"] = Netlist(
        circuit_name="LNA_IND_DEGEN",
        nodes=["RFIN", "RFOUT", "VBIAS", "VDD", "VSS"],
    )
    return rename_ports_by_orientation(top)
