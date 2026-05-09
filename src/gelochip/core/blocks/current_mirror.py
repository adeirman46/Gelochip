"""
Current mirror building blocks.

Available topologies:
    current_mirror          – Basic NMOS/PMOS diode-connected mirror
    cascode_current_mirror  – High-output-impedance cascode mirror
    wilson_current_mirror   – Wilson mirror (improved output impedance)

All functions return gdsfactory Components with ports:
    vbias  – Reference current input (diode-connected gate/drain)
    iout   – Mirror output (drain of copy transistor)
    vdd    – Supply rail (PMOS variants)
    vss    – Ground rail (NMOS variants)
"""
from __future__ import annotations
from typing import Optional

from gdsfactory.component import Component
from gdsfactory.cell import cell
from pydantic import validate_arguments

from gelochip.glayout.pdk.mappedpdk import MappedPDK
from gelochip.glayout.cells.elementary.current_mirror import current_mirror as _cm
from gelochip.glayout.primitives.fet import nmos, pmos
from gelochip.glayout.routing.c_route import c_route
from gelochip.glayout.routing.L_route import L_route
from gelochip.glayout.util.comp_utils import prec_ref_center, movex, movey
from gelochip.glayout.util.port_utils import add_ports_perimeter, rename_ports_by_orientation
from gelochip.glayout.spice.netlist import Netlist


@validate_arguments
def current_mirror(
    pdk: MappedPDK,
    *,
    mirror_ratio: float = 1.0,
    ref_width: float = 4.0,
    ref_length: Optional[float] = None,
    ref_fingers: int = 1,
    output_fingers: int = 1,
    n_or_p: str = "nfet",
    with_dummy: bool = True,
    sd_rmult: int = 1,
) -> Component:
    """
    Basic current mirror (diode-connected reference + copy transistor).

    Args:
        pdk:            Technology PDK.
        mirror_ratio:   W_copy / W_ref – sets the current multiplication factor.
        ref_width:      Reference transistor gate width per finger (µm).
        ref_length:     Gate length (µm), defaults to PDK minimum.
        ref_fingers:    Number of fingers in reference transistor.
        output_fingers: Number of fingers in copy transistor.
        n_or_p:         "nfet" (NMOS, current sink) or "pfet" (PMOS, current source).
        with_dummy:     Add dummy edge fingers for better matching.
        sd_rmult:       S/D via array multiplier (higher current handling).

    Returns:
        Component with ports:
            vbias_N   – Reference drain/gate (connect to I_ref source)
            iout_N    – Copy drain  (mirror output)
            vss_S     – Ground (NMOS) or VDD (PMOS)

    Example::

        from gelochip.glayout.pdk.gf180_mapped import gf180_mapped_pdk as pdk
        cm = current_mirror(pdk, mirror_ratio=2.0, ref_width=4.0, n_or_p="nfet")
        cm.show()
    """
    ref_length = ref_length or pdk.get_grule("poly")["min_width"]
    copy_width = ref_width * mirror_ratio

    return _cm(
        pdk=pdk,
        numcols=2,
        device=n_or_p,
        width=ref_width,
        length=ref_length,
        fingers=ref_fingers,
        multipliers=1,
        with_dummy=(with_dummy, with_dummy),
        sd_rmult=sd_rmult,
    )


