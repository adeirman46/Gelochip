from __future__ import annotations

from typing import Optional

from gdsfactory.cell import cell
from gdsfactory.component import Component
from gdsfactory.components.rectangle import rectangle
from gdsfactory.port import Port
from pydantic import validate_arguments

from glayout.pdk.mappedpdk import MappedPDK
from glayout.primitives.fet import nmos, pmos
from glayout.primitives.mimcap import mimcap
from glayout.routing.straight_route import straight_route
from glayout.spice import Netlist
from glayout.util.comp_utils import prec_ref_center, movex, movey
from glayout.util.port_utils import add_ports_perimeter


def _expose_port(top: Component, name: str, port: Port) -> None:
    top.add_port(name=name, port=port)


def _make_pin(pdk: MappedPDK, size: tuple[float, float], glayer: str = "met2_pin") -> Component:
    pin = Component("pin")
    pin << rectangle(size=size, layer=pdk.get_glayer(glayer), centered=True)
    return add_ports_perimeter(pin, layer=pdk.get_glayer(glayer), prefix="pin_")


def _get_component_netlist(component: Component) -> Netlist:
    netlist_info = component.info.get("netlist") if hasattr(component, "info") else None
    if isinstance(netlist_info, Netlist):
        return netlist_info

    netlist_obj = component.info.get("netlist_obj") if hasattr(component, "info") else None
    if isinstance(netlist_obj, Netlist):
        return netlist_obj

    if isinstance(netlist_info, str) and netlist_info.strip():
        netlist_data = component.info.get("netlist_data") if hasattr(component, "info") else None
        if isinstance(netlist_data, dict):
            circuit_name = netlist_data.get("circuit_name")
            nodes = netlist_data.get("nodes")
            source_netlist = netlist_data.get("source_netlist")
            if circuit_name and nodes and source_netlist:
                parameters: dict[str, str] = {}
                model_index = 1 + len(nodes)
                for line in netlist_info.splitlines():
                    stripped = line.strip()
                    if not stripped or stripped.startswith(".") or stripped.startswith("*"):
                        continue
                    if stripped[0].upper() != "X":
                        continue
                    parts = stripped.split()
                    if len(parts) > model_index:
                        parameters["model"] = parts[model_index]
                        break
                netlist = Netlist(
                    circuit_name=circuit_name,
                    nodes=list(nodes),
                    parameters=parameters,
                )
                netlist.source_netlist = source_netlist
                return netlist

        for line in netlist_info.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith(".subckt"):
                parts = stripped.split()
                if len(parts) >= 3:
                    netlist = Netlist(circuit_name=parts[1], nodes=parts[2:])
                    netlist.source_netlist = netlist_info
                    return netlist

    raise ValueError(f"Missing netlist data for component: {component.name}")


def _label_ports(component: Component, port_names: Optional[list[str]] = None) -> None:
    names = port_names or list(component.ports.keys())
    for name in names:
        port = component.ports.get(name)
        if port is None:
            continue
        component.add_label(text=name, position=port.center, layer=port.layer)


