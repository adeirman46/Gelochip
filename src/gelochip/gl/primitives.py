"""
Primitive device factories — single transistors / passives.
For matched/pre-routed structures use gl/cells.py instead.

Usage inside Module.layout()::

    def layout(self):
        vin, vout = self.pin('vin'), self.pin('vout')
        gl.pmos(w=4, fingers=2, g=vin, d=vout, s=gl.vdd)
        gl.nmos(w=2, fingers=2, g=vin, d=vout, s=gl.gnd)

Functional usage::

    vin, vout = gl.Net('vin'), gl.Net('vout')
    mp = gl.pmos(w=4, g=vin, d=vout, s=gl.vdd, pdk=gl.gf180)
    mn = gl.nmos(w=2, g=vin, d=vout, s=gl.gnd, pdk=gl.gf180)
    chip = gl.build(mp, mn, name='inverter')
"""
from __future__ import annotations

from typing import Optional

from gelochip.gl.net import Net
from gelochip.gl.device import Device, _active_module


def _resolve_pdk(pdk):
    if pdk is not None:
        return pdk
    mod = _active_module()
    if mod is not None and getattr(mod, "_pdk", None) is not None:
        return mod._pdk
    from gelochip.gl import gf180
    if gf180 is not None:
        return gf180
    raise RuntimeError(
        "No PDK available. Pass pdk=gl.gf180 or call gl.set_pdk(gl.gf180) first."
    )


def _conn(**kwargs):
    return {k: v for k, v in kwargs.items() if v is not None}


# ─── NMOS ─────────────────────────────────────────────────────────────────────

def nmos(
    *,
    w: float = 1.0,
    l: Optional[float] = None,
    fingers: int = 1,
    multipliers: int = 1,
    g: Optional[Net] = None,
    d: Optional[Net] = None,
    s: Optional[Net] = None,
    b: Optional[Net] = None,
    with_dummy: bool = True,
    with_tie: bool = True,
    with_substrate_tap: bool = False,
    sd_rmult: int = 1,
    pdk=None,
    tag: str = "",
) -> Device:
    """
    NMOS transistor primitive.

    Parameters
    ----------
    w           : gate width per finger (µm)
    l           : gate length (µm) — default: PDK min
    fingers     : number of gate fingers
    multipliers : device multiplier (parallel rows)
    g, d, s, b  : gate / drain / source / bulk Nets

    Example::

        mn = gl.nmos(w=2, fingers=4, g=vin, d=vout, s=gl.gnd)
    """
    _pdk = _resolve_pdk(pdk)
    length = l or _pdk.get_grule("poly")["min_width"]

    from glayout.primitives.fet import nmos as _nmos
    from glayout.util.port_utils import rename_ports_by_orientation

    comp = _nmos(
        _pdk,
        width=w,
        length=length,
        fingers=fingers,
        multipliers=multipliers,
        with_dummy=with_dummy,
        with_tie=with_tie,
        with_substrate_tap=with_substrate_tap,
        sd_rmult=sd_rmult,
    )
    comp = rename_ports_by_orientation(comp)
    dev = Device("nmos", comp, _conn(gate=g, drain=d, source=s, tie=b), tag=tag or "mn")
    dev._spec = dict(kind="nmos", w=w, l=l, fingers=fingers, multipliers=multipliers,
                     g=g, d=d, s=s, b=b, with_substrate_tap=with_substrate_tap,
                     sd_rmult=sd_rmult, pdk=pdk, tag=tag)
    return dev


# ─── PMOS ─────────────────────────────────────────────────────────────────────

def pmos(
    *,
    w: float = 1.0,
    l: Optional[float] = None,
    fingers: int = 1,
    multipliers: int = 1,
    g: Optional[Net] = None,
    d: Optional[Net] = None,
    s: Optional[Net] = None,
    b: Optional[Net] = None,
    with_dummy: bool = True,
    with_tie: bool = True,
    with_substrate_tap: bool = False,
    sd_rmult: int = 1,
    pdk=None,
    tag: str = "",
) -> Device:
    """
    PMOS transistor primitive.

    Parameters
    ----------
    w, l, fingers, multipliers : sizing
    g, d, s, b                 : gate / drain / source / bulk Nets

    Example::

        mp = gl.pmos(w=4, fingers=2, g=vin, d=vout, s=gl.vdd)
    """
    _pdk = _resolve_pdk(pdk)
    length = l or _pdk.get_grule("poly")["min_width"]

    from glayout.primitives.fet import pmos as _pmos
    from glayout.util.port_utils import rename_ports_by_orientation

    comp = _pmos(
        _pdk,
        width=w,
        length=length,
        fingers=fingers,
        multipliers=multipliers,
        with_dummy=with_dummy,
        with_tie=with_tie,
        with_substrate_tap=with_substrate_tap,
        sd_rmult=sd_rmult,
    )
    comp = rename_ports_by_orientation(comp)
    dev = Device("pmos", comp, _conn(gate=g, drain=d, source=s, tie=b), tag=tag or "mp")
    dev._spec = dict(kind="pmos", w=w, l=l, fingers=fingers, multipliers=multipliers,
                     g=g, d=d, s=s, b=b, with_substrate_tap=with_substrate_tap,
                     sd_rmult=sd_rmult, pdk=pdk, tag=tag)
    return dev


