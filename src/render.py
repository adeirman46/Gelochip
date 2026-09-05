"""Render the tapeout GDS to PNGs so the layout can be eyeballed in the notebook."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection
import klayout.db as kdb
from pathlib import Path

# gf180 layers, drawn back-to-front
STACK = [
    ("comp",    (22, 0),  "#9e9e9e", 0.55),
    ("poly",    (30, 0),  "#c62828", 0.55),
    ("met1",    (34, 0),  "#1565c0", 0.50),
    ("via1",    (35, 0),  "#212121", 0.85),
    ("met2",    (36, 0),  "#2e7d32", 0.55),
    ("via2",    (38, 0),  "#212121", 0.85),
    ("met3",    (42, 0),  "#ef6c00", 0.55),
    ("via3",    (40, 0),  "#212121", 0.85),
    ("met4",    (46, 0),  "#ad1457", 0.60),
    ("via4",    (41, 0),  "#212121", 0.85),
    ("met5",    (81, 0),  "#6a1b9a", 0.55),
    ("CAP_MK",  (117, 5), "#fdd835", 0.30),
    ("FuseTop", (75, 0),  "#00acc1", 0.45),
]
BOUNDARY = (0, 0)


def _polys(cell, ly, layer, clip=None):
    li = ly.find_layer(*layer)
    if li is None:
        return []
    r = kdb.Region(cell.begin_shapes_rec(li))
    if clip is not None:
        r = r & kdb.Region(clip.to_itype(ly.dbu))
    r.merge()
    out = []
    for p in r.each():
        p = p.resolved_holes()
        pts = [(pt.x * ly.dbu, pt.y * ly.dbu) for pt in p.each_point_hull()]
        if len(pts) >= 3:
            out.append(pts)
    return out


def render(gds, png, title, clip=None, annotate=None, figsize=(9, 9), legend=True):
    ly = kdb.Layout(); ly.read(str(gds)); cell = ly.top_cell()
    fig, ax = plt.subplots(figsize=figsize)
    fig.patch.set_facecolor("white")
    handles = []
    for name, layer, color, alpha in STACK:
        polys = _polys(cell, ly, layer, clip)
        if not polys:
            continue
        ax.add_collection(PolyCollection(polys, facecolors=color, edgecolors="none",
                                         alpha=alpha, linewidths=0))
        handles.append(plt.Line2D([0], [0], marker="s", linestyle="",
                                  markerfacecolor=color, markeredgecolor="none",
                                  markersize=9, alpha=min(1, alpha + 0.25),
                                  label=f"{name} {layer[0]}/{layer[1]}"))
    # The 0/0 project boundary is only meaningful un-clipped: clipping it just
    # draws a dashed rectangle on the window edge, which reads as a border.
    if clip is None:
        for pts in _polys(cell, ly, BOUNDARY, None):
            ax.add_collection(PolyCollection([pts], facecolors="none",
                                             edgecolors="#111111", linewidths=1.6,
                                             linestyles="--"))
    if clip is None:
        bb = cell.dbbox(); x0, y0, x1, y1 = bb.left, bb.bottom, bb.right, bb.top
    else:
        x0, y0, x1, y1 = clip.left, clip.bottom, clip.right, clip.top
    m = 0.02 * max(x1 - x0, y1 - y0)
    ax.set_xlim(x0 - m, x1 + m); ax.set_ylim(y0 - m, y1 + m)
    ax.set_aspect("equal")
    ax.set_xlabel("x (um)"); ax.set_ylabel("y (um)")
    ax.set_title(title, fontsize=11)
    ax.grid(alpha=0.15, linewidth=0.5)
    for a in (annotate or []):
        ax.annotate(a["text"], xy=a["xy"], xytext=a.get("xytext", a["xy"]),
                    fontsize=a.get("fontsize", 9), color=a.get("color", "#111111"),
                    weight="bold", ha=a.get("ha", "left"), va="center",
                    arrowprops=dict(arrowstyle="->", color=a.get("color", "#111111"),
                                    lw=1.1) if "xytext" in a else None,
                    bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none", alpha=0.75))
    if legend and handles:
        ax.legend(handles=handles, loc="center left", bbox_to_anchor=(1.01, 0.5),
                  fontsize=8, frameon=False)
    fig.tight_layout()
    fig.savefig(png, dpi=170, bbox_inches="tight")
    plt.close(fig)
    return png
