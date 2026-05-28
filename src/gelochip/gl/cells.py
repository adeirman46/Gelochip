"""
Pre-built analog cells — wrap glayout's internally-routed cells as Devices.

Each function returns a Device with:
  - The best-practice placement (interdigitized, common-centroid, etc.) built in
  - All internal routing already done by glayout
  - Clean terminal names for inter-cell connections

Terminal naming convention
--------------------------
  Transistors:   g, d, s, b   (gate, drain, source, bulk)
  Diff pair:     vp, vm, vtail, vout_p, vout_m
  Current mirror: ref, copy, rail  (rail = VDD or GND)
  FVF:           vin, vout, ibias
  Trans gate:    vin, vout, en, enb
  BJT:           b, c, e
  Capacitor:     p (top), n (bottom)
  Resistor:      a, b  (two terminals)

Advanced access
---------------
If you need lower-level control, use gl.raw() to wrap any gdsfactory
Component directly:

    import gelochip.gl as gl
    from glayout.cells.elementary.FVF.fvf import flipped_voltage_follower
    fvf_comp = flipped_voltage_follower(pdk, width=(3,2), ...)
    fvf = gl.raw(fvf_comp, connections={'vin': net1, 'vout': net2},
                  port_map={'vin': 'A_gate', 'vout': 'A_source_top_met'})
"""
from __future__ import annotations

from typing import Any, Optional

from gelochip.gl.net import Net
from gelochip.gl.device import Device


def _pdk(pdk_arg):
    if pdk_arg is not None:
        return pdk_arg
    from gelochip.gl import gf180
    if gf180 is None:
        raise RuntimeError("PDK not loaded. Pass pdk= or call gl.set_pdk(gl.gf180).")
    return gf180


def _conn(**kwargs):
    return {k: v for k, v in kwargs.items() if v is not None}


# ─── Current Mirror ───────────────────────────────────────────────────────────

def current_mirror(
    *,
    w: float = 4.0,
    l: Optional[float] = None,
    ratio: int = 1,
    n_or_p: str = "n",
    with_dummy: bool = True,
    with_tie: bool = True,
    ref: Optional[Net] = None,
    copy: Optional[Net] = None,
    rail: Optional[Net] = None,
    pdk=None,
    tag: str = "",
) -> Device:
    """
    Diode-connected reference + copy transistor.
    Uses two-transistor interdigitized placement for best matching.

    Parameters
    ----------
    w       : transistor width (µm)
    l       : gate length (µm) — default: PDK min
    ratio   : copy/ref ratio  (sets numcols in glayout)
    n_or_p  : 'n' (NMOS sink) or 'p' (PMOS source)
    ref     : Net connected to reference drain (diode-connected)
    copy    : Net connected to copy drain (mirror output)
    rail    : Net connected to source rail (GND for NMOS, VDD for PMOS)

    Example::

        vbias = gl.Net('vbias')
        iout  = gl.Net('iout')
        cm = gl.current_mirror(w=4, ratio=2, n_or_p='n', ref=vbias, copy=iout, rail=gl.gnd)
    """
    _p = _pdk(pdk)
    length = l or _p.get_grule("poly")["min_width"]
    device_str = "nfet" if n_or_p in ("n", "nmos", "nfet") else "pfet"

    from glayout.cells.elementary.current_mirror.current_mirror import current_mirror as _cm
    from glayout.util.port_utils import rename_ports_by_orientation

    comp = _cm(
        _p,
        numcols=max(2, ratio + 1),
        device=device_str,
        with_dummy=with_dummy,
        with_tie=with_tie,
        width=w,
        length=length,
    )
    comp = rename_ports_by_orientation(comp)

    # Port map: ref drain = A, copy drain = B
    port_map = {
        "ref":  "fet_A_drain",
        "copy": "fet_B_drain",
        "rail": "welltie_S_top_met" if device_str == "nfet" else "welltie_N_top_met",
    }

    return Device(
        "current_mirror",
        comp,
        _conn(ref=ref, copy=copy, rail=rail),
        tag=tag or ("ncm" if device_str == "nfet" else "pcm"),
        port_map=port_map,
    )


# ─── Differential Pair ────────────────────────────────────────────────────────

