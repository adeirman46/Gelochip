"""
gl.Module — PyTorch-style base class for analog circuits.

Define your topology in ``layout()``, then call ``.build()`` to get a Layout.

Usage::

    class Inverter(gl.Module):
        def __init__(self, wp=4.0, wn=2.0):
            super().__init__(gl.gf180)
            self.wp = wp
            self.wn = wn

        def layout(self):
            vin  = self.pin('vin')
            vout = self.pin('vout')

            gl.pmos(w=self.wp, fingers=2, g=vin, d=vout, s=gl.vdd)
            gl.nmos(w=self.wn, fingers=2, g=vin, d=vout, s=gl.gnd)

    inv = Inverter(wp=4, wn=2)
    chip = inv.build()
    chip.show()
    chip.drc()
    chip.sim()

Sequential::

    class OTA(gl.Module):
        def __init__(self):
            super().__init__(gl.gf180)
            self.stage1 = DiffPairStage()
            self.stage2 = CommonSource()

        def layout(self):
            v1 = self.stage1.build()        # stage 1 result
            v2 = self.stage2.build(v1)      # feed forward
            ...
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from gelochip.gl.net import Net, vdd, gnd, vss
from gelochip.gl.device import Device, _push_module, _pop_module


class Module:
    """
    Base class for all analog circuits.

    Sub-class and override ``layout()`` to declare devices and connections.
    Devices instantiated with ``gl.pmos / gl.nmos / ...`` inside ``layout()``
    are automatically registered here — the same way ``nn.Module`` tracks
    submodules in PyTorch.
    """

    def __init__(self, pdk=None):
        from gelochip.gl import gf180 as _gf180
        self._pdk = pdk or _gf180
        self._devices: List[Device] = []
        self._pins: Dict[str, Net] = {}
        self._name: str = self.__class__.__name__.lower()

    # ── pin / net access ──────────────────────────────────────────────────────

    def pin(self, name: str) -> Net:
        """
        Declare an I/O pin net.

        Calling ``self.pin('vin')`` inside ``layout()`` creates a named Net
        that will become an exposed port on the compiled Component.
        """
        if name not in self._pins:
            n = Net(name)
            n.is_pin = True
            self._pins[name] = n
        return self._pins[name]

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def layout(self) -> None:
        """Override to define topology. Called by build()."""
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement layout()"
        )

    def build(self, name: Optional[str] = None, placement: str = "column",
              sep_mult: float = 2.0, met_layer: int = 1,
              width_mult: float = 1.0) -> "Layout":
        """
        Run layout(), compile geometry, route nets → Layout.

        Parameters
        ----------
        name       : override cell name (default: class name)
        placement  : 'row' (left→right) | 'column' (bottom→top)
        sep_mult   : device separation multiplier (higher = more spacing)
        met_layer  : metal layer for routing wires (1=met1 … 5=met5)
        width_mult : wire width multiplier (1.0 = port width)
        """
        if name:
            self._name = name

        _push_module(self)
        try:
            self.layout()
        finally:
            _pop_module()

        from gelochip.gl.compiler import compile_module
        return compile_module(self, placement=placement, sep_mult=sep_mult,
                              met_layer=met_layer, width_mult=width_mult)

    # ── internal ──────────────────────────────────────────────────────────────

    def _register_device(self, dev: Device) -> None:
        self._devices.append(dev)

    def _all_nets(self) -> Dict[str, Net]:
        """Collect every Net referenced by any device connection or pin."""
        nets: Dict[str, Net] = {}
        for n in (vdd, gnd):
            nets[n.name] = n
        for net in self._pins.values():
            nets[net.name] = net
        for dev in self._devices:
            for net in dev.connections.values():
                if isinstance(net, Net):
                    nets[net.name] = net
        return nets


# ─── Sequential / Parallel containers ────────────────────────────────────────

class Sequential(Module):
    """
    Cascade modules vertically (like ``nn.Sequential``).

    Each sub-module is placed above the previous one.
    Useful for multi-stage amplifiers.

    Example::

        class TwoStageOTA(gl.Sequential):
            def __init__(self):
                super().__init__(
                    DiffPairStage(),
                    CommonSourceStage(),
                    pdk=gl.gf180,
                )
    """

    def __init__(self, *modules: Module, pdk=None):
        super().__init__(pdk)
        self._children: List[Module] = list(modules)
        for m in self._children:
            if m._pdk is None:
                m._pdk = self._pdk

    def layout(self) -> None:
        for child in self._children:
            _push_module(child)
            try:
                child.layout()
            finally:
                _pop_module()
            # merge child devices into self
            self._devices.extend(child._devices)
            child._devices.clear()


class Parallel(Module):
    """
    Place modules side-by-side (like a matched / interdigitized structure).

    Useful for differential pairs, current-mirror arrays, etc.

    Example::

        pair = gl.Parallel(
            gl.nmos(w=3, fingers=4, g=vin, s=vtail, d=voutp),
            gl.nmos(w=3, fingers=4, g=vim,  s=vtail, d=voutn),
            pdk=gl.gf180,
        )
    """

    def __init__(self, *devices_or_modules, pdk=None):
        super().__init__(pdk)
        for item in devices_or_modules:
            if isinstance(item, Device):
                self._devices.append(item)
            elif isinstance(item, Module):
                self._devices.extend(item._devices)

    def layout(self) -> None:
        pass  # devices already loaded in __init__

    def build(self, name: Optional[str] = None, placement: str = "column",
              sep_mult: float = 2.0, met_layer: int = 1,
              width_mult: float = 1.0) -> "Layout":
        if name:
            self._name = name
        from gelochip.gl.compiler import compile_module
        return compile_module(self, placement=placement, sep_mult=sep_mult,
                              met_layer=met_layer, width_mult=width_mult)


# ─── Layout result ────────────────────────────────────────────────────────────

class Layout:
    """
    Compiled analog layout.  Returned by ``Module.build()``.

    One-liner verification methods::

        chip = Inverter().build()
        chip.show()      # klayout render
        chip.drc()       # Magic DRC
        chip.lvs()       # Netgen LVS
        chip.sim()       # ngspice DC OP
        chip.save('out.gds')
    """

    def __init__(self, component: Any, pdk: Any, name: str):
        self._comp = component
        self._pdk = pdk
        self.name = name
        self._gds_path: Optional[str] = None

    # ── display ───────────────────────────────────────────────────────────────

    def show(self, out_png: Optional[str] = None, width: int = 1600, height: int = 900) -> "Layout":
        gds = self._gds()
        try:
            import klayout.lay as klay
            from IPython.display import Image, display
            lv = klay.LayoutView()
            lv.load_layout(gds, True)
            lv.max_hier()
            lv.zoom_fit()
            png = out_png or gds.replace(".gds", "_preview.png")
            lv.save_image(png, width, height)
            display(Image(png))
        except Exception as e:
            print(f"[gl.show] {e}\n[gl.show] GDS → {gds}")
        return self

    # ── verification ──────────────────────────────────────────────────────────

    def drc(self, silent: bool = False) -> dict:
        from gelochip.verification.drc_lvs import run_drc
        res = run_drc(self._gds(), self.name, self._comp)
        if not silent:
            if res.get("skipped"):
                print(f"[gl.drc] skipped — {res.get('error', 'tools not found')}")
            else:
                icon = "✅" if res.get("is_pass") else "❌"
                print(f"[gl.drc] {icon}  {res.get('total_errors', '?')} errors")
        return res

    def lvs(self) -> dict:
        from gelochip.verification.drc_lvs import run_lvs
        res = run_lvs(self._gds(), self.name, self._comp)
        if res.get("skipped"):
            print(f"[gl.lvs] skipped — {res.get('conclusion', 'tools not found')}")
        else:
            icon = "✅" if res.get("is_pass") else "❌"
            print(f"[gl.lvs] {icon}  {res.get('conclusion', '')}")
        return res

    def sim(self, vdd_v: float = 3.3) -> dict:
        from gelochip.gl.verify import run_sim
        return run_sim(self._comp, self.name, vdd=vdd_v)

    # ── save ──────────────────────────────────────────────────────────────────

    def save(self, path: str) -> "Layout":
        self._comp.write_gds(path)
        self._gds_path = path
        print(f"[gl] saved → {path}")
        return self

    @property
    def component(self) -> Any:
        return self._comp

    # ── internal ──────────────────────────────────────────────────────────────

    def _gds(self) -> str:
        import tempfile
        if self._gds_path is None:
            self._gds_path = os.path.join(tempfile.gettempdir(), f"{self.name}.gds")
            self._comp.write_gds(self._gds_path)
        return self._gds_path
