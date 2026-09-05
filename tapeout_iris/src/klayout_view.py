"""Second, independent renderer using KLayout's own layout view.

`render.py` draws with matplotlib from parsed polygons -- useful because it can
colour and annotate exactly what we want, but it is *our* code interpreting the
GDS. This module renders with KLayout's real display engine and the foundry's own
layer properties (`gf180mcu.lyp`), so the two views are produced by completely
independent paths. If they agree, the geometry is what we think it is.
"""
import os
from pathlib import Path

PDK_ROOT = os.environ.get(
    "PDK_ROOT",
    "/home/irman/pdks/volare/gf180mcu/versions/0fe599b2afb6708d281543108caf8310912f54af")
LYP = Path(PDK_ROOT) / "gf180mcuD" / "libs.tech" / "klayout" / "tech" / "gf180mcu.lyp"


def klayout_png(gds, png, box=None, width=900, height=900, lyp=None):
    """Render `gds` with KLayout. `box` = (x0, y0, x1, y1) in um, or None for a fit."""
    import klayout.lay as lay
    import klayout.db as db
    lv = lay.LayoutView()
    lv.load_layout(str(gds), 0)
    p = Path(lyp) if lyp else LYP
    if p.exists():
        try:
            lv.load_layer_props(str(p))
        except Exception:
            pass                      # fall back to KLayout's automatic colours
    lv.max_hier()
    if box is None:
        lv.zoom_fit()
    else:
        lv.zoom_box(db.DBox(*box))
    Path(png).parent.mkdir(parents=True, exist_ok=True)
    lv.save_image(str(png), width, height)
    return str(png)


def show_both(gds, name, img_dir, title="", box=None, mpl_figsize=(9, 9),
              kl_px=(900, 900), render_fn=None):
    """Render the same view twice -- matplotlib and KLayout -- and display both."""
    from IPython.display import Image, display, Markdown
    import klayout.db as kdb
    img_dir = Path(img_dir)
    mpl_png = img_dir / f"{name}_mpl.png"
    kl_png = img_dir / f"{name}_klayout.png"
    if render_fn is None:
        from render import render as render_fn
    clip = kdb.DBox(*box) if box else None
    render_fn(gds, mpl_png, title + "  [matplotlib]", clip=clip, figsize=mpl_figsize)
    klayout_png(gds, kl_png, box=box, width=kl_px[0], height=kl_px[1])
    display(Markdown(f"**{title}** — left/top: our matplotlib renderer; "
                     f"right/bottom: KLayout's own engine with `gf180mcu.lyp`"))
    display(Image(filename=str(mpl_png)))
    display(Image(filename=str(kl_png)))
    return mpl_png, kl_png
