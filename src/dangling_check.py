"""Is any routing metal left unconnected?

Every net in the core should be reachable from one of the nine named nets. Any net
that is not is dangling metal -- a route that goes nowhere. Fill tiles are floating
by design, so this runs on the pre-fill core.
"""
import sys, collections
sys.path.insert(0, "/home/irman/gLayout/notebook/tapeout")
import klayout.db as kdb
from net_audit_v2 import extract, L

NAMED = {"RFP","RFN","VRECT","VOUT","VSS","VMID1","VMID2","N1","N2"}


def main(gds):
    ly, top, l2n, R = extract(gds)
    dbu = ly.dbu
    # net id -> names, from every label layer
    name_of = collections.defaultdict(set)
    for lname, (l, d) in (("met2",(36,10)), ("met3",(42,10)), ("met4",(46,10)), ("met5",(81,10))):
        li = ly.find_layer(l, d)
        if li is None: continue
        it = top.begin_shapes_rec(li)
        while not it.at_end():
            if it.shape().is_text():
                t = it.shape().text.transformed(it.trans())
                key = lname if lname in R else "met4"
                n = l2n.probe_net(R[key], kdb.DPoint(t.x*dbu, t.y*dbu))
                if n is not None:
                    name_of[n.cluster_id].add(it.shape().text.string)
            it.next()

    # walk every routing polygon and ask which net it belongs to
    layers = ["met1","met2","met3","met4","met5","fusetop"]
    per_net = collections.defaultdict(lambda: collections.Counter())
    unnamed_area = collections.Counter()
    for lname in layers:
        reg = kdb.Region(top.shapes(ly.layer(*(L[lname] if lname in L else (75,0)))))
        reg.merge()
        for p in reg.each():
            # A merged polygon can be an L or a comb, so its bbox centre is often
            # OUTSIDE the metal and probe_net returns None -- which reads as a false
            # "orphan". Scan for a point genuinely inside this polygon first.
            one = kdb.Region(p)
            b = p.bbox()
            px = py = None
            for fx in (0.5, 0.25, 0.75, 0.1, 0.9):
                for fy in (0.5, 0.25, 0.75, 0.1, 0.9):
                    qx = (b.left + (b.right - b.left)*fx)*dbu
                    qy = (b.bottom + (b.top - b.bottom)*fy)*dbu
                    probe_box = kdb.Region(kdb.DBox(qx-0.01, qy-0.01, qx+0.01, qy+0.01).to_itype(dbu))
                    if not (one & probe_box).is_empty():
                        px, py = qx, qy
                        break
                if px is not None:
                    break
            if px is None:                      # fall back to an actual hull vertex
                v = next(p.each_point_hull())
                px, py = v.x*dbu, v.y*dbu
            n = l2n.probe_net(R[lname], kdb.DPoint(px, py))
            nid = n.cluster_id if n else None
            per_net[nid][lname] += 1
            if nid is None or not (name_of.get(nid, set()) & NAMED):
                unnamed_area[lname] += p.area()*dbu*dbu

    print(f"{'net':>8s}  {'names':26s} shapes per layer")
    print("-"*88)
    for nid, cnt in sorted(per_net.items(), key=lambda kv: -sum(kv[1].values())):
        nm = sorted(name_of.get(nid, set())) if nid is not None else ["<no net>"]
        tag = ",".join(nm) if nm else "<UNNAMED>"
        print(f"{str(nid):>8s}  {tag:26s} {dict(cnt)}")
    print("-"*88)
    tot_unnamed = sum(unnamed_area.values())
    print("metal NOT reachable from any of the nine named nets:")
    for k, v in unnamed_area.items():
        print(f"   {k:8s} {v:10.2f} um^2")
    print(f"   TOTAL    {tot_unnamed:10.2f} um^2")
    print("\nno dangling routing metal:", tot_unnamed < 1e-6)
    return tot_unnamed


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else
         "/home/irman/gLayout/notebook/rf_harvester_tapeout_out/v2_core_full.gds")