@validate_arguments
def cascode_current_mirror(
    pdk: MappedPDK,
    *,
    mirror_ratio: float = 1.0,
    ref_width: float = 4.0,
    cascode_width: float = 2.0,
    ref_length: Optional[float] = None,
    fingers: int = 1,
    n_or_p: str = "nfet",
    with_dummy: bool = True,
    sd_rmult: int = 1,
) -> Component:
    """
    Cascode (high-swing) current mirror.

    Two stacked transistor rows: main mirror + cascode transistors above.
    Provides higher output impedance (Rout ≈ gm·ro²) than a basic mirror.

    Args:
        pdk:            Technology PDK.
        mirror_ratio:   W_copy / W_ref.
        ref_width:      Main transistor width (µm).
        cascode_width:  Cascode transistor width (µm). Typically ≤ ref_width.
        ref_length:     Gate length (µm).
        fingers:        Gate fingers per device.
        n_or_p:         "nfet" or "pfet".
        with_dummy:     Dummy edge fingers.
        sd_rmult:       S/D via multiplier.

    Returns:
        Component with ports: vbias_*, iout_*, vbias_cas_*, vss_* (or vdd_*)

    Topology (NMOS)::

        VDD             VDD
         |               |
        [M_ref_cas]    [M_copy_cas]   ← cascode row
         |               |
        [M_ref_main]   [M_copy_main]  ← main mirror row
         |               |
        VSS             VSS
    """
    ref_length = ref_length or pdk.get_grule("poly")["min_width"]

    top = Component("cascode_current_mirror")

    main_ref = nmos(pdk, width=ref_width, length=ref_length, fingers=fingers,
                    with_dummy=(with_dummy, with_dummy), sd_rmult=sd_rmult) \
        if n_or_p == "nfet" else \
        pmos(pdk, width=ref_width, length=ref_length, fingers=fingers,
             with_dummy=(with_dummy, with_dummy), sd_rmult=sd_rmult)

    main_copy = nmos(pdk, width=ref_width * mirror_ratio, length=ref_length,
                     fingers=fingers, with_dummy=(with_dummy, with_dummy), sd_rmult=sd_rmult) \
        if n_or_p == "nfet" else \
        pmos(pdk, width=ref_width * mirror_ratio, length=ref_length,
             fingers=fingers, with_dummy=(with_dummy, with_dummy), sd_rmult=sd_rmult)

    cas_ref = nmos(pdk, width=cascode_width, length=ref_length, fingers=fingers,
                   with_dummy=(with_dummy, with_dummy)) \
        if n_or_p == "nfet" else \
        pmos(pdk, width=cascode_width, length=ref_length, fingers=fingers,
             with_dummy=(with_dummy, with_dummy))

    cas_copy = nmos(pdk, width=cascode_width * mirror_ratio, length=ref_length,
                    fingers=fingers, with_dummy=(with_dummy, with_dummy)) \
        if n_or_p == "nfet" else \
        pmos(pdk, width=cascode_width * mirror_ratio, length=ref_length,
             fingers=fingers, with_dummy=(with_dummy, with_dummy))

    mr_ref = prec_ref_center(main_ref)
    mr_copy = prec_ref_center(main_copy)
    cr_ref = prec_ref_center(cas_ref)
    cr_copy = prec_ref_center(cas_copy)

    top.add(mr_ref)
    top.add(mr_copy)
    top.add(cr_ref)
    top.add(cr_copy)

    bbox = main_ref.bbox
    x_spacing = (bbox[1][0] - bbox[0][0]) + pdk.get_grule("met2")["min_separation"]
    y_spacing = (bbox[1][1] - bbox[0][1]) + pdk.get_grule("met2")["min_separation"]

    movex(mr_copy, x_spacing)
    movey(cr_ref, y_spacing)
    movex(cr_copy, x_spacing)
    movey(cr_copy, y_spacing)

    top.add_ports(mr_ref.get_ports_list(), prefix="ref_main_")
    top.add_ports(mr_copy.get_ports_list(), prefix="copy_main_")
    top.add_ports(cr_ref.get_ports_list(), prefix="ref_cas_")
    top.add_ports(cr_copy.get_ports_list(), prefix="copy_cas_")

    return rename_ports_by_orientation(top)


@validate_arguments
def wilson_current_mirror(
    pdk: MappedPDK,
    *,
    mirror_ratio: float = 1.0,
    ref_width: float = 4.0,
    ref_length: Optional[float] = None,
    fingers: int = 1,
    n_or_p: str = "nfet",
) -> Component:
    """
    Wilson current mirror.

    Uses negative feedback (third transistor M3) to boost output impedance
    and reduce the effect of finite β (β²·ro compared to ro for basic mirror).

    Args:
        pdk:          Technology PDK.
        mirror_ratio: Copy / reference width ratio.
        ref_width:    Reference transistor width (µm).
        ref_length:   Gate length (µm).
        fingers:      Gate fingers per device.
        n_or_p:       "nfet" or "pfet".

    Returns:
        Component with ports: iin_*, iout_*, vss_* (or vdd_*)

    Topology (NMOS)::

        IOUT ──── drain(M3)
                       │
                  gate(M3) = drain(M1) = gate(M2)
                       │
                  source(M3) = drain(M2)
                       │
                  source(M2)     source(M1)
                       │               │
                      VSS            VSS
    """
    ref_length = ref_length or pdk.get_grule("poly")["min_width"]
    top = Component("wilson_current_mirror")

    fet_fn = nmos if n_or_p == "nfet" else pmos

    m1 = fet_fn(pdk, width=ref_width, length=ref_length, fingers=fingers)
    m2 = fet_fn(pdk, width=ref_width * mirror_ratio, length=ref_length, fingers=fingers)
    m3 = fet_fn(pdk, width=ref_width * mirror_ratio, length=ref_length, fingers=fingers)

    r1 = prec_ref_center(m1)
    r2 = prec_ref_center(m2)
    r3 = prec_ref_center(m3)
    top.add(r1); top.add(r2); top.add(r3)

    bbox_w = m1.bbox[1][0] - m1.bbox[0][0]
    bbox_h = m1.bbox[1][1] - m1.bbox[0][1]
    sep = pdk.get_grule("met2")["min_separation"]

    movex(r2, bbox_w + sep)
    movey(r3, bbox_h + sep)
    movex(r3, bbox_w + sep)

    top.add_ports(r1.get_ports_list(), prefix="m1_")
    top.add_ports(r2.get_ports_list(), prefix="m2_")
    top.add_ports(r3.get_ports_list(), prefix="m3_")

    top.info["netlist"] = Netlist(
        circuit_name="WILSON_CMIRROR",
        nodes=["IIN", "IOUT", "VSS" if n_or_p == "nfet" else "VDD"],
    )

    return rename_ports_by_orientation(top)
