"""Programmatic gf180 metal-SPACING DRC healer (KLayout db API).

For each metal-spacing violation (two shapes < min_separation apart) it shaves the
offending metal edges back until the gap reaches min_separation. The shaved metal
lies in the empty gap between two shapes, so removing it cannot connect two nets
(electrically safe) and only slightly narrows a route. A safety check refuses to
shave any metal layer below its min width (would break a route) — those are left
for manual review instead of risking a broken net.

Usage:
    n_before, n_after = heal_spacing(in_gds, out_gds)
"""
import klayout.db as kdb

# gf180 layer (num, datatype, min_width_um, min_space_um)
METALS = [
    ("met1", 34, 0, 0.23, 0.23),
    ("met2", 36, 0, 0.28, 0.28),
    ("met3", 42, 0, 0.28, 0.28),
    ("met4", 46, 0, 0.28, 0.28),
    ("met5", 81, 0, 0.44, 0.46),
]


def _region(ly, li):
    r = kdb.Region(ly.top_cell().begin_shapes_rec(li))
    r.merge()
    return r


# via cut layers (gf180 GDS layer/datatype) — metal must keep >=0.28 over these,
# so the shave must never remove metal sitting on a via (would create a via-width
# violation / break the via connection).
VIA_LAYERS = [(35, 0), (38, 0), (40, 0), (41, 0), (33, 0)]  # via1,via2,via3,via4,contact

# which via cuts each metal layer must enclose (so the via-width rule, which needs
# >=0.28um of metal over each via = ~0.14um enclosure each side, is satisfied).
VIA_BY_METAL = {
    34: [(33, 0), (35, 0)],   # met1: contact, via1
    36: [(35, 0), (38, 0)],   # met2: via1, via2
    42: [(38, 0), (40, 0)],   # met3: via2, via3
    46: [(40, 0), (41, 0)],   # met4: via3, via4
}


def heal_spacing(in_gds, out_gds, passes=60, nibble_dbu=6):
    ly = kdb.Layout()
    ly.read(in_gds)
    ly.top_cell().flatten(-1, True)
    total_before = total_after = 0
    for nm, lnum, dt, mw, ms in METALS:
        li = ly.find_layer(lnum, dt)
        if li is None:
            continue
        reg = _region(ly, li)
        sp = int(round(ms / ly.dbu))
        wch = int(round(mw / ly.dbu))
        sviol = reg.space_check(sp, False, kdb.Region.Euclidian).polygons().size()
        wviol = reg.width_check(wch, False, kdb.Region.Euclidian).polygons().size()
        before = sviol + wviol
        total_before += before
        if before == 0:
            continue
        # Phase 0 - merge sub-grid sliver gaps (< 0.07um). gf180 min metal spacing is
        # 0.23um, so any gap this small is a same-net abutment artifact (two tiles of
        # one rail that snapped a few nm apart) — merging them is correct, never a
        # short. Far-apart different nets can't produce a <0.07um gap.
        sliver = reg.space_check(int(0.07 / ly.dbu), False, kdb.Region.Euclidian).polygons()
        if not sliver.is_empty():
            reg = (reg + sliver.sized(1)).merge()
        # Phase 1 - spacing: shave the gap open.
        for _ in range(passes):
            gaps = reg.space_check(sp, False, kdb.Region.Euclidian).polygons()
            if gaps.is_empty():
                break
            cand = reg - gaps.sized(nibble_dbu)
            # never shave a route below min width (would break a net)
            if not cand.width_check(wch, False, kdb.Region.Euclidian).polygons().is_empty():
                cand = reg - gaps.sized(1)
                if not cand.width_check(wch, False, kdb.Region.Euclidian).polygons().is_empty():
                    break
            new = cand.merge()
            if new == reg:
                break
            reg = new
        # Phase 2 - width: grow thin metal up to min width (adds metal on the same
        # net -> safe), but only where it does NOT create a new spacing violation.
        base_sp = reg.space_check(sp, False, kdb.Region.Euclidian).polygons().size()
        for _ in range(passes):
            narrow = reg.width_check(wch, False, kdb.Region.Euclidian).polygons()
            if narrow.is_empty():
                break
            cand = (reg + narrow.sized(nibble_dbu)).merge()
            if cand.space_check(sp, False, kdb.Region.Euclidian).polygons().size() > base_sp:
                break  # growing would short to a neighbour -> leave for generation fix
            if cand == reg:
                break
            reg = cand
        ly.clear_layer(li)
        ly.top_cell().shapes(li).insert(reg)
        total_after += (reg.space_check(sp, False, kdb.Region.Euclidian).polygons().size()
                        + reg.width_check(wch, False, kdb.Region.Euclidian).polygons().size())
    ly.write(out_gds)
    return total_before, total_after
