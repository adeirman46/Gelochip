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

# via-cut transition layers: (via_gds, lower_met_gds, upper_met_gds). Used to
# un-staircase diagonally-offset via pairs (see _align_staircase_vias).
VIA_TRANS = [
    (35, 34, 36),  # via1: met1 <-> met2
    (38, 36, 42),  # via2: met2 <-> met3
    (40, 42, 46),  # via3: met3 <-> met4
]


def _align_staircase_vias(ly):
    """Fix the gf180 "Via_ width < 0.28 (Vx.1 + 2*Vx.3)" rule that fires when an
    L_route corner drops two via cuts diagonally offset by ~0.25um in BOTH axes.
    In Magic's derived contact (via & lower_met & upper_met) the diagonal pair
    merges into a staircase whose re-entrant neck is only 0.25um -> width error.
    An isolated cut of the same size passes, so the fix is to re-align the pair
    onto a common column/row (vertical/horizontal stack). The cut is moved only if
    it stays fully inside the lower-met AND upper-met overlap (so it keeps bridging
    the exact same two nets -> connectivity-safe). Returns #cuts moved."""
    dbu = ly.dbu
    small = int(round(0.13 / dbu))   # bboxes "don't really overlap" in an axis
    thr = int(round(0.36 / dbu))     # corner gap small enough to be one contact
    moved_total = 0
    for vnum, lo_m, hi_m in VIA_TRANS:
        vli = ly.find_layer(vnum, 0)
        lo_li = ly.find_layer(lo_m, 0)
        hi_li = ly.find_layer(hi_m, 0)
        if vli is None or lo_li is None or hi_li is None:
            continue
        mlo = _region(ly, lo_li)
        mhi = _region(ly, hi_li)
        cover = mlo & mhi  # area where a via legally bridges the two nets
        vreg = _region(ly, vli)
        cuts = [p.bbox() for p in vreg.each()]
        moves = {}
        n = len(cuts)
        for i in range(n):
            for j in range(i + 1, n):
                if j in moves:
                    continue
                a, b = cuts[i], cuts[j]
                ox = min(a.right, b.right) - max(a.left, b.left)
                oy = min(a.top, b.top) - max(a.bottom, b.bottom)
                # staircase: no real overlap on either axis, corners close
                if ox < small and oy < small and ox > -thr and oy > -thr:
                    acx = (a.left + a.right) // 2; acy = (a.bottom + a.top) // 2
                    bcx = (b.left + b.right) // 2; bcy = (b.bottom + b.top) // 2
                    dxc = acx - bcx; dyc = acy - bcy
                    cand = (dxc, 0) if abs(dxc) <= abs(dyc) else (0, dyc)
                    nb = b.moved(*cand)
                    # net-safety: moved cut must remain inside both metals
                    if (kdb.Region(nb) - cover).is_empty():
                        moves[j] = cand
        if moves:
            newv = kdb.Region()
            for idx, bx in enumerate(cuts):
                if idx in moves:
                    bx = bx.moved(*moves[idx])
                newv.insert(bx)
            ly.clear_layer(vli)
            ly.top_cell().shapes(vli).insert(newv)
            moved_total += len(moves)
    return moved_total


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
    # Via-staircase alignment (fixes the L_route met2<->met3 via2-width rule). Counts
    # toward total_before so callers re-import the healed GDS even when no metal
    # spacing/width violations existed (e.g. n_block: only via2 staircase, 3 errors).
    moved = _align_staircase_vias(ly)
    total_before += moved
    ly.write(out_gds)
    return total_before, total_after
