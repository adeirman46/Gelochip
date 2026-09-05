"""Corrected MIM cap wrapper.

BUG (present in GLayout_RF_EnergyHarvester_Signoff.ipynb, cells 21 and in the
shipped 287x291 um GDS):

    bp = comp.ports["row0_col0_bottom_met_S"]      # y = -(size/2 + met2_enclosure)
    v  = comp << via_stack(pdk, "met2", "met3", centered=True)
    v.movex(bx).movey(by + 0.5)                    # <-- 0.5 um inboard

The bottom met2 plate overhangs the met3 top plate by only ~0.6 um, so `by+0.5`
sits 0.1 um outside the top plate -- far less than the via's own met3 landing
pad (~0.6 um).  The pad therefore overlaps the met3 top plate and welds the two
capacitor plates together.  Every MIM in the design is shorted; for the 22 pF
storage cap that ties VOUT directly to VSS.

FIX: the bottom plate escapes on its own layer (met2) and only steps up to met3
once it is a full met3 spacing clear of the top plate, with the clearance
derived from the real via_stack size instead of a guessed constant.
"""
from gdsfactory import Component


def _layer_bbox(pdk, comp, glayer):
    polys = comp.get_polygons(by_spec=pdk.get_glayer(glayer))
    if not polys:
        return None
    xs = [p[:, 0] for p in polys]; ys = [p[:, 1] for p in polys]
    return (min(x.min() for x in xs), min(y.min() for y in ys),
            max(x.max() for x in xs), max(y.max() for y in ys))


def add_cap_stubs(pdk, comp, bank, lw, via_stack, evaluate_bbox):
    """TOP plate -> met3 stub north.  BOTTOM plate -> met2 finger south, then a
    via up to met3 placed clear of the top plate.  Returns (top_y, bot_y)."""
    m2 = _layer_bbox(pdk, comp, "met2")
    m3 = _layer_bbox(pdk, comp, "met3")
    w, h = evaluate_bbox(bank)

    # ---- top plate: met3, north --------------------------------------------
    tx = 0.0
    y_top_end = h / 2 + 1.0
    comp.add_polygon([(tx - lw / 2, m3[3] - 1.0), (tx + lw / 2, m3[3] - 1.0),
                      (tx + lw / 2, y_top_end), (tx - lw / 2, y_top_end)],
                     layer=pdk.get_glayer("met3"))
    comp.add_port(name="TOP_stub_N", center=(tx, y_top_end), width=lw,
                  orientation=90, layer=pdk.get_glayer("met3"))

    # ---- bottom plate: met2 finger south, then step up to met3 -------------
    vs = via_stack(pdk, "met2", "met3", centered=True)
    vw, vh = evaluate_bbox(vs)
    sep = float(pdk.get_grule("met3")["min_separation"])
    bx = 0.0
    # the via's met3 pad top edge must clear the met3 top plate by >= sep
    y_via = m3[1] - vh / 2 - sep - 0.2
    fing_w = max(lw, vw + 0.4)
    y_fing_end = y_via - vh / 2 - 0.2
    comp.add_polygon([(bx - fing_w / 2, m2[1] + 1.0), (bx + fing_w / 2, m2[1] + 1.0),
                      (bx + fing_w / 2, y_fing_end), (bx - fing_w / 2, y_fing_end)],
                     layer=pdk.get_glayer("met2"))
    v = comp << vs
    v.movex(bx).movey(y_via)
    y_bot_end = min(-h / 2 - 1.0, y_via - vh / 2 - 1.0)
    comp.add_polygon([(bx - lw / 2, y_via), (bx + lw / 2, y_via),
                      (bx + lw / 2, y_bot_end), (bx - lw / 2, y_bot_end)],
                     layer=pdk.get_glayer("met3"))
    comp.add_port(name="BOT_stub_S", center=(bx, y_bot_end), width=lw,
                  orientation=270, layer=pdk.get_glayer("met3"))
    return dict(top_plate_m3=m3, bot_plate_m2=m2, y_via=y_via,
                clearance_to_top_plate=m3[1] - (y_via + vh / 2))


def make_cap_blocks(g):
    """Build corrected cap_block / cap_block_storage bound to the notebook's
    own helpers (mimcap_bank, prec_ref_center, via_stack, evaluate_bbox)."""
    mimcap_bank   = g["mimcap_bank"]
    prec_ref_center = g["prec_ref_center"]
    via_stack     = g["via_stack"]
    evaluate_bbox = g["evaluate_bbox"]

    def _block(pdk, cfg, target_pf, unit_key, max_cols):
        lw = cfg["layout"]["lane_width_um"]
        comp = Component()
        bank = mimcap_bank(pdk, target_pf, cfg["caps"][unit_key],
                           cfg["caps"]["mim_ff_per_um2"], max_cols=max_cols)
        rb = comp << bank
        prec_ref_center(rb)
        comp.add_ports(rb.get_ports_list())
        info = add_cap_stubs(pdk, comp, bank, lw, via_stack, evaluate_bbox)
        comp.info["capacitance_pf"] = bank.info["capacitance_pf"]
        comp.info["stub_geometry"] = info
        return comp

    def cap_block(pdk, cfg, target_pf, max_cols=6, name="capbank"):
        return _block(pdk, cfg, target_pf, "stage_unit_um", max_cols)

    def cap_block_storage(pdk, cfg):
        return _block(pdk, cfg, cfg["caps"]["storage_cap_pf"], "storage_unit_um", 7)

    return cap_block, cap_block_storage
