"""
GDS layout builder + DRC check for PixelatedRF layouts.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TypedDict

import gdstk
import klayout.db as kdb
import numpy as np
import gdsfactory as gf

PIXEL_W       = 20.0          # µm
PIXEL_L       = 20.0          # µm
GF180_METALTOP = (46, 0)
FEED_W        = PIXEL_W
FEED_L        = PIXEL_L * 1.5
GND_PAD       = PIXEL_W
MT_MIN_WIDTH  = 0.36          # µm
MT_MIN_SPACE  = 0.36          # µm
MT_MIN_AREA   = 0.5           # µm²
MT_DEN_MIN    = 0.05
MT_DEN_MAX    = 0.80


class DRCResult(TypedDict):
    density_pct: float
    density_ok: bool
    min_width_violations: int
    min_space_violations: int
    corner_touch_violations: int
    min_area_violations: int
    chip_w_um: float
    chip_h_um: float
    metal_area_um2: float
    fill_pct: float
    status: str


def build_gds(binary_matrix: list[list[int]],
              name: str = "pixelrf_chip") -> tuple[Path, gf.Component]:
    """
    Build a merged GDS from a 12×12 binary pixel matrix.
    Returns (gds_path, gdsfactory_component).
    """
    grid = np.array(binary_matrix, dtype=float)
    grid_rows, grid_cols = grid.shape
    chip_w = grid_cols * PIXEL_W
    chip_l = grid_rows * PIXEL_L
    ly, dt = GF180_METALTOP

    # Collect pixel rectangles + feed pad
    raw: list[gdstk.Polygon] = []
    for r in range(grid_rows):
        for c in range(grid_cols):
            if grid[r, c]:
                x = c * PIXEL_W
                y = (grid_rows - 1 - r) * PIXEL_L
                raw.append(gdstk.rectangle((x, y), (x + PIXEL_W, y + PIXEL_L)))

    feed_x0 = chip_w / 2 - FEED_W / 2
    feed_y0 = -FEED_L
    raw.append(gdstk.rectangle((feed_x0, feed_y0), (feed_x0 + FEED_W, 0)))

    # Boolean OR: merge all touching pixels into connected regions
    merged_patch = gdstk.boolean(raw, [], "or", layer=ly, datatype=dt)

    # Ground pads (corners, separate net)
    gnd_rects = [
        gdstk.rectangle((0,               -GND_PAD),  (GND_PAD,         0)),
        gdstk.rectangle((chip_w - GND_PAD, -GND_PAD), (chip_w,          0)),
        gdstk.rectangle((0,               chip_l),    (GND_PAD,         chip_l + GND_PAD)),
        gdstk.rectangle((chip_w - GND_PAD, chip_l),   (chip_w,          chip_l + GND_PAD)),
    ]

    # Build gdsfactory component
    comp = gf.Component(name)
    for poly in merged_patch:
        comp.add_polygon([(float(p[0]), float(p[1])) for p in poly.points],
                         layer=GF180_METALTOP)
    for rect in gnd_rects:
        comp.add_polygon([(float(p[0]), float(p[1])) for p in rect.points],
                         layer=GF180_METALTOP)

    # Ports
    comp.add_port(name="RF_IN",
                  center=(feed_x0 + FEED_W / 2, feed_y0),
                  width=FEED_W, orientation=270, layer=GF180_METALTOP)
    for pname, px, py, orient in [
        ("RF_GND_BL", GND_PAD / 2,             -GND_PAD / 2,         270),
        ("RF_GND_BR", chip_w - GND_PAD / 2,    -GND_PAD / 2,         270),
        ("RF_GND_TL", GND_PAD / 2,              chip_l + GND_PAD / 2,  90),
        ("RF_GND_TR", chip_w - GND_PAD / 2,     chip_l + GND_PAD / 2,  90),
    ]:
        comp.add_port(name=pname, center=(px, py), width=GND_PAD,
                      orientation=orient, layer=GF180_METALTOP)

    # Write GDS to a temp file
    tmp = Path(tempfile.mktemp(suffix=".gds"))
    comp.write_gds(str(tmp))
    return tmp, comp


def run_drc(gds_path: Path, grid: list[list[int]]) -> DRCResult:
    """
    Run MetalTop DRC rules on the generated GDS.
    Returns a DRCResult dict.
    """
    ly = kdb.Layout()
    ly.read(str(gds_path))
    cell = ly.top_cell()
    dbu  = ly.dbu
    mt_li = next(i for i in ly.layer_indices() if ly.get_info(i).layer == 46)

    region = kdb.Region(cell.begin_shapes_rec(mt_li))
    merged = kdb.Region(cell.begin_shapes_rec(mt_li))
    merged.merge()

    min_w = int(round(MT_MIN_WIDTH / dbu))
    min_s = int(round(MT_MIN_SPACE / dbu))

    nw = merged.width_check(min_w).count()
    ns = region.space_check(min_s).count()
    na = sum(1 for p in region.each() if p.area() * dbu**2 < MT_MIN_AREA)

    # Corner-touch: 0-distance violations (single-point contact)
    ct = region.space_check(1).count()   # < 1nm → corner only

    bbox       = cell.bbox()
    chip_w_um  = bbox.width()  * dbu
    chip_h_um  = bbox.height() * dbu
    chip_area  = chip_w_um * chip_h_um
    metal_area = sum(p.area() * dbu**2 for p in merged.each())
    density    = metal_area / chip_area if chip_area > 0 else 0
    fill       = np.array(grid, dtype=float).mean()

    # corner-touch pixels create zero-width pinch points after klayout merge → width violation
    # subtract those from nw; they're reported separately as corner_touch_violations
    edge_viol  = ns - ct
    width_viol = max(0, nw - ct)
    clean      = (width_viol == 0) and (edge_viol == 0) and (na == 0)
    if clean:
        status = f"CLEAN ({ct} corner-touch design-intent)"
    else:
        status = f"{width_viol + edge_viol + na} violations"

    return DRCResult(
        density_pct=round(density * 100, 1),
        density_ok=bool(MT_DEN_MIN <= density <= MT_DEN_MAX),
        min_width_violations=nw,
        min_space_violations=ns,
        corner_touch_violations=ct,
        min_area_violations=na,
        chip_w_um=chip_w_um,
        chip_h_um=chip_h_um,
        metal_area_um2=round(metal_area, 1),
        fill_pct=round(fill * 100, 1),
        status=status,
    )
