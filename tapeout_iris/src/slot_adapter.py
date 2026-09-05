"""D05 slot adapter — connects the RF-harvester core to the Chipathon 2026
project-slot boundary pins, and emits the tapeout package.

Everything here is driven by the organiser's own D05.def.tgz: the slot size,
the pin rectangles and the Metal2 corner obstructions are PARSED, never
hard-coded, so re-running against a newly issued def bundle is a no-op edit.
"""
from __future__ import annotations
import json, os, re, tarfile, tempfile
from pathlib import Path

import yaml

# ------------------------------------------------------------------ slot spec
DEF_DBU_PER_UM = 200          # "UNITS DISTANCE MICRONS 200" in every D05 def


class SlotSpec:
    """One project-slot variant, parsed from D05.def.tgz."""

    def __init__(self, tgz: str | Path, variant: str, project: str = "D05"):
        self.tgz, self.variant, self.project = str(tgz), variant, project
        self._load()

    # -- parsing -----------------------------------------------------------
    def _member(self, tf: tarfile.TarFile, suffix: str) -> str:
        want = f"{self.project}/project_defs/{self.variant}/" \
               f"{self.project}_{self.variant}{suffix}"
        f = tf.extractfile(want)
        if f is None:
            raise FileNotFoundError(want)
        return f.read().decode()

    def _load(self):
        with tarfile.open(self.tgz) as tf:
            iface = yaml.safe_load(self._member(tf, "_interface.yaml"))
            deftxt = self._member(tf, ".def")
            sel = json.loads(
                tf.extractfile(f"{self.project}/project_defs/"
                               f"{self.project}_selected_variants.json").read())

        self.iface, self.selected = iface, sel
        self.size_um = tuple(float(v) for v in iface["size_microns"])
        self.origin_um = tuple(float(v) for v in iface["origin_microns"])
        self.top_cell_hint = sel["project_size"]["top_cell"]
        self.available_variants = sel["selected_variants"]

        # Metal2 keep-outs, dbu -> um, in USER (slot) coordinates
        self.m2_obstructions = [
            tuple(v / DEF_DBU_PER_UM for v in rect)
            for rect in (iface.get("metal2_blockages") or [])
        ]
        # sanity: the def BLOCKAGES section must agree with the yaml
        dm2 = [tuple(float(v) / DEF_DBU_PER_UM for v in m)
               for m in re.findall(
                   r"-\s+LAYER Metal2\s+\+\s+RECT\s+\(\s*(\d+)\s+(\d+)\s*\)"
                   r"\s+\(\s*(\d+)\s+(\d+)\s*\)", deftxt)]
        assert sorted(dm2) == sorted(self.m2_obstructions), \
            f"{self.variant}: def BLOCKAGES {dm2} != interface metal2_blockages {self.m2_obstructions}"

        # pins: name -> {rects (user um), band, centre, edge}
        self.pins = {}
        for p in iface["pins"]:
            rects = [[v / DEF_DBU_PER_UM for v in r["translated_user"]]
                     for r in p["rectangles"]]
            x0 = min(r[0] for r in rects); x1 = max(r[2] for r in rects)
            y0 = min(r[1] for r in rects); y1 = max(r[3] for r in rects)
            # a pin is a thin strip against one edge: its long axis tells us
            # whether it is a N/S (horizontal) or W/E (vertical) pin, and the
            # touching side tells us which one.  (EV's VSS box starts at x=0,
            # so testing x first would misclassify it as a west pin.)
            if (x1 - x0) > (y1 - y0):
                edge = "S" if y0 <= 0.0 else "N"
            else:
                edge = "W" if x0 <= 0.0 else "E"
            self.pins[p["project_pin"]] = dict(
                rects=rects, box=(x0, y0, x1, y1), edge=edge,
                cx=(x0 + x1) / 2, cy=(y0 + y1) / 2,
                pad=p["padring_instance"], cell=p["cell"],
                use=p["use"], layer=p["rectangles"][0]["routing_layer"])

    # -- checks ------------------------------------------------------------
    def obstruction_report(self, m2_region, dbu):
        """m2_region: klayout Region of Metal2 in USER coords."""
        import klayout.db as kdb
        out = []
        for i, (x0, y0, x1, y1) in enumerate(self.m2_obstructions):
            box = kdb.DBox(x0, y0, x1, y1).to_itype(dbu)
            hit = m2_region & kdb.Region(box)
            out.append(dict(index=i, rect=(x0, y0, x1, y1),
                            area_um2=hit.area() * dbu * dbu,
                            clear=hit.is_empty()))
        return out

    def __repr__(self):
        return (f"<SlotSpec {self.project}_{self.variant} "
                f"{self.size_um[0]:.0f}x{self.size_um[1]:.0f}um "
                f"origin={self.origin_um} pins={list(self.pins)} "
                f"m2_obstructions={len(self.m2_obstructions)}>")


# =========================================================== core pad finding
def core_pad_positions(gds_path, layer=(46, 10)):
    """Recursively collect {text: (x, y)} for every label on `layer`.

    The core's chip-level rail pads are met4 pin/label pairs created inside a
    small `pad` sub-component, so they are NOT visible in Component.labels once
    the hierarchy is preserved — read them back out of the written GDS instead.
    """
    import klayout.db as kdb
    ly = kdb.Layout(); ly.read(str(gds_path))
    top = ly.top_cell(); li = ly.layer(*layer)
    out = {}
    it = top.begin_shapes_rec(li)
    while not it.at_end():
        sh = it.shape()
        if sh.is_text():
            t = sh.text.transformed(it.trans())
            out.setdefault(sh.text.string, []).append(
                (t.x * ly.dbu, t.y * ly.dbu))
        it.next()
    return out


