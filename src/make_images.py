"""Render every figure used by the tapeout notebook."""
import sys
sys.path.insert(0, "/home/irman/gLayout/notebook/tapeout")
import klayout.db as kdb
from pathlib import Path
from render import render
from slot_adapter import SlotSpec

NB   = Path("/home/irman/gLayout/notebook")
IMG  = NB / "tapeout" / "img"; IMG.mkdir(parents=True, exist_ok=True)
CHIP = NB / "rf_harvester_tapeout_out" / "D05_Gelochip.gds"
ORIG = NB / "rf_harvester_signoff_out" / "harvester_top_full.gds"
spec = SlotSpec(NB / "D05.def.tgz", "EH")


def storage_bank(gds):
    """bbox of the largest CAP_MK cluster = the 22 pF storage bank."""
    ly = kdb.Layout(); ly.read(str(gds)); c = ly.top_cell()
    r = kdb.Region(c.begin_shapes_rec(ly.layer(117, 5))); r.merge()
    g = r.sized(int(1.5 / ly.dbu)); g.merge()
    b = max((p.bbox() for p in g.each()), key=lambda b: b.width() * b.height())
    return kdb.DBox(b.left*ly.dbu, b.bottom*ly.dbu, b.right*ly.dbu, b.top*ly.dbu)


def cap_escape_x(gds, bank):
    """x of the narrow met3 finger just below the bank that is NOT a guard-ring
    tap (the tap runs all the way down to the met2 ring; the cap stub does not)."""
    ly = kdb.Layout(); ly.read(str(gds)); c = ly.top_cell(); dbu = ly.dbu
    strip = kdb.Region(kdb.DBox(bank.left-6, bank.bottom-12,
                                bank.right+6, bank.bottom+0.5).to_itype(dbu))
    r = (kdb.Region(c.begin_shapes_rec(ly.layer(42, 0))) & strip); r.merge()
    best = None
    for p in r.each():
        b = p.bbox()
        w, top = b.width()*dbu, b.top*dbu
        if w < 4.0 and top > bank.bottom - 6.0:      # reaches up toward the cap
            if best is None or top > best[1]:
                best = (b.center().x*dbu, top)
    return best[0] if best else (bank.left + bank.right) / 2


def main():
    out = []
    # 1 -- whole slot, pins called out
    ann = [dict(text=n, xy=(2.0, p["cy"]), xytext=(-72.0, p["cy"]),
                color="#0d47a1", fontsize=11, ha="right") for n, p in spec.pins.items()]
    out.append(render(CHIP, IMG/"01_chip_full.png",
        "D05_Gelochip - full 550 x 550 um project slot (variant EH)",
        annotate=ann, figsize=(10, 10)))

    # 2 -- the west routing channel
    out.append(render(CHIP, IMG/"02_boundary_router.png",
        "Boundary router: core met4 rail pads -> met3 lanes -> Metal2 slot pins",
        clip=kdb.DBox(-5, 0, 160, 550),
        annotate=[dict(text=n, xy=(2.0, p["cy"]), xytext=(22.0, p["cy"]),
                       color="#0d47a1", fontsize=10) for n, p in spec.pins.items()],
        figsize=(7, 11)))

    # 3 / 4 -- the storage-cap bottom-plate escape, fixed vs original
    bf = storage_bank(CHIP); xf = cap_escape_x(CHIP, bf)
    out.append(render(CHIP, IMG/"03_cap_fixed.png",
        "FIXED - bottom plate leaves on met2, steps up to met3 CLEAR of the top plate",
        clip=kdb.DBox(xf-3.5, bf.bottom-8.0, xf+4.0, bf.bottom+4.5), figsize=(6.6, 9),
        annotate=[
          dict(text="met3 TOP plate (VOUT)\nstops here", xy=(xf+2.0, bf.bottom+3.0),
               fontsize=9, ha="center", color="#bf360c"),
          dict(text="met2 finger from the\nbottom plate (VSS)", xy=(xf, bf.bottom-0.1),
               xytext=(xf-3.2, bf.bottom-2.2), fontsize=9, color="#1b5e20"),
          dict(text="via2 up to met3,\nclear of the top plate", xy=(xf, bf.bottom-0.6),
               xytext=(xf+0.8, bf.bottom-3.6), fontsize=9, color="#0d47a1"),
        ]))
    bo = storage_bank(ORIG); xo = cap_escape_x(ORIG, bo)
    out.append(render(ORIG, IMG/"04_cap_original.png",
        "ORIGINAL (19 Jul) - the bottom-plate stub (met3) runs INTO the met3 top plate",
        clip=kdb.DBox(xo-3.5, bo.bottom-8.0, xo+4.0, bo.bottom+4.5), figsize=(6.6, 9),
        annotate=[
          dict(text="met3 TOP plate (VOUT)", xy=(xo+2.0, bo.bottom+3.0),
               fontsize=9, ha="center", color="#bf360c"),
          dict(text="stub touches the plate\n=> VOUT welded to VSS", xy=(xo, bo.bottom+0.1),
               xytext=(xo-3.2, bo.bottom-2.6), fontsize=9, color="#b71c1c"),
        ]))

    # 5 -- core only
    out.append(render(CHIP, IMG/"05_core.png",
        "Harvester core (287 x 291 um) centred in the slot",
        clip=kdb.DBox(125, 124, 425, 426), figsize=(9, 9)))
    return out


if __name__ == "__main__":
    for p in main():
        print(f"  {Path(p).name:28s} {Path(p).stat().st_size/1024:7.0f} kB")