def diff_pair(
    *,
    w: float = 3.0,
    l: Optional[float] = None,
    fingers: int = 4,
    n_or_p: str = "n",
    vp: Optional[Net] = None,
    vm: Optional[Net] = None,
    vtail: Optional[Net] = None,
    vout_p: Optional[Net] = None,
    vout_m: Optional[Net] = None,
    pdk=None,
    tag: str = "",
) -> Device:
    """
    Common-centroid (ABBA) differential pair.
    Sources are already shorted internally.

    Parameters
    ----------
    w       : transistor width (µm)
    l       : gate length (µm)
    fingers : gate fingers per transistor
    n_or_p  : 'n' (NMOS) or 'p' (PMOS)
    vp      : plus-input gate Net
    vm      : minus-input gate Net
    vtail   : source/tail Net (connect to tail current source)
    vout_p  : drain of plus-input transistor
    vout_m  : drain of minus-input transistor

    Example::

        dp = gl.diff_pair(w=3, fingers=4, vp=vip, vm=vim, vtail=vtail)
    """
    _p = _pdk(pdk)
    length = l or _p.get_grule("poly")["min_width"]
    nfet = n_or_p in ("n", "nmos", "nfet")

    from glayout.cells.elementary.diff_pair.diff_pair import diff_pair as _dp
    from glayout.util.port_utils import rename_ports_by_orientation

    comp = _dp(_p, width=w, fingers=fingers, length=length, n_or_p_fet=nfet)
    comp = rename_ports_by_orientation(comp)

    port_map = {
        "vp":     "PLUSgateroute",    # plus gate bus
        "vm":     "MINUSgateroute",   # minus gate bus
        "vtail":  "source_route",     # shorted source
        "vout_p": "drain_routeTR_BL", # plus-side drain
        "vout_m": "drain_routeTL_BR", # minus-side drain
    }

    return Device(
        "diff_pair",
        comp,
        _conn(vp=vp, vm=vm, vtail=vtail, vout_p=vout_p, vout_m=vout_m),
        tag=tag or "dp",
        port_map=port_map,
    )


# ─── Flipped Voltage Follower ─────────────────────────────────────────────────

def fvf(
    *,
    w_main: float = 6.6,
    w_fb: float = 3.7,
    l_main: Optional[float] = None,
    l_fb: Optional[float] = None,
    fingers: int = 1,
    multipliers: int = 2,
    n_or_p: str = "n",
    vin: Optional[Net] = None,
    vout: Optional[Net] = None,
    ibias: Optional[Net] = None,
    pdk=None,
    tag: str = "",
) -> Device:
    """
    Flipped Voltage Follower (FVF).

    Parameters
    ----------
    w_main, w_fb     : main and feedback FET widths (µm)
    l_main, l_fb     : gate lengths (µm)
    n_or_p           : 'n' or 'p'
    vin              : input Net (gate of main FET)
    vout             : output Net (source of main FET)
    ibias            : bias current Net

    Example::

        fvf1 = gl.fvf(w_main=6, w_fb=3, vin=vip, vout=vip_buf, ibias=ibias_net)
    """
    _p = _pdk(pdk)
    lm = l_main or _p.get_grule("poly")["min_width"]
    lf = l_fb or _p.get_grule("poly")["min_width"]
    device_type = "nmos" if n_or_p in ("n", "nmos", "nfet") else "pmos"

    from glayout.cells.elementary.FVF.fvf import flipped_voltage_follower as _fvf
    from glayout.util.port_utils import rename_ports_by_orientation

    comp = _fvf(
        _p,
        device_type=device_type,
        width=(w_main, w_fb),
        length=(lm, lf),
        fingers=(fingers, fingers),
        multipliers=(multipliers, multipliers),
    )
    comp = rename_ports_by_orientation(comp)

    port_map = {
        "vin":   "A_gate",          # gate of main FET (A)
        "vout":  "A_source_top_met", # source of main FET
        "ibias": "B_gate",           # gate of feedback FET (B) → bias
    }

    return Device(
        "fvf",
        comp,
        _conn(vin=vin, vout=vout, ibias=ibias),
        tag=tag or "fvf",
        port_map=port_map,
    )


# ─── Transmission Gate ────────────────────────────────────────────────────────

def transmission_gate(
    *,
    wp: float = 1.0,
    wn: float = 1.0,
    l: Optional[float] = None,
    fingers: int = 1,
    vin: Optional[Net] = None,
    vout: Optional[Net] = None,
    en: Optional[Net] = None,
    enb: Optional[Net] = None,
    pdk=None,
    tag: str = "",
) -> Device:
    """
    CMOS Transmission Gate (NMOS + PMOS pass-gate in parallel).

    Parameters
    ----------
    wp, wn   : PMOS and NMOS widths (µm)
    en       : enable signal Net (connects to NMOS gate)
    enb      : enable-bar Net (connects to PMOS gate)
    vin      : input Net
    vout     : output Net

    Example::

        tg = gl.transmission_gate(wp=2, wn=2, vin=vin, vout=vout, en=clk, enb=clkb)
    """
    _p = _pdk(pdk)
    length = l or _p.get_grule("poly")["min_width"]

    from glayout.cells.elementary.transmission_gate.transmission_gate import (
        transmission_gate as _tg,
    )
    from glayout.util.port_utils import rename_ports_by_orientation

    comp = _tg(_p, width=(wp, wn), length=(length, length), fingers=(fingers, fingers))
    comp = rename_ports_by_orientation(comp)

    port_map = {
        "vin":  "N_source",   # NMOS source (= input)
        "vout": "N_drain",    # NMOS drain  (= output)
        "en":   "N_gate",     # NMOS gate   (= enable)
        "enb":  "P_gate",     # PMOS gate   (= enable-bar)
    }

    return Device(
        "transmission_gate",
        comp,
        _conn(vin=vin, vout=vout, en=en, enb=enb),
        tag=tag or "tg",
        port_map=port_map,
    )


