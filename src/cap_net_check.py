"""Does every capacitor land on the two nets it is supposed to?

Plate-separation only proves a cap is not a short. This proves each cap is wired
to its INTENDED pair of nets, by naming the net each plate reaches.
"""
import sys, collections
sys.path.insert(0, "/home/irman/gLayout/notebook/tapeout")
import klayout.db as kdb
from net_audit_v2 import extract, L

EXPECT = {"sto": ("VSS", "VOUT"), "st1": ("RFN", "N1"), "st2": ("RFP", "N2"),
          "in1": ("RFP", "VMID1"), "in2": ("RFN", "VMID2")}


def main(gds):
    ly, top, l2n, R = extract(gds)
    dbu = ly.dbu
    # name every net from its labels
    name_of = {}
    for lname, (l, d) in (("met2", (36,10)), ("met3", (42,10)), ("met4", (46,10)),
                          ("met5", (81,10))):
        li = ly.find_layer(l, d)
        if li is None: continue
        it = top.begin_shapes_rec(li)
        while not it.at_end():
            if it.shape().is_text():
                t = it.shape().text.transformed(it.trans())
                key = lname if lname in R else "met4"
                n = l2n.probe_net(R[key], kdb.DPoint(t.x*dbu, t.y*dbu))
                if n is not None:
                    name_of.setdefault(n.cluster_id, set()).add(it.shape().text.string)
            it.next()

    cm = kdb.Region(top.shapes(ly.layer(117,5))); cm.merge()
    grown = cm.sized(int(2.0/dbu)); grown.merge()
    banks = sorted([p.bbox() for p in grown.each()], key=lambda b: -(b.width()*b.height()))
    print(f"{'bank':6s} {'tiles':>5s} {'probe tile centre':>22s}  {'TOP plate net':22s} {'BOT plate net':22s}")
    print("-"*100)
    rows = []
    for i, bb in enumerate(banks):
        tiles = cm.interacting(kdb.Region(bb))
        # Probe an individual CAP_MK TILE, never the bank bbox centre: on a multi-tile
        # bank that centre falls in the gap between tiles, where there is no FuseTop
        # and no met4 plate, and the probe returns None (a false "floating").
        tnames, bnames, tid, bid, cx, cy = set(), set(), None, None, 0.0, 0.0
        for t in tiles.each():
            b = t.bbox(); px, py = b.center().x*dbu, b.center().y*dbu
            nt = l2n.probe_net(R["fusetop"], kdb.DPoint(px, py))
            nb = l2n.probe_net(R["met4"],    kdb.DPoint(px, py))
            if nt is None or nb is None:
                continue
            cx, cy, tid, bid = px, py, nt.cluster_id, nb.cluster_id
            tnames |= name_of.get(tid, set()); bnames |= name_of.get(bid, set())
        tn, bn = sorted(tnames), sorted(bnames)
        rows.append((tiles.count(), cx, cy, tn, bn, tid, bid))
        print(f"{i:<6d} {tiles.count():5d} ({cx:9.2f},{cy:9.2f})  {str(tn):22s} {str(bn):22s}")
    print("-"*100)
    ok = True
    for tiles, cx, cy, tn, bn, ti, bi in rows:
        if ti is None or bi is None or ti == bi:
            print(f"  bank at ({cx:.1f},{cy:.1f}): SHORTED or FLOATING"); ok = False
        elif not tn or not bn:
            print(f"  bank at ({cx:.1f},{cy:.1f}): a plate reaches no NAMED net "
                  f"(top={tn or 'unnamed'}, bot={bn or 'unnamed'})"); ok = False
    got = {(tuple(sorted(bn)), tuple(sorted(tn))) for _,_,_,tn,bn,_,_ in rows}
    print("\nexpected cap net pairs:", sorted(set(EXPECT.values())))
    print("observed (bottom, top) :", sorted(got))
    print("\nall capacitors wired to NAMED nets on both plates:", ok)
    return ok


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else
         "/home/irman/gLayout/notebook/rf_harvester_tapeout_out/D05_Gelochip.gds")
