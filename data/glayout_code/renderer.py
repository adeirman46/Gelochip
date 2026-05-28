"""
GDS → PNG rendering via klayout.
"""
from pathlib import Path


def render_gds(gds_path: str, output_path: str = None, width: int = 900, height: int = 600) -> str:
    """Render a GDS file to PNG. Returns the output path."""
    import klayout.lay as klay

    gds_path = str(gds_path)
    if output_path is None:
        output_path = gds_path.replace(".gds", ".png")

    if not Path(gds_path).exists():
        raise FileNotFoundError(f"GDS not found: {gds_path}")

    lv = klay.LayoutView()
    lv.load_layout(gds_path, True)
    lv.max_hier()
    lv.zoom_fit()
    lv.save_image(str(output_path), width, height)
    return str(output_path)


def render_all_steps(steps: list[dict], width: int = 900, height: int = 600) -> list[dict]:
    """
    Render before/after GDS for every step. Skips steps where GDS is missing or empty.
    Returns the updated steps list with before_png / after_png filled in.
    """
    updated = []
    for step in steps:
        s = step.copy()
        for gds_key, png_key in (("before_gds", "before_png"), ("after_gds", "after_png")):
            gds = s.get(gds_key)
            if gds and Path(gds).exists() and Path(gds).stat().st_size > 100:
                png = gds.replace(".gds", ".png")
                try:
                    render_gds(gds, png, width, height)
                    s[png_key] = png
                except Exception:
                    pass
        updated.append(s)
    return updated
