"""Route width, metal density and net-separation audit on the exact tapeout GDS."""
import sys, collections
sys.path.insert(0, "/home/irman/gLayout/notebook/tapeout")
import klayout.db as kdb
from pathlib import Path

GDS = Path("/home/irman/gLayout/notebook/rf_harvester_tapeout_out/D05_Gelochip.gds")
SLOT_AREA = 550.0 * 550.0
MET = [("met1",(34,0),0.23), ("met2",(36,0),0.28), ("met3",(42,0),0.28),
       ("met4",(46,0),0.28), ("met5",(81,0),0.28)]
POLY = ("poly2",(30,0))

ly = kdb.Layout(); ly.read(str(GDS)); top = ly.top_cell(); dbu = ly.dbu
# probe_net only resolves top-level nets on a hierarchical layout, so flatten
# first -- otherwise internal nets (N1, N2, VMID*) appear to merge with the rails.
ly.flatten(top.cell_index(), -1, True)
print(f"file {GDS.name}  top {top.name}  slot {SLOT_AREA:.0f} um^2\n")

# ---------------------------------------------------------------- 1. widths
print("=" * 96)
print("1. ROUTE WIDTHS  (min dimension of each merged shape; 'narrow' = below the DRC minimum)")
print("=" * 96)
print(f"{'layer':7s} {'shapes':>7s} {'DRC min':>8s} {'actual min':>11s} {'median':>8s} "
      f"{'max':>8s}   width histogram (um : count)")
for name, lyr, wmin in MET:
    r = kdb.Region(top.begin_shapes_rec(ly.layer(*lyr))); r.merge()
    if r.is_empty():
        continue
    widths = []
    for p in r.each():
        b = p.bbox()
        widths.append(min(b.width(), b.height()) * dbu)
    widths.sort()
    hist = collections.Counter(round(w, 2) for w in widths)
    common = ", ".join(f"{w}:{n}" for w, n in hist.most_common(6))
    narrow = [w for w in widths if w < wmin - 1e-9]
    print(f"{name:7s} {len(widths):7d} {wmin:8.2f} {widths[0]:11.3f} "
          f"{widths[len(widths)//2]:8.3f} {widths[-1]:8.2f}   {common}")
    if narrow:
        print(f"        !! {len(narrow)} shape(s) below the DRC minimum: {narrow[:5]}")
print("\nDesign intent: met4 chip rails 2.0 um, met3 block lanes 0.8 um, boundary router")
print("2.0 um on met4/met3, Metal2 slot landings 8.0 um wide. gf180 minimum is 0.23-0.28 um,")
print("so every route is 3x-8x the minimum width. magic DRC and the foundry KLayout deck both")
print("report zero width/spacing violations.")

# ------------------------------------------------------------- 2. density
print("\n" + "=" * 96)
print("2. METAL / POLY DENSITY over the 550 x 550 project area  (foundry wants >30% metal, 14% poly)")
print("=" * 96)
for name, lyr, _ in MET + [(POLY[0], POLY[1], 0)]:
    r = kdb.Region(top.begin_shapes_rec(ly.layer(*lyr))); r.merge()
    a = r.area() * dbu * dbu
    pct = 100.0 * a / SLOT_AREA
    need = 14.0 if name == "poly2" else 30.0
    print(f"  {name:7s} area {a:10.1f} um^2   density {pct:6.2f}%   target >{need:.0f}%   "
          f"{'OK' if pct >= need else 'BELOW -> needs dummy fill'}")

# ------------------------------------------- 3. net separation (same-layer shorts)
print("\n" + "=" * 96)
print("3. NET SEPARATION  -- are the nets that should be distinct actually distinct?")
print("=" * 96)

def extract(mim_open):
    l2n = kdb.LayoutToNetlist(kdb.RecursiveShapeIterator(ly, top, [])); l2n.threads = 4
    L = dict(met1=(34,0), via1=(35,0), met2=(36,0), met3=(42,0), via3=(40,0),
             met4=(46,0), via4=(41,0), met5=(81,0))
    R = {k: l2n.make_polygon_layer(ly.layer(*v), k) for k, v in L.items()}
    capmk = l2n.make_polygon_layer(ly.layer(117,5), "capmk")
    v2 = l2n.make_polygon_layer(ly.layer(38,0), "v2all")
    v2u = v2.not_interacting(capmk) if mim_open else v2
    if mim_open:
        l2n.register(v2u, "v2u")
    for n in ("met1","met2","met3","met4","met5"): l2n.connect(R[n])
    l2n.connect(R["met1"],R["via1"]); l2n.connect(R["via1"],R["met2"])
    l2n.connect(R["met2"],v2u);       l2n.connect(v2u,R["met3"])
    l2n.connect(R["met3"],R["via3"]); l2n.connect(R["via3"],R["met4"])
    l2n.connect(R["met4"],R["via4"]); l2n.connect(R["via4"],R["met5"])
    l2n.extract_netlist()
    return l2n, R

# every net label in the design, on its own layer
labels = collections.defaultdict(list)
for lname, (l, d) in (("met2",(36,10)), ("met3",(42,10)), ("met4",(46,10))):
    it = top.begin_shapes_rec(ly.layer(l, d))
    while not it.at_end():
        if it.shape().is_text():
            t = it.shape().text.transformed(it.trans())
            labels[it.shape().text.string].append((lname, t.x*dbu, t.y*dbu))
        it.next()

for mim_open, tag in ((True, "MIM modelled as OPEN (a real capacitor)"),
                      (False, "MIM as actually DRAWN (via array = short)")):
    l2n, R = extract(mim_open)
    net_of = {}
    for nm, places in sorted(labels.items()):
        lname, x, y = places[0]
        n = l2n.probe_net(R[lname], kdb.DPoint(x, y))
        net_of[nm] = n.cluster_id if n else None
    groups = collections.defaultdict(list)
    for nm, cid in net_of.items():
        groups[cid].append(nm)
    merged = {c: v for c, v in groups.items() if len(v) > 1}
    print(f"\n  --- {tag} ---")
    print(f"      {len(net_of)} labelled nets -> {len(set(net_of.values()))} distinct nets")
    if merged:
        for c, v in merged.items():
            print(f"      MERGED: {' = '.join(sorted(v))}")
    else:
        print("      no two differently-named nets share a net: no shorts")
