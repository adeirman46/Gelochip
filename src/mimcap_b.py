"""GF180MCU MIM-B capacitor (the only MIM option available on a 5LM stack).

GLayout's `mimcap()` draws Metal2 + CAP_MK + a Via2 array + Metal3 and calls it a
MIM.  On GF180 that is a plain via stack -- a short.  A real MIM needs FuseTop
(75/0) as the top electrode, and `run_drc.py`'s variant table offers the M2/M3
flavour (mim_option=A) only for 3LM and 6LM.  This design is 5LM, where the only
variants (C and D) select mim_option=B:

    bottom plate  = Metal4   (topmin1_metal)
    dielectric    = MIM module
    top plate     = FuseTop  (75/0), covered by CAP_MK (117/5)
    contact       = Via4     (top_via)
    both terminals come out on Metal5

Rules implemented (libs.tech/klayout/drc/rule_decks/mim_b.drc):
  MIMTM.1  met4 to a neighbouring MIM bottom plate .............. >= 1.2 um
  MIMTM.2  met4 enclosure of via4 inside the MIM region ......... >= 0.4 um
  MIMTM.3  met4 enclosure of FuseTop ............................ >= 0.6 um
  MIMTM.4  FuseTop enclosure of via4 ............................ >= 0.4 um
  MIMTM.5  FuseTop to the via4 that contacts the bottom plate ... >= 0.4 um
  MIMTM.6  FuseTop to unrelated FuseTop ......................... >= 0.6 um
  MIMTM.7  FuseTop covered by CAP_MK ............................ >= 0 um
  MIMTM.8a minimum FuseTop area ................................. >= 25 um^2
  MIMTM.8b maximum FuseTop area per cap ......................... <= 10000 um^2
  MIMTM.9  via4 spacing on the top plate ........................ >= 0.5 um
  MIMTM.10 no Via3 may touch the Metal4 bottom plate
  MIMTM.11 total FuseTop on one shared bottom plate ............. <= 10000 um^2
plus V4.1 (via4 exactly 0.26), V4.2b (0.36 in arrays), M5.1/M5.2a (0.28/0.28).
"""
from gdsfactory import Component

FUSETOP = (75, 0)
CAPMK   = (117, 5)

VIA          = 0.26     # V4.1: via4 is exactly 0.26 x 0.26
VIA_PITCH    = 0.80     # 0.26 + 0.54 gap  (MIMTM.9 wants >= 0.5 on the top plate)
FT_VIA_INSET = 0.40     # MIMTM.4
M4_ENC_FT    = 0.80     # MIMTM.3 (>= 0.6)
M4_ENC_VIA   = 0.50     # MIMTM.2 (>= 0.4)
FT_TO_BVIA   = 0.50     # MIMTM.5 (>= 0.4)
M5_ENC_VIA   = 0.20     # V4.4a (>= 0.01); 0.2 for comfort
M5_SPACE     = 0.40     # M5.2a is 0.28; 0.4 for comfort
CAPMK_ENC    = 0.20     # MIMTM.7 (>= 0)
PLATE_SPACE  = 1.40     # MIMTM.1 (>= 1.2) between neighbouring bottom plates


def _rect(comp, x0, y0, x1, y1, layer):
    comp.add_polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], layer=layer)


