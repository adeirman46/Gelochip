"""
Pre-built analog blocks accessible as gl.inverter(), gl.current_mirror(), etc.
Each returns a DeviceProxy so its terminals can be wired into a parent Circuit.

Usage::

    with gl.Circuit("opamp_stage", pdk) as c:
        cm   = c.block(gl.current_mirror(pdk, ratio=2, w=4, n_or_p="nfet"), tag="cm")
        dp   = c.block(gl.diff_pair(pdk, w=3, fingers=4), tag="dp")

        c.vbias >> cm.vbias
        cm.iout  >> dp.vtail
        c.vp     >> dp.inp
        c.vn     >> dp.inn
        ...

    result = c.build()
"""
from __future__ import annotations

from typing import Optional

from gdsfactory.component import Component
from glayout.pdk.mappedpdk import MappedPDK


def inverter(
    pdk: MappedPDK,
    *,
    wp: float = 4.0,
    wn: float = 2.0,
    l: Optional[float] = None,
    fingers: int = 1,
    **kwargs,
) -> Component:
    """
    CMOS inverter: PMOS (pull-up) + NMOS (pull-down).

    Terminals on the returned Component:
        pin_vin, pin_vout, pin_vdd, pin_gnd
    """
    from glayout.primitives.fet import nmos, pmos
    from glayout.routing.smart_route import smart_route
    from glayout.util.port_utils import rename_ports_by_orientation
    from glayout.util.snap_to_grid import component_snap_to_grid
    import gdsfactory as gf

    length = l or pdk.get_grule("poly")["min_width"]
    sep = pdk.util_max_metal_seperation() * 4

    top = gf.Component("INVERTER")
    mp_comp = rename_ports_by_orientation(
        pmos(pdk, width=wp, length=length, fingers=fingers, with_substrate_tap=False, **kwargs)
    )
    mn_comp = rename_ports_by_orientation(
        nmos(pdk, width=wn, length=length, fingers=fingers, with_substrate_tap=False, **kwargs)
    )

    mp_ref = top << mp_comp
    mn_ref = top << mn_comp

    # Stack PMOS above NMOS
    mn_ref.movey(0)
    mp_ref.movey(mn_ref.ymax + sep)

    # Route: gate-to-gate (vin)
    try:
        top << smart_route(pdk, mp_ref.ports["gate_S"], mn_ref.ports["gate_N"])
    except Exception:
        pass

    # Route: drain-to-drain (vout)
    try:
        top << smart_route(pdk, mp_ref.ports["drain_S"], mn_ref.ports["drain_N"])
    except Exception:
        pass

    # Expose pins
    for src, pin in [
        ("gate_W", "pin_vin"),
        ("drain_E", "pin_vout"),
    ]:
        try:
            top.add_port(name=pin, port=mn_ref.ports[src])
        except Exception:
            pass
    try:
        top.add_port(name="pin_vdd", port=mp_ref.ports["source_N"])
    except Exception:
        pass
    try:
        top.add_port(name="pin_gnd", port=mn_ref.ports["source_S"])
    except Exception:
        pass

    return component_snap_to_grid(rename_ports_by_orientation(top))


def current_mirror(
    pdk: MappedPDK,
    *,
    ratio: float = 1.0,
    w: float = 4.0,
    l: Optional[float] = None,
    fingers: int = 1,
    n_or_p: str = "nfet",
    **kwargs,
) -> Component:
    """
    Basic current mirror (diode-connected reference + copy transistor).

    Terminals: pin_vbias (ref), pin_iout (copy drain), pin_vss / pin_vdd
    """
    from glayout.cells.elementary.current_mirror import current_mirror as _cm
    from glayout.util.port_utils import rename_ports_by_orientation

    length = l or pdk.get_grule("poly")["min_width"]
    comp = _cm(
        pdk,
        numcols=2,
        device=n_or_p,
        width=w,
        length=length,
        fingers=fingers,
        multipliers=1,
        with_dummy=(True, True),
    )
    return rename_ports_by_orientation(comp)


def diff_pair(
    pdk: MappedPDK,
    *,
    w: float = 3.0,
    l: Optional[float] = None,
    fingers: int = 4,
    n_or_p: bool = True,
    **kwargs,
) -> Component:
    """
    Differential pair (common-centroid ABBA placement).

    Terminals: pin_vp (plus), pin_vn (minus), pin_vtail, pin_vdd1/2
    """
    from glayout.cells.elementary.diff_pair.diff_pair import diff_pair as _dp

    length = l or pdk.get_grule("poly")["min_width"]
    return _dp(pdk, width=w, fingers=fingers, length=length, n_or_p_fet=n_or_p, **kwargs)
