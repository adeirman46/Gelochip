"""Render an xschem .sch file to a white-background PNG with real device
glyphs and colored nets — for inclusion in the LaTeX/PDF report.

xschem's own headless image export is unreliable in the container and no
SVG rasterizer is installed, so we parse the .sch (the same simple format
the quality gate reads) and draw it deterministically with matplotlib:
wires in blue, MOSFET/R/C/L/source/ground glyphs, net labels, and block
instances as titled boxes with named pins.
"""

from __future__ import annotations

import re
from pathlib import Path

# xschem net/wire palette on white (kept close to xschem's own hues but
# darkened where needed so they read on a white page).
NET_COLOR = "#0044bb"
DEV_COLOR = "#111111"
LABEL_COLOR = "#227722"
PIN_COLOR = "#bb2200"
BLOCK_FILL = "#eef4ff"
BLOCK_EDGE = "#3366aa"

_C_RE = re.compile(
    r'^C \{([^}]+)\} +(-?\d+) +(-?\d+) +([0-3]) +([01]) *(\{.*)?$')
_N_RE = re.compile(r'^N +(-?\d+) +(-?\d+) +(-?\d+) +(-?\d+)')
_T_RE = re.compile(r'^T \{([^}]*)\} +(-?\d+) +(-?\d+)')
_ATTR_RE = re.compile(r'(\w+)=("[^"]*"|\S+)')


def _rot(dx: int, dy: int, rot: int, flip: int) -> tuple[int, int]:
    if flip:
        dx = -dx
    for _ in range(rot):
        dx, dy = -dy, dx
    return dx, dy


def _attrs(blob: str | None) -> dict:
    if not blob:
        return {}
    return {k: v.strip('"').rstrip("}") for k, v in _ATTR_RE.findall(blob)}


