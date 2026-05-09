"""
Mixer cells.

    gilbert_cell_mixer – Gilbert cell double-balanced active mixer
    passive_mixer      – CMOS passive (current-commutating) mixer

Gilbert cell is the workhorse for up/down conversion in RF ICs.
Passive mixer trades gain for linearity and noise.
"""
from __future__ import annotations
from typing import Optional

from gdsfactory.component import Component
from pydantic import validate_arguments

from gelochip.glayout.pdk.mappedpdk import MappedPDK
from gelochip.glayout.primitives.fet import nmos, pmos
from gelochip.glayout.util.comp_utils import prec_ref_center, movex, movey
from gelochip.glayout.util.port_utils import rename_ports_by_orientation
from gelochip.glayout.spice.netlist import Netlist
from gelochip.core.blocks.diff_pair import diff_pair
from gelochip.core.blocks.current_mirror import current_mirror


@validate_arguments
def gilbert_cell_mixer(
    pdk: MappedPDK,
    *,
    # RF transconductance pair (bottom)
    rf_width: float = 10.0,
    rf_length: Optional[float] = None,
    rf_fingers: int = 4,
    # LO switching quad (middle)
    lo_width: float = 6.0,
    lo_length: Optional[float] = None,
    lo_fingers: int = 2,
    # PMOS load
    load_width: float = 10.0,
    load_fingers: int = 4,
    # Tail current bias
    tail_width: float = 4.0,
    tail_fingers: int = 2,
    sd_rmult: int = 1,
) -> Component:
    """
    Gilbert cell double-balanced active mixer.

    Provides conversion gain (Gc ≈ 2/π · gm_rf · Rload), good port isolation,
    and suppresses even-order distortion products.

    Topology::

        VDD
         ├───────────────┤
       [PMOS load+]    [PMOS load-]
         │                │
       M_lo1  M_lo2    M_lo3  M_lo4  ← LO switching quad
         │       └────────┘    │
         └────────────────────-┘
                    │
              M_rf+ | M_rf-          ← RF Gm diff pair
                    │
                [I_tail]
                    │
                  VSS

    Args:
        pdk:           Technology PDK.
        rf_width:      RF Gm transistor width per finger (µm).
        rf_length:     RF transistor gate length (µm).
        rf_fingers:    RF transistor gate fingers.
        lo_width:      LO switching transistor width per finger (µm).
        lo_length:     LO transistor gate length (µm).
        lo_fingers:    LO transistor gate fingers.
        load_width:    PMOS load transistor width per finger (µm).
        load_fingers:  PMOS load transistor fingers.
        tail_width:    Tail current transistor width (µm).
        tail_fingers:  Tail current transistor fingers.
        sd_rmult:      S/D via multiplier.

    Returns:
        Component with ports:
            rfp_gate_*  – RF differential input (+)
            rfn_gate_*  – RF differential input (−)
            lop_gate_*  – LO differential input (+)
            lon_gate_*  – LO differential input (−)
            ifp_*       – IF output (+)
            ifn_*       – IF output (−)
            vbias_*     – Tail current bias
            vdd_*, vss_*

    Example::

        gc = gilbert_cell_mixer(pdk, rf_width=10.0, rf_fingers=4)
        gc.show()
    """
    rf_length = rf_length or pdk.get_grule("poly")["min_width"]
    lo_length = lo_length or rf_length
    top = Component("gilbert_cell_mixer")

    m_rfp = nmos(pdk, width=rf_width, length=rf_length, fingers=rf_fingers, sd_rmult=sd_rmult)
    m_rfn = nmos(pdk, width=rf_width, length=rf_length, fingers=rf_fingers, sd_rmult=sd_rmult)
    m_lo1 = nmos(pdk, width=lo_width, length=lo_length, fingers=lo_fingers)
    m_lo2 = nmos(pdk, width=lo_width, length=lo_length, fingers=lo_fingers)
    m_lo3 = nmos(pdk, width=lo_width, length=lo_length, fingers=lo_fingers)
    m_lo4 = nmos(pdk, width=lo_width, length=lo_length, fingers=lo_fingers)
    m_loadp = pmos(pdk, width=load_width, length=rf_length, fingers=load_fingers)
    m_loadn = pmos(pdk, width=load_width, length=rf_length, fingers=load_fingers)
    m_tail = nmos(pdk, width=tail_width, length=rf_length, fingers=tail_fingers)

    sep = pdk.get_grule("met2")["min_separation"]
    rf_bbox_w = m_rfp.bbox[1][0] - m_rfp.bbox[0][0]
    rf_bbox_h = m_rfp.bbox[1][1] - m_rfp.bbox[0][1]
    lo_bbox_h = m_lo1.bbox[1][1] - m_lo1.bbox[0][1]

    r_rfp  = prec_ref_center(m_rfp);   top.add(r_rfp)
    r_rfn  = prec_ref_center(m_rfn);   top.add(r_rfn)
    r_lo1  = prec_ref_center(m_lo1);   top.add(r_lo1)
    r_lo2  = prec_ref_center(m_lo2);   top.add(r_lo2)
    r_lo3  = prec_ref_center(m_lo3);   top.add(r_lo3)
    r_lo4  = prec_ref_center(m_lo4);   top.add(r_lo4)
    r_ldp  = prec_ref_center(m_loadp); top.add(r_ldp)
    r_ldn  = prec_ref_center(m_loadn); top.add(r_ldn)
    r_tail = prec_ref_center(m_tail);  top.add(r_tail)

    movex(r_rfn,  rf_bbox_w + sep)
    movey(r_lo1,  rf_bbox_h + sep)
    movex(r_lo2,  rf_bbox_w / 2 + sep / 2);  movey(r_lo2, rf_bbox_h + sep)
    movex(r_lo3,  rf_bbox_w + sep);          movey(r_lo3, rf_bbox_h + sep)
    movex(r_lo4,  3 * (rf_bbox_w / 2 + sep / 2)); movey(r_lo4, rf_bbox_h + sep)
    movey(r_ldp,  rf_bbox_h + lo_bbox_h + 2 * sep)
    movex(r_ldn,  rf_bbox_w + sep); movey(r_ldn, rf_bbox_h + lo_bbox_h + 2 * sep)
    movey(r_tail, -(rf_bbox_h + sep))
    movex(r_tail, rf_bbox_w / 2)

    for ref, prefix in [
        (r_rfp, "rfp_"), (r_rfn, "rfn_"),
        (r_lo1, "lo1_"), (r_lo2, "lo2_"), (r_lo3, "lo3_"), (r_lo4, "lo4_"),
        (r_ldp, "loadp_"), (r_ldn, "loadn_"), (r_tail, "tail_"),
    ]:
        top.add_ports(ref.get_ports_list(), prefix=prefix)

    top.info["specs"] = {
        "topology": "gilbert_cell",
        "reference": "Gilbert, JSSC 1968",
    }
    top.info["netlist"] = Netlist(
        circuit_name="GILBERT_CELL_MIXER",
        nodes=["RFP", "RFN", "LOP", "LON", "IFP", "IFN", "VBIAS", "VDD", "VSS"],
    )
    return rename_ports_by_orientation(top)


