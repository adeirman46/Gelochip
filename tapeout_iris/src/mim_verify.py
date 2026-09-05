"""Prove a MIM-B structure is a capacitor: the two plates must be separate nets.

The connectivity model has to know how a MIM is contacted:
  * a via4 that lands ON FuseTop contacts the MIM TOP plate -> met5 <-> fusetop
  * a via4 that lands OFF FuseTop is an ordinary via       -> met5 <-> met4
  * fusetop and met4 are NEVER connected to each other -- that gap is the
    MIM dielectric, i.e. the capacitor itself.
A naive "via4 joins met4 to met5" model would report the cap as a short, which is
the same mistake that made magic read GLayout's fake MIM as a plate short.
"""
import sys
import klayout.db as kdb

MET4, VIA4, MET5, FUSETOP, CAPMK = (46,0), (41,0), (81,0), (75,0), (117,5)


def check(gds, probes, flatten=True, verbose=True):
    ly = kdb.Layout(); ly.read(str(gds)); top = ly.top_cell(); dbu = ly.dbu
    if flatten:
        ly.flatten(top.cell_index(), -1, True)
    l2n = kdb.LayoutToNetlist(kdb.RecursiveShapeIterator(ly, top, [])); l2n.threads = 4
    m4 = l2n.make_polygon_layer(ly.layer(*MET4), "met4")
    m5 = l2n.make_polygon_layer(ly.layer(*MET5), "met5")
    ft = l2n.make_polygon_layer(ly.layer(*FUSETOP), "fusetop")
    v4 = l2n.make_polygon_layer(ly.layer(*VIA4), "via4")
    v4_top = v4.interacting(ft)          # contacts the MIM top plate
    v4_bot = v4.not_interacting(ft)      # ordinary met4<->met5 via
    l2n.register(v4_top, "via4_on_fusetop")
    l2n.register(v4_bot, "via4_normal")
    for r in (m4, m5, ft):
        l2n.connect(r)
    l2n.connect(m5, v4_top); l2n.connect(v4_top, ft)     # met5 -> top plate
    l2n.connect(m5, v4_bot); l2n.connect(v4_bot, m4)     # met5 -> bottom plate
    l2n.extract_netlist()

    if verbose:
        nft = kdb.Region(top.begin_shapes_rec(ly.layer(*FUSETOP))); nft.merge()
        ncm = kdb.Region(top.begin_shapes_rec(ly.layer(*CAPMK)));   ncm.merge()
        nv  = kdb.Region(top.begin_shapes_rec(ly.layer(*VIA4)))
        print(f"  FuseTop  {nft.count():3d} plate(s), {nft.area()*dbu*dbu:9.1f} um^2"
              f"  -> {nft.area()*dbu*dbu/1000.0:.3f} pF at 1.0 fF/um^2")
        print(f"  CAP_MK   {ncm.count():3d} marker(s)   via4 total {nv.count():5d}"
              f"  ({v4_top.count()} on FuseTop, {v4_bot.count()} ordinary)")
    out = {}
    for nm, (layer, x, y) in probes.items():
        R = {"met4": m4, "met5": m5, "fusetop": ft}[layer]
        n = l2n.probe_net(R, kdb.DPoint(x, y))
        out[nm] = n.cluster_id if n else None
        if verbose:
            print(f"  probe {nm:16s} {layer:8s} ({x:8.2f},{y:8.2f}) -> net "
                  f"{out[nm] if out[nm] is not None else 'NONE'}")
    return out


if __name__ == "__main__":
    import os
    sys.path.insert(0, "/home/irman/gLayout/notebook/tapeout")
    S = "/tmp/claude-1000/-home-irman-gLayout/b7a27b5f-0e2d-480f-8800-93b6519a3ad4/scratchpad"
    print("=== single MIM-B unit (28 x 28 um FuseTop) ===")
    r = check(f"{S}/mimb_unit.gds", {
        "TOP plate (fusetop)": ("fusetop", 0.0, 0.0),
        "TOP terminal (met5)": ("met5", 0.0, 0.0),
        "BOT plate (met4)":    ("met4", 0.0, 14.4),
        "BOT terminal (met5)": ("met5", 0.0, -14.63),
    })
    top_ok = r["TOP plate (fusetop)"] == r["TOP terminal (met5)"]
    bot_ok = r["BOT plate (met4)"] == r["BOT terminal (met5)"]
    sep    = r["TOP terminal (met5)"] != r["BOT terminal (met5)"]
    print(f"  top plate reaches its terminal : {top_ok}")
    print(f"  bottom plate reaches its terminal: {bot_ok}")
    print(f"  the two plates are SEPARATE nets : {sep}   <-- this is the capacitor")
    print("\n=== 2 x 2 MIM-B array ===")
    r = check(f"{S}/mimb_arr.gds", {
        "TOP bus (met5)": ("met5", -18.5, 0.0),
        "BOT bus (met5)": ("met5",  33.7, 0.0),
    })
    print(f"  TOP bus != BOT bus : {r['TOP bus (met5)'] != r['BOT bus (met5)']}")
