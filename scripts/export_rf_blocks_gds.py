from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gdsfactory.component import Component

from gelochip.glayout import gf180 as pdk
from gelochip.glayout.cells.composite.rf_blocks import (
    lna_block,
    rf_amp_block,
    buffer_block,
    combiner_8to1,
    rx_frontend,
    mtp_memory_wrapper,
)


def _require_pdk() -> None:
    if pdk is None:
        raise RuntimeError(
            "gf180 PDK not available. Set PDK_ROOT to the gf180 PDK path and retry."
        )


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _component_size(component: Component) -> tuple[float, float]:
    bbox = component.bbox
    width = bbox[1][0] - bbox[0][0]
    height = bbox[1][1] - bbox[0][1]
    return width, height


def _max_component_size(components: Iterable[Component]) -> tuple[float, float]:
    max_w = 0.0
    max_h = 0.0
    for comp in components:
        width, height = _component_size(comp)
        if width > max_w:
            max_w = width
        if height > max_h:
            max_h = height
    return max_w, max_h


def _grid_components(
    components: list[Component],
    spacing_x: float,
    spacing_y: float,
    name: str = "rf_blocks_combined",
) -> Component:
    combined = Component(name)
    if not components:
        return combined

    cols = max(1, math.ceil(math.sqrt(len(components))))
    for idx, comp in enumerate(components):
        ref = combined << comp
        col = idx % cols
        row = idx // cols
        ref.movex(col * spacing_x)
        ref.movey(-row * spacing_y)
    return combined


def _save_png(component: Component, path: Path) -> bool:
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return False

    try:
        plot_result = component.plot(show=False)
        if hasattr(plot_result, "savefig"):
            fig = plot_result
        else:
            fig = plot_result.get_figure()
        fig.savefig(path, dpi=200, bbox_inches="tight")
        plt.close(fig)
        return True
    except Exception:
        return False


def _safe_show(component: Component, label: str) -> None:
    try:
        component.show()
    except Exception as exc:
        print(f"[WARN] Failed to open {label}: {exc}")


def _build_blocks() -> list[tuple[str, Component]]:
    _require_pdk()
    return [
        ("lna_block", lna_block(pdk)),
        ("rf_amp_block", rf_amp_block(pdk)),
        ("buffer_block", buffer_block(pdk)),
        ("combiner_8to1", combiner_8to1(pdk)),
        ("rx_frontend", rx_frontend(pdk)),
        ("mtp_memory_wrapper", mtp_memory_wrapper(pdk)),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export GDS for rf_blocks and build a combined GDS."
    )
    parser.add_argument(
        "--out",
        default=str(ROOT / "outputs" / "rf_blocks_gds"),
        help="Output directory for GDS and previews.",
    )
    parser.add_argument(
        "--margin",
        type=float,
        default=40.0,
        help="Extra spacing between blocks in the combined layout (um).",
    )
    parser.add_argument(
        "--png",
        action="store_true",
        help="Generate PNG previews if matplotlib is available.",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Open the combined GDS in KLayout (if available).",
    )
    parser.add_argument(
        "--show-all",
        action="store_true",
        help="Open each block in KLayout (if available).",
    )

    args = parser.parse_args()
    out_dir = Path(args.out).resolve()
    blocks_dir = out_dir / "blocks"
    png_dir = out_dir / "png"
    _ensure_dir(blocks_dir)
    if args.png:
        _ensure_dir(png_dir)

    blocks = _build_blocks()
    components = [comp for _, comp in blocks]

    max_w, max_h = _max_component_size(components)
    spacing_x = max_w + args.margin
    spacing_y = max_h + args.margin

    gds_paths: list[Path] = []
    for name, comp in blocks:
        gds_path = blocks_dir / f"{name}.gds"
        comp.write_gds(str(gds_path))
        gds_paths.append(gds_path)
        if args.png:
            png_path = png_dir / f"{name}.png"
            if not _save_png(comp, png_path):
                print(f"[WARN] PNG preview skipped for {name} (matplotlib missing or failed).")
        if args.show_all:
            _safe_show(comp, name)

    combined = _grid_components(components, spacing_x, spacing_y)
    combined_path = out_dir / "rf_blocks_combined.gds"
    combined.write_gds(str(combined_path))

    if args.png:
        combined_png = png_dir / "rf_blocks_combined.png"
        if not _save_png(combined, combined_png):
            print("[WARN] PNG preview skipped for combined layout.")

    if args.show:
        _safe_show(combined, "combined")

    print("\nGDS output:")
    for gds_path in gds_paths:
        print(f"  {gds_path}")
    print(f"  {combined_path}")

    if args.png:
        print("\nPNG output:")
        for name, _ in blocks:
            print(f"  {png_dir / (name + '.png')}")
        print(f"  {png_dir / 'rf_blocks_combined.png'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
