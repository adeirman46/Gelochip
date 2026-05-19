"""Via stack / array wrappers."""
from __future__ import annotations
from typing import Optional, Union

from gdsfactory.component import Component

from glayout.pdk.mappedpdk import MappedPDK
from glayout.primitives.via_gen import via_stack as _via_stack, via_array as _via_array


def via_stack(
    pdk: MappedPDK,
    glayer_start: str,
    glayer_end: str,
    *,
    size: Optional[tuple[float, float]] = None,
    lay_every_layer: bool = True,
) -> Component:
    """
    Single via stack connecting two generic layers.

    Args:
        pdk:           Technology PDK.
        glayer_start:  Bottom generic layer name (e.g. "active_diff", "met1").
        glayer_end:    Top generic layer name (e.g. "met3").
        size:          (width, height) override in µm.
        lay_every_layer: Place vias at every intermediate layer.

    Returns:
        Component with ports: top_met_*, bot_met_*
    """
    kwargs = {}
    if size is not None:
        kwargs["size"] = size
    return _via_stack(pdk, glayer_start, glayer_end, **kwargs)


def via_array(
    pdk: MappedPDK,
    glayer_start: str,
    glayer_end: str,
    *,
    size: tuple[Optional[float], Optional[float]] = (None, None),
    num_vias: Optional[tuple[Optional[int], Optional[int]]] = None,
    minus1: bool = False,
) -> Component:
    """
    Via array (multiple vias arranged in a grid for higher current capacity).

    Args:
        pdk:           Technology PDK.
        glayer_start:  Bottom generic layer name.
        glayer_end:    Top generic layer name.
        size:          (width, height) in µm; None = auto from via rules.
        num_vias:      Explicit (cols, rows) override.
        minus1:        Remove one via row/col at each edge (for FET finger arrays).

    Returns:
        Component with ports matching the top metal shape.
    """
    kwargs = {"size": size, "minus1": minus1}
    if num_vias is not None:
        kwargs["num_vias"] = num_vias
    return _via_array(pdk, glayer_start, glayer_end, **kwargs)
