"""
MOSFET primitive wrappers.

Each function returns a gdsfactory Component with named ports:
    gate_N / gate_S / gate_E / gate_W   – poly gate access
    drain_N / drain_S / drain_E / drain_W
    source_N / source_S / source_E / source_W
    bulk_N  / bulk_S  / bulk_E  / bulk_W   (via guard-ring tie)
"""
from __future__ import annotations
from typing import Optional, Union

from gdsfactory.component import Component
from pydantic import validate_arguments

from gelochip.glayout.pdk.mappedpdk import MappedPDK
from gelochip.glayout.primitives.fet import nmos as _glayout_nmos, pmos as _glayout_pmos
from gelochip.glayout.spice.netlist import Netlist


@validate_arguments
def nmos(
    pdk: MappedPDK,
    *,
    width: float = 1.0,
    length: Optional[float] = None,
    fingers: int = 1,
    multipliers: int = 1,
    with_substrate_tap: bool = True,
    with_dummy: Union[bool, tuple[bool, bool]] = True,
    with_tie: bool = True,
    tie_layers: tuple[str, str] = ("met2", "met1"),
    sd_rmult: int = 1,
    gate_rmult: int = 1,
    interfinger_topmet: str = "met2",
) -> Component:
    """
    NMOS transistor.

    Args:
        pdk:               Technology PDK (gf180 recommended / sky130 / ihp130).
        width:             Gate width per finger in µm.
        length:            Gate length in µm (defaults to PDK minimum).
        fingers:           Number of gate fingers.
        multipliers:       Number of parallel transistor rows (device multiplier).
        with_substrate_tap: Include an n-well / p-sub contact guard ring.
        with_dummy:        Add dummy fingers at edges (True = both, (L, R) = per side).
        with_tie:          Route the bulk tap to the source.
        tie_layers:        Metal layers for bulk tie.
        sd_rmult:          Source/drain via multiplier (increases current capacity).
        gate_rmult:        Gate metal width multiplier.
        interfinger_topmet: Top metal for inter-finger routing.

    Returns:
        Component with ports: gate_*, drain_*, source_*, bulk_*

    SPICE:
        Subcircuit stored in component.info["netlist"].
        Nodes: [D, G, S, B]

    Example::

        from gelochip.glayout.pdk.gf180_mapped import gf180_mapped_pdk as pdk
        m1 = nmos(pdk, width=2.0, fingers=4)
        m1.show()
    """
    length = length or pdk.get_grule("poly")["min_width"]
    return _glayout_nmos(
        pdk=pdk,
        width=width,
        length=length,
        fingers=fingers,
        multipliers=multipliers,
        with_substrate_tap=with_substrate_tap,
        with_dummy=with_dummy,
        with_tie=with_tie,
        tie_layers=tie_layers,
        sd_rmult=sd_rmult,
        gate_rmult=gate_rmult,
        interfinger_topmet=interfinger_topmet,
    )


@validate_arguments
def pmos(
    pdk: MappedPDK,
    *,
    width: float = 1.0,
    length: Optional[float] = None,
    fingers: int = 1,
    multipliers: int = 1,
    with_substrate_tap: bool = True,
    with_dummy: Union[bool, tuple[bool, bool]] = True,
    with_tie: bool = True,
    tie_layers: tuple[str, str] = ("met2", "met1"),
    sd_rmult: int = 1,
    gate_rmult: int = 1,
    interfinger_topmet: str = "met2",
) -> Component:
    """
    PMOS transistor.

    Same arguments as :func:`nmos` — substrate tap connects to VDD instead of VSS.

    Returns:
        Component with ports: gate_*, drain_*, source_*, bulk_*

    Example::

        from gelochip.glayout.pdk.gf180_mapped import gf180_mapped_pdk as pdk
        mp = pmos(pdk, width=4.0, fingers=2)
        mp.show()
    """
    length = length or pdk.get_grule("poly")["min_width"]
    return _glayout_pmos(
        pdk=pdk,
        width=width,
        length=length,
        fingers=fingers,
        multipliers=multipliers,
        with_substrate_tap=with_substrate_tap,
        with_dummy=with_dummy,
        with_tie=with_tie,
        tie_layers=tie_layers,
        sd_rmult=sd_rmult,
        gate_rmult=gate_rmult,
        interfinger_topmet=interfinger_topmet,
    )
