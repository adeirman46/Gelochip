"""
Differential pair building blocks.

    diff_pair      – Standard differential pair with tail current source
    folded_cascode – Folded-cascode OTA input stage (high gain, wide swing)

Port convention (differential pair):
    inp  – Non-inverting input (+)
    inn  – Inverting input (−)
    outp – Output drain of MP (differential +)
    outn – Output drain of MN (differential −)
    ibias – Tail current bias
    vdd, vss – Supply rails
"""
from __future__ import annotations
from typing import Optional

from gdsfactory.component import Component
from gdsfactory.cell import cell
from pydantic import validate_arguments

from gelochip.glayout.pdk.mappedpdk import MappedPDK
from gelochip.glayout.cells.elementary.diff_pair import diff_pair as _diff_pair
from gelochip.glayout.primitives.fet import nmos, pmos
from gelochip.glayout.routing.c_route import c_route
from gelochip.glayout.routing.L_route import L_route
from gelochip.glayout.util.comp_utils import prec_ref_center, movex, movey
from gelochip.glayout.util.port_utils import rename_ports_by_orientation, add_ports_perimeter
from gelochip.glayout.spice.netlist import Netlist


@validate_arguments
def diff_pair(
    pdk: MappedPDK,
    *,
    width: float = 4.0,
    length: Optional[float] = None,
    fingers: int = 2,
    tail_current_width: float = 2.0,
    tail_current_fingers: int = 1,
    n_or_p: str = "nfet",
    with_common_centroid: bool = True,
    sd_rmult: int = 1,
) -> Component:
    """
    Differential pair with integrated tail current transistor.

    Args:
        pdk:                   Technology PDK.
        width:                 Input transistor gate width per finger (µm).
        length:                Gate length (µm).
        fingers:               Gate fingers per input transistor.
        tail_current_width:    Tail transistor width (µm). Controls I_tail.
        tail_current_fingers:  Tail transistor fingers.
        n_or_p:                "nfet" (NMOS tail) or "pfet" (PMOS tail).
        with_common_centroid:  Use AB–BA common-centroid placement for matching.
        sd_rmult:              S/D via multiplier for high-current operation.

    Returns:
        Component with ports:
            inp_gate_*   – Non-inverting input
            inn_gate_*   – Inverting input
            outp_drain_* – Differential output (+)
            outn_drain_* – Differential output (−)
            ibias_gate_* – Tail current bias input
            vdd_*, vss_* – Supply rails

    Example::

        dp = diff_pair(pdk, width=6.0, fingers=4, n_or_p="nfet")
        dp.show()
    """
    length = length or pdk.get_grule("poly")["min_width"]
    return _diff_pair(
        pdk=pdk,
        half_diffpair_params=(width, length, fingers),
        diffpair_bias=(tail_current_width, length, tail_current_fingers),
        rmult=sd_rmult,
        with_antenna_diode_on_diffinputs=0,
    )


@validate_arguments
def folded_cascode(
    pdk: MappedPDK,
    *,
    input_width: float = 4.0,
    input_length: Optional[float] = None,
    input_fingers: int = 2,
    cascode_width: float = 2.0,
    cascode_fingers: int = 2,
    load_width: float = 4.0,
    load_fingers: int = 2,
    bias_width: float = 2.0,
    input_n_or_p: str = "nfet",
    sd_rmult: int = 1,
) -> Component:
    """
    Folded-cascode OTA input stage.

    The input differential pair folds into a cascode load, providing high
    gain and rail-to-rail input common-mode range.

    Topology::

        VDD ─── M_load_p (PMOS cascode load)
                    │
                 M_input_n (NMOS diff pair, folded)
                    │
                 M_cascode_n (NMOS cascode bias)
                    │
                 VSS

    Args:
        pdk:             Technology PDK.
        input_width:     Differential input transistor width (µm).
        input_length:    Gate length (µm).
        input_fingers:   Input transistor fingers.
        cascode_width:   Cascode transistor width (µm).
        cascode_fingers: Cascode transistor fingers.
        load_width:      PMOS/NMOS load transistor width (µm).
        load_fingers:    Load transistor fingers.
        bias_width:      Current mirror bias transistor width (µm).
        input_n_or_p:    "nfet" input pair or "pfet" input pair.
        sd_rmult:        S/D via multiplier.

    Returns:
        Component with ports: inp_*, inn_*, out_*, ibias_*, vdd_*, vss_*
    """
    input_length = input_length or pdk.get_grule("poly")["min_width"]

    top = Component("folded_cascode_ota")
    input_fet = nmos if input_n_or_p == "nfet" else pmos
    load_fet = pmos if input_n_or_p == "nfet" else nmos
    casc_fet = nmos if input_n_or_p == "nfet" else pmos

    m_inp = input_fet(pdk, width=input_width, length=input_length,
                      fingers=input_fingers, sd_rmult=sd_rmult)
    m_inn = input_fet(pdk, width=input_width, length=input_length,
                      fingers=input_fingers, sd_rmult=sd_rmult)
    m_cas = casc_fet(pdk, width=cascode_width, length=input_length,
                     fingers=cascode_fingers, sd_rmult=sd_rmult)
    m_load = load_fet(pdk, width=load_width, length=input_length,
                      fingers=load_fingers)

    r_inp = prec_ref_center(m_inp)
    r_inn = prec_ref_center(m_inn)
    r_cas = prec_ref_center(m_cas)
    r_load = prec_ref_center(m_load)
    top.add(r_inp); top.add(r_inn); top.add(r_cas); top.add(r_load)

    bbox_w = m_inp.bbox[1][0] - m_inp.bbox[0][0]
    bbox_h = m_inp.bbox[1][1] - m_inp.bbox[0][1]
    sep = pdk.get_grule("met2")["min_separation"]

    movex(r_inn, bbox_w + sep)
    movey(r_cas, -(bbox_h + sep))
    movex(r_cas, (bbox_w + sep) / 2)
    movey(r_load, bbox_h + sep)
    movex(r_load, (bbox_w + sep) / 2)

    top.add_ports(r_inp.get_ports_list(), prefix="inp_")
    top.add_ports(r_inn.get_ports_list(), prefix="inn_")
    top.add_ports(r_cas.get_ports_list(), prefix="casc_")
    top.add_ports(r_load.get_ports_list(), prefix="load_")

    top.info["netlist"] = Netlist(
        circuit_name="FOLDED_CASCODE_OTA",
        nodes=["INP", "INN", "OUT", "IBIAS", "VDD", "VSS"],
    )
    return rename_ports_by_orientation(top)
