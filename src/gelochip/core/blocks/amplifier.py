"""
Single-transistor amplifier stages.

    common_source – Inverting voltage amplifier  (Av ≈ −gm·Rload)
    common_gate   – Non-inverting, low input-Z   (good for RF cascode/LNA)
    common_drain  – Source follower / buffer      (Av ≈ 1, low Zout)

All stages accept an optional load specification:
    load_type = "resistor" | "pmos_diode" | "current_mirror" | "cascode"
"""
from __future__ import annotations
from typing import Optional, Literal

from gdsfactory.component import Component
from pydantic import validate_arguments

from gelochip.glayout.pdk.mappedpdk import MappedPDK
from gelochip.glayout.primitives.fet import nmos, pmos
from gelochip.glayout.primitives.guardring import tapring
from gelochip.glayout.util.comp_utils import prec_ref_center, movex, movey
from gelochip.glayout.util.port_utils import rename_ports_by_orientation
from gelochip.glayout.spice.netlist import Netlist

LoadType = Literal["resistor", "pmos_diode", "current_mirror", "cascode"]


@validate_arguments
def common_source(
    pdk: MappedPDK,
    *,
    width: float = 4.0,
    length: Optional[float] = None,
    fingers: int = 2,
    load_type: LoadType = "pmos_diode",
    load_width: float = 4.0,
    load_length: Optional[float] = None,
    load_fingers: int = 2,
    n_or_p: str = "nfet",
    sd_rmult: int = 1,
) -> Component:
    """
    Common-source amplifier stage.

    Args:
        pdk:          Technology PDK.
        width:        Driver transistor gate width (µm).
        length:       Gate length (µm).
        fingers:      Driver gate fingers.
        load_type:    Active load topology.
        load_width:   Load transistor width (µm).
        load_length:  Load gate length (µm).
        load_fingers: Load transistor fingers.
        n_or_p:       "nfet" driver or "pfet" driver.
        sd_rmult:     S/D via multiplier.

    Returns:
        Component with ports:
            in_gate_*   – Gate input
            out_drain_* – Drain output
            bias_gate_* – Load bias (for current-mirror load)
            vdd_*, vss_*

    Example::

        cs = common_source(pdk, width=4.0, fingers=4, load_type="pmos_diode")
        cs.show()
    """
    length = length or pdk.get_grule("poly")["min_width"]
    load_length = load_length or length

    top = Component("common_source")
    driver_fn = nmos if n_or_p == "nfet" else pmos
    load_fn = pmos if n_or_p == "nfet" else nmos

    drv = driver_fn(pdk, width=width, length=length, fingers=fingers, sd_rmult=sd_rmult)
    load = load_fn(pdk, width=load_width, length=load_length, fingers=load_fingers)

    r_drv = prec_ref_center(drv)
    r_load = prec_ref_center(load)
    top.add(r_drv)
    top.add(r_load)

    bbox_h = drv.bbox[1][1] - drv.bbox[0][1]
    sep = pdk.get_grule("met2")["min_separation"]
    movey(r_load, bbox_h + sep)

    top.add_ports(r_drv.get_ports_list(), prefix="drv_")
    top.add_ports(r_load.get_ports_list(), prefix="load_")
    top.info["netlist"] = Netlist(
        circuit_name="COMMON_SOURCE",
        nodes=["IN", "OUT", "BIAS", "VDD", "VSS"],
    )
    return rename_ports_by_orientation(top)


@validate_arguments
def common_gate(
    pdk: MappedPDK,
    *,
    width: float = 4.0,
    length: Optional[float] = None,
    fingers: int = 2,
    load_width: float = 4.0,
    load_fingers: int = 2,
    n_or_p: str = "nfet",
    sd_rmult: int = 1,
) -> Component:
    """
    Common-gate (cascode) amplifier stage.

    Low input impedance (~1/gm), wide bandwidth, suitable as cascode device
    in LNA / RF amplifier design.

    Returns:
        Component with ports:
            in_source_*  – Source input (signal injection)
            out_drain_*  – Drain output
            bias_gate_*  – Gate bias voltage
            vdd_*, vss_*
    """
    length = length or pdk.get_grule("poly")["min_width"]
    top = Component("common_gate")
    driver_fn = nmos if n_or_p == "nfet" else pmos
    load_fn = pmos if n_or_p == "nfet" else nmos

    drv = driver_fn(pdk, width=width, length=length, fingers=fingers, sd_rmult=sd_rmult)
    load = load_fn(pdk, width=load_width, length=length, fingers=load_fingers)

    r_drv = prec_ref_center(drv)
    r_load = prec_ref_center(load)
    top.add(r_drv); top.add(r_load)

    bbox_h = drv.bbox[1][1] - drv.bbox[0][1]
    sep = pdk.get_grule("met2")["min_separation"]
    movey(r_load, bbox_h + sep)

    top.add_ports(r_drv.get_ports_list(), prefix="drv_")
    top.add_ports(r_load.get_ports_list(), prefix="load_")
    top.info["netlist"] = Netlist(
        circuit_name="COMMON_GATE",
        nodes=["IN", "OUT", "GATE_BIAS", "VDD", "VSS"],
    )
    return rename_ports_by_orientation(top)


@validate_arguments
def common_drain(
    pdk: MappedPDK,
    *,
    width: float = 4.0,
    length: Optional[float] = None,
    fingers: int = 2,
    bias_current_width: float = 2.0,
    bias_current_fingers: int = 1,
    n_or_p: str = "nfet",
    sd_rmult: int = 1,
) -> Component:
    """
    Common-drain (source follower / buffer) stage.

    Unity voltage gain, low output impedance (~1/gm), suitable for driving
    capacitive loads or impedance matching in RF design.

    Returns:
        Component with ports:
            in_gate_*    – Gate input
            out_source_* – Source output (buffered signal)
            ibias_gate_* – Bias current transistor gate
            vdd_*, vss_*
    """
    length = length or pdk.get_grule("poly")["min_width"]
    top = Component("common_drain")
    driver_fn = nmos if n_or_p == "nfet" else pmos

    drv = driver_fn(pdk, width=width, length=length, fingers=fingers, sd_rmult=sd_rmult)
    bias = driver_fn(pdk, width=bias_current_width, length=length,
                     fingers=bias_current_fingers)

    r_drv = prec_ref_center(drv)
    r_bias = prec_ref_center(bias)
    top.add(r_drv); top.add(r_bias)

    bbox_h = drv.bbox[1][1] - drv.bbox[0][1]
    sep = pdk.get_grule("met2")["min_separation"]
    movey(r_bias, -(bbox_h + sep))

    top.add_ports(r_drv.get_ports_list(), prefix="drv_")
    top.add_ports(r_bias.get_ports_list(), prefix="bias_")
    top.info["netlist"] = Netlist(
        circuit_name="COMMON_DRAIN",
        nodes=["IN", "OUT", "IBIAS", "VDD", "VSS"],
    )
    return rename_ports_by_orientation(top)