# ─── functional build() ───────────────────────────────────────────────────────

def build(*devices_or_modules, name: str = "circuit", pdk=None,
          placement: str = "column", sep_mult: float = 2.0,
          met_layer: int = 1, width_mult: float = 1.0):
    """
    Functional API: assemble Devices/Modules into a DRC-clean Layout.

    Automatically runs the RL corrector in the background to find
    DRC-clean layout parameters — no extra parameters needed.

    Example::

        vin, vout = gl.Net('vin'), gl.Net('vout')
        mp = gl.pmos(w=4, g=vin, d=vout, s=gl.vdd)
        mn = gl.nmos(w=2, g=vin, d=vout, s=gl.gnd)
        chip = gl.build(mp, mn, name='inverter')
        chip.show()
        chip.drc()   # ← 0 errors
    """
    from gelochip.gl.module import Module
    from gelochip.gl.compiler import compile_module
    import gelochip.gl.drc_corrector as _dc

    _pdk = _resolve_pdk(pdk)

    # Collect devices only (no Modules in the args)
    only_devices = [i for i in devices_or_modules if isinstance(i, Device)]
    has_modules  = any(not isinstance(i, Device) for i in devices_or_modules)
    all_have_spec = (
        not has_modules
        and only_devices
        and all(hasattr(d, '_spec') for d in only_devices)
    )

    # ── RL-backed build ─────────────────────────────────────────────────────
    # Skip if we're already inside an RL build call (recursion guard),
    # or if Modules were passed (no specs to reconstruct from).
    if all_have_spec and not _dc._RL_ACTIVE:
        print(f"[gl.build] running DRC sweep for '{name}'...")
        specs = [d._spec for d in only_devices]

        def _builder(_, layout_params, bname):
            rebuilt = []
            for sp in specs:
                lp_kw = {"with_tie":   layout_params["with_tie"],
                         "with_dummy": layout_params["with_dummy"]}
                _fn = nmos if sp["kind"] == "nmos" else pmos
                rebuilt.append(_fn(
                    w=sp["w"], l=sp["l"], fingers=sp["fingers"],
                    multipliers=sp["multipliers"],
                    g=sp["g"], d=sp["d"], s=sp["s"], b=sp["b"],
                    with_substrate_tap=sp["with_substrate_tap"],
                    sd_rmult=sp["sd_rmult"], pdk=sp["pdk"], tag=sp["tag"],
                    **lp_kw,
                ))
            c = object.__new__(Module)
            c._pdk = _pdk; c._devices = rebuilt; c._pins = {}; c._name = bname
            return compile_module(c,
                                  placement=layout_params["placement"],
                                  sep_mult=layout_params["sep_mult"],
                                  met_layer=layout_params["met_layer"],
                                  width_mult=layout_params["width_mult"])

        return _dc._run_drc_sweep(_builder, name)

    # ── Plain build (inside RL loop, or Module args, or no specs) ───────────
    if not _dc._RL_ACTIVE and not all_have_spec and only_devices:
        print(f"[gl.build] plain build for '{name}' "
              "(restart Jupyter kernel to enable DRC sweep)")
    container = object.__new__(Module)
    container._pdk = _pdk
    container._devices = []
    container._pins = {}
    container._name = name
    for item in devices_or_modules:
        if isinstance(item, Device):
            container._devices.append(item)
        elif isinstance(item, Module):
            container._devices.extend(item._devices)
            container._pins.update(item._pins)
    return compile_module(container, placement=placement, sep_mult=sep_mult,
                          met_layer=met_layer, width_mult=width_mult)
