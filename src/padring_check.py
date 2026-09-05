"""Is the project actually landed on the EH padring, and are the routes wide enough?"""
import sys, collections
sys.path.insert(0, "/home/irman/gLayout/notebook/tapeout")
import klayout.db as kdb
from slot_adapter import SlotSpec

GDS = "/home/irman/gLayout/notebook/rf_harvester_tapeout_out/D05_Gelochip.gds"
VARIANT = "EH"
MET = [("met1",(34,0),0.23), ("met2",(36,0),0.28), ("met3",(42,0),0.28),
       ("met4",(46,0),0.28), ("met5",(81,0),0.28)]

spec = SlotSpec("/home/irman/gLayout/notebook/D05.def.tgz", VARIANT)
ly = kdb.Layout(); ly.read(GDS); top = ly.top_cell(); dbu = ly.dbu
m2 = kdb.Region(top.begin_shapes_rec(ly.layer(36,0))); m2.merge()
pin_lbl = {}
it = top.begin_shapes_rec(ly.layer(36,10))
while not it.at_end():
    if it.shape().is_text():
        t = it.shape().text.transformed(it.trans())
        pin_lbl.setdefault(it.shape().text.string, []).append((t.x*dbu, t.y*dbu))
    it.next()

print("=" * 104)
print(f"1. PADRING HANDOVER — does our Metal2 cover every DEF pin rectangle of variant {VARIANT}?")
print("=" * 104)
print(f"{'pin':6s} {'pad':5s} {'DEF rects':>9s} {'required area':>14s} {'our met2 there':>15s} "
      f"{'labelled':>9s}  verdict")
allok = True
for pin, info in spec.pins.items():
    need = cov = 0.0
    for (x0, y0, x1, y1) in info["rects"]:
        box = kdb.DBox(x0, y0, x1, y1)
        need += (x1-x0)*(y1-y0)
        cov  += (m2 & kdb.Region(box.to_itype(dbu))).area()*dbu*dbu
    lab = pin in pin_lbl
    good = cov >= need - 1e-6 and lab
    allok &= good
    print(f"{pin:6s} {info['pad']:5s} {len(info['rects']):9d} {need:12.3f}um2 "
          f"{cov:13.3f}um2 {str(lab):>9s}  {'LANDED' if good else '*** GAP ***'}")
print(f"\nevery DEF pin rectangle fully covered and labelled: {allok}")

print("\n" + "=" * 104)
print("2. ROUTE WIDTHS — min dimension of every merged shape per layer")
print("=" * 104)
print(f"{'layer':7s} {'shapes':>7s} {'DRC min':>8s} {'actual min':>11s} {'median':>8s} {'max':>9s}   most common widths")
for name, lyr, wmin in MET:
    r = kdb.Region(top.begin_shapes_rec(ly.layer(*lyr))); r.merge()
    if r.is_empty(): continue
    w = sorted(min(p.bbox().width(), p.bbox().height())*dbu for p in r.each())
    hist = collections.Counter(round(x, 2) for x in w)
    narrow = [x for x in w if x < wmin - 1e-9]
    print(f"{name:7s} {len(w):7d} {wmin:8.2f} {w[0]:11.3f} {w[len(w)//2]:8.3f} {w[-1]:9.2f}   "
          + ", ".join(f"{a}:{b}" for a, b in hist.most_common(5)))
    if narrow:
        print(f"        !! {len(narrow)} shape(s) BELOW the DRC minimum: {narrow[:5]}")
        allok = False
print("\nno shape below its DRC minimum width:", allok)
