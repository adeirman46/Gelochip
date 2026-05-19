"""
Operational amplifier cells.

    two_stage_opamp        – Classic 2-stage Miller-compensated OTA
    folded_cascode_opamp   – Folded-cascode OTA with rail-to-rail input
"""
from __future__ import annotations
from typing import Optional

from gdsfactory.component import Component

from glayout.pdk.mappedpdk import MappedPDK
from glayout.cells.composite.opamp import opamp as _opamp
from glayout.spice.netlist import Netlist


def two_stage_opamp(
    pdk: MappedPDK,
    *,
    # Stage 1: differential pair
    diff_pair_width: float = 6.0,
    diff_pair_length: Optional[float] = None,
    diff_pair_fingers: int = 4,
    # Stage 1: tail current
    tail_width: float = 2.0,
    tail_fingers: int = 1,
    # Stage 1: PMOS load
    pload_width: float = 6.0,
    pload_fingers: int = 4,
    # Stage 2: common-source
    cs_width: float = 4.0,
    cs_fingers: int = 2,
    # Miller compensation
    miller_cap_size: tuple[float, float] = (4.0, 4.0),
    # Output stage
    out_res_width: float = 1.0,
    sd_rmult: int = 1,
    with_antenna_diode: bool = False,
) -> Component:
    """
    Two-stage Miller-compensated operational transconductance amplifier (OTA).

    Architecture::

        VDD
         │
       (PMOS stacked current mirror load) ──┐
         │                                   │
       (NMOS diff pair) ──────────────────── Vout1
         │                                   │
       (tail NMOS)                    [Miller Cc]
         │                                   │
        VSS                          (CS NMOS stage 2)
                                            │
                                          VOUT

    Args:
        pdk:              Technology PDK.
        diff_pair_width:  Input diff-pair transistor width (µm).
        diff_pair_length: Gate length (µm).
        diff_pair_fingers: Input diff-pair gate fingers.
        tail_width:       Tail current transistor width (µm).
        tail_fingers:     Tail current transistor fingers.
        pload_width:      PMOS stacked mirror load width (µm).
        pload_fingers:    PMOS load gate fingers.
        cs_width:         Second-stage common-source transistor width (µm).
        cs_fingers:       Second-stage gate fingers.
        miller_cap_size:  (width, height) of Miller compensation capacitor (µm).
        out_res_width:    Output resistor width for stability (µm).
        sd_rmult:         S/D via multiplier.
        with_antenna_diode: Add antenna diode protection on diff inputs.

    Returns:
        Component with ports:
            inp_gate_*   – Non-inverting input (+)
            inn_gate_*   – Inverting input (−)
            out_*        – Op-amp output
            vbias_*      – External bias input
            vdd_*, vss_*

    Example::

        from glayout.pdk.gf180_mapped import gf180_mapped_pdk as pdk
        oa = two_stage_opamp(pdk, diff_pair_width=6.0, diff_pair_fingers=4)
        oa.write_gds("opamp.gds")
    """
    diff_pair_length = diff_pair_length or pdk.get_grule("poly")["min_width"]

    return _opamp(
        pdk=pdk,
        half_diffpair_params=(diff_pair_width, diff_pair_length, diff_pair_fingers),
        diffpair_bias=(tail_width, diff_pair_length, tail_fingers),
        half_common_source_params=(cs_width, diff_pair_length, cs_fingers, sd_rmult),
        half_common_source_bias=(pload_width, diff_pair_length, pload_fingers, sd_rmult),
        rmult=sd_rmult,
        with_antenna_diode_on_diffinputs=int(with_antenna_diode),
        miller_cap_size=miller_cap_size,
        miller_cap_rmult=sd_rmult,
    )


def folded_cascode_opamp(
    pdk: MappedPDK,
    *,
    input_width: float = 6.0,
    input_length: Optional[float] = None,
    input_fingers: int = 4,
    cascode_width: float = 4.0,
    cascode_fingers: int = 4,
    load_width: float = 6.0,
    load_fingers: int = 4,
    bias_width: float = 2.0,
    miller_cap_size: tuple[float, float] = (5.0, 5.0),
    sd_rmult: int = 1,
) -> Component:
    """
    Folded-cascode OTA.

    Higher gain than two-stage (A ≈ gm1·(ro2||ro4)·gm3·ro3) and inherently
    frequency-compensated (single dominant pole).  Better suited for
    high-speed applications than the Miller OTA.

    Args:
        pdk:            Technology PDK.
        input_width:    NMOS diff-pair input transistor width (µm).
        input_length:   Gate length (µm).
        input_fingers:  Input transistor fingers.
        cascode_width:  NMOS cascode transistor width (µm).
        cascode_fingers: Cascode transistor fingers.
        load_width:     PMOS cascode load width (µm).
        load_fingers:   Load transistor fingers.
        bias_width:     Bias current mirror transistor width (µm).
        miller_cap_size: Compensation capacitor (µm × µm).
        sd_rmult:       S/D via multiplier.

    Returns:
        Component with ports: inp_*, inn_*, out_*, ibias_*, vdd_*, vss_*
    """
    from core.blocks.diff_pair import folded_cascode
    from core.blocks.current_mirror import current_mirror
    from glayout.util.comp_utils import prec_ref_center, movex, movey
    from glayout.util.port_utils import rename_ports_by_orientation

    input_length = input_length or pdk.get_grule("poly")["min_width"]
    top = Component("folded_cascode_opamp")

    fc = folded_cascode(
        pdk,
        input_width=input_width,
        input_length=input_length,
        input_fingers=input_fingers,
        cascode_width=cascode_width,
        cascode_fingers=cascode_fingers,
        load_width=load_width,
        load_fingers=load_fingers,
        input_n_or_p="nfet",
        sd_rmult=sd_rmult,
    )
    cm = current_mirror(pdk, mirror_ratio=1.0, ref_width=bias_width,
                        n_or_p="pfet", sd_rmult=sd_rmult)

    r_fc = prec_ref_center(fc)
    r_cm = prec_ref_center(cm)
    top.add(r_fc); top.add(r_cm)

    bbox_w = fc.bbox[1][0] - fc.bbox[0][0]
    sep = pdk.get_grule("met2")["min_separation"]
    movex(r_cm, -(bbox_w + sep) / 2)

    top.add_ports(r_fc.get_ports_list(), prefix="fc_")
    top.add_ports(r_cm.get_ports_list(), prefix="bias_")

    top.info["netlist"] = Netlist(
        circuit_name="FOLDED_CASCODE_OPAMP",
        nodes=["INP", "INN", "OUT", "IBIAS", "VDD", "VSS"],
    )
    return rename_ports_by_orientation(top)
