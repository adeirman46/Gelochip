"""
compile_module — turns a Module (devices + connections) into a Layout.

Steps:
  1. Place all Device components (row / column)
  2. For each Net with 2+ ports, call smart_route for consecutive pairs
  3. Mark I/O pin ports
  4. Snap to grid, normalise port names
"""
from __future__ import annotations

from typing import TYPE_CHECKING, List

import gdsfactory as gf
from gdsfactory.component import Component
from gdsfactory.port import Port

from gelochip.gl.net import Net

if TYPE_CHECKING:
    from gelochip.gl.module import Module, Layout
    from gelochip.gl.device import Device


def compile_module(
    mod: "Module",
    placement: str = "column",
    sep_mult: float = 2.0,
    met_layer: int = 1,
    width_mult: float = 1.0,
) -> "Layout":
    from gelochip.gl.module import Layout

    top = Component(mod._name)
    pdk = mod._pdk

    # ── 1. Placement ──────────────────────────────────────────────────────────
    sep = max(pdk.util_max_metal_seperation() * 6 * sep_mult, 2.0 * sep_mult)

    if placement == "column":
        _place_column(top, mod._devices, sep)
    else:
        _place_row(top, mod._devices, sep)

    # ── 2. Routing ────────────────────────────────────────────────────────────
    _route_all(top, mod, pdk, met_layer=met_layer, width_mult=width_mult)

    # ── 3. Pins ───────────────────────────────────────────────────────────────
    _add_pins(top, mod)

    # ── 4. Snap + rename ──────────────────────────────────────────────────────
    try:
        from glayout.util.snap_to_grid import component_snap_to_grid
        from glayout.util.port_utils import rename_ports_by_orientation
        top = component_snap_to_grid(rename_ports_by_orientation(top))
    except Exception:
        pass

    return Layout(top, pdk, mod._name)


# ─── Placement helpers ────────────────────────────────────────────────────────

def _place_row(top: Component, devices: List["Device"], sep: float):
    x = 0.0
    for dev in devices:
        ref = top << dev.component
        ref.movex(x - dev.component.xmin)
        dev._ref = ref
        x = ref.xmax + sep


def _place_column(top: Component, devices: List["Device"], sep: float):
    y = 0.0
    for dev in devices:
        ref = top << dev.component
        ref.movey(y - dev.component.ymin)
        dev._ref = ref
        y = ref.ymax + sep


# ─── Routing ─────────────────────────────────────────────────────────────────

def _collect_net_ports(mod: "Module") -> dict:
    """
    Build a mapping:  net_name → [Port, Port, ...]
    by iterating over every device's connections.
    """
    from collections import defaultdict
    net_ports = defaultdict(list)

    for dev in mod._devices:
        for terminal_kw, net in dev.connections.items():
            if not isinstance(net, Net):
                continue
            port = dev.get_port(terminal_kw)
            if port is not None:
                net_ports[net.name].append(port)

    return net_ports


_POLY_LAYERS = {(30, 0), (30, 1), (66, 20)}  # GDS layer tuples for poly/active


def _is_metal_port(port) -> bool:
    """Return True only for metal-layer ports (safe to route with smart_route)."""
    try:
        layer = getattr(port, "layer", None)
        if layer is None:
            return True
        if isinstance(layer, (tuple, list)):
            return tuple(layer) not in _POLY_LAYERS
        return True
    except Exception:
        return True


def _route_all(top: Component, mod: "Module", pdk, met_layer: int = 1, width_mult: float = 1.0):
    from glayout.routing.smart_route import smart_route

    net_ports = _collect_net_ports(mod)
    glayer = f"met{max(1, min(met_layer, 5))}"

    for net_name, ports in net_ports.items():
        # filter out poly-layer ports — smart_route can't handle them
        metal_ports = [p for p in ports if _is_metal_port(p)]
        if len(metal_ports) < 2:
            continue
        for i in range(len(metal_ports) - 1):
            try:
                p1, p2 = metal_ports[i], metal_ports[i + 1]
                w1 = max(p1.width * width_mult, pdk.util_max_metal_seperation() * 2)
                w2 = max(p2.width * width_mult, pdk.util_max_metal_seperation() * 2)
                route = smart_route(
                    pdk, p1, p2,
                    e1glayer=glayer, e2glayer=glayer, cglayer=glayer,
                    hglayer=glayer, vglayer=glayer,
                    width1=w1, width2=w2,
                )
                top << route
            except Exception as exc:
                # fall back to default routing if layer/width kwargs fail
                try:
                    top << smart_route(pdk, metal_ports[i], metal_ports[i + 1])
                except Exception as exc2:
                    print(f"  [gl.route] net '{net_name}' [{i}→{i+1}]: {exc2}")


# ─── Pin markers ──────────────────────────────────────────────────────────────

def _add_pins(top: Component, mod: "Module"):
    net_ports = _collect_net_ports(mod)

    for pin_name, pin_net in mod._pins.items():
        ports = net_ports.get(pin_net.name, [])
        if ports:
            try:
                top.add_port(name=f"pin_{pin_name}", port=ports[0])
            except Exception:
                pass
