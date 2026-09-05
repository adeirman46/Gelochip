"""Dummy metal / poly fill for the D05 project slot.

The foundry wants >30% metal and 14% poly coverage (M1.4, M2.4, M3.4, M4.4, M5.4,
MT.3, PL.8).  This slot is 0.2-11% on every layer, so it needs fill.

Fill tiles are floating squares placed only where they clear, by a per-layer
margin, everything already drawn on that layer plus the slot edge, the Metal2
corner keep-outs and the pin landings.  met4 uses a 1.4 um clearance rather than
0.3 because MIMTM.1 keeps any Metal4 at least 1.2 um away from a MIM bottom
plate.
"""
import klayout.db as kdb

LAYERS = {                      # name: (layer, clearance_um, target_pct)
    "met1":  ((34, 0), 0.60, 30.0),
    "met2":  ((36, 0), 0.60, 30.0),
    "met3":  ((42, 0), 0.60, 30.0),
    "met4":  ((46, 0), 1.40, 30.0),      # MIMTM.1
    "met5":  ((81, 0), 0.60, 30.0),
    "poly2": ((30, 0), 0.60, 14.0),
}
COMP = (22, 0)


def _free_region(ly, top, layer, clearance, slot, keepouts, margin, dbu, extra=()):
    free = kdb.Region(slot.enlarged(int(-margin/dbu), int(-margin/dbu)))
    li = ly.find_layer(*layer)
    if li is not None:
        occ = kdb.Region(top.begin_shapes_rec(li)); occ.merge()
        free -= occ.sized(int(clearance/dbu))
    for k in keepouts:
        free -= kdb.Region(k).sized(int(clearance/dbu))
    for r in extra:
        free -= r.sized(int(clearance/dbu))
    free.merge()
    return free


def fill(gds_in, gds_out, slot_um=(0.0, 0.0, 550.0, 550.0), keepouts_um=(),
         tile=2.4, pitch=3.6, margin=3.0, layers=None, verbose=True):
    ly = kdb.Layout(); ly.read(str(gds_in)); top = ly.top_cell(); dbu = ly.dbu
    slot = kdb.DBox(*slot_um).to_itype(dbu)
    keeps = [kdb.DBox(*k).to_itype(dbu) for k in keepouts_um]
    layers = layers or LAYERS
    area_slot = (slot_um[2]-slot_um[0]) * (slot_um[3]-slot_um[1])

    # poly fill must also stay off active
    comp_li = ly.find_layer(*COMP)
    comp = kdb.Region(top.begin_shapes_rec(comp_li)) if comp_li is not None else kdb.Region()
    comp.merge()

    report = {}
    for name, (layer, clr, target) in layers.items():
        li = ly.layer(*layer)
        before = kdb.Region(top.begin_shapes_rec(li)); before.merge()
        a0 = before.area() * dbu * dbu
        extra = (comp,) if name == "poly2" else ()
        free = _free_region(ly, top, layer, clr, slot, keeps, margin, dbu, extra)

        t = int(tile / dbu); p = int(pitch / dbu)
        n = 0
        x = slot.left + p
        tiles = kdb.Region()
        while x + t < slot.right:
            y = slot.bottom + p
            col = kdb.Region()
            while y + t < slot.top:
                col.insert(kdb.Box(x, y, x + t, y + t))
                y += p
            col = col.inside(free)          # keep only tiles wholly in free space
            tiles += col
            n += col.count()
            x += p
        top.shapes(li).insert(tiles)
        a1 = (before + tiles).merged().area() * dbu * dbu
        report[name] = dict(tiles=n, before_pct=100*a0/area_slot,
                            after_pct=100*a1/area_slot, target=target,
                            ok=100*a1/area_slot >= target)
        if verbose:
            print(f"  {name:6s} {n:6d} tiles   {100*a0/area_slot:6.2f}% -> "
                  f"{100*a1/area_slot:6.2f}%  (target {target:.0f}%)  "
                  f"{'OK' if report[name]['ok'] else 'STILL LOW'}")
    ly.write(str(gds_out))
    return report
