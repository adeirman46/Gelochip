"""Top-level assembly for the MIM-B tapeout.

The sign-off notebook's `harvester_top` interleaved the capacitors with the
active blocks and ran the chip rails on met4 straight across them.  That cannot
work with real MIM-B capacitors: their bottom plates ARE met4 and their terminals
ARE met5, and MIMTM.1 keeps every other met4 at least 1.2 um away from a plate.

So the floorplan is banded instead:

    y 290..470   active blocks (rectifier, bias, pump, load) + met4 chip rails
    y 200..280   riser channel: cap met5 buses climb here and step down to met4
    y  40..185   capacitor field (met4 bottom plates, met5 terminals)

Every met4 rail is therefore >= 15 um clear of any MIM bottom plate, and the only
met4 near the caps is each cap's own plate.
"""
from gdsfactory import Component

# Rails below the active blocks, reached by SOUTH- and WEST-facing ports.
RAILS = {                        # net -> rail y (um), all met4
    "VRECT":  392.0,
    "VMID1":  380.0,
    "VMID2":  368.0,
    "N1":     356.0,
    "N2":     344.0,
    "RFP":    332.0,
    "RFN":    320.0,
    "VOUT":   308.0,
    "VSS":    296.0,
}
# A second band ABOVE the blocks, for the NORTH-facing ports.  Routing those
# downward would take the drop straight back through its own block and merge
# with the block's internal met3 -- which is exactly how N1/N2/VOUT/VRECT/VSS
# first got welded together.  Each top rail is tied to its main rail by a met5
# vertical in the clear channel east of the blocks.
# N1/N2 join this band too: their ports sit at y~444, INSIDE the pump, above the
# pump's own met3 VSS bar at y~434.  Dropping them downward crosses that bar and
# shorts N1/N2 to VSS.  Routing up leaves the block immediately.
RAILS_TOP = {"VRECT": 500.0, "VOUT": 512.0, "N1": 524.0, "N2": 536.0}
TIE_X     = {"VRECT": 300.0, "VOUT": 318.0, "N1": 250.0, "N2": 265.0}
CAP_TOP_Y = 185.0               # nothing but cap plates below this
RAIL_W    = 2.0
LANE_W    = 0.8


