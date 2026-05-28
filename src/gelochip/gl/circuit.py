"""
gl.Circuit — PyTorch-like analog circuit builder.

Workflow:
    with gl.Circuit("inverter", pdk) as c:
        mp = c.pmos(w=4, fingers=2)
        mn = c.nmos(w=2, fingers=2)

        c.vin >> [mp.gate, mn.gate]
        c.vdd >> mp.source
        c.gnd >> mn.source
        mp.drain + mn.drain >> c.vout

    result = c.build()
    result.show()
    result.drc()
    result.lvs()
    result.sim()
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple, Union

from gdsfactory.component import Component
from gdsfactory.port import Port
from glayout.pdk.mappedpdk import MappedPDK


# ─── Terminal / Net primitives ────────────────────────────────────────────────

class Terminal:
    """Proxy for one transistor pin (gate / drain / source / bulk)."""

    def __init__(self, device: "DeviceProxy", signal: str):
        self.device = device
        self.signal = signal  # "gate", "drain", "source", "tie", ...

    # terminal + terminal → MultiTerminal (short together on same net)
    def __add__(self, other: Union["Terminal", "MultiTerminal"]) -> "MultiTerminal":
        if isinstance(other, MultiTerminal):
            return MultiTerminal([self] + other.terminals)
        return MultiTerminal([self, other])

    # net >> terminal
    def __rrshift__(self, other: "Net") -> "Net":
        other._connect(self)
        return other

    # terminal >> net  or  terminal >> terminal
    def __rshift__(self, other: Union["Net", "Terminal", List]) -> "Net":
        if isinstance(other, Net):
            other._connect(self)
            return other
        if isinstance(other, Terminal):
            n = _anon_net()
            n._connect(self)
            n._connect(other)
            return n
        if isinstance(other, list):
            n = _anon_net()
            n._connect(self)
            for t in other:
                n._connect(t)
            return n
        raise TypeError(f"Cannot connect Terminal to {type(other)}")

    def get_port(self) -> Optional[Port]:
        """Resolve to a concrete gdsfactory Port after placement."""
        ref = self.device._ref
        if ref is None:
            return None
        sig = self.signal.lower()
        # bulk/body aliases
        if sig in ("bulk", "body", "b", "tie"):
            sig = "tie"
        # collect matching ports (skip structural/dummy ports)
        _skip = re.compile(
            r"dummy|diff|via|layer|array|plusdoped|well|tap|substrate|pwell|nwell",
            re.I,
        )
        candidates: List[Tuple[str, Port]] = [
            (name, port)
            for name, port in ref.ports.items()
            if sig in name.lower() and not _skip.search(name)
        ]
        if not candidates:
            return None
        # prefer N for drain/iout, S for source/gnd, any for gate
        pref = "N" if sig in ("drain", "iout", "out") else ("S" if sig in ("source", "tail") else "E")
        for name, port in candidates:
            if name.endswith(f"_{pref}"):
                return port
        # fall back to first match
        return candidates[0][1]


class MultiTerminal:
    """Several terminals that all land on the same net."""

    def __init__(self, terminals: List[Terminal]):
        self.terminals = terminals

    def __add__(self, other: Union[Terminal, "MultiTerminal"]) -> "MultiTerminal":
        more = other.terminals if isinstance(other, MultiTerminal) else [other]
        return MultiTerminal(self.terminals + more)

    # multiterminal >> net
    def __rshift__(self, other: "Net") -> "Net":
        for t in self.terminals:
            other._connect(t)
        return other

    # net >> multiterminal
    def __rrshift__(self, other: "Net") -> "Net":
        for t in self.terminals:
            other._connect(t)
        return other


_anon_counter = 0

def _anon_net() -> "Net":
    global _anon_counter
    _anon_counter += 1
    return Net(f"_net{_anon_counter}")


class Net:
    """Named electrical node connecting multiple terminals."""

    def __init__(self, name: str, circuit: Optional["Circuit"] = None):
        self.name = name
        self._circuit = circuit
        self._terminals: List[Terminal] = []
        self.is_pin = False  # True → expose as top-level I/O port

        if circuit is not None:
            circuit._nets[name] = self

    def _connect(self, terminal: Terminal):
        if terminal not in self._terminals:
            self._terminals.append(terminal)
        # register terminal's device with circuit if needed
        if self._circuit and terminal.device not in self._circuit._devices:
            self._circuit._devices.append(terminal.device)

    # net >> terminal / [terminals] / multiterminal
    def __rshift__(self, other: Union[Terminal, List, MultiTerminal, "Net"]) -> "Net":
        if isinstance(other, list):
            for t in other:
                self._connect(t)
        elif isinstance(other, (Terminal, MultiTerminal)):
            if isinstance(other, MultiTerminal):
                for t in other.terminals:
                    self._connect(t)
            else:
                self._connect(other)
        elif isinstance(other, Net):
            for t in self._terminals:
                other._connect(t)
        return self

    # terminal >> net  (reverse shift handled on Terminal side; this covers list >> net)
    def __rlshift__(self, other) -> "Net":
        return self.__rshift__(other)


# ─── Device proxy ─────────────────────────────────────────────────────────────

class DeviceProxy:
    """
    Wraps a gdsfactory Component.  Exposes named terminals as properties
    so you can write  ``mp.gate``, ``mp.drain``, ``mp.source``.
    """

    def __init__(self, component: Component, tag: str, circuit: Optional["Circuit"] = None):
        self._component = component
        self._tag = tag
        self._ref: Any = None           # ComponentReference after placement
        self._circuit = circuit
        if circuit is not None and self not in circuit._devices:
            circuit._devices.append(self)

    # --- standard FET terminals ---
    @property
    def gate(self) -> Terminal:
        return Terminal(self, "gate")

    @property
    def drain(self) -> Terminal:
        return Terminal(self, "drain")

    @property
    def source(self) -> Terminal:
        return Terminal(self, "source")

    @property
    def bulk(self) -> Terminal:
        return Terminal(self, "tie")

    # --- block-level terminals ---
    @property
    def inp(self) -> Terminal:
        return Terminal(self, "inp")

    @property
    def inn(self) -> Terminal:
        return Terminal(self, "inn")

    @property
    def out(self) -> Terminal:
        return Terminal(self, "out")

    @property
    def vbias(self) -> Terminal:
        return Terminal(self, "bias")

    @property
    def iout(self) -> Terminal:
        return Terminal(self, "iout")

    @property
    def vtail(self) -> Terminal:
        return Terminal(self, "tail")

    # allow arbitrary terminal lookup by name
    def pin(self, name: str) -> Terminal:
        return Terminal(self, name)


# ─── GDSResult: the built layout ─────────────────────────────────────────────

class GDSResult:
    """
    Returned by ``Circuit.build()``.
    Wraps the gdsfactory Component with one-liner verification methods.
    """

    def __init__(self, component: Component, pdk: MappedPDK, name: str):
        self._comp = component
        self._pdk = pdk
        self.name = name
        self._gds_path: Optional[str] = None

    # ── display ───────────────────────────────────────────────────────────────

    def show(self, out_png: Optional[str] = None, width: int = 1600, height: int = 900) -> "GDSResult":
        """Render GDS in notebook / save PNG."""
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
            print(f"[gl] show: {e}")
            print(f"[gl] GDS → {gds}")
        return self

    # ── verification ──────────────────────────────────────────────────────────

    def drc(self) -> dict:
        """Run DRC via Magic VLSI (needs PDK_ROOT + magic installed)."""
        from gelochip.verification.drc_lvs import run_drc
        res = run_drc(self._gds(), self.name, self._comp)
        if res.get("skipped"):
            print(f"[gl.drc] skipped — {res.get('error', 'tools not found')}")
        else:
            icon = "✅" if res.get("is_pass") else "❌"
            print(f"[gl.drc] {icon}  {res.get('total_errors', '?')} errors")
        return res

    def lvs(self) -> dict:
        """Run LVS via Netgen."""
        from gelochip.verification.drc_lvs import run_lvs
        res = run_lvs(self._gds(), self.name, self._comp)
        if res.get("skipped"):
            print(f"[gl.lvs] skipped — {res.get('conclusion', 'tools not found')}")
        else:
            icon = "✅" if res.get("is_pass") else "❌"
            print(f"[gl.lvs] {icon}  {res.get('conclusion', '')}")
        return res

    def sim(self, vdd: float = 3.3) -> dict:
        """Run DC operating-point simulation via ngspice with gf180 models."""
        from gelochip.gl.verify import run_sim
        return run_sim(self._comp, self.name, vdd=vdd)

    # ── save / access ─────────────────────────────────────────────────────────

    def save(self, path: str) -> "GDSResult":
        self._comp.write_gds(path)
        self._gds_path = path
        print(f"[gl] saved → {path}")
        return self

    @property
    def component(self) -> Component:
        return self._comp

    # ── internal ──────────────────────────────────────────────────────────────

    def _gds(self) -> str:
        import os, tempfile
        if self._gds_path is None:
            self._gds_path = os.path.join(tempfile.gettempdir(), f"{self.name}.gds")
            self._comp.write_gds(self._gds_path)
        return self._gds_path


# ─── Circuit builder ──────────────────────────────────────────────────────────

class Circuit:
    """
    PyTorch-style analog circuit builder.

    Instantiate devices with ``c.nmos()``, ``c.pmos()``, etc.
    Declare connections with ``>>``.
    Call ``c.build()`` to produce a placed-and-routed ``GDSResult``.

    Power/ground rails are available as ``c.vdd`` and ``c.gnd``.
    Any other attribute (``c.vin``, ``c.vout``, …) auto-creates an I/O net.
    """

    def __init__(self, name: str, pdk: MappedPDK):
        self.name = name
        self.pdk = pdk
        self._devices: List[DeviceProxy] = []
        self._nets: Dict[str, Net] = {}

        # power/ground pre-defined
        for pin_name in ("vdd", "gnd", "vss"):
            n = Net(pin_name, self)
            n.is_pin = True

    # ── context manager (optional) ────────────────────────────────────────────

    def __enter__(self) -> "Circuit":
        return self

    def __exit__(self, *_):
        pass

    # ── net / pin access ──────────────────────────────────────────────────────

    @property
    def vdd(self) -> Net:
        return self._nets["vdd"]

    @property
    def gnd(self) -> Net:
        return self._nets.get("gnd") or self._nets.get("vss")

    def net(self, name: str) -> Net:
        if name not in self._nets:
            n = Net(name, self)
            n.is_pin = True
        return self._nets[name]

    def __getattr__(self, name: str) -> Net:
        if name.startswith("_") or name in ("name", "pdk"):
            raise AttributeError(name)
        return self.net(name)

    # ── device factories ──────────────────────────────────────────────────────

    def nmos(
        self,
        *,
        w: float = 1.0,
        l: Optional[float] = None,
        fingers: int = 1,
        multipliers: int = 1,
        tag: Optional[str] = None,
        **kwargs,
    ) -> DeviceProxy:
        from gelochip.gl.primitives import _make_nmos
        comp = _make_nmos(self.pdk, w=w, l=l, fingers=fingers, multipliers=multipliers, **kwargs)
        return self._register(comp, tag or f"mn{len(self._devices)}")

    def pmos(
        self,
        *,
        w: float = 1.0,
        l: Optional[float] = None,
        fingers: int = 1,
        multipliers: int = 1,
        tag: Optional[str] = None,
        **kwargs,
    ) -> DeviceProxy:
        from gelochip.gl.primitives import _make_pmos
        comp = _make_pmos(self.pdk, w=w, l=l, fingers=fingers, multipliers=multipliers, **kwargs)
        return self._register(comp, tag or f"mp{len(self._devices)}")

    def res(
        self,
        *,
        w: float = 0.5,
        l: float = 5.0,
        tag: Optional[str] = None,
        **kwargs,
    ) -> DeviceProxy:
        from gelochip.gl.primitives import _make_res
        comp = _make_res(self.pdk, w=w, l=l, **kwargs)
        return self._register(comp, tag or f"r{len(self._devices)}")

    def cap(
        self,
        *,
        w: float = 5.0,
        l: float = 5.0,
        tag: Optional[str] = None,
        **kwargs,
    ) -> DeviceProxy:
        from gelochip.gl.primitives import _make_cap
        comp = _make_cap(self.pdk, w=w, l=l, **kwargs)
        return self._register(comp, tag or f"c{len(self._devices)}")

    def block(self, component: Component, tag: Optional[str] = None) -> DeviceProxy:
        """Wrap any pre-built glayout Component as a Device in this circuit."""
        return self._register(component, tag or f"blk{len(self._devices)}")

    def _register(self, comp: Component, tag: str) -> DeviceProxy:
        proxy = DeviceProxy(comp, tag, self)
        return proxy

    # ── build ─────────────────────────────────────────────────────────────────

    def build(self, placement: str = "row") -> GDSResult:
        """
        Assemble the layout:
        1. Place all devices left-to-right (default) or as specified.
        2. Route all nets using smart_route.
        3. Add I/O pin markers at circuit boundary.

        Parameters
        ----------
        placement : "row" | "column" | "grid"
        """
        top = Component(self.name)

        # 1. placement
        if placement == "column":
            self._place_column(top)
        else:
            self._place_row(top)

        # 2. routing
        self._route_all(top)

        # 3. pins
        self._add_pins(top)

        # snap + rename
        try:
            from glayout.util.snap_to_grid import component_snap_to_grid
            from glayout.util.port_utils import rename_ports_by_orientation
            top = component_snap_to_grid(rename_ports_by_orientation(top))
        except Exception:
            pass

        return GDSResult(top, self.pdk, self.name)

    # ── placement helpers ─────────────────────────────────────────────────────

    def _place_row(self, top: Component):
        sep = max(self.pdk.util_max_metal_seperation() * 6, 2.0)
        x = 0.0
        for dev in self._devices:
            ref = top << dev._component
            ref.movex(x - dev._component.xmin)
            dev._ref = ref
            x = ref.xmax + sep

    def _place_column(self, top: Component):
        sep = max(self.pdk.util_max_metal_seperation() * 6, 2.0)
        y = 0.0
        for dev in self._devices:
            ref = top << dev._component
            ref.movey(y - dev._component.ymin)
            dev._ref = ref
            y = ref.ymax + sep

    # ── routing ───────────────────────────────────────────────────────────────

    def _route_all(self, top: Component):
        from glayout.routing.smart_route import smart_route

        for net_name, net in self._nets.items():
            ports: List[Port] = []
            for terminal in net._terminals:
                p = terminal.get_port()
                if p is not None:
                    ports.append(p)

            if len(ports) < 2:
                continue

            # route consecutive pairs along the net
            for i in range(len(ports) - 1):
                try:
                    route = smart_route(self.pdk, ports[i], ports[i + 1])
                    top << route
                except Exception as exc:
                    print(f"  [gl.route] '{net_name}' ports[{i}→{i+1}]: {exc}")

    # ── pin markers ───────────────────────────────────────────────────────────

    def _add_pins(self, top: Component):
        for net_name, net in self._nets.items():
            if not net.is_pin:
                continue
            for terminal in net._terminals:
                p = terminal.get_port()
                if p is None:
                    continue
                try:
                    top.add_port(name=f"pin_{net_name}", port=p)
                    break
                except Exception:
                    pass
