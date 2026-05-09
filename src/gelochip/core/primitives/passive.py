"""
Passive component wrappers: resistor, capacitor (MIM), inductor (future).

Port convention:
    resistor  → plus_*, minus_*
    capacitor → top_*, bot_*
    mimcap    → top_met_*, bot_met_*
"""
from __future__ import annotations
from typing import Optional

from gdsfactory.component import Component
from pydantic import validate_arguments

from gelochip.glayout.pdk.mappedpdk import MappedPDK
from gelochip.glayout.primitives.mimcap import mimcap as _mimcap, mimcap_array as _mimcap_array
from gelochip.glayout.primitives.resistor import resistor as _resistor


@validate_arguments
def resistor(
    pdk: MappedPDK,
    *,
    width: float = 5.0,
    length: float = 1.0,
    num_series: int = 1,
    with_substrate_tap: bool = False,
    multipliers: int = 1,
) -> Component:
    """
    Diode-connected PFET programmable resistor (PDK-agnostic).

    Small-signal resistance ≈ (1/gm) ∥ ro.  Works with gf180, sky130, and ihp130.

    Args:
        pdk:               Technology PDK (gf180 default).
        width:             PFET gate width (µm). Larger → lower resistance.
        length:            PFET gate length (µm). Larger → higher resistance.
        num_series:        Resistors in series (increases total resistance).
        with_substrate_tap: Add substrate contact tap.
        multipliers:       Resistors in parallel (decreases total resistance).

    Returns:
        Component with ports: plus_*, minus_*

    Example::

        from gelochip.glayout.pdk.gf180_mapped import gf180_mapped_pdk as pdk
        r = resistor(pdk, width=2.0, length=5.0, num_series=3)
    """
    return _resistor(
        pdk=pdk,
        width=width,
        length=length,
        num_series=num_series,
        with_substrate_tap=with_substrate_tap,
        multipliers=multipliers,
    )


@validate_arguments
def capacitor(
    pdk: MappedPDK,
    *,
    width: float = 5.0,
    length: float = 5.0,
) -> Component:
    """
    MIM capacitor.

    Args:
        pdk:    Technology PDK.
        width:  Cap width in µm.
        length: Cap length in µm.

    Returns:
        Component with ports: top_met_*, bot_met_*
    """
    return _mimcap(pdk=pdk, size=(width, length))


@validate_arguments
def mimcap(
    pdk: MappedPDK,
    *,
    width: float = 5.0,
    length: float = 5.0,
    rows: int = 1,
    columns: int = 1,
) -> Component:
    """
    MIM capacitor array (rows × columns fingers for higher capacitance).

    Returns:
        Component with ports: top_met_*, bot_met_*
    """
    if rows == 1 and columns == 1:
        return _mimcap(pdk=pdk, size=(width, length))
    return _mimcap_array(pdk=pdk, size=(width, length), num_caps=(rows, columns))


def inductor(
    pdk: MappedPDK,
    *,
    turns: int = 3,
    inner_diameter: float = 50.0,
    width: float = 5.0,
    spacing: float = 5.0,
    layer: str = "met5",
) -> Component:
    """
    Spiral inductor (basic rectangular spiral).

    NOTE: Full RF spiral inductor with EM simulation hooks is on the roadmap.
          This stub returns an empty component with placeholder ports for
          AI-agent topology assembly.

    Returns:
        Component with ports: port1_*, port2_* (center-tap future)
    """
    comp = Component("spiral_inductor")
    comp.info["turns"] = turns
    comp.info["inner_diameter"] = inner_diameter
    comp.info["width"] = width
    comp.info["spacing"] = spacing
    comp.info["layer"] = layer
    comp.info["todo"] = "Full spiral inductor generation pending EM-aware routing"
    return comp