@validate_arguments
@cell
def lna_block(
    pdk: MappedPDK,
    *,
    gm_width: float = 20.0,
    gm_length: Optional[float] = None,
    gm_fingers: int = 4,
    cas_width: float = 20.0,
    cas_length: Optional[float] = None,
    cas_fingers: int = 4,
    load_width: float = 10.0,
    load_length: Optional[float] = None,
    load_fingers: int = 2,
    input_cap_size: tuple[float, float] = (10.0, 10.0),
    sd_rmult: int = 2,
) -> Component:
    """Cascode LNA block with AC-coupled input.

    Pins:
        RF_IN (in), RF_OUT (out), VB_GM (in), VB_CAS (in), VDD (in), VSS (in)
    """
    pdk.activate()
    gm_length = gm_length or pdk.get_grule("poly")["min_width"]
    cas_length = cas_length or gm_length
    load_length = load_length or gm_length

    top = Component("lna_block")

    gm = nmos(
        pdk,
        width=gm_width,
        length=gm_length,
        fingers=gm_fingers,
        sd_rmult=sd_rmult,
        with_tie=True,
        with_substrate_tap=False,
    )
    cas = nmos(
        pdk,
        width=cas_width,
        length=cas_length,
        fingers=cas_fingers,
        sd_rmult=sd_rmult,
        with_tie=True,
        with_substrate_tap=False,
    )
    load = pmos(
        pdk,
        width=load_width,
        length=load_length,
        fingers=load_fingers,
        sd_rmult=sd_rmult,
        with_tie=True,
        with_substrate_tap=False,
    )
    cap = mimcap(pdk, size=input_cap_size)

    r_gm = prec_ref_center(gm)
    r_cas = prec_ref_center(cas)
    r_load = prec_ref_center(load)
    r_cap = prec_ref_center(cap)

    top.add(r_gm)
    top.add(r_cas)
    top.add(r_load)
    top.add(r_cap)

    sep = pdk.get_grule("met2")["min_separation"]
    gm_h = gm.bbox[1][1] - gm.bbox[0][1]
    gm_w = gm.bbox[1][0] - gm.bbox[0][0]
    cas_h = cas.bbox[1][1] - cas.bbox[0][1]
    load_h = load.bbox[1][1] - load.bbox[0][1]
    cap_w = cap.bbox[1][0] - cap.bbox[0][0]

    movey(r_cas, gm_h / 2 + cas_h / 2 + sep)
    movey(r_load, gm_h / 2 + cas_h + load_h / 2 + 2 * sep)
    movex(r_cap, -(gm_w / 2 + cap_w / 2 + sep))

    top << straight_route(pdk, r_gm.ports["drain_N"], r_cas.ports["source_S"])
    top << straight_route(pdk, r_cas.ports["drain_N"], r_load.ports["drain_S"])
    top << straight_route(pdk, r_load.ports["gate_S"], r_load.ports["source_S"])
    top << straight_route(pdk, r_cap.ports["top_met_E"], r_gm.ports["gate_W"])

    _expose_port(top, "RF_IN", r_cap.ports["bottom_met_W"])
    _expose_port(top, "RF_OUT", r_cas.ports["drain_N"])
    _expose_port(top, "VB_GM", r_gm.ports["gate_W"])
    _expose_port(top, "VB_CAS", r_cas.ports["gate_W"])
    _expose_port(top, "VDD", r_load.ports["source_N"])
    _expose_port(top, "VSS", r_gm.ports["source_S"])

    _label_ports(top)

    netlist = Netlist(
        circuit_name="LNA_BLOCK",
        nodes=["RF_IN", "RF_OUT", "VB_GM", "VB_CAS", "VDD", "VSS"],
    )
    gm_netlist = _get_component_netlist(gm)
    cas_netlist = _get_component_netlist(cas)
    load_netlist = _get_component_netlist(load)
    cap_netlist = _get_component_netlist(cap)
    gm_drain = "NET_GM_DRAIN"
    netlist.connect_netlist(
        gm_netlist,
        [("D", gm_drain), ("G", "VB_GM"), ("S", "VSS"), ("B", "VSS")],
    )
    netlist.connect_netlist(
        cas_netlist,
        [("D", "RF_OUT"), ("G", "VB_CAS"), ("S", gm_drain), ("B", "VSS")],
    )
    netlist.connect_netlist(
        load_netlist,
        [("D", "RF_OUT"), ("G", "VDD"), ("S", "VDD"), ("B", "VDD")],
    )
    netlist.connect_netlist(cap_netlist, [("V1", "VB_GM"), ("V2", "RF_IN")])
    top.info["netlist"] = netlist
    return top


