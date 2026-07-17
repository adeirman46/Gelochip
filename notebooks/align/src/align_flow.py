"""Reusable SPICE -> GDS helpers around the ALIGN engine.

ALIGN itself is installed in the isolated venv ``notebooks/align/.venv-align``
(it pins ``pydantic<2``). This module shells out to that venv and renders the
result with the project's ``gdstk`` + ``matplotlib``.

Importable from the notebook or any script:

    import sys; sys.path.insert(0, "src")
    from align_flow import run_align, show_gds, PDKS, EXAMPLES, DATASETS

Paths are derived from this file's location, so cwd does not matter.

Gotcha baked in: ALIGN's ``--skipGDS`` flag is defined with ``action='store_false'``
(align/cmdline.py), so its default is *True* (GDS skipped) and *passing* the flag
sets it to False -> GDS written. ``run_align`` always passes it, so you get a GDS.
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
from pathlib import Path

# ── layout (everything resolved from this file) ─────────────────────────────
ALIGN_DIR   = Path(__file__).resolve().parent.parent   # notebooks/align
VENV        = ALIGN_DIR / ".venv-align"
ALIGN_PY    = VENV / "bin" / "python"
S2L         = VENV / "bin" / "schematic2layout.py"
PDKS        = ALIGN_DIR / "pdks"
DEFAULT_PDK = PDKS / "FinFET14nm_Mock_PDK"
EXAMPLES    = ALIGN_DIR / "examples"
DATASETS    = ALIGN_DIR / "datasets"
NETLISTS    = ALIGN_DIR / "netlists"
RUNS        = ALIGN_DIR / "runs"

# lp_solve shared lib lives outside the default loader path
LP_SOLVE_LIBDIR = "/usr/lib/lp_solve"


def _env() -> dict:
    env = dict(os.environ)
    env["LD_LIBRARY_PATH"] = f"{LP_SOLVE_LIBDIR}:" + env.get("LD_LIBRARY_PATH", "")
    return env


def available_pdks() -> list[str]:
    return sorted(p.name for p in PDKS.iterdir() if p.is_dir()) if PDKS.exists() else []


def available_examples() -> list[str]:
    return sorted(p.name for p in EXAMPLES.iterdir() if p.is_dir()) if EXAMPLES.exists() else []


def example_netlist(name: str) -> str:
    """Return the SPICE text of a shipped example (searches examples/ and examples/sky130/)."""
    for cand in (EXAMPLES / "sky130" / name / f"{name}.sp",   # sky130 models (work on SKY130/GF180_PDK)
                 EXAMPLES / name / f"{name}.sp"):
        if cand.exists():
            return cand.read_text()
    raise FileNotFoundError(f"example netlist not found: {name} (looked in {EXAMPLES})")


def run_align(design: str, netlist: str, *, pdk=DEFAULT_PDK, nvariants: int = 8,
              effort: int = 0, extra_args=None, timeout: int = 1800,
              verbose: bool = True) -> list[Path]:
    """Write ``netlist`` into a design dir and run ALIGN; return generated .gds paths.

    The ``.subckt`` name in ``netlist`` should match ``design``. Outputs land in
    ``runs/<design>/build/`` (``<SUBCKT>_<variant>.gds`` and ``.python.gds``).
    """
    if not ALIGN_PY.exists():
        raise FileNotFoundError(f"isolated venv missing: {VENV}\n-> run setup_align.sh first")

    design = design.strip()
    pdk = Path(pdk)
    if not pdk.is_dir():                      # allow a bare PDK name, e.g. "SKY130_PDK"
        pdk = PDKS / pdk.name
    if not pdk.is_dir():
        raise FileNotFoundError(f"PDK not found: {pdk}  (available: {available_pdks()})")

    work = RUNS / design
    if work.exists():
        shutil.rmtree(work)
    netdir = work / "netlist"
    netdir.mkdir(parents=True)
    (netdir / f"{design}.sp").write_text(netlist.strip() + "\n")
    build = work / "build"
    build.mkdir()

    def _cmd(nv):
        c = [str(ALIGN_PY), str(S2L), str(netdir.resolve()),
             "-p", str(Path(pdk).resolve()),
             "-n", str(nv), "-l", "INFO",
             "--skipGDS"]                     # inverted flag: presence ENABLES GDS
        if effort:
            c += ["-e", str(effort)]
        if extra_args:
            c += list(extra_args)
        return c

    # working_dir defaults to cwd, so run from build/ and don't pass -w.
    # ALIGN routing is stochastic and can fail intermittently; retry with more
    # placement candidates (nvariants), which raises the odds of a routable layout.
    plan = [nvariants, max(nvariants * 2, 8), max(nvariants * 3, 16)]
    p = None
    for attempt, nv in enumerate(plan):
        if attempt:
            shutil.rmtree(build, ignore_errors=True); build.mkdir()
        cmd = _cmd(nv)
        if verbose and attempt == 0:
            print("·", " ".join(cmd), "\n  (cwd:", build, ")\n")
        p = subprocess.run(cmd, cwd=str(build), env=_env(),
                           capture_output=True, text=True, timeout=timeout)
        if p.returncode == 0 and glob.glob(str(build / "*.gds")):
            break
        if attempt < len(plan) - 1:
            print(f"  (attempt {attempt + 1} with -n {nv} produced no GDS; retrying with -n {plan[attempt + 1]})")
    if verbose:
        print(p.stdout[-3000:])
    if p.returncode != 0:
        print("─── stderr ───\n", p.stderr[-3000:])
        raise RuntimeError(f"ALIGN exited {p.returncode} after {len(plan)} attempts — see output above")

    all_gds = sorted(glob.glob(str(build / "*.gds")))
    cpp_gds = [g for g in all_gds if not g.endswith(".python.gds")]   # prefer C++ GDS
    gds = cpp_gds or all_gds
    if verbose:
        print("\n✓ GDS:", [Path(g).name for g in gds] or "NONE FOUND")
    if not gds:
        raise RuntimeError("ALIGN finished but produced no GDS (routing may have failed; "
                           "try a higher nvariants/effort or add a .const.json)")
    return [Path(g) for g in gds]


# Clean, distinct render theme (avoids the muddy PDK .lyp): stable saturated color + hatch per
# GDS layer on black, so every layer reads clearly even where they overlap.
_THEME_COLORS = [0xff5050, 0x50d050, 0x5070ff, 0xf0f040, 0x40e0e0, 0xe060e0,
                 0xffa030, 0xc8c8c8, 0x9050ff, 0x40c0a0, 0xff80b0, 0x80b0ff]
_THEME_HATCH = [5, 3, 6, 9, 2, 11, 4, 22, 1, 24, 7, 8]   # hatched dithers -> black shows through
# ALIGN construction/boundary markers (PR boundary, areaid, outline) — not fab layers.
_MARKERS = {(100, 5), (101, 0), (102, 0), (103, 0), (104, 0), (235, 5), (236, 0)}
# (layer, datatype) -> human name, for the legend (GF180MCU + sky130 draw layers).
_LAYER_NAMES = {
    # gf180
    (21, 0): "nwell", (12, 0): "dnwell", (204, 0): "lvpwell", (22, 0): "comp",
    (30, 0): "poly2", (31, 0): "pplus", (32, 0): "nplus", (33, 0): "contact",
    (34, 0): "metal1", (35, 0): "via1", (36, 0): "metal2", (38, 0): "via2",
    (40, 0): "via3", (41, 0): "via4", (42, 0): "metal3", (46, 0): "metal4", (81, 0): "metal5",
    # sky130
    (64, 20): "nwell", (65, 20): "diff", (65, 44): "tap", (66, 20): "poly", (66, 44): "licon",
    (67, 20): "li1", (67, 44): "mcon", (68, 20): "met1", (68, 44): "via", (69, 20): "met2",
    (69, 44): "via2", (70, 20): "met3", (70, 44): "via3", (71, 20): "met4",
    (93, 44): "nsdm", (94, 20): "psdm",
}
# wells / implants: real layers but large background fills — draw faint (outline-only) so devices show.
_FAINT = {"nwell", "pwell", "lvpwell", "dnwell", "pplus", "nplus", "nsdm", "psdm", "tap"}


def view_klayout(gds_path, colors="clean", width: int = 1100, height: int = 1100):
    """Render a GDS with the **KLayout** engine (headless); return it for inline display.

    Applies a clean, distinct color theme (saturated color + hatch per layer on black) so the
    layout reads clearly — unlike the muddy PDK ``.lyp``. Keeps pin/net labels (VDD, VOUT, …),
    crops ALIGN's outline marker, and sizes the image to the layout aspect (fills the frame).
    ``colors`` is accepted for compatibility; the clean theme is always used. Saves
    ``<gds>.klayout.png`` and returns an ``IPython.display.Image`` (embeds as a cell's last expr).
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # set before importing klayout.lay
    import klayout.lay as lay
    import klayout.db as kdb

    gds_path = Path(gds_path)
    lv = lay.LayoutView()
    lv.load_layout(str(gds_path), 0)
    lv.set_config("text-visible", "true")        # keep pin/net labels visible
    ly = lv.active_cellview().layout()

    # Clean distinct theme: stable color per GDS layer; wells/implants drawn faint (outline-only)
    # so devices/routing stand out. Collect (color, name) for the legend.
    legend = []
    seen_names = set()
    try:
        lv.clear_layers()
        order = {}
        for li in sorted(ly.layer_indexes(),
                         key=lambda x: (ly.get_info(x).layer, ly.get_info(x).datatype)):
            info = ly.get_info(li)
            if (info.layer, info.datatype) in _MARKERS:
                continue
            name = _LAYER_NAMES.get((info.layer, info.datatype), f"{info.layer}/{info.datatype}")
            order.setdefault(info.layer, len(order))
            k = order[info.layer]
            color = _THEME_COLORS[k % len(_THEME_COLORS)]
            faint = name in _FAINT
            node = lay.LayerPropertiesNode()
            node.source = f"{info.layer}/{info.datatype}@1"
            node.frame_color = color
            node.fill_color = color
            node.dither_pattern = 1 if faint else _THEME_HATCH[k % len(_THEME_HATCH)]  # 1=hollow
            node.transparent = faint
            node.visible = True
            node.width = 2 if faint else 1
            lv.insert_layer(lv.end_layers(), node)
            if name not in seen_names:
                seen_names.add(name)
                legend.append((color, name))
    except Exception as e:
        print("  (clean theme failed, using KLayout default:", e, ")")

    lv.max_hier()
    lv.zoom_fit()
    # Tight content box over the real (non-marker) layers, so the layout fills the frame and the
    # oversized outline (104/0) is cropped out. Falls back to zoom_fit if anything looks wrong.
    long_side = max(width, height)
    png = gds_path.with_suffix(".klayout.png")
    box = None
    try:
        cell = lv.active_cellview().cell
        full = cell.dbbox()
        farea = full.width() * full.height()
        acc = kdb.DBox()
        for li in ly.layer_indexes():
            info = ly.get_info(li)
            if (info.layer, info.datatype) in _MARKERS:
                continue
            bb = cell.dbbox(li)
            if bb.empty() or (farea > 0 and bb.width() * bb.height() >= 0.985 * farea):
                continue
            acc += bb
        if not acc.empty() and acc.width() > 0 and acc.height() > 0:
            pad = 0.02 * max(acc.width(), acc.height())
            box = acc.enlarged(pad, pad)
    except Exception as e:
        print("  (box computation failed, using zoom_fit:", e, ")")

    try:
        if box is not None:
            aspect = box.width() / box.height()
            if aspect >= 1:
                width, height = long_side, max(1, round(long_side / aspect))
            else:
                width, height = max(1, round(long_side * aspect)), long_side
            lv.save_image_with_options(str(png), int(width), int(height), 0, 0, 0.0, box, False)
        else:
            lv.save_image(str(png), int(long_side), int(long_side))
    except Exception as e:
        print("  (tight render failed, falling back to zoom_fit:", e, ")")
        lv.zoom_fit()
        lv.save_image(str(png), int(long_side), int(long_side))
    # Overlay pin/net labels (VDD, VOUT, …) at their coordinates — guaranteed-visible pinouts,
    # independent of KLayout's text rendering. Best-effort; never fatal.
    if box is not None:
        try:
            import gdstk
            from PIL import Image as _PImg, ImageDraw, ImageFont
            lib = gdstk.read_gds(str(gds_path))
            labels = lib.top_level()[0].get_labels(depth=None)
            if labels:
                sc = lib.unit / 1e-6                      # gdstk user-units -> microns (match box)
                img = _PImg.open(str(png)).convert("RGB")
                W, H = img.size
                draw = ImageDraw.Draw(img)
                try:
                    import matplotlib.font_manager as fm
                    font = ImageFont.truetype(fm.findfont("DejaVu Sans:bold"), max(13, W // 60))
                except Exception:
                    font = ImageFont.load_default()
                for lb in labels:
                    x, y = lb.origin[0] * sc, lb.origin[1] * sc
                    if not (box.left <= x <= box.right and box.bottom <= y <= box.top):
                        continue
                    px = int((x - box.left) / box.width() * W)
                    py = int((box.top - y) / box.height() * H)
                    for dx in (-2, -1, 1, 2):
                        for dy in (-2, -1, 1, 2):
                            draw.text((px + dx, py + dy), lb.text, fill="black", font=font)
                    draw.text((px, py), lb.text, fill="white", font=font)
                img.save(str(png))
        except Exception as e:
            print("  (label overlay skipped:", e, ")")

    # Append a layer legend (color swatch + gf180/sky130 layer name) as a right-side panel.
    if legend:
        try:
            from PIL import Image as _PImg, ImageDraw, ImageFont
            import matplotlib.font_manager as fm
            lay_img = _PImg.open(str(png)).convert("RGB")
            W, H = lay_img.size
            try:
                font = ImageFont.truetype(fm.findfont("DejaVu Sans"), max(14, H // 45))
            except Exception:
                font = ImageFont.load_default()
            fsz = getattr(font, "size", 14)
            sw, lh, pad = int(fsz * 1.2), int(fsz * 1.7), 12
            tmp = ImageDraw.Draw(lay_img)
            panel_w = sw + 10 + int(max(tmp.textlength(n, font=font) for _, n in legend)) + 2 * pad
            out = _PImg.new("RGB", (W + panel_w, H), (0, 0, 0))
            out.paste(lay_img, (0, 0))
            d = ImageDraw.Draw(out)
            d.text((W + pad, pad), "Layers", fill=(255, 255, 255), font=font)
            for i, (c, n) in enumerate(legend):
                y = pad + lh * (i + 1)
                rgb = ((c >> 16) & 255, (c >> 8) & 255, c & 255)
                d.rectangle([W + pad, y, W + pad + sw, y + sw], fill=rgb, outline=(200, 200, 200))
                d.text((W + pad + sw + 10, y), n, fill=(230, 230, 230), font=font)
            out.save(str(png))
        except Exception as e:
            print("  (legend skipped:", e, ")")

    print("KLayout render:", png)
    try:
        from IPython.display import Image
        return Image(filename=str(png))      # last-expression in a cell -> embedded inline
    except Exception:
        return png


def drc_report(gds_path, show: int = 25):
    """Report ALIGN's built-in DRC / connectivity check for a generated layout.

    ALIGN runs an internal checker (shorts / opens / spacing / width) against the PDK's
    abstracted rules during routing and writes ``<variant>.errors``. This surfaces that —
    it is ALIGN's own check, not a Magic/KLayout sky130 sign-off DRC. Returns the error count.
    """
    gds_path = Path(gds_path)
    variant = gds_path.stem                                  # e.g. FIVE_TRANSISTOR_OTA_0
    candidates = [gds_path.parent / "3_pnr" / f"{variant}.errors",
                  gds_path.parent / f"{variant}.errors"]
    errfile = next((c for c in candidates if c.exists()), None)
    lines = [ln for ln in errfile.read_text().splitlines() if ln.strip()] if errfile else []
    n = len(lines)
    print(f"DRC (ALIGN built-in check): {'✓ clean — 0 errors' if n == 0 else f'✗ {n} error(s)'}")
    for ln in lines[:show]:
        print("    •", ln)
    if n > show:
        print(f"    … and {n - show} more")
    return n


def show_gds(gds_path, figsize=(7, 7), save_png: bool = True):
    """Flatten a GDS and draw every layer with matplotlib; optionally save a PNG.

    (A lightweight fallback. Prefer :func:`view_klayout` for a true KLayout view.)
    """
    import gdstk
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection

    gds_path = Path(gds_path)
    lib = gdstk.read_gds(str(gds_path))
    top = lib.top_level()[0]
    scale = lib.unit / 1e-6                      # user-units -> microns
    by_layer: dict = {}
    for pg in top.get_polygons(depth=None):      # flatten hierarchy
        by_layer.setdefault((pg.layer, pg.datatype), []).append(pg.points * scale)

    # Order layers by total area so big background/well/outline layers go behind
    # (and are drawn faint), letting routing + device detail show on top.
    def _area(polys):
        a = 0.0
        for p in polys:
            xs, ys = p[:, 0], p[:, 1]
            a += (xs.max() - xs.min()) * (ys.max() - ys.min())
        return a

    order = sorted(by_layer, key=lambda k: _area(by_layer[k]), reverse=True)

    fig, ax = plt.subplots(figsize=figsize)
    cmap = plt.get_cmap("tab20")
    for i, key in enumerate(order):
        alpha = 0.18 if i == 0 else 0.55         # faint the largest (usually outline/well)
        ax.add_collection(PolyCollection(
            by_layer[key], facecolors=cmap(key[0] % 20), edgecolors="none",
            alpha=alpha, label=f"L{key[0]}/{key[1]}"))
    ax.autoscale_view()
    ax.set_aspect("equal")
    (x0, y0), (x1, y1) = top.bounding_box()
    w, h = (x1 - x0) * scale, (y1 - y0) * scale
    ax.set_title(f"{gds_path.name}   ·   {w:.2f} × {h:.2f} µm   ·   {len(by_layer)} layers")
    ax.set_xlabel("µm")
    ax.set_ylabel("µm")
    ax.legend(fontsize=6, ncol=2, loc="upper right", framealpha=0.7)
    fig.tight_layout()
    if save_png:
        png = gds_path.with_suffix(".png")
        fig.savefig(png, dpi=150, bbox_inches="tight")
        print("saved", png)
    return fig
