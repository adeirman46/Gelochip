import json
import math
import os
import sys
from pathlib import Path

import pya

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config" / "iris_config.json").read_text())
USER = os.environ.get("USER", "root")
os.environ["USER"] = USER
os.environ.setdefault("GF_PDK_OPTION", CONFIG["layout"]["gf_option"])
sys.path.insert(0, str((ROOT.parent / "gf180mcu-pdk/libraries/gf180mcu_fd_pr/latest/cells/klayout/pymacros").resolve()))
from cells import gf180mcu  # noqa: E402


class IrisLayoutBuilder:
    def __init__(self):
        gf180mcu()
        self.layout = pya.Layout()
        self.layout.dbu = 0.001
        self.route_segments = []
        self.layers = {
            "pr": self.layout.layer(0, 0),
            "comp": self.layout.layer(22, 0),
            "poly": self.layout.layer(30, 0),
            "contact": self.layout.layer(33, 0),
            "m1": self.layout.layer(34, 0),
            "via1": self.layout.layer(35, 0),
            "m2": self.layout.layer(36, 0),
            "via2": self.layout.layer(38, 0),
            "m3": self.layout.layer(42, 0),
            "mt30": self.layout.layer(53, 0),
            "m1_label": self.layout.layer(34, 10),
            "m2_label": self.layout.layer(36, 10),
            "m3_label": self.layout.layer(42, 10),
            "m3_pin": self.layout.layer(42, 16),
        }
        self.bus_w = self.um(2.0)
        self.port_w = self.um(2.0)
        self.contact_size = self.um(0.22)
        self.contact_enc = self.um(0.30)
        self.via_size = self.um(0.26)
        self.via_enc = self.um(0.40)

    def um(self, value: float) -> int:
        return int(round(value / self.layout.dbu))

    def shift_box(self, box: pya.Box, dx: int, dy: int) -> pya.Box:
        return pya.Box(box.left + dx, box.bottom + dy, box.right + dx, box.top + dy)

    def box_center(self, box: pya.Box) -> tuple[int, int]:
        return ((box.left + box.right) // 2, (box.bottom + box.top) // 2)

    def draw_box(self, cell: pya.Cell, layer: str, x1: int, y1: int, x2: int, y2: int):
        cell.shapes(self.layers[layer]).insert(pya.Box(min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)))

    def draw_route(self, cell: pya.Cell, layer: str, start: tuple[int, int], end: tuple[int, int], width: int, net: str):
        x1, y1 = start
        x2, y2 = end
        if x1 == x2:
            self.draw_box(cell, layer, x1 - width // 2, y1, x2 + width // 2, y2)
            length_um = abs(y2 - y1) * self.layout.dbu
        elif y1 == y2:
            self.draw_box(cell, layer, x1, y1 - width // 2, x2, y2 + width // 2)
            length_um = abs(x2 - x1) * self.layout.dbu
        else:
            mid = (x2, y1)
            self.draw_route(cell, layer, start, mid, width, net)
            self.draw_route(cell, layer, mid, end, width, net)
            return
        self.route_segments.append({
            "net": net,
            "layer": layer,
            "length_um": length_um,
            "width_um": width * self.layout.dbu,
        })

    def add_label(self, cell: pya.Cell, layer: str, text: str, x: int, y: int):
        cell.shapes(self.layers[layer]).insert(pya.Text(text, x, y))

    def add_via(self, cell: pya.Cell, lower: str, upper: str, x: int, y: int):
        via_layer = "via1" if (lower, upper) == ("m1", "m2") or (lower, upper) == ("m2", "m1") else "via2"
        lower_size = self.via_size + 2 * self.via_enc
        upper_size = self.via_size + 2 * self.via_enc
        self.draw_box(cell, lower, x - lower_size // 2, y - lower_size // 2, x + lower_size // 2, y + lower_size // 2)
        self.draw_box(cell, upper, x - upper_size // 2, y - upper_size // 2, x + upper_size // 2, y + upper_size // 2)
        self.draw_box(cell, via_layer, x - self.via_size // 2, y - self.via_size // 2, x + self.via_size // 2, y + self.via_size // 2)

    def make_poly_contact(self, cell: pya.Cell, x: int, y: int) -> tuple[int, int]:
        size = self.contact_size + 2 * self.contact_enc
        self.draw_box(cell, "poly", x - size // 2, y - size // 2, x + size // 2, y + size // 2)
        self.draw_box(cell, "m1", x - size // 2, y - size // 2, x + size // 2, y + size // 2)
        self.draw_box(cell, "contact", x - self.contact_size // 2, y - self.contact_size // 2, x + self.contact_size // 2, y + self.contact_size // 2)
        return x, y

    def create_mos(self, kind: str, w_um: float, l_um: float, nf: int, name: str) -> tuple[pya.Cell, dict]:
        params = {"volt": "3.3V", "bulk": "Bulk Tie", "w": w_um, "l": l_um, "nf": nf}
        cell = self.layout.create_cell(kind, "gf180mcu", params)
        metal_boxes = [shape.bbox() for shape in cell.shapes(self.layers["m1"]).each()]
        poly_boxes = [shape.bbox() for shape in cell.shapes(self.layers["poly"]).each()]
        bbox = cell.bbox()
        cx = (bbox.left + bbox.right) // 2
        drain = min(metal_boxes, key=lambda box: abs(self.box_center(box)[0] - cx))
        sources = [box for box in metal_boxes if box != drain]
        sources = sorted(sources, key=lambda box: self.box_center(box)[0])
        return cell, {"name": name, "bbox": bbox, "drain": drain, "sources": sources, "poly": poly_boxes}

    def create_mimcap(self, side_um: float) -> tuple[pya.Cell, dict]:
        params = {"mim_option": "MIM-A", "metal_level": "M4", "l": side_um, "w": side_um}
        cell = self.layout.create_cell("mimcap", "gf180mcu", params)
        top_box = [shape.bbox() for shape in cell.shapes(self.layers["m3"]).each()][0]
        bot_box = [shape.bbox() for shape in cell.shapes(self.layers["m2"]).each()][0]
        # v3: wrap MIM in a M2 guard ring 4 µm outside plate edge, addressing MIM.9/10/11
        parent_bbox = cell.bbox()
        gr_pad = self.um(4.0)
        gr_w = self.um(1.5)
        left = parent_bbox.left - gr_pad
        right = parent_bbox.right + gr_pad
        bot = parent_bbox.bottom - gr_pad
        top = parent_bbox.top + gr_pad
        self.draw_box(cell, "m2", left - gr_w, bot - gr_w, right + gr_w, bot)  # bottom edge
        self.draw_box(cell, "m2", left - gr_w, top, right + gr_w, top + gr_w)  # top edge
        self.draw_box(cell, "m2", left - gr_w, bot, left, top)                  # left edge
        self.draw_box(cell, "m2", right, bot, right + gr_w, top)                # right edge
        return cell, {"bbox": cell.bbox(), "top": top_box, "bot": bot_box}

    def place_instance(self, parent: pya.Cell, child: pya.Cell, x: int, y: int):
        parent.insert(pya.CellInstArray(child.cell_index(), pya.Trans(pya.Point(x, y))))
        return {"x": x, "y": y, "cell": child}

    def transformed(self, info: dict, box: pya.Box) -> pya.Box:
        return self.shift_box(box, info["x"], info["y"])

    def tap_gate(self, cell: pya.Cell, inst: dict, meta: dict, side: str = "right") -> tuple[int, int]:
        poly_boxes = [self.transformed(inst, box) for box in meta["poly"]]
        left = min(box.left for box in poly_boxes)
        right = max(box.right for box in poly_boxes)
        top = max(box.top for box in poly_boxes)
        bus_h = self.um(0.5)
        self.draw_box(cell, "poly", left, top - bus_h, right, top + bus_h)
        tap_x = right + self.um(0.7) if side == "right" else left - self.um(0.7)
        tap_y = top
        self.draw_route(cell, "poly", (right if side == "right" else left, tap_y), (tap_x, tap_y), self.um(0.4), f"{meta['name']}_gate_poly")
        return self.make_poly_contact(cell, tap_x, tap_y)

    def tap_source(self, cell: pya.Cell, inst: dict, meta: dict, y_track: int, net: str) -> tuple[int, int]:
        x_values = []
        for source_box in meta["sources"]:
            box = self.transformed(inst, source_box)
            sx, sy = self.box_center(box)
            self.add_via(cell, "m1", "m2", sx, sy)
            self.draw_route(cell, "m2", (sx, sy), (sx, y_track), self.bus_w, net)
            x_values.append(sx)
        anchor_x = sum(x_values) // len(x_values)
        self.draw_route(cell, "m2", (min(x_values), y_track), (max(x_values), y_track), self.bus_w, net)
        return anchor_x, y_track

    def tap_drain(self, cell: pya.Cell, inst: dict, meta: dict, target_y: int, net: str) -> tuple[int, int]:
        box = self.transformed(inst, meta["drain"])
        dx, dy = self.box_center(box)
        self.add_via(cell, "m1", "m2", dx, dy)
        self.draw_route(cell, "m2", (dx, dy), (dx, target_y), self.bus_w, net)
        return dx, target_y

    def tap_metal1_pad(self, cell: pya.Cell, x: int, y: int, target_y: int, net: str) -> tuple[int, int]:
        self.add_via(cell, "m1", "m2", x, y)
        self.draw_route(cell, "m2", (x, y), (x, target_y), self.bus_w, net)
        return x, target_y

    def build_rectifier(self) -> tuple[pya.Cell, dict]:
        cell = self.layout.create_cell("iris_rectifier")
        pmos, p_meta = self.create_mos("pmos", CONFIG["rectifier"]["pmos_w_um"], CONFIG["rectifier"]["pmos_l_um"], CONFIG["rectifier"]["pmos_nf"], "pmos")
        nmos, n_meta = self.create_mos("nmos", CONFIG["rectifier"]["nmos_w_um"], CONFIG["rectifier"]["nmos_l_um"], CONFIG["rectifier"]["nmos_nf"], "nmos")

        mp1 = self.place_instance(cell, pmos, self.um(20), self.um(115))
        mp2 = self.place_instance(cell, pmos, self.um(150), self.um(115))
        mn1 = self.place_instance(cell, nmos, self.um(20), self.um(25))
        mn2 = self.place_instance(cell, nmos, self.um(150), self.um(25))

        vrect_y = self.um(210)
        vss_y = self.um(15)
        rfp_y_top = self.um(155)
        rfp_y_bot = self.um(95)
        rfn_y_top = self.um(155)
        rfn_y_bot = self.um(95)
        gaten_x = self.um(118)
        gatep_x = self.um(250)

        mp1_gate = self.tap_gate(cell, mp1, p_meta)
        mp2_gate = self.tap_gate(cell, mp2, p_meta)
        mn1_gate = self.tap_gate(cell, mn1, n_meta)
        mn2_gate = self.tap_gate(cell, mn2, n_meta)

        mp1_source = self.tap_source(cell, mp1, p_meta, vrect_y, "vrect")
        mp2_source = self.tap_source(cell, mp2, p_meta, vrect_y, "vrect")
        self.draw_route(cell, "m2", mp1_source, mp2_source, self.bus_w, "vrect")

        mn1_source = self.tap_source(cell, mn1, n_meta, vss_y, "vss")
        mn2_source = self.tap_source(cell, mn2, n_meta, vss_y, "vss")
        self.draw_route(cell, "m2", mn1_source, mn2_source, self.bus_w, "vss")

        mp1_drain = self.tap_drain(cell, mp1, p_meta, rfp_y_top, "rfp")
        mn1_drain = self.tap_drain(cell, mn1, n_meta, rfp_y_bot, "rfp")
        self.draw_route(cell, "m2", mp1_drain, (mp1_drain[0], mn1_drain[1]), self.bus_w, "rfp")
        self.draw_route(cell, "m2", (mp1_drain[0], mn1_drain[1]), mn1_drain, self.bus_w, "rfp")

        mp2_drain = self.tap_drain(cell, mp2, p_meta, rfn_y_top, "rfn")
        mn2_drain = self.tap_drain(cell, mn2, n_meta, rfn_y_bot, "rfn")
        self.draw_route(cell, "m2", mp2_drain, (mp2_drain[0], mn2_drain[1]), self.bus_w, "rfn")
        self.draw_route(cell, "m2", (mp2_drain[0], mn2_drain[1]), mn2_drain, self.bus_w, "rfn")

        for point in (mp1_gate, mn1_gate):
            self.add_via(cell, "m1", "m2", point[0], point[1])
            self.draw_route(cell, "m2", point, (gaten_x, point[1]), self.bus_w, "gaten")
        self.draw_route(cell, "m2", (gaten_x, mp1_gate[1]), (gaten_x, mn1_gate[1]), self.bus_w, "gaten")

        for point in (mp2_gate, mn2_gate):
            self.add_via(cell, "m1", "m2", point[0], point[1])
            self.draw_route(cell, "m2", point, (gatep_x, point[1]), self.bus_w, "gatep")
        self.draw_route(cell, "m2", (gatep_x, mp2_gate[1]), (gatep_x, mn2_gate[1]), self.bus_w, "gatep")

        ports = {
            "rfp": (mp1_drain[0], self.um(175), "m2"),
            "rfn": (mp2_drain[0], self.um(175), "m2"),
            "vrect": (self.um(135), vrect_y, "m2"),
            "vss": (self.um(135), vss_y, "m2"),
            "gatep": (gatep_x, self.um(120), "m2"),
            "gaten": (gaten_x, self.um(120), "m2"),
        }
        return cell, ports

    def build_startup_bias(self) -> tuple[pya.Cell, dict]:
        cell = self.layout.create_cell("iris_startup_bias")
        small_pmos, p_meta = self.create_mos("pmos", CONFIG["rectifier"]["bias_pmos_w_um"], CONFIG["rectifier"]["bias_pmos_l_um"], 1, "bias_pmos")
        small_nmos, n_meta = self.create_mos("nmos", CONFIG["rectifier"]["bias_nmos_w_um"], CONFIG["rectifier"]["bias_nmos_l_um"], 1, "bias_nmos")
        cinj_side = math.sqrt(CONFIG["rectifier"]["inject_cap_pf"] * 1e-12 / 2.0e-15)
        mim, c_meta = self.create_mimcap(cinj_side)

        cg = self.place_instance(cell, mim, self.um(20), self.um(60))
        cn = self.place_instance(cell, mim, self.um(95), self.um(60))
        pp = self.place_instance(cell, small_pmos, self.um(185), self.um(120))
        np = self.place_instance(cell, small_nmos, self.um(185), self.um(40))
        pg = self.place_instance(cell, small_pmos, self.um(255), self.um(120))
        ng = self.place_instance(cell, small_nmos, self.um(255), self.um(40))

        gatep_x = self.um(215)
        gaten_x = self.um(285)
        vrect_y = self.um(205)
        vss_y = self.um(15)
        rfp_y = self.um(125)
        rfn_y = self.um(125)

        for inst, meta, gate_x, gate_net, rail_net in (
            (pp, p_meta, gatep_x, "gatep", "vrect"),
            (pg, p_meta, gaten_x, "gaten", "vrect"),
            (np, n_meta, gatep_x, "gatep", "vss"),
            (ng, n_meta, gaten_x, "gaten", "vss"),
        ):
            gate_tap = self.tap_gate(cell, inst, meta)
            self.add_via(cell, "m1", "m2", gate_tap[0], gate_tap[1])
            self.draw_route(cell, "m2", gate_tap, (gate_x, gate_tap[1]), self.bus_w, gate_net if rail_net not in ("vrect", "vss") else rail_net)
            drain_y = self.um(120) if rail_net == "vrect" else self.um(80)
            drain = self.tap_drain(cell, inst, meta, drain_y, gate_net)
            self.draw_route(cell, "m2", drain, (gate_x, drain[1]), self.bus_w, gate_net)
            source_y = vrect_y if rail_net == "vrect" else vss_y
            self.tap_source(cell, inst, meta, source_y, rail_net)

        self.draw_route(cell, "m2", (gatep_x, self.um(70)), (gatep_x, self.um(160)), self.bus_w, "gatep")
        self.draw_route(cell, "m2", (gaten_x, self.um(70)), (gaten_x, self.um(160)), self.bus_w, "gaten")

        cg_top = self.transformed(cg, c_meta["top"])
        cg_bot = self.transformed(cg, c_meta["bot"])
        cn_top = self.transformed(cn, c_meta["top"])
        cn_bot = self.transformed(cn, c_meta["bot"])
        cg_top_center = self.box_center(cg_top)
        cg_bot_center = self.box_center(cg_bot)
        cn_top_center = self.box_center(cn_top)
        cn_bot_center = self.box_center(cn_bot)
        self.add_via(cell, "m2", "m3", cg_top_center[0], cg_top_center[1])
        self.add_via(cell, "m2", "m3", cn_top_center[0], cn_top_center[1])
        self.draw_route(cell, "m3", cg_top_center, (cg_top_center[0], rfn_y), self.bus_w, "rfn")
        self.draw_route(cell, "m3", cn_top_center, (cn_top_center[0], rfp_y), self.bus_w, "rfp")
        self.draw_route(cell, "m2", cg_bot_center, (gatep_x, cg_bot_center[1]), self.bus_w, "gatep")
        self.draw_route(cell, "m2", cn_bot_center, (gaten_x, cn_bot_center[1]), self.bus_w, "gaten")

        ports = {
            "rfp": (cn_top_center[0], rfp_y, "m3"),
            "rfn": (cg_top_center[0], rfn_y, "m3"),
            "gatep": (gatep_x, self.um(95), "m2"),
            "gaten": (gaten_x, self.um(95), "m2"),
            "vrect": (self.um(235), vrect_y, "m2"),
            "vss": (self.um(235), vss_y, "m2"),
        }
        return cell, ports

    def build_frontend(self) -> tuple[pya.Cell, dict]:
        cell = self.layout.create_cell("iris_frontend")
        rect, rect_ports = self.build_rectifier()
        bias, bias_ports = self.build_startup_bias()
        rect_i = self.place_instance(cell, rect, self.um(20), self.um(20))
        bias_i = self.place_instance(cell, bias, self.um(10), self.um(240))

        def abs_port(inst, ports, name):
            x, y, layer = ports[name]
            return inst["x"] + x, inst["y"] + y, layer

        nets = ["rfp", "rfn", "gatep", "gaten", "vrect", "vss"]
        for net in nets:
            x1, y1, layer1 = abs_port(rect_i, rect_ports, net)
            x2, y2, layer2 = abs_port(bias_i, bias_ports, net)
            if layer1 == "m3" or layer2 == "m3":
                if layer1 == "m2":
                    self.add_via(cell, "m2", "m3", x1, y1)
                    layer1 = "m3"
                if layer2 == "m2":
                    self.add_via(cell, "m2", "m3", x2, y2)
                    layer2 = "m3"
                self.draw_route(cell, "m3", (x1, y1), (x2, y2), self.bus_w, net)
            else:
                self.draw_route(cell, "m2", (x1, y1), (x2, y2), self.bus_w, net)

        ports = {
            "rfp": (abs_port(rect_i, rect_ports, "rfp")[0], self.um(455), "m3"),
            "rfn": (abs_port(rect_i, rect_ports, "rfn")[0], self.um(455), "m3"),
            "vrect": (self.um(250), self.um(445), "m2"),
            "vss": (self.um(250), self.um(25), "m2"),
        }
        gatep_x, gatep_y, _ = abs_port(rect_i, rect_ports, "gatep")
        gaten_x, gaten_y, _ = abs_port(rect_i, rect_ports, "gaten")
        self.draw_route(cell, "m2", (gatep_x, gatep_y), (gatep_x, self.um(430)), self.bus_w, "gatep")
        self.draw_route(cell, "m2", (gaten_x, gaten_y), (gaten_x, self.um(430)), self.bus_w, "gaten")
        self.draw_route(cell, "m2", (self.um(250), self.um(350)), (self.um(250), self.um(445)), self.bus_w, "vrect")
        self.draw_route(cell, "m2", (self.um(250), self.um(25)), (self.um(250), self.um(120)), self.bus_w, "vss")
        self.add_via(cell, "m2", "m3", ports["rfp"][0], ports["rfp"][1])
        self.add_via(cell, "m2", "m3", ports["rfn"][0], ports["rfn"][1])
        return cell, ports

    def build_charge_pump(self) -> tuple[pya.Cell, dict]:
        cell = self.layout.create_cell("iris_chargepump")
        diode, d_meta = self.create_mos("nmos", CONFIG["charge_pump"]["diode_w_um"], CONFIG["charge_pump"]["diode_l_um"], CONFIG["charge_pump"]["diode_nf"], "cp_diode")
        cstage_side = math.sqrt(CONFIG["charge_pump"]["stage_cap_pf"] * 1e-12 / 2.0e-15)
        cstore_side = math.sqrt(CONFIG["charge_pump"]["storage_cap_pf"] * 1e-12 / 2.0e-15)
        cstage, cs_meta = self.create_mimcap(cstage_side)
        cstore, cst_meta = self.create_mimcap(cstore_side)

        d1 = self.place_instance(cell, diode, self.um(25), self.um(190))
        d2 = self.place_instance(cell, diode, self.um(120), self.um(190))
        d3 = self.place_instance(cell, diode, self.um(215), self.um(190))
        c1 = self.place_instance(cell, cstage, self.um(20), self.um(55))
        c2 = self.place_instance(cell, cstage, self.um(125), self.um(55))
        c3 = self.place_instance(cell, cstage, self.um(230), self.um(55))
        c4 = self.place_instance(cell, cstore, self.um(345), self.um(45))

        vrect_x = self.um(40)
        n1_x = self.um(135)
        n2_x = self.um(230)
        vout_x = self.um(325)
        diode_y = self.um(265)
        source_y = self.um(175)
        clock_y = self.um(140)
        vss_y = self.um(25)

        diode_nodes = [(d1, vrect_x, n1_x, "vrect", "n1"), (d2, n1_x, n2_x, "n1", "n2"), (d3, n2_x, vout_x, "n2", "vout")]
        for inst, pre_x, post_x, pre_net, post_net in diode_nodes:
            gate_tap = self.tap_gate(cell, inst, d_meta)
            self.add_via(cell, "m1", "m2", gate_tap[0], gate_tap[1])
            self.draw_route(cell, "m2", gate_tap, (pre_x, gate_tap[1]), self.bus_w, pre_net)
            drain = self.tap_drain(cell, inst, d_meta, diode_y, pre_net)
            self.draw_route(cell, "m2", drain, (pre_x, diode_y), self.bus_w, pre_net)
            source = self.tap_source(cell, inst, d_meta, source_y, post_net)
            self.draw_route(cell, "m2", source, (post_x, source_y), self.bus_w, post_net)

        self.draw_route(cell, "m2", (vrect_x, diode_y), (vrect_x, source_y), self.bus_w, "vrect")
        self.draw_route(cell, "m2", (n1_x, diode_y), (n1_x, source_y), self.bus_w, "n1")
        self.draw_route(cell, "m2", (n2_x, diode_y), (n2_x, source_y), self.bus_w, "n2")
        self.draw_route(cell, "m2", (vout_x, diode_y), (vout_x, source_y), self.bus_w, "vout")

        cap_bindings = [
            (c1, cs_meta, "rfp", vrect_x, n1_x),
            (c2, cs_meta, "rfn", n1_x, n2_x),
            (c3, cs_meta, "rfp", n2_x, vout_x),
        ]
        for inst, meta, clock_net, _, bottom_x in cap_bindings:
            top = self.transformed(inst, meta["top"])
            bot = self.transformed(inst, meta["bot"])
            top_c = self.box_center(top)
            bot_c = self.box_center(bot)
            self.add_via(cell, "m2", "m3", top_c[0], top_c[1])
            self.draw_route(cell, "m3", top_c, (top_c[0], clock_y), self.bus_w, clock_net)
            self.draw_route(cell, "m2", bot_c, (bottom_x, bot_c[1]), self.bus_w, f"{clock_net}_bottom")

        store_top = self.transformed(c4, cst_meta["top"])
        store_bot = self.transformed(c4, cst_meta["bot"])
        store_top_c = self.box_center(store_top)
        store_bot_c = self.box_center(store_bot)
        self.add_via(cell, "m2", "m3", store_top_c[0], store_top_c[1])
        self.draw_route(cell, "m3", store_top_c, (vout_x, store_top_c[1]), self.bus_w, "vout")
        self.draw_route(cell, "m2", store_bot_c, (vout_x, vss_y), self.bus_w, "vss")
        self.draw_route(cell, "m2", (vout_x, source_y), (vout_x, vss_y), self.bus_w, "vout")

        ports = {
            "rfp": (self.um(60), clock_y, "m3"),
            "rfn": (self.um(165), clock_y, "m3"),
            "vrect": (vrect_x, diode_y, "m2"),
            "vout": (vout_x, self.um(110), "m3"),
            "vss": (vout_x, vss_y, "m2"),
        }
        return cell, ports

    def build_top(self) -> tuple[pya.Cell, dict]:
        top = self.layout.create_cell("iris")
        die = self.um(CONFIG["die_size_um"])
        self.draw_box(top, "pr", 0, 0, die, die)

        frontend, fe_ports = self.build_frontend()
        pump, cp_ports = self.build_charge_pump()
        fe_i = self.place_instance(top, frontend, self.um(20), self.um(20))
        cp_i = self.place_instance(top, pump, self.um(15), self.um(25))

        def abs_port(inst, ports, name):
            x, y, layer = ports[name]
            return inst["x"] + x, inst["y"] + y, layer

        shared_nets = ["rfp", "rfn", "vrect", "vss"]
        for net in shared_nets:
            x1, y1, layer1 = abs_port(fe_i, fe_ports, net)
            x2, y2, layer2 = abs_port(cp_i, cp_ports, net)
            layer = "m3" if "m3" in (layer1, layer2) else "m2"
            if layer == "m3":
                if layer1 == "m2":
                    self.add_via(top, "m2", "m3", x1, y1)
                if layer2 == "m2":
                    self.add_via(top, "m2", "m3", x2, y2)
            self.draw_route(top, layer, (x1, y1), (x2, y2), self.bus_w, net)
            label_layer = "m3_label" if layer == "m3" else "m2_label"
            self.add_label(top, label_layer, net, x1, y1)

        vout_x, vout_y, vout_layer = abs_port(cp_i, cp_ports, "vout")
        if vout_layer == "m2":
            self.add_via(top, "m2", "m3", vout_x, vout_y)
            vout_layer = "m3"
        self.add_label(top, "m3_label", "vout", vout_x, vout_y)

        pads = {
            "rfp": (self.um(40), die - self.um(30)),
            "rfn": (self.um(110), die - self.um(30)),
            "vout": (die - self.um(40), self.um(250)),
            "vss": (self.um(40), self.um(30)),
        }
        # v3: alias LVS-friendly names to legacy names for M3.pin port labels
        pad_aliases = {
            "rfp": ["rfp", "VIN+"],
            "rfn": ["rfn", "VIN-"],
            "vout": ["vout", "VOUT"],
            "vss": ["vss", "VSS"],
        }
        for name, (px, py) in pads.items():
            pad_half = self.um(15)
            # M3 pad geometry, widened from 12 -> 15 to satisfy MT30.8 min-area
            self.draw_box(top, "m3", px - pad_half, py - pad_half, px + pad_half, py + pad_half)
            for label in pad_aliases[name]:
                self.add_label(top, "m3_label", label, px, py)
                # v3: place port labels on M3.pin (42.16) explicitly for LVS binder
                self.add_label(top, "m3_pin", label, px, py)

        net_points = {
            "rfp": abs_port(fe_i, fe_ports, "rfp"),
            "rfn": abs_port(fe_i, fe_ports, "rfn"),
            "vout": (vout_x, vout_y, vout_layer),
            "vss": abs_port(fe_i, fe_ports, "vss"),
        }
        for name, (nx, ny, layer) in net_points.items():
            px, py = pads[name]
            if layer == "m2":
                self.add_via(top, "m2", "m3", nx, ny)
            self.draw_route(top, "m3", (nx, ny), (px, py), self.bus_w, name)

        # v3: label VRECT as a M3.pin probe point directly on the internal frontend
        # vrect net (no dedicated top-level pad, avoids shorting into other pads).
        try:
            vrect_x_net, vrect_y_net, vrect_layer = abs_port(fe_i, fe_ports, "vrect")
            if vrect_layer == "m2":
                self.add_via(top, "m2", "m3", vrect_x_net, vrect_y_net)
                probe_half = self.um(4)
                self.draw_box(top, "m3", vrect_x_net - probe_half, vrect_y_net - probe_half,
                              vrect_x_net + probe_half, vrect_y_net + probe_half)
            for lbl in ("vrect", "VRECT"):
                self.add_label(top, "m3_label", lbl, vrect_x_net, vrect_y_net)
                self.add_label(top, "m3_pin", lbl, vrect_x_net, vrect_y_net)
        except Exception:
            pass

        # v3: MT30 density fill tiles in the empty upper-right and lower-right corners
        self._add_mt30_fill(top, die)

        return top, {"die_size_um": CONFIG["die_size_um"]}

    def _add_mt30_fill(self, top: pya.Cell, die: int):
        """Insert a coarse MT30 (top-metal) fill array over regions not covered by active routing."""
        tile = self.um(30)
        pitch = self.um(45)
        # Two fill bands: right edge column and upper-right block, avoiding pad rows.
        keep_out = [
            (self.um(0), self.um(0), self.um(200), self.um(200)),          # frontend
            (self.um(0), self.um(200), self.um(400), die),                  # pump + top
            (die - self.um(80), self.um(200), die, die - self.um(50)),     # vrect/vout pad column
            (self.um(0), die - self.um(60), self.um(180), die),            # rfp/rfn pad row
            (die - self.um(80), self.um(0), die, self.um(80)),             # bottom-right
        ]
        def inside_keep(x1, y1, x2, y2):
            for kx1, ky1, kx2, ky2 in keep_out:
                if not (x2 < kx1 or x1 > kx2 or y2 < ky1 or y1 > ky2):
                    return True
            return False
        x = self.um(220)
        count = 0
        while x + tile < die:
            y = self.um(20)
            while y + tile < die:
                if not inside_keep(x, y, x + tile, y + tile):
                    self.draw_box(top, "mt30", x, y, x + tile, y + tile)
                    count += 1
                y += pitch
            x += pitch
        self.mt30_fill_count = count

    def write_outputs(self):
        top, summary = self.build_top()
        gds = ROOT / "layout" / "iris.gds"
        self.layout.write(str(gds))
        net_caps = {}
        tech = {
            "m1": {"r_sheet": 0.08, "c_per_um_f": 0.18e-15},
            "m2": {"r_sheet": 0.05, "c_per_um_f": 0.15e-15},
            "m3": {"r_sheet": 0.03, "c_per_um_f": 0.10e-15},
        }
        for seg in self.route_segments:
            props = tech.get(seg["layer"])
            if not props:
                continue
            net_caps.setdefault(seg["net"], {"r_ohm": 0.0, "c_f": 0.0})
            net_caps[seg["net"]]["r_ohm"] += props["r_sheet"] * (seg["length_um"] / max(seg["width_um"], 0.1))
            net_caps[seg["net"]]["c_f"] += props["c_per_um_f"] * seg["length_um"]
        (ROOT / "layout" / "route_parasitics.json").write_text(json.dumps(net_caps, indent=2))
        (ROOT / "layout" / "layout_summary.json").write_text(json.dumps(summary, indent=2))
        print(gds)


if __name__ == "__main__":
    builder = IrisLayoutBuilder()
    builder.write_outputs()