@validate_arguments
@cell
def rf_amp_block(
    pdk: MappedPDK,
    *,
    width: float = 8.0,
    length: Optional[float] = None,
    fingers: int = 2,
    load_width: float = 6.0,
    load_length: Optional[float] = None,
    load_fingers: int = 2,
    sd_rmult: int = 2,
) -> Component:
    """Single-stage RF amplifier (common-source with biased load).

    Pins:
        RF_IN (in), RF_OUT (out), VBIAS (in), VDD (in), VSS (in)
    """
    pdk.activate()
    length = length or pdk.get_grule("poly")["min_width"]
    load_length = load_length or length

    top = Component("rf_amp_block")

    drv = nmos(
        pdk,
        width=width,
        length=length,
        fingers=fingers,
        sd_rmult=sd_rmult,
        with_tie=True,
        with_substrate_tap=False,
    )
    load = pmos(
        pdk,
        width=load_width,
        length=load_length,
        fingers=load_fingers,
        sd_rmult=sd_rmult,
        with_tie=True,
        with_substrate_tap=False,
    )

    r_drv = prec_ref_center(drv)
    r_load = prec_ref_center(load)
    top.add(r_drv)
    top.add(r_load)

    sep = pdk.get_grule("met2")["min_separation"]
    drv_h = drv.bbox[1][1] - drv.bbox[0][1]
    load_h = load.bbox[1][1] - load.bbox[0][1]
    movey(r_load, drv_h / 2 + load_h / 2 + sep)

    top << straight_route(pdk, r_drv.ports["drain_N"], r_load.ports["drain_S"])

    _expose_port(top, "RF_IN", r_drv.ports["gate_W"])
    _expose_port(top, "RF_OUT", r_drv.ports["drain_N"])
    _expose_port(top, "VBIAS", r_load.ports["gate_W"])
    _expose_port(top, "VDD", r_load.ports["source_N"])
    _expose_port(top, "VSS", r_drv.ports["source_S"])

    _label_ports(top)

    netlist = Netlist(
        circuit_name="RF_AMP_BLOCK",
        nodes=["RF_IN", "RF_OUT", "VBIAS", "VDD", "VSS"],
    )
    drv_netlist = _get_component_netlist(drv)
    load_netlist = _get_component_netlist(load)
    netlist.connect_netlist(
        drv_netlist,
        [("D", "RF_OUT"), ("G", "RF_IN"), ("S", "VSS"), ("B", "VSS")],
    )
    netlist.connect_netlist(
        load_netlist,
        [("D", "RF_OUT"), ("G", "VBIAS"), ("S", "VDD"), ("B", "VDD")],
    )
    top.info["netlist"] = netlist
    return top


@validate_arguments
@cell
def buffer_block(
    pdk: MappedPDK,
    *,
    width: float = 6.0,
    length: Optional[float] = None,
    fingers: int = 2,
    bias_width: float = 3.0,
    bias_fingers: int = 1,
    sd_rmult: int = 2,
) -> Component:
    """Source follower buffer.

    Pins:
        IN (in), OUT (out), VBIAS (in), VDD (in), VSS (in)
    """
    pdk.activate()
    length = length or pdk.get_grule("poly")["min_width"]

    top = Component("buffer_block")

    drv = nmos(
        pdk,
        width=width,
        length=length,
        fingers=fingers,
        sd_rmult=sd_rmult,
        with_tie=True,
        with_substrate_tap=False,
    )
    bias = nmos(
        pdk,
        width=bias_width,
        length=length,
        fingers=bias_fingers,
        sd_rmult=sd_rmult,
        with_tie=True,
        with_substrate_tap=False,
    )

    r_drv = prec_ref_center(drv)
    r_bias = prec_ref_center(bias)
    top.add(r_drv)
    top.add(r_bias)

    sep = pdk.get_grule("met2")["min_separation"]
    drv_h = drv.bbox[1][1] - drv.bbox[0][1]
    bias_h = bias.bbox[1][1] - bias.bbox[0][1]
    movey(r_bias, -(drv_h / 2 + bias_h / 2 + sep))

    top << straight_route(pdk, r_drv.ports["source_S"], r_bias.ports["drain_N"])

    _expose_port(top, "IN", r_drv.ports["gate_W"])
    _expose_port(top, "OUT", r_drv.ports["source_S"])
    _expose_port(top, "VBIAS", r_bias.ports["gate_W"])
    _expose_port(top, "VDD", r_drv.ports["drain_N"])
    _expose_port(top, "VSS", r_bias.ports["source_S"])

    _label_ports(top)

    netlist = Netlist(
        circuit_name="BUFFER_BLOCK",
        nodes=["IN", "OUT", "VBIAS", "VDD", "VSS"],
    )
    drv_netlist = _get_component_netlist(drv)
    bias_netlist = _get_component_netlist(bias)
    netlist.connect_netlist(
        drv_netlist,
        [("D", "VDD"), ("G", "IN"), ("S", "OUT"), ("B", "VSS")],
    )
    netlist.connect_netlist(
        bias_netlist,
        [("D", "OUT"), ("G", "VBIAS"), ("S", "VSS"), ("B", "VSS")],
    )
    top.info["netlist"] = netlist
    return top


