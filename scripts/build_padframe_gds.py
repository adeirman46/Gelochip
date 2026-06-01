"""Render the real SSCS Chipathon-2025 gf180 padring GDS to a PNG used as the
Chip-Studio GDS-view backdrop."""
import klayout.lay as klay
GDS = "/home/irman/Gelochip/src/gelochip/padring/Chipathon2025_2_padring.gds"
lv = klay.LayoutView(); lv.load_layout(GDS, True); lv.max_hier(); lv.zoom_fit()
for o in ("/home/irman/Gelochip/app/static/kaizen/padframe.png",
          "/home/irman/Gelochip/data/circuits/padframe.png"):
    lv.save_image(o, 1200, 1200)
print("rendered real chipathon padring -> padframe.png")