def render_schematic(sch_path: str | Path, png_path: str | Path,
                     title: str | None = None) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle, FancyBboxPatch, Polygon, Rectangle

    sch = Path(sch_path)
    lines = sch.read_text(errors="replace").splitlines()
    fig, ax = plt.subplots(figsize=(11, 8))

    def X(v):  # world x
        return v

    def Y(v):  # xschem y grows downward
        return -v

    def wire(x1, y1, x2, y2, color=NET_COLOR, lw=1.4):
        ax.plot([X(x1), X(x2)], [Y(y1), Y(y2)], color=color,
                lw=lw, solid_capstyle="round", zorder=2)

    def dot(x, y, color=NET_COLOR, r=3):
        ax.add_patch(Circle((X(x), Y(y)), r, color=color, zorder=4))

    def dev_label(x, y, text, dy=-18, size=7, color=DEV_COLOR):
        if text:
            ax.text(X(x), Y(y) + dy, text, ha="center", va="center",
                    fontsize=size, color=color, zorder=6)

    def draw_mos(x, y, rot, flip, kind, name, wl):
        # terminals: gate left, drain top, source bottom (nfet); we draw a
        # generic MOSFET glyph, rotation-aware only for pin stubs.
        col = DEV_COLOR
        # body bar
        ax.plot([X(x), X(x)], [Y(y - 16), Y(y + 16)], color=col, lw=1.6,
                zorder=3)
        # gate plate
        gx, gy = _rot(-20, 0, rot, flip)
        ax.plot([X(x - 6), X(x - 6)], [Y(y - 16), Y(y + 16)], color=col,
                lw=1.6, zorder=3)
        ax.plot([X(x + gx), X(x - 6)], [Y(y + gy), Y(y)], color=col, lw=1.4,
                zorder=3)
        # drain/source stubs
        for sy in (-30, 30):
            dx2, dy2 = _rot(20, sy, rot, flip)
            ax.plot([X(x), X(x + 20)], [Y(y + sy), Y(y + sy)], color=col,
                    lw=1.4, zorder=3)
            ax.plot([X(x + 20), X(x + 20)], [Y(y + sy), Y(y)], color=col,
                    lw=1.0, zorder=3, alpha=0)
        tag = "N" if "nfet" in kind else "P"
        ax.text(X(x + 8), Y(y), tag, fontsize=6.5, color="#666", zorder=5,
                ha="center", va="center")
        dev_label(x, y, f"{name}", dy=-40, size=7)
        if wl:
            dev_label(x, y, wl, dy=42, size=6, color="#888")

    def draw_res(x, y, rot, flip, name, value):
        col = DEV_COLOR
        if rot in (0, 2):
            ax.add_patch(Rectangle((X(x) - 6, Y(y + 20)), 12, 40,
                         fill=False, edgecolor=col, lw=1.4, zorder=3))
            ax.plot([X(x), X(x)], [Y(y - 30), Y(y + 20)], color=col, lw=1.2)
            ax.plot([X(x), X(x)], [Y(y - 20), Y(y + 30)], color=col, lw=1.2)
        else:
            ax.add_patch(Rectangle((X(x - 20), Y(y) - 6), 40, 12,
                         fill=False, edgecolor=col, lw=1.4, zorder=3))
            ax.plot([X(x - 30), X(x + 30)], [Y(y), Y(y)], color=col, lw=1.2)
        dev_label(x, y, f"{name} {value}".strip(), dy=0 if rot in (1, 3) else 0,
                  size=6.5)

    def draw_cap(x, y, name, value):
        col = DEV_COLOR
        ax.plot([X(x - 12), X(x + 12)], [Y(y - 5), Y(y - 5)], color=col, lw=2)
        ax.plot([X(x - 12), X(x + 12)], [Y(y + 5), Y(y + 5)], color=col, lw=2)
        ax.plot([X(x), X(x)], [Y(y - 30), Y(y - 5)], color=col, lw=1.2)
        ax.plot([X(x), X(x)], [Y(y + 5), Y(y + 30)], color=col, lw=1.2)
        dev_label(x, y, f"{name} {value}".strip(), dy=0, size=6.5)

    def draw_ind(x, y, name, value):
        col = DEV_COLOR
        import numpy as np
        for i in range(3):
            cy = y - 15 + i * 15
            th = np.linspace(-1.4, 1.4, 20)
            ax.plot([X(x) + 7 * np.cos(t) for t in th],
                    [Y(cy) + 7 * s for s in np.sin(th)], color=col, lw=1.2)
        ax.plot([X(x), X(x)], [Y(y - 30), Y(y - 22)], color=col, lw=1.2)
        ax.plot([X(x), X(x)], [Y(y + 22), Y(y + 30)], color=col, lw=1.2)
        dev_label(x, y, f"{name} {value}".strip(), dy=0, size=6.5)

    def draw_src(x, y, name, value, current=False):
        col = DEV_COLOR
        ax.add_patch(Circle((X(x), Y(y)), 15, fill=False, edgecolor=col,
                     lw=1.4, zorder=3))
        ax.plot([X(x), X(x)], [Y(y - 30), Y(y - 15)], color=col, lw=1.2)
        ax.plot([X(x), X(x)], [Y(y + 15), Y(y + 30)], color=col, lw=1.2)
        sym = "I" if current else "~"
        ax.text(X(x), Y(y), sym, ha="center", va="center", fontsize=9,
                color=col, zorder=5)
        dev_label(x, y, f"{name}", dy=0, size=6.5)
        dev_label(x, y, value, dy=44, size=5.5, color="#888")

    def draw_gnd(x, y):
        col = DEV_COLOR
        ax.plot([X(x), X(x)], [Y(y), Y(y + 8)], color=col, lw=1.2)
        for i, w in enumerate((12, 8, 4)):
            ax.plot([X(x - w), X(x + w)], [Y(y + 8 + i * 4)] * 2, color=col,
                    lw=1.2)

    def draw_block(x, y, name, symfile):
        w, h = 90, 70
        ax.add_patch(FancyBboxPatch((X(x) - w / 2, Y(y) - h / 2), w, h,
                     boxstyle="round,pad=2", facecolor=BLOCK_FILL,
                     edgecolor=BLOCK_EDGE, lw=1.6, zorder=3))
        base = Path(symfile).stem
        ax.text(X(x), Y(y) + 6, base, ha="center", va="center", fontsize=7.5,
                color=BLOCK_EDGE, zorder=6, fontweight="bold")
        ax.text(X(x), Y(y) - 8, name, ha="center", va="center", fontsize=6.5,
                color="#555", zorder=6)

    for ln in lines:
        s = ln.strip()
        m = _N_RE.match(s)
        if m:
            x1, y1, x2, y2 = map(int, m.groups()[:4])
            wire(x1, y1, x2, y2)
            continue
        m = _T_RE.match(s)
        if m:
            txt, tx, ty = m.group(1), int(m.group(2)), int(m.group(3))
            if txt and not txt.startswith("@"):
                ax.text(X(tx), Y(ty), txt[:40], fontsize=8, color="#444",
                        zorder=6, ha="left", va="center", style="italic")
            continue
        m = _C_RE.match(s)
        if not m:
            continue
        sym, x, y, rot, flip = (m.group(1), int(m.group(2)), int(m.group(3)),
                                int(m.group(4)), int(m.group(5)))
        a = _attrs(m.group(6))
        name = a.get("name", "")
        base = sym.rsplit("/", 1)[-1]
        if "nfet" in base or "pfet" in base:
            wl = f"{a.get('W', '')}/{a.get('L', '')}".strip("/")
            draw_mos(x, y, rot, flip, base, name, wl)
        elif base.startswith("res"):
            draw_res(x, y, rot, flip, name, a.get("value", ""))
        elif base.startswith("capa"):
            draw_cap(x, y, name, a.get("value", ""))
        elif base.startswith("ind"):
            draw_ind(x, y, name, a.get("value", ""))
        elif base.startswith("vsource"):
            draw_src(x, y, name, a.get("value", ""))
        elif base.startswith("isource"):
            draw_src(x, y, name, a.get("value", ""), current=True)
        elif base.startswith("gnd"):
            draw_gnd(x, y)
        elif base.startswith(("lab_pin",)):
            lab = a.get("lab", "")
            dot(x, y, PIN_COLOR if lab == "0" else NET_COLOR, r=2.5)
            if lab and lab != "0":
                ax.text(X(x) + 6, Y(y) - 6, lab, fontsize=6.5,
                        color=LABEL_COLOR, zorder=6, ha="left", va="center")
        elif base.startswith(("ipin", "opin", "iopin")):
            lab = a.get("lab", "")
            col = "#227722" if base.startswith("ipin") else "#aa2266"
            ax.add_patch(Polygon([(X(x) - 10, Y(y) - 5), (X(x) + 6, Y(y) - 5),
                         (X(x) + 12, Y(y)), (X(x) + 6, Y(y) + 5),
                         (X(x) - 10, Y(y) + 5)], closed=True, facecolor="white",
                         edgecolor=col, lw=1.2, zorder=5))
            ax.text(X(x) - 2, Y(y), lab, fontsize=6, color=col, zorder=6,
                    ha="center", va="center")
        elif base.startswith(("code", "title", "launcher", "netlist")):
            continue
        else:  # a block .sym instance
            draw_block(x, y, name, base)

    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(title or sch.stem, fontsize=12, color="#222")
    ax.margins(0.05)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    fig.tight_layout()
    fig.savefig(png_path, dpi=150, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    return Path(png_path)


if __name__ == "__main__":
    import sys
    render_schematic(sys.argv[1], sys.argv[2],
                     sys.argv[3] if len(sys.argv) > 3 else None)
