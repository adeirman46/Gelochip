"""Whole-chip net audit with correct MIM-B modelling.

Full metal stack, plus the MIM rule that makes a capacitor a capacitor:
    via4 that lands ON FuseTop  -> met5 <-> fusetop   (the MIM top plate)
    via4 that lands OFF FuseTop -> met5 <-> met4      (an ordinary via)
    fusetop is NEVER joined to met4 -- that gap is the dielectric.
"""
import sys, collections
import klayout.db as kdb

L = dict(met1=(34,0), via1=(35,0), met2=(36,0), via2=(38,0), met3=(42,0),
         via3=(40,0), met4=(46,0), met5=(81,0))
VIA4, FUSETOP = (41,0), (75,0)


def extract(gds, flatten=True):
    ly = kdb.Layout(); ly.read(str(gds)); top = ly.top_cell()
    if flatten:
        ly.flatten(top.cell_index(), -1, True)
    l2n = kdb.LayoutToNetlist(kdb.RecursiveShapeIterator(ly, top, [])); l2n.threads = 4
    R = {k: l2n.make_polygon_layer(ly.layer(*v), k) for k, v in L.items()}
    ft = l2n.make_polygon_layer(ly.layer(*FUSETOP), "fusetop")
    v4 = l2n.make_polygon_layer(ly.layer(*VIA4), "via4")
    v4_top = v4.interacting(ft); l2n.register(v4_top, "via4_on_fusetop")
    v4_bot = v4.not_interacting(ft); l2n.register(v4_bot, "via4_normal")
    R["fusetop"] = ft
    for n in ("met1","met2","met3","met4","met5","fusetop"):
        l2n.connect(R[n])
    l2n.connect(R["met1"], R["via1"]); l2n.connect(R["via1"], R["met2"])
    l2n.connect(R["met2"], R["via2"]); l2n.connect(R["via2"], R["met3"])
    l2n.connect(R["met3"], R["via3"]); l2n.connect(R["via3"], R["met4"])
    l2n.connect(R["met5"], v4_top);    l2n.connect(v4_top, R["fusetop"])
    l2n.connect(R["met5"], v4_bot);    l2n.connect(v4_bot, R["met4"])
    l2n.extract_netlist()
    return ly, top, l2n, R


def audit(gds, verbose=True):
    ly, top, l2n, R = extract(gds)
    dbu = ly.dbu
    labs = collections.defaultdict(list)
    for lname, (l, d) in (("met2",(36,10)), ("met3",(42,10)), ("met4",(46,10))):
        it = top.begin_shapes_rec(ly.layer(l, d))
        while not it.at_end():
            if it.shape().is_text():
                t = it.shape().text.transformed(it.trans())
                labs[it.shape().text.string].append((lname, t.x*dbu, t.y*dbu))
            it.next()
    regs = {k: kdb.Region(top.shapes(ly.layer(*L[k]))) for k in ("met2","met3","met4")}
    for k in regs: regs[k].merge()
    nets = {}
    for nm in sorted(labs):
        lname, x, y = labs[nm][0]
        pt = kdb.Region(kdb.DBox(x-0.3, y-0.3, x+0.3, y+0.3).to_itype(dbu))
        hit = regs[lname].interacting(pt)
        cx, cy = x, y
        for p in hit.each():
            b = p.bbox(); cx, cy = b.center().x*dbu, b.center().y*dbu; break
        n = l2n.probe_net(R[lname], kdb.DPoint(cx, cy))
        nets[nm] = n.cluster_id if n else None
    groups = collections.defaultdict(list)
    for nm, c in nets.items():
        groups[c].append(nm)
    merged = {c: v for c, v in groups.items() if len(v) > 1}
    if verbose:
        ftr = kdb.Region(top.shapes(ly.layer(*FUSETOP))); ftr.merge()
        v4r = kdb.Region(top.shapes(ly.layer(*VIA4)))
        print(f"  FuseTop plates: {ftr.count()}, {ftr.area()*dbu*dbu:9.1f} um^2 "
              f"-> {ftr.area()*dbu*dbu/1000.0:.3f} pF at 1.0 fF/um^2")
        print(f"  via4: {v4r.count()} total")
        for nm in sorted(nets):
            print(f"    {nm:8s} net {nets[nm]}")
        print(f"  {len(nets)} labelled nets -> {len(set(nets.values()))} distinct")
        for c, v in merged.items():
            print(f"    MERGED: {' = '.join(sorted(v))}")
    return nets, merged


if __name__ == "__main__":
    for f in sys.argv[1:]:
        print("=" * 70); print(f)
        audit(f)