# ================================================================ chip builder
LAND_W    = 8.0     # how far the met2 landing reaches into the slot (um)
LANE_X0   = 24.0    # first routing lane, measured from the slot edge (um)
LANE_PITCH = 16.0
RAIL_W    = 2.0     # met4 / met3 route width (um)


def build_chip(pdk, core, spec, pads_user, netmap, name,
               core_offset=None, lane_x0=LANE_X0, lane_pitch=LANE_PITCH,
               rail_w=RAIL_W, land_w=LAND_W, boundary_layer=(0, 0),
               verbose=True):
    """Place `core` inside `spec`'s 550x550 slot and route its rail pads out to
    the padring's Metal2 boundary pins.

    pads_user : {core_net: (x, y)}  core-local coordinates of the met4 rail pads
    netmap    : {slot_pin: core_net}  e.g. {"VCC": "VRECT", "VSS": "VSS", ...}
    Returns (chip_component, routing_report).
    """
    from gdsfactory import Component
    from gdsfactory.components import rectangle
    from glayout import via_stack, via_array, evaluate_bbox

    W, H = spec.size_um
    chip = Component(name=name)

    # ---- place the core, centred in the slot unless told otherwise --------
    cw, ch = evaluate_bbox(core)
    bb = core.bbox                              # [[x0,y0],[x1,y1]]
    if core_offset is None:
        core_offset = ((W - cw) / 2 - float(bb[0][0]),
                       (H - ch) / 2 - float(bb[0][1]))
    dx, dy = core_offset
    ref = chip << core
    ref.movex(dx).movey(dy)
    core_box = (float(bb[0][0]) + dx, float(bb[0][1]) + dy,
                float(bb[1][0]) + dx, float(bb[1][1]) + dy)

    def add_rect(x0, y0, x1, y1, glayer):
        chip.add_polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
                         layer=pdk.get_glayer(glayer) if isinstance(glayer, str)
                         else glayer)

    def via(x, y, lo, hi, power):
        if power:
            v = chip << via_array(pdk, lo, hi, size=(1.6, 1.6),
                                  lay_every_layer=True)
        else:
            v = chip << via_stack(pdk, lo, hi, centered=True)
        vb = v.bbox
        v.movex(x - float(vb[0][0] + vb[1][0]) / 2)
        v.movey(y - float(vb[0][1] + vb[1][1]) / 2)

    report = []
    order = [p for p in spec.pins if p in netmap]
    # The routing lanes live in the channel WEST of the core.  If the core is wide
    # enough to reach them, a lane would be drawn straight through the core's own
    # met3 and silently merge with it -- refuse rather than emit a broken chip.
    last_lane = lane_x0 + (len(order) - 1) * lane_pitch
    if last_lane + rail_w >= core_box[0]:
        raise ValueError(
            f"routing channel too narrow: lanes reach x={last_lane + rail_w:.1f} um "
            f"but the core starts at x={core_box[0]:.1f} um. Move the core east "
            f"(core_offset) or reduce lane_x0/lane_pitch.")
    for i, pin in enumerate(order):
        net = netmap[pin]
        info = spec.pins[pin]
        power = info["use"] in ("POWER", "GROUND")
        px, py = pads_user[net]
        px, py = px + dx, py + dy                       # core pad, slot frame
        x0, y0, x1, y1 = info["box"]
        lane = lane_x0 + i * lane_pitch
        h = rail_w / 2

        if info["edge"] != "W":
            raise NotImplementedError(
                f"pin {pin} is on the {info['edge']} edge; this router "
                f"currently implements west-edge slots (variants D and EH)")

        cy = info["cy"]
        # 1. Metal2 landing covering every def pin rectangle, reaching inward
        add_rect(0.0, y0, land_w, y1, "met2")
        # 2. met2 pin + label so LVS sees a real port
        add_rect(land_w / 2 - 0.25, cy - 0.25, land_w / 2 + 0.25, cy + 0.25,
                 "met2_pin")
        chip.add_label(text=pin, position=(land_w / 2, cy),
                       layer=pdk.get_glayer("met2_label"))
        # 3. met2 -> met4 at the landing, met4 run east to the lane
        via(land_w / 2, cy, "met2", "met4", power)
        add_rect(land_w / 2 - h, cy - h, lane + h, cy + h, "met4")
        # 4. met4 -> met3, vertical lane up/down to the core rail's y
        via(lane, cy, "met3", "met4", power)
        add_rect(lane - h, min(cy, py) - h, lane + h, max(cy, py) + h, "met3")
        # 5. met3 -> met4, met4 run east into the core's rail pad
        via(lane, py, "met3", "met4", power)
        add_rect(lane - h, py - h, px + h, py + h, "met4")

        report.append(dict(pin=pin, net=net, pad=info["pad"], use=info["use"],
                           core_pad=(round(px, 3), round(py, 3)),
                           slot_pin=(round(cy, 3)), lane=lane,
                           dy=round(cy - py, 3), power=power))
        if verbose:
            print(f"  {pin:5s} <- {net:6s} core met4 pad ({px:7.2f},{py:7.2f})"
                  f"  lane x={lane:5.1f}  -> Metal2 pin y={cy:6.2f}"
                  f"  (dy {cy-py:+7.2f} um){'  [power]' if power else ''}")

    # ---- 550 x 550 project boundary marker -------------------------------
    add_rect(0.0, 0.0, W, H, boundary_layer)
    return chip, dict(routes=report, core_box=core_box,
                      core_offset=(dx, dy), slot=(W, H))