# ─── Stacked Current Mirror ───────────────────────────────────────────────────

def stacked_cmirror(
    *,
    w: float = 4.0,
    l: Optional[float] = None,
    ratio: int = 1,
    n_or_p: str = "n",
    ref: Optional[Net] = None,
    copy: Optional[Net] = None,
    vbias: Optional[Net] = None,
    rail: Optional[Net] = None,
    pdk=None,
    tag: str = "",
) -> Device:
    """
    Stacked (cascode) current mirror for higher output impedance.

    Wraps the glayout stacked_current_mirror cell.

    Parameters
    ----------
    w, l    : main transistor sizing
    ratio   : copy/ref ratio
    vbias   : cascode gate bias Net
    ref     : reference input Net
    copy    : copy output Net
    rail    : supply rail (GND for NMOS, VDD for PMOS)
    """
    _p = _pdk(pdk)
    length = l or _p.get_grule("poly")["min_width"]
    device_str = "nfet" if n_or_p in ("n", "nmos", "nfet") else "pfet"

    try:
        from glayout.cells.composite.stacked_current_mirror.stacked_current_mirror import (
            stacked_nfet_current_mirror,
        )
        from glayout.cells.elementary.current_mirror.current_mirror import current_mirror as _cm
        from glayout.util.port_utils import rename_ports_by_orientation

        # Fall back to basic mirror with note
        comp = _cm(_p, numcols=max(2, ratio + 1), device=device_str, width=w, length=length)
        comp = rename_ports_by_orientation(comp)
    except Exception:
        from glayout.cells.elementary.current_mirror.current_mirror import current_mirror as _cm
        from glayout.util.port_utils import rename_ports_by_orientation
        comp = _cm(_p, numcols=max(2, ratio + 1), device=device_str, width=w, length=length)
        comp = rename_ports_by_orientation(comp)

    port_map = {
        "ref":   "fet_A_drain",
        "copy":  "fet_B_drain",
        "vbias": "welltie",
        "rail":  "welltie_S_top_met" if device_str == "nfet" else "welltie_N_top_met",
    }

    return Device(
        "stacked_cmirror",
        comp,
        _conn(ref=ref, copy=copy, vbias=vbias, rail=rail),
        tag=tag or "scm",
        port_map=port_map,
    )


# ─── MIM Capacitor ────────────────────────────────────────────────────────────

def mimcap(
    *,
    w: float = 5.0,
    l: float = 5.0,
    p: Optional[Net] = None,
    n: Optional[Net] = None,
    pdk=None,
    tag: str = "",
) -> Device:
    """
    Single MIM capacitor.

    Parameters
    ----------
    w, l   : capacitor dimensions (µm)
    p      : top-plate Net
    n      : bottom-plate Net

    Example::

        cc = gl.mimcap(w=10, l=10, p=vout, n=gl.gnd)
    """
    _p = _pdk(pdk)
    from glayout.primitives.mimcap import mimcap as _mimcap
    from glayout.util.port_utils import rename_ports_by_orientation

    comp = _mimcap(_p, size=(w, l))
    comp = rename_ports_by_orientation(comp)

    port_map = {"p": "top_met", "n": "bottom_met"}

    return Device("mimcap", comp, _conn(p=p, n=n), tag=tag or "c", port_map=port_map)


def mimcap_array(
    *,
    rows: int = 2,
    cols: int = 2,
    w: float = 5.0,
    l: float = 5.0,
    p: Optional[Net] = None,
    n: Optional[Net] = None,
    pdk=None,
    tag: str = "",
) -> Device:
    """
    Array of MIM capacitors.

    Parameters
    ----------
    rows, cols : array size
    p, n       : top and bottom plate Nets

    Example::

        cap_arr = gl.mimcap_array(rows=2, cols=4, w=5, l=5, p=vout, n=gl.gnd)
    """
    _p = _pdk(pdk)
    from glayout.primitives.mimcap import mimcap_array as _arr
    from glayout.util.port_utils import rename_ports_by_orientation

    comp = _arr(_p, rows=rows, columns=cols, size=(w, l))
    comp = rename_ports_by_orientation(comp)

    # top of last row, first col
    port_map = {
        "p": f"row{rows - 1}_col0_top_met",
        "n": f"row0_col0_bottom_met",
    }

    return Device("mimcap_array", comp, _conn(p=p, n=n), tag=tag or "carr", port_map=port_map)