@validate_arguments
@cell
def combiner_8to1(
    pdk: MappedPDK,
    *,
    num_inputs: int = 8,
    pin_pitch: float = 6.0,
    trunk_width: float = 2.0,
    pin_size: tuple[float, float] = (1.5, 1.5),
) -> Component:
    """Passive 8:1 combiner (9 pins).

    Pins:
        IN0..IN7 (in), OUT (out)
    """
    pdk.activate()
    top = Component("combiner_8to1")

    trunk_h = pin_pitch * (num_inputs - 1) + pin_size[1]
    trunk = Component("combiner_trunk")
    trunk << rectangle(size=(trunk_width, trunk_h), layer=pdk.get_glayer("met2"), centered=True)
    trunk = add_ports_perimeter(trunk, layer=pdk.get_glayer("met2"), prefix="trunk_")
    trunk_ref = top << trunk

    out_pin = _make_pin(pdk, pin_size)
    out_ref = top << out_pin
    movex(out_ref, trunk_width / 2 + pin_size[0])
    top << straight_route(pdk, out_ref.ports["pin_W"], trunk_ref.ports["trunk_E"])
    _expose_port(top, "OUT", out_ref.ports["pin_E"])

    for idx in range(num_inputs):
        pin = _make_pin(pdk, pin_size)
        pin_ref = top << pin
        movex(pin_ref, -(trunk_width / 2 + pin_size[0]))
        movey(pin_ref, (idx - (num_inputs - 1) / 2) * pin_pitch)
        top << straight_route(pdk, pin_ref.ports["pin_E"], trunk_ref.ports["trunk_W"])
        _expose_port(top, f"IN{idx}", pin_ref.ports["pin_W"])

    _label_ports(top)

    top.info["netlist"] = Netlist(
        circuit_name="COMBINER_8TO1",
        nodes=[f"IN{idx}" for idx in range(num_inputs)] + ["OUT"],
    )
    return top