def mimcap_b(pdk, size=(28.0, 28.0), ff_per_um2=1.0, name=None):
    """One MIM-B unit, centred on its FuseTop plate.

    Ports: TOP_N (met5, top plate) and BOT_S (met5, bottom plate), both on met5
    because MIMTM.10 forbids contacting the Metal4 bottom plate from below.
    """
    W, H = size
    area = W * H
    if area < 25.0:
        raise ValueError(f"MIMTM.8a: FuseTop area {area:.1f} um^2 < 25 um^2")
    if area > 10000.0:
        raise ValueError(f"MIMTM.8b: FuseTop area {area:.1f} um^2 > 10000 um^2")

    c = Component(name=name or f"mimcap_b_{W:g}x{H:g}")
    m4, m5 = pdk.get_glayer("met4"), pdk.get_glayer("met5")
    v4 = pdk.get_glayer("via4")
    hw, hh = W / 2.0, H / 2.0

    # ---- top plate: FuseTop + its CAP_MK marker --------------------------
    _rect(c, -hw, -hh, hw, hh, FUSETOP)
    _rect(c, -hw - CAPMK_ENC, -hh - CAPMK_ENC, hw + CAPMK_ENC, hh + CAPMK_ENC, CAPMK)

    # ---- bottom plate: Metal4, enclosing FuseTop, extended south for the
    #      bottom contact (MIMTM.5 gap + via + MIMTM.2 enclosure)
    bvia_cy = -hh - FT_TO_BVIA - VIA / 2.0
    m4_bot  = bvia_cy - VIA / 2.0 - M4_ENC_VIA
    _rect(c, -hw - M4_ENC_FT, m4_bot, hw + M4_ENC_FT, hh + M4_ENC_FT, m4)

    # ---- via4 "sea" on the top plate (MIMTM.4 inset, MIMTM.9 spacing) ----
    lim = hw - FT_VIA_INSET - VIA / 2.0
    limy = hh - FT_VIA_INSET - VIA / 2.0
    n_x = int((2 * lim) // VIA_PITCH) + 1
    n_y = int((2 * limy) // VIA_PITCH) + 1
    x0 = -(n_x - 1) * VIA_PITCH / 2.0
    y0 = -(n_y - 1) * VIA_PITCH / 2.0
    for i in range(n_x):
        for j in range(n_y):
            x, y = x0 + i * VIA_PITCH, y0 + j * VIA_PITCH
            _rect(c, x - VIA/2, y - VIA/2, x + VIA/2, y + VIA/2, v4)
    # met5 top terminal covering the sea of vias
    t_half_x = abs(x0) + VIA/2 + M5_ENC_VIA
    t_half_y = abs(y0) + VIA/2 + M5_ENC_VIA
    _rect(c, -t_half_x, -t_half_y, t_half_x, t_half_y, m5)
    c.add_port(name="TOP_N", center=(0.0, t_half_y), width=min(W, 2.0),
               orientation=90, layer=m5)

    # ---- bottom contact: a via4 row south of the FuseTop, then met5 ------
    bl = hw + M4_ENC_FT - M4_ENC_VIA - VIA / 2.0
    n_b = int((2 * bl) // VIA_PITCH) + 1
    bx0 = -(n_b - 1) * VIA_PITCH / 2.0
    for i in range(n_b):
        x = bx0 + i * VIA_PITCH
        _rect(c, x - VIA/2, bvia_cy - VIA/2, x + VIA/2, bvia_cy + VIA/2, v4)
    b_half_x = abs(bx0) + VIA/2 + M5_ENC_VIA
    b_lo = bvia_cy - VIA/2 - M5_ENC_VIA
    b_hi = bvia_cy + VIA/2 + M5_ENC_VIA
    if b_hi > -t_half_y - M5_SPACE:                     # keep M5 terminals apart
        raise ValueError("met5 terminals too close; increase FT_TO_BVIA")
    _rect(c, -b_half_x, b_lo, b_half_x, b_hi, m5)
    c.add_port(name="BOT_S", center=(0.0, b_lo), width=min(W, 2.0),
               orientation=270, layer=m5)

    c.info["capacitance_pf"] = area * ff_per_um2 / 1000.0
    c.info["fusetop_area_um2"] = area
    c.info["m4_plate"] = (-hw - M4_ENC_FT, m4_bot, hw + M4_ENC_FT, hh + M4_ENC_FT)
    c.info["n_top_vias"] = n_x * n_y
    c.info["n_bot_vias"] = n_b
    return c


def mimcap_b_array(pdk, rows=1, columns=1, size=(28.0, 28.0), ff_per_um2=1.0,
                   bus_w=2.0, name=None):
    """rows x columns array of MIM-B units with both terminals bussed out.

    Terminal routing (all on met5, since MIMTM.10 forbids contacting the Metal4
    bottom plate from below):

      TOP  -- a met5 link along each row's centre line merges that row's top
              plates, and runs LEFT to a vertical met5 bus.
      BOT  -- a met5 strip along each row's bottom-contact line merges that
              row's bottom terminals, and runs RIGHT to a second vertical bus.

    The two nets leave on opposite sides, so no met5 crossing is needed and no
    Metal4 routing is required inside the array (which would violate MIMTM.1's
    1.2 um keep-away from the bottom plates).
    """
    c = Component(name=name or f"mimcap_b_arr_{rows}x{columns}")
    m5 = pdk.get_glayer("met5")
    unit = mimcap_b(pdk, size, ff_per_um2)
    ub = unit.bbox
    uw = float(ub[1][0] - ub[0][0])
    uh = float(ub[1][1] - ub[0][1])
    px = uw + PLATE_SPACE                     # MIMTM.1 between bottom plates
    py = uh + PLATE_SPACE
    W, H = size
    hw, hh = W / 2.0, H / 2.0
    bvia_cy = -hh - FT_TO_BVIA - VIA / 2.0

    x0 = -(columns - 1) * px / 2.0
    y0 = -(rows - 1) * py / 2.0
    for r in range(rows):
        for k in range(columns):
            ref = c << unit
            ref.movex(x0 + k * px).movey(y0 + r * py)

    left_plate  = x0 - (hw + M4_ENC_FT)
    right_plate = x0 + (columns - 1) * px + (hw + M4_ENC_FT)
    top_bus_x = left_plate - PLATE_SPACE - bus_w / 2.0
    bot_bus_x = right_plate + PLATE_SPACE + bus_w / 2.0

    for r in range(rows):
        yc = y0 + r * py
        # TOP link: along the row centre, out to the left bus
        _rect(c, top_bus_x - bus_w/2, yc - bus_w/2, right_plate, yc + bus_w/2, m5)
        # BOT link: along the bottom-contact line, out to the right bus
        by = yc + bvia_cy
        _rect(c, left_plate, by - VIA/2 - M5_ENC_VIA,
              bot_bus_x + bus_w/2, by + VIA/2 + M5_ENC_VIA, m5)

    ylo = y0 + bvia_cy - VIA/2 - M5_ENC_VIA
    yhi = y0 + (rows - 1) * py + hh + M4_ENC_FT
    _rect(c, top_bus_x - bus_w/2, ylo, top_bus_x + bus_w/2, yhi, m5)
    _rect(c, bot_bus_x - bus_w/2, ylo, bot_bus_x + bus_w/2, yhi, m5)

    c.add_port(name="TOP_W", center=(top_bus_x, yhi), width=bus_w,
               orientation=90, layer=m5)
    c.add_port(name="BOT_E", center=(bot_bus_x, yhi), width=bus_w,
               orientation=90, layer=m5)
    c.info["capacitance_pf"] = rows * columns * unit.info["capacitance_pf"]
    c.info["unit_pf"] = unit.info["capacitance_pf"]
    c.info["rows"], c.info["columns"] = rows, columns
    c.info["fusetop_area_um2"] = rows * columns * unit.info["fusetop_area_um2"]
    return c


def mimcap_b_bank(pdk, target_pf, unit_um=(28.0, 28.0), ff_per_um2=1.0,
                  max_cols=6, name=None):
    """Pick a rows x cols MIM-B array closest to `target_pf`."""
    unit_ff = unit_um[0] * unit_um[1] * ff_per_um2
    n = max(1, round(target_pf * 1000.0 / unit_ff))
    cols = min(max_cols, n)
    rows = -(-n // cols)
    a = mimcap_b_array(pdk, rows, cols, unit_um, ff_per_um2, name=name)
    print(f"[mimcap_b_bank] {target_pf} pF -> {rows}x{cols} x {unit_ff/1000:.3f} pF"
          f" = {a.info['capacitance_pf']:.3f} pF")
    return a
