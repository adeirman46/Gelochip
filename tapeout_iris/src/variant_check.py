"""Check the final GDS against the Metal2 corner obstructions of the issued variants.

The GDS is built FOR one variant: its Metal2 landings sit on that variant's pin
bands.  Checking it against a different variant's keep-outs is meaningless -- the
landings would move if you rebuilt.  So the built variant is asserted, and the
others are reported as informational only.
"""
import sys, json, os
import klayout.db as kdb
from pathlib import Path
sys.path.insert(0, "/home/irman/gLayout/notebook/tapeout")
from slot_adapter import SlotSpec

TGZ   = "/home/irman/gLayout/notebook/D05.def.tgz"
OUT   = Path("/home/irman/gLayout/notebook/rf_harvester_tapeout_out")
GDS   = OUT / "D05_Gelochip.gds"
BUILT = os.environ.get("D05_VARIANT", "EH")

ly = kdb.Layout(); ly.read(str(GDS)); top = ly.top_cell(); dbu = ly.dbu
m2 = kdb.Region(top.begin_shapes_rec(ly.layer(36, 0))); m2.merge()
bb = top.dbbox()
print(f"GDS {GDS.name}   top={top.name}   bbox=({bb.left:.1f},{bb.bottom:.1f})-({bb.right:.1f},{bb.top:.1f})")
print(f"This GDS was BUILT FOR variant {BUILT}: its Metal2 landings sit on {BUILT}'s pin bands.\n")

def margin_um(box):
    g = 0
    while g < 400:
        g += 5
        if not (m2 & kdb.Region(box.enlarged(int(g/dbu), int(g/dbu)))).is_empty():
            return g - 5
    return ">400"

rows, verdict_ok = [], True
for v in ("D", "EH", "EV"):
    s = SlotSpec(TGZ, v)
    tag = "BUILT" if v == BUILT else "info only"
    print(f"--- variant {v}  [{tag}]  origin {s.origin_um}, pins on "
          f"{''.join(sorted({p['edge'] for p in s.pins.values()}))} edge ---")
    if not s.m2_obstructions:
        print("    no Metal2 corner obstruction issued for this slot -> nothing to check")
        rows.append(dict(variant=v, built=(v == BUILT), clear=True, obstructions=[]))
        continue
    rep = s.obstruction_report(m2, dbu)
    for o in rep:
        x0, y0, x1, y1 = o["rect"]
        box = kdb.DBox(x0, y0, x1, y1).to_itype(dbu)
        if o["clear"]:
            note = f"CLEAR (nearest Metal2 > {margin_um(box)} um away)"
        elif v == BUILT:
            note = f"*** VIOLATION *** {o['area_um2']:.4f} um^2 of Metal2 inside"
        else:
            note = (f"{o['area_um2']:.4f} um^2 of Metal2 inside -- NOT a violation of this "
                    f"build: rebuild with D05_VARIANT={v} and the landings move")
        print(f"    keep-out ({x0:7.2f},{y0:7.2f})-({x1:7.2f},{y1:7.2f})  {note}")
    ok = all(o["clear"] for o in rep)
    rows.append(dict(variant=v, built=(v == BUILT), clear=ok, obstructions=rep))
    if v == BUILT:
        verdict_ok = ok
    print()

print("=" * 78)
print(f"VERDICT for the built variant ({BUILT}): "
      f"{'CLEAR - no Metal2 in any issued keep-out' if verdict_ok else '*** VIOLATION ***'}")
others = [r for r in rows if not r["built"] and r["obstructions"] and not r["clear"]]
if others:
    print("Note: " + ", ".join(r["variant"] for r in others) +
          " would need a rebuild before their keep-outs apply (verified separately).")
json.dump(rows, open(OUT / "variant_obstruction_report.json", "w"), indent=1, default=str)