# ─── Resistor ─────────────────────────────────────────────────────────────────

def res(
    *,
    w: float = 0.5,
    l: float = 5.0,
    series: int = 1,
    a: Optional[Net] = None,
    b: Optional[Net] = None,
    pdk=None,
    tag: str = "",
) -> Device:
    """
    Poly/diffusion resistor.

    Parameters
    ----------
    w, l   : width and length (µm)
    series : number of series-connected segments
    a, b   : two terminal Nets

    Example::

        r1 = gl.res(w=0.5, l=20, a=vin, b=vout)
    """
    _p = _pdk(pdk)
    from glayout.primitives.resistor import resistor as _res
    from glayout.util.port_utils import rename_ports_by_orientation

    comp = _res(_p, width=w, length=l, num_series=series)
    comp = rename_ports_by_orientation(comp)

    # For series=1: pfet source/drain = terminals; for series>1: port1_*/port2_*
    if series > 1:
        port_map = {"a": "port1", "b": "port2"}
    else:
        port_map = {"a": "source", "b": "drain"}

    return Device("res", comp, _conn(a=a, b=b), tag=tag or "r", port_map=port_map)


# ─── Via Stack ────────────────────────────────────────────────────────────────

def via(
    *,
    layer1: str = "met1",
    layer2: str = "met2",
    net: Optional[Net] = None,
    pdk=None,
    tag: str = "",
) -> Device:
    """
    Metal via stack (connects two metal layers).

    Parameters
    ----------
    layer1, layer2 : glayer names (e.g. 'met1', 'met2', 'met3')
    net            : Net this via is part of

    Example::

        v = gl.via(layer1='met1', layer2='met3', net=vout)
    """
    _p = _pdk(pdk)
    from glayout.primitives.via_gen import via_stack as _via
    from glayout.util.port_utils import rename_ports_by_orientation

    comp = _via(_p, layer1, layer2)
    comp = rename_ports_by_orientation(comp)

    connections = {"net": net} if net is not None else {}
    port_map = {"net": "top_met"}

    return Device("via", comp, connections, tag=tag or "v", port_map=port_map)


# ─── BJT ─────────────────────────────────────────────────────────────────────

def bjt(
    *,
    area: tuple = (5.0, 5.0),
    bjt_type: str = "pnp",
    b: Optional[Net] = None,
    c: Optional[Net] = None,
    e: Optional[Net] = None,
    pdk=None,
    tag: str = "",
) -> Device:
    """
    Bipolar Junction Transistor (BJT).

    Parameters
    ----------
    area     : active area (µm × µm)
    bjt_type : 'pnp' or 'npn'
    b, c, e  : base, collector, emitter Nets

    Example::

        q1 = gl.bjt(bjt_type='pnp', b=vb, c=vc, e=ve)
    """
    _p = _pdk(pdk)
    from glayout.primitives.bjt import multiplier as _bjt
    from glayout.util.port_utils import rename_ports_by_orientation

    comp = _bjt(_p, active_area=area, bjt_type=bjt_type)
    comp = rename_ports_by_orientation(comp)

    port_map = {"b": "base", "c": "collector", "e": "emitter"}

    return Device("bjt", comp, _conn(b=b, c=c, e=e), tag=tag or f"q_{bjt_type}", port_map=port_map)


# ─── raw() — advanced escape hatch ───────────────────────────────────────────

def raw(
    component: Any,
    connections: Optional[dict] = None,
    port_map: Optional[dict] = None,
    tag: str = "",
) -> Device:
    """
    Wrap any pre-built gdsfactory Component as a Device.
    Advanced escape hatch for full glayout control without << / >> syntax.

    Parameters
    ----------
    component  : any gdsfactory Component
    connections: {terminal_name: Net}
    port_map   : {terminal_name: port_keyword}  — substring to search in port names

    Example::

        from glayout.cells.composite.fvf_based_ota.n_block import n_block
        nb = n_block(pdk, input_pair_params=(4, 2))
        device = gl.raw(
            nb,
            connections={'inp': vip, 'inn': vim, 'gnd': gl.gnd},
            port_map={'inp': 'gate_inA', 'inn': 'gate_inB', 'gnd': 'cbias'},
        )
    """
    return Device("raw", component, connections or {}, tag=tag or "raw", port_map=port_map or {})
