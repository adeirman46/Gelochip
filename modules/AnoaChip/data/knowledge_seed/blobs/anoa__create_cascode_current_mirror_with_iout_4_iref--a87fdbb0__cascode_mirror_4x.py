# cascode_mirror_4x — cascode current mirror (nfet), 4 transistors on two interdigitized rows
# (bottom = mirror pair M1/M2, top = cascode pair M3/M4). Adapted from glayout's
# current_mirror.py routing technique: parallel c_routes NEST via different extensions.
#
#   iref -> M3.drain, M3.source -> M1.drain, M1.source -> VDD   (reference, A side)
#   iout -> M4.drain, M4.source -> M2.drain, M2.source -> VDD   (output,    B side)
#   M3 diode (g=d) shared with M4.gate; M1 diode (g=d) shared with M2.gate.
from glayout import MappedPDK
from glayout.placement.four_transistor_interdigitized import generic_4T_interdigitzed
from glayout.routing.c_route import c_route
from glayout.routing.L_route import L_route
from glayout.routing.straight_route import straight_route
from glayout.spice.netlist import Netlist
from glayout.backend import Component
import gdstk


def build(pdk: MappedPDK) -> Component:
    W, L, NF, NUMCOLS = 5.0, 1.0, 1, 2
    comp = Component(name="cascode_mirror_4x")

    # ONE tie total: rows BARE (with_tie=False); the ring is generic_4T's OWN substrate-tap
    # ring (with_substrate_tap default True — glayout computes its enclosure), so we add NO
    # manual tapring. (Passing with_substrate_tap=False crashes glayout — library bug.)
    core = generic_4T_interdigitzed(
        pdk, top_row_device="nfet", bottom_row_device="nfet", numcols=NUMCOLS, length=L,
        top_kwargs=dict(width=W, fingers=NF, with_tie=False),
        bottom_kwargs=dict(width=W, fingers=NF, with_tie=False))
    cref = comp << core
    cref.movey(-(cref.ymax + cref.ymin) / 2)          # center vertically before routing

    ms = pdk.util_max_metal_seperation()
    # east: rail source short (inner), then the two stack routes (nested outward)
    comp << c_route(pdk, cref.ports["bottom_A_source_E"], cref.ports["bottom_B_source_E"],
                    extension=3 * ms, viaoffset=False)
    comp << c_route(pdk, cref.ports["top_A_source_E"], cref.ports["bottom_A_drain_E"],
                    extension=6 * ms, viaoffset=False)     # M3.s -> M1.d
    comp << c_route(pdk, cref.ports["top_B_source_E"], cref.ports["bottom_B_drain_E"],
                    extension=9 * ms, viaoffset=False)     # M4.s -> M2.d
    # west: the two gate shorts (nested), each diode-connected via its con_N
    gshort_b = comp << c_route(pdk, cref.ports["bottom_A_gate_W"], cref.ports["bottom_B_gate_W"],
                               extension=3 * ms, viaoffset=False)
    comp << L_route(pdk, cref.ports["bottom_A_drain_W"], gshort_b.ports["con_N"],
                    viaoffset=False, fullbottom=False)     # M1 diode
    gshort_t = comp << c_route(pdk, cref.ports["top_A_gate_W"], cref.ports["top_B_gate_W"],
                               extension=6 * ms, viaoffset=False)
    comp << L_route(pdk, cref.ports["top_A_drain_W"], gshort_t.ports["con_N"],
                    viaoffset=False, fullbottom=False)     # M3 diode
    # the SINGLE ring = generic_4T's own substrate-tap ring (ports substratetap_*).
    # Route the edge DUMMIES to it (5T-OTA tutorial pattern; skip any absent port).
    for dummy_port, ring_port in (
            ("top_A_0_dummy_L_gsdcon_top_met_W",    "substratetap_W_top_met_W"),
            ("top_B_1_dummy_R_gsdcon_top_met_E",    "substratetap_E_top_met_E"),
            ("bottom_A_0_dummy_L_gsdcon_top_met_W", "substratetap_W_top_met_W"),
            ("bottom_B_1_dummy_R_gsdcon_top_met_E", "substratetap_E_top_met_E")):
        try:
            comp << straight_route(pdk, cref.ports[dummy_port], cref.ports[ring_port],
                                   glayer2="met1")
        except KeyError:
            pass
    # LVS reference netlist: map the 4T netlist onto the cascode topology
    casc = Netlist(circuit_name="CASCODE_CMIRROR",
                   nodes=["iref", "iout", "VDD", "N1", "N2", "B"])
    casc.connect_netlist(core.info["netlist"], [
        ("VDD1", "iref"), ("VSS1", "N1"), ("VG1", "iref"),
        ("VDD2", "iout"), ("VSS2", "N2"), ("VG2", "iref"),
        ("VDD3", "N1"), ("VSS3", "VDD"), ("VG3", "N1"),
        ("VDD4", "N2"), ("VSS4", "VDD"), ("VG4", "N1"),
        ("VB", "B")])
    comp.info["netlist"] = casc
    # ports + labels (LVS matches by label; the ring carries the bulk label B)
    lay = pdk.get_glayer("met2")
    for pin, port in (("iref", cref.ports["top_A_drain_N"]),
                      ("iout", cref.ports["top_B_drain_N"]),
                      ("VDD", cref.ports["bottom_A_source_E"]),
                      ("B", cref.ports["substratetap_S_top_met_S"])):
        comp.add_port(name=pin, port=port)
        comp.add(gdstk.Label(pin, origin=port.center, layer=lay[0], texttype=lay[1]))
    return comp
