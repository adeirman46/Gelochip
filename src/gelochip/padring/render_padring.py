"""Render the SSCS Chipathon-2025 gf180 padring GDS to a PNG via KLayout.

Usage:
    python src/gelochip/padring/render_padring.py
Outputs:
    src/gelochip/padring/Chipathon2025_2_padring_view.png   (high-res reference)
    app/static/kaizen/padframe.png  +  data/circuits/padframe.png  (served backdrop)
"""
from pathlib import Path
import klayout.lay as klay

HERE = Path(__file__).resolve().parent
GDS = HERE / "Chipathon2025_2_padring.gds"
ROOT = HERE.parents[2]                       # repo root


def render(gds: Path, out: Path, size: int = 2000) -> None:
    lv = klay.LayoutView()
    lv.load_layout(str(gds), True)
    lv.max_hier()
    lv.zoom_fit()
    out.parent.mkdir(parents=True, exist_ok=True)
    lv.save_image(str(out), size, size)
    print(f"  {out}  ({size}x{size})")


def main() -> None:
    print(f"rendering {GDS.name}:")
    # 1) a high-res reference image right next to the GDS (for comparison)
    render(GDS, HERE / "Chipathon2025_2_padring_view.png", size=2000)
    # 2) the backdrop used by Chip Studio (served at /datasets/padframe.png)
    for served in (ROOT / "app/static/kaizen/padframe.png",
                   ROOT / "data/circuits/padframe.png"):
        render(GDS, served, size=1400)


if __name__ == "__main__":
    main()