@validate_arguments
def passive_mixer(
    pdk: MappedPDK,
    *,
    switch_width: float = 4.0,
    switch_length: Optional[float] = None,
    switch_fingers: int = 4,
    n_or_p: str = "nfet",
) -> Component:
    """
    CMOS passive (current-commutating) mixer.

    Four-transistor H-bridge switch driven by differential LO.
    Higher linearity than Gilbert cell (no Gm stage), zero DC current,
    but conversion loss ~3 dB.

    Topology::

        RF+ ─── [M1]─── IF+
                  ╲  ╱
                   ╲╱  LO± switching
                   ╱╲
                 ╱    ╲
        RF- ─── [M2]─── IF-

    Args:
        pdk:             Technology PDK.
        switch_width:    Switch transistor width per finger (µm).
        switch_length:   Gate length (µm).
        switch_fingers:  Gate fingers per switch transistor.
        n_or_p:          "nfet" or "pfet" switch (or "cmos" for transmission gates).

    Returns:
        Component with ports:
            rfp_*, rfn_* – RF input differential
            lop_*, lon_* – LO differential drive
            ifp_*, ifn_* – IF output
    """
    switch_length = switch_length or pdk.get_grule("poly")["min_width"]
    top = Component("passive_mixer")
    fet_fn = nmos if n_or_p == "nfet" else pmos

    m1 = fet_fn(pdk, width=switch_width, length=switch_length, fingers=switch_fingers)
    m2 = fet_fn(pdk, width=switch_width, length=switch_length, fingers=switch_fingers)
    m3 = fet_fn(pdk, width=switch_width, length=switch_length, fingers=switch_fingers)
    m4 = fet_fn(pdk, width=switch_width, length=switch_length, fingers=switch_fingers)

    sep = pdk.get_grule("met2")["min_separation"]
    bbox_w = m1.bbox[1][0] - m1.bbox[0][0]
    bbox_h = m1.bbox[1][1] - m1.bbox[0][1]

    r1 = prec_ref_center(m1); top.add(r1)
    r2 = prec_ref_center(m2); top.add(r2); movex(r2, bbox_w + sep)
    r3 = prec_ref_center(m3); top.add(r3); movey(r3, bbox_h + sep)
    r4 = prec_ref_center(m4); top.add(r4); movex(r4, bbox_w + sep); movey(r4, bbox_h + sep)

    for ref, prefix in [(r1, "m1_"), (r2, "m2_"), (r3, "m3_"), (r4, "m4_")]:
        top.add_ports(ref.get_ports_list(), prefix=prefix)

    top.info["netlist"] = Netlist(
        circuit_name="PASSIVE_MIXER",
        nodes=["RFP", "RFN", "LOP", "LON", "IFP", "IFN"],
    )
    return rename_ports_by_orientation(top)