@validate_arguments
@cell
def rx_frontend(
    pdk: MappedPDK,
    *,
    lna_gm_width: float = 20.0,
    lna_gm_fingers: int = 4,
    switch_width: float = 4.0,
    switch_length: Optional[float] = None,
    switch_fingers: int = 2,
) -> Component:
    """RX front-end: LNA + passive LO switches.

    Pins (max 8):
        RF_IN (in), LO_P (in), LO_N (in), IF_P (out), IF_N (out),
        VBIAS (in), VDD (in), VSS (in)
    """
    pdk.activate()
    switch_length = switch_length or pdk.get_grule("poly")["min_width"]

    top = Component("rx_frontend")

    lna = lna_block(
        pdk,
        gm_width=lna_gm_width,
        gm_fingers=lna_gm_fingers,
    )
    sw_p = nmos(
        pdk,
        width=switch_width,
        length=switch_length,
        fingers=switch_fingers,
        with_tie=True,
        with_substrate_tap=False,
    )
    sw_n = nmos(
        pdk,
        width=switch_width,
        length=switch_length,
        fingers=switch_fingers,
        with_tie=True,
        with_substrate_tap=False,
    )

    r_lna = prec_ref_center(lna)
    r_sw_p = prec_ref_center(sw_p)
    r_sw_n = prec_ref_center(sw_n)

    top.add(r_lna)
    top.add(r_sw_p)
    top.add(r_sw_n)

    sep = pdk.get_grule("met2")["min_separation"]
    lna_w = lna.bbox[1][0] - lna.bbox[0][0]
    sw_w = sw_p.bbox[1][0] - sw_p.bbox[0][0]
    sw_h = sw_p.bbox[1][1] - sw_p.bbox[0][1]

    movex(r_sw_p, lna_w / 2 + sw_w / 2 + 2 * sep)
    movey(r_sw_p, sw_h / 2 + sep)
    movex(r_sw_n, lna_w / 2 + sw_w / 2 + 2 * sep)
    movey(r_sw_n, -(sw_h / 2 + sep))

    top << straight_route(pdk, r_lna.ports["RF_OUT"], r_sw_p.ports["source_W"])
    top << straight_route(pdk, r_lna.ports["RF_OUT"], r_sw_n.ports["source_W"])

    top << straight_route(pdk, r_lna.ports["VB_GM"], r_lna.ports["VB_CAS"])

    _expose_port(top, "RF_IN", r_lna.ports["RF_IN"])
    _expose_port(top, "LO_P", r_sw_p.ports["gate_S"])
    _expose_port(top, "LO_N", r_sw_n.ports["gate_S"])
    _expose_port(top, "IF_P", r_sw_p.ports["drain_E"])
    _expose_port(top, "IF_N", r_sw_n.ports["drain_E"])
    _expose_port(top, "VBIAS", r_lna.ports["VB_GM"])
    _expose_port(top, "VDD", r_lna.ports["VDD"])
    _expose_port(top, "VSS", r_lna.ports["VSS"])

    _label_ports(top)

    netlist = Netlist(
        circuit_name="RX_FRONTEND",
        nodes=["RF_IN", "LO_P", "LO_N", "IF_P", "IF_N", "VBIAS", "VDD", "VSS"],
    )
    lna_netlist = _get_component_netlist(lna)
    sw_p_netlist = _get_component_netlist(sw_p)
    sw_n_netlist = _get_component_netlist(sw_n)
    rf_out_int = "RF_OUT_INT"
    netlist.connect_netlist(
        lna_netlist,
        [
            ("RF_IN", "RF_IN"),
            ("RF_OUT", rf_out_int),
            ("VB_GM", "VBIAS"),
            ("VB_CAS", "VBIAS"),
            ("VDD", "VDD"),
            ("VSS", "VSS"),
        ],
    )
    netlist.connect_netlist(
        sw_p_netlist,
        [("D", "IF_P"), ("G", "LO_P"), ("S", rf_out_int), ("B", "VSS")],
    )
    netlist.connect_netlist(
        sw_n_netlist,
        [("D", "IF_N"), ("G", "LO_N"), ("S", rf_out_int), ("B", "VSS")],
    )
    top.info["netlist"] = netlist
    return top


@validate_arguments
@cell
def mtp_memory_wrapper(
    pdk: MappedPDK,
    *,
    size: tuple[float, float] = (60.0, 40.0),
    pin_size: tuple[float, float] = (2.0, 2.0),
) -> Component:
    """MTP memory macro wrapper.

    Pins:
        WL (in), BL (inout), BLB (inout), VDD (in), VSS (in),
        VPP (in), PGM (in), ERASE (in)
    """
    pdk.activate()
    top = Component("mtp_memory_wrapper")
    top << rectangle(size=size, layer=pdk.get_glayer("met1"), centered=True)

    pins = {
        "WL": (-size[0] / 2 - pin_size[0], 0.0, "pin_E"),
        "BL": (size[0] / 2 + pin_size[0], size[1] / 4, "pin_W"),
        "BLB": (size[0] / 2 + pin_size[0], -size[1] / 4, "pin_W"),
        "VDD": (0.0, size[1] / 2 + pin_size[1], "pin_S"),
        "VPP": (size[0] / 4, size[1] / 2 + pin_size[1], "pin_S"),
        "VSS": (0.0, -(size[1] / 2 + pin_size[1]), "pin_N"),
        "PGM": (-size[0] / 4, -(size[1] / 2 + pin_size[1]), "pin_N"),
        "ERASE": (size[0] / 4, -(size[1] / 2 + pin_size[1]), "pin_N"),
    }

    for name, (x, y, port_name) in pins.items():
        pin = _make_pin(pdk, pin_size)
        pin_ref = top << pin
        movex(pin_ref, x)
        movey(pin_ref, y)
        _expose_port(top, name, pin_ref.ports[port_name])

    _label_ports(top)

    top.info["netlist"] = Netlist(
        circuit_name="MTP_MEMORY_WRAPPER",
        nodes=["WL", "BL", "BLB", "VDD", "VSS", "VPP", "PGM", "ERASE"],
    )
    return top