def build(pdk, cfg, g, with_caps=True, rail_pads=True):
    """Return (component, netlist). `g` is the ips.load() namespace."""
    from mimcap_b import mimcap_b_array
    evaluate_bbox = g["evaluate_bbox"]
    prec_ref_center = g["prec_ref_center"]
    mlink = g["mlink"]
    via_stack = g["via_stack"]
    rectangle = g["rectangle"]
    tapring = g["tapring"]
    Netlist = g["Netlist"]

    top = Component(name="rfeh_core_raw")   # NOT "RFEH_CORE": the LVS flat copy claims that name

    def place(block, cx, cy, tag):
        ref = top << block
        prec_ref_center(ref)
        ref.movex(cx).movey(cy)
        top.add_ports(ref.get_ports_list(), prefix=tag)
        return ref

    # ---------------- active blocks, top band ---------------------------
    rect_b = g["rectifier"](pdk, cfg)
    bias_b = g["startup_bias"](pdk, cfg)
    pump_b = g["pump_ladder"](pdk, cfg)
    load_b = g["load_diode"](pdk, cfg)
    rw, rh = evaluate_bbox(rect_b); bw, bh = evaluate_bbox(bias_b)
    pw, ph = evaluate_bbox(pump_b); lw_, lh = evaluate_bbox(load_b)

    y_act = 440.0
    x = 70.0
    place(rect_b, x + rw/2, y_act, "RECT_");  x += rw + 16
    place(bias_b, x + bw/2, y_act, "BIAS_");  x += bw + 16
    place(pump_b, x + pw/2, y_act, "PUMP_");  x += pw + 16
    place(load_b, x + lw_/2, y_act, "LOAD_")
    x_right = x + lw_ + 10

    # ---------------- capacitor field, bottom band ----------------------
    caps = {}
    if with_caps:
        sto = g["cap_block_storage"](pdk, cfg)
        st1 = g["cap_block"](pdk, cfg, cfg["charge_pump"]["stage_cap_pf"], max_cols=1)
        st2 = g["cap_block"](pdk, cfg, cfg["charge_pump"]["stage_cap_pf"], max_cols=1)
        in1 = g["cap_block"](pdk, cfg, cfg["startup_bias"]["inject_cap_pf"]/2, max_cols=1)
        in2 = g["cap_block"](pdk, cfg, cfg["startup_bias"]["inject_cap_pf"]/2, max_cols=1)
        sw, sh = evaluate_bbox(sto)
        tw, th = evaluate_bbox(st1)
        iw, ih = evaluate_bbox(in1)
        # ONE row, with every cap in its own x column.  Each MIM-B array carries a
        # met5 TOP bus on its left edge and a met5 BOT bus on its right edge; if two
        # caps share an x span those buses land on top of each other and short the
        # nets together (that is how N1 first merged with VMID1).
        GAP = 16.0
        xc = 60.0
        for blk, tag, bw_ in ((sto, "STO_", sw), (st1, "ST1_", tw), (st2, "ST2_", tw),
                              (in1, "IN1_", iw), (in2, "IN2_", iw)):
            bh_ = evaluate_bbox(blk)[1]
            place(blk, xc + bw_/2, 40.0 + bh_/2, tag)
            xc += bw_ + GAP
        x_right = max(x_right, xc + 12)
        caps = {"sto": (sto, "VSS", "VOUT"), "st1": (st1, "RFN", "N1"),
                "st2": (st2, "RFP", "N2"),     "in1": (in1, "RFP", "VMID1"),
                "in2": (in2, "RFN", "VMID2")}
        x_right = max(x_right, 60 + sw + 30 + 2*tw + 24 + 12)

    # ---------------- drops and risers -----------------------------------
    anchors = {k: [] for k in RAILS}
    RANK = {"met1":1, "met2":2, "met3":3, "met4":4, "met5":5}

    def drop(port, rail, table=None):
        """Route a block port to its rail on met3, honouring the way it faces.

        South ports drop straight down; west ports jog west out of the block
        footprint first; north ports go to the RAILS_TOP band instead.  met3
        crosses the met4 rails harmlessly -- only the final via touches met4.
        """
        table = table or RAILS
        p = top.ports[port]
        px, py = (float(v) for v in p.center)
        pl = pdk.layer_to_glayer(p.layer)
        ty = table[rail]
        if pl != "met3":
            lo, hi = sorted((pl, "met3"), key=lambda gg: RANK[gg])
            v = top << via_stack(pdk, lo, hi, centered=True)
            v.movex(px).movey(py)
        orient = round(float(p.orientation)) % 360
        if orient == 180:                       # west-facing: escape west first
            nx = px - 5.0
            top.add_polygon([(nx, py - LANE_W/2), (px, py - LANE_W/2),
                             (px, py + LANE_W/2), (nx, py + LANE_W/2)],
                            layer=pdk.get_glayer("met3"))
            px = nx
        elif orient == 0:                       # east-facing: escape east first
            nx = px + 5.0
            top.add_polygon([(px, py - LANE_W/2), (nx, py - LANE_W/2),
                             (nx, py + LANE_W/2), (px, py + LANE_W/2)],
                            layer=pdk.get_glayer("met3"))
            px = nx
        y0, y1 = min(py, ty), max(py, ty)
        top.add_polygon([(px - LANE_W/2, y0), (px + LANE_W/2, y0),
                         (px + LANE_W/2, y1), (px - LANE_W/2, y1)],
                        layer=pdk.get_glayer("met3"))
        v = top << via_stack(pdk, "met3", "met4", centered=True)
        v.movex(px).movey(ty)
        return {"x": px, "y": ty, "glayer": "met4"}

    def riser(port, rail):
        """Take a cap terminal (met5) up to `rail`'s y and hand back a met4 anchor."""
        p = top.ports[port]
        px, py = (float(v) for v in p.center)
        ty = RAILS[rail]
        y0, y1 = min(py, ty), max(py, ty)
        top.add_polygon([(px - RAIL_W/2, y0), (px + RAIL_W/2, y0),
                         (px + RAIL_W/2, y1), (px - RAIL_W/2, y1)],
                        layer=pdk.get_glayer("met5"))
        v = top << via_stack(pdk, "met4", "met5", centered=True)
        v.movex(px).movey(ty)
        return {"x": px, "y": ty, "glayer": "met4"}

    if with_caps:
        for key, (blk, bot_net, top_net) in caps.items():
            anchors[bot_net].append(riser(f"{key.upper()}_BOT_stub_S", bot_net))
            anchors[top_net].append(riser(f"{key.upper()}_TOP_stub_N", top_net))

    # ---------------- met4 chip rails ------------------------------------
    x_left = 40.0
    members = {
        "VRECT": ["RECT_VRECT_lane_S", "BIAS_VRECT_lane_S"],
        "VMID1": ["BIAS_VMID1_lane_S"],
        "VMID2": ["BIAS_VMID2_lane_S"],
        "N1":    [],
        "N2":    [],
        "RFP":   ["RECT_RFP_lane_S"],
        "RFN":   ["RECT_RFN_lane_S"],
        "VOUT":  [],
        "VSS":   ["RECT_VSS_lane_S", "BIAS_VSS_lane_S", "PUMP_VSS_stub_W",
                  "LOAD_VSS_stub_S"],
    }
    members_top = {
        "VRECT": ["PUMP_VRECT_stub_N"],
        "VOUT":  ["PUMP_VOUT_stub_N", "LOAD_VOUT_stub_N"],
        "N1":    ["PUMP_N1_bar_S"],
        "N2":    ["PUMP_N2_bar_S"],
    }
    PWR = {"VSS", "VRECT"}
    for net, y in RAILS.items():
        items = [drop(p, net) for p in members.get(net, [])] + anchors[net]
        if not items:
            continue
        items = items + [{"x": x_left, "y": y, "glayer": "met4"}]
        # The rail MUST reach the tie column, otherwise the met5 tie lands on an
        # isolated met4 pad and the net silently splits in two: the bottom band
        # (blocks + caps) ends up separate from the top band. N1/N2 only escaped
        # this because their tie x happened to fall inside the rail's span.
        if net in RAILS_TOP:
            items = items + [{"x": TIE_X[net], "y": y, "glayer": "met4"}]
        mlink(pdk, top, items, y, glayer="met4",
              width=RAIL_W if net in PWR else LANE_W, axis="h",
              via_size=(0.7, 1.7) if net in PWR else None)

    # top-band rails for the north-facing ports, tied down on met5
    for net, ty in RAILS_TOP.items():
        items = [drop(p, net, RAILS_TOP) for p in members_top[net]]
        items.append({"x": TIE_X[net], "y": ty, "glayer": "met4"})
        mlink(pdk, top, items, ty, glayer="met4",
              width=RAIL_W if net in PWR else LANE_W, axis="h",
              via_size=(0.7, 1.7) if net in PWR else None)
        mlink(pdk, top, [{"x": TIE_X[net], "y": ty, "glayer": "met4"},
                         {"x": TIE_X[net], "y": RAILS[net], "glayer": "met4"}],
              TIE_X[net], glayer="met5", width=RAIL_W, axis="v",
              via_size=(1.7, 1.7))

    # VSS: tie the two VSS rails with a met5 trunk on the west edge
    # ---------------- chip-level rail pads --------------------------------
    # gf180 puts met4_pin and met4_label on the SAME layer (46/10), so a labelled
    # pad is always a PORT.  At chip level that duplicates the boundary pins
    # (two VOUT ports, two RFP ports, ...) and netgen then fails port matching.
    # So the chip build asks for rail_pads=False and reads the coordinates from
    # info["rail_pads"] instead.
    PAD_X = x_left - 0.5
    top.info["rail_pads"] = {"RFP": (PAD_X, RAILS["RFP"]), "RFN": (PAD_X, RAILS["RFN"]),
                             "VRECT": (PAD_X, RAILS["VRECT"]), "VOUT": (PAD_X, RAILS["VOUT"]),
                             "VSS": (PAD_X, RAILS["VSS"])}
    if rail_pads:
        def rail_pad(text, xp, yp):
            pad = rectangle(layer=pdk.get_glayer("met4"), size=(2.4, 2.4), centered=True).copy()
            pad.add_label(text=text, layer=pdk.get_glayer("met4_label"))
            pad << rectangle(layer=pdk.get_glayer("met4_pin"), size=(0.5, 0.5), centered=True)
            r = top << pad
            r.movex(xp).movey(yp)
        for text, rail in (("RFP", "RFP"), ("RFN", "RFN"), ("VRECT", "VRECT"),
                           ("VOUT", "VOUT"), ("VSS", "VSS")):
            rail_pad(text, PAD_X, RAILS[rail])
    else:
        # still need real metal where the boundary router lands
        for rail in ("RFP", "RFN", "VRECT", "VOUT", "VSS"):
            yq = RAILS[rail]
            top.add_polygon([(PAD_X - 1.2, yq - 1.2), (PAD_X + 1.2, yq - 1.2),
                             (PAD_X + 1.2, yq + 1.2), (PAD_X - 1.2, yq + 1.2)],
                            layer=pdk.get_glayer("met4"))

    # ---------------- netlist --------------------------------------------
    nl = Netlist(circuit_name="RFEH_CORE",
                 nodes=["RFP", "RFN", "VRECT", "VOUT", "VSS", "VMID1", "VMID2", "N1", "N2"])
    nl.connect_netlist(rect_b.info["netlist"],
                       [("RFP", "RFP"), ("RFN", "RFN"), ("VRECT", "VRECT"), ("VSS", "VSS")])
    nl.connect_netlist(bias_b.info["netlist"],
                       [("VRECT", "VRECT"), ("VMID1", "VMID1"), ("VMID2", "VMID2"), ("VSS", "VSS")])
    nl.connect_netlist(pump_b.info["netlist"],
                       [("VRECT", "VRECT"), ("N1", "N1"), ("N2", "N2"),
                        ("VOUT", "VOUT"), ("VSS", "VSS")])
    nl.connect_netlist(load_b.info["netlist"], [("VOUT", "VOUT"), ("VSS", "VSS")])
    top.info["netlist"] = nl
    if with_caps:
        top.info["cap_values"] = [(k, a, b, blk.info["capacitance_pf"])
                                  for k, (blk, a, b) in caps.items()]
    return top
