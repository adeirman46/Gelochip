"""Guard ring (substrate/well tap ring) wrapper."""
from __future__ import annotations
from typing import Optional

from gdsfactory.component import Component
from pydantic import validate_arguments

from gelochip.glayout.pdk.mappedpdk import MappedPDK
from gelochip.glayout.primitives.guardring import tapring as _tapring


@validate_arguments
def guard_ring(
    pdk: MappedPDK,
    enclosed_rectangle: tuple[float, float],
    *,
    sdlayer: str = "p+s/d",
    horizontal_glayer: str = "met1",
    vertical_glayer: str = "met1",
) -> Component:
    """
    Guard ring (tap ring) around a rectangular area for latch-up protection.

    Args:
        pdk:                Technology PDK.
        enclosed_rectangle: (width, height) of the area to surround in µm.
        sdlayer:            Diffusion layer for the tap ("p+s/d" or "n+s/d").
        horizontal_glayer:  Metal for top/bottom straps.
        vertical_glayer:    Metal for left/right straps.

    Returns:
        Component with perimeter ports for VDD/VSS connection.
    """
    return _tapring(
        pdk=pdk,
        enclosed_rectangle=enclosed_rectangle,
        sdlayer=sdlayer,
        horizontal_glayer=horizontal_glayer,
        vertical_glayer=vertical_glayer,
    )
