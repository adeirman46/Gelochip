"""Generate architecture block diagram, per-block schematics, and annotated layout.

Outputs (relative to iris_rf/):
  report/fig_architecture.png
  report/fig_schematic_matching.png
  report/fig_schematic_bias.png
  report/fig_schematic_rectifier.png
  report/fig_schematic_pump.png
  layout/iris_layout_annotated.png
"""
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "report"
LAYOUT = ROOT / "layout"
REPORT.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------
# 1) Architecture block diagram
# --------------------------------------------------------------------------
def make_architecture():
    fig, ax = plt.subplots(figsize=(14, 4.2), dpi=180)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 30)
    ax.axis("off")

    blocks = [
        ("RF\nSource\n(Antenna)", 2, 10, 10, "#dbeafe"),
        ("Matching\nNetwork\n(L-C, off-chip)", 15, 8, 12, "#bfdbfe"),
        ("Injection-\nAssisted\nBias", 30, 7, 12, "#fde68a"),
        ("Diff.\nCross-Coupled\nRectifier", 45, 6, 12, "#fca5a5"),
        ("Dickson\nCharge\nPump\n(3 stages)", 60, 5, 12, "#c4b5fd"),
        ("Storage\nCapacitor\n20 pF", 75, 6, 12, "#a7f3d0"),
        ("Load\nR_L", 90, 8, 8, "#e5e7eb"),
    ]
    coords = []
    for label, x, y, w, color in blocks:
        h = 14
        box = FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.3,rounding_size=1.2",
            linewidth=1.6,
            edgecolor="#111827",
            facecolor=color,
        )
        ax.add_patch(box)
        ax.text(x + w / 2, y + h / 2, label, ha="center", va="center", fontsize=10, fontweight="bold")
        coords.append((x, y, w, h))

    # arrows
    for i in range(len(coords) - 1):
        x1, y1, w1, h1 = coords[i]
        x2, y2, w2, h2 = coords[i + 1]
        start = (x1 + w1, y1 + h1 / 2)
        end = (x2, y2 + h2 / 2)
        arrow = FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=18, linewidth=1.6, color="#111827")
        ax.add_patch(arrow)

    # signal labels
    label_pairs = [
        (12.5, 17, "V_ant"),
        (27, 17, "RFP / RFN\n(differential)"),
        (42, 17, "V_gate_p/n"),
        (57, 17, "V_rect"),
        (72, 17, "V_pump"),
        (87, 17, "V_out"),
    ]
    for x, y, txt in label_pairs:
        ax.text(x, y + 6, txt, ha="center", va="bottom", fontsize=8, color="#374151")

    # Feedback / gate coupling annotation
    ax.text(50, 2.5,
            "Injection-assisted startup: bias network pre-charges V_gate to lower rectifier Vth",
            ha="center", fontsize=9, color="#374151", style="italic")

    ax.set_title("IRIS — RF Energy Harvester Architecture (GF180MCU, 30–100 MHz)",
                 fontsize=13, fontweight="bold", pad=6)

    fig.tight_layout()
    out = REPORT / "fig_architecture.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print("wrote", out)


# --------------------------------------------------------------------------
# 2a) Matching network schematic
# --------------------------------------------------------------------------
def make_matching():
    fig, ax = plt.subplots(figsize=(9, 4.2), dpi=180)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 40)
    ax.axis("off")

    # sources
    ax.plot([5, 5], [30, 24], "k", lw=1.5)
    ax.plot([5, 5], [10, 16], "k", lw=1.5)
    ax.add_patch(plt.Circle((5, 20), 4, fill=False, lw=1.5))
    ax.text(5, 20, "~", ha="center", va="center", fontsize=14, fontweight="bold")
    ax.text(-2, 20, "V_ant", ha="right", va="center", fontsize=10)

    # series inductor Lmatch (top rail)
    ax.plot([9, 20], [30, 30], "k", lw=1.5)
    ax.add_patch(Rectangle((20, 28), 12, 4, fill=False, lw=1.5))
    ax.text(26, 30, "L_match\n120 nH", ha="center", va="center", fontsize=9)
    ax.plot([32, 60], [30, 30], "k", lw=1.5)

    # shunt cap Cmatch
    ax.plot([46, 46], [30, 24], "k", lw=1.5)
    ax.plot([44, 48], [24, 24], "k", lw=2)
    ax.plot([44, 48], [22, 22], "k", lw=2)
    ax.plot([46, 46], [22, 16], "k", lw=1.5)
    ax.text(52, 23, "C_match\n5.6 pF", ha="left", va="center", fontsize=9)

    # damping R
    ax.add_patch(Rectangle((60, 28), 8, 4, fill=False, lw=1.5))
    ax.text(64, 30, "R_damp 2 Ω", ha="center", va="center", fontsize=9)
    ax.plot([68, 85], [30, 30], "k", lw=1.5)
    ax.text(88, 30, "RFP", ha="left", va="center", fontsize=10, fontweight="bold")

    # bottom rail
    ax.plot([9, 85], [10, 10], "k", lw=1.5)
    ax.text(88, 10, "RFN", ha="left", va="center", fontsize=10, fontweight="bold")

    ax.text(50, 38, "Matching Network (differential, off-chip)",
            ha="center", fontsize=12, fontweight="bold")
    ax.text(50, 3, "Effective voltage gain ≈ 6× at 30–100 MHz (resonant)",
            ha="center", fontsize=9, style="italic", color="#374151")

    fig.tight_layout()
    out = REPORT / "fig_schematic_matching.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print("wrote", out)


# --------------------------------------------------------------------------
# 2b) Startup / injection bias schematic
# --------------------------------------------------------------------------
def make_bias():
    fig, ax = plt.subplots(figsize=(9, 5.5), dpi=180)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 55)
    ax.axis("off")

    ax.text(50, 52, "Injection-Assisted Startup Bias Network",
            ha="center", fontsize=12, fontweight="bold")

    # rails
    ax.plot([5, 95], [46, 46], "k", lw=1.5)
    ax.text(2, 46, "V_rect", ha="right", va="center", fontsize=10)
    ax.plot([5, 95], [6, 6], "k", lw=1.5)
    ax.text(2, 6, "V_ss", ha="right", va="center", fontsize=10)

    # PMOS bias (diode-connected) left/right
    def pmos_diode(cx, gate_net):
        # simple MOS symbol
        ax.plot([cx - 3, cx - 3], [30, 40], "k", lw=1.5)          # channel
        ax.plot([cx - 5, cx - 3], [30, 30], "k", lw=1.5)          # source lead
        ax.plot([cx - 5, cx - 3], [40, 40], "k", lw=1.5)
        ax.add_patch(plt.Circle((cx - 5, 40), 0.6, color="k"))    # source dot
        ax.plot([cx - 5, cx - 5], [40, 46], "k", lw=1.5)          # to Vrect
        ax.plot([cx - 3, cx - 5], [30, 30], "k", lw=1.5)
        ax.plot([cx - 5, cx - 5], [30, 20], "k", lw=1.5)          # to output node
        ax.plot([cx - 1, cx - 3], [35, 35], "k", lw=1.5)          # gate
        ax.text(cx - 0.5, 35, f"P (W=4µ/L=1µ)\ngate=%s" % gate_net, ha="left", va="center", fontsize=8)
    # NMOS bias (diode-connected)
    def nmos_diode(cx, gate_net):
        ax.plot([cx - 3, cx - 3], [12, 22], "k", lw=1.5)
        ax.plot([cx - 5, cx - 3], [12, 12], "k", lw=1.5)
        ax.plot([cx - 5, cx - 3], [22, 22], "k", lw=1.5)
        ax.plot([cx - 5, cx - 5], [12, 6], "k", lw=1.5)
        ax.plot([cx - 5, cx - 5], [22, 30], "k", lw=1.5)
        ax.plot([cx - 1, cx - 3], [17, 17], "k", lw=1.5)
        ax.text(cx - 0.5, 17, f"N (W=2µ/L=1µ)\ngate=%s" % gate_net, ha="left", va="center", fontsize=8)

    pmos_diode(25, "gate_p")
    nmos_diode(25, "gate_p")
    pmos_diode(70, "gate_n")
    nmos_diode(70, "gate_n")

    # injection caps (RFN → gate_p, RFP → gate_n)
    ax.text(15, 32, "C_inj", ha="center", va="center", fontsize=9)
    ax.plot([13, 17], [30, 30], "k", lw=2)
    ax.plot([13, 17], [28, 28], "k", lw=2)
    ax.plot([15, 15], [30, 25], "k", lw=1.5)
    ax.plot([15, 15], [28, 25], "k", lw=1.5)
    ax.plot([15, 20], [25, 25], "k", lw=1.5)  # to gate_p node
    ax.plot([15, 15], [30, 50], "k--", lw=1.0)
    ax.text(15, 51, "RFN", ha="center", fontsize=9)

    ax.text(60, 32, "C_inj", ha="center", va="center", fontsize=9)
    ax.plot([58, 62], [30, 30], "k", lw=2)
    ax.plot([58, 62], [28, 28], "k", lw=2)
    ax.plot([60, 60], [30, 25], "k--", lw=1.0)
    ax.plot([60, 65], [25, 25], "k", lw=1.5)
    ax.plot([60, 60], [30, 50], "k--", lw=1.0)
    ax.text(60, 51, "RFP", ha="center", fontsize=9)

    ax.text(50, 1, "AC coupling from RF nodes to gate_p/gate_n → lowers effective Vth of rectifier",
            ha="center", fontsize=9, style="italic", color="#374151")

    fig.tight_layout()
    out = REPORT / "fig_schematic_bias.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print("wrote", out)


# --------------------------------------------------------------------------
# 2c) Cross-coupled rectifier schematic
# --------------------------------------------------------------------------
def make_rectifier():
    fig, ax = plt.subplots(figsize=(9, 5.5), dpi=180)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 55)
    ax.axis("off")

    ax.text(50, 52, "Differential Cross-Coupled CMOS Rectifier",
            ha="center", fontsize=12, fontweight="bold")

    # Vrect rail top
    ax.plot([5, 95], [46, 46], "k", lw=1.6)
    ax.text(2, 46, "V_rect", ha="right", va="center", fontsize=10)

    # VSS bottom
    ax.plot([5, 95], [6, 6], "k", lw=1.6)
    ax.text(2, 6, "V_ss", ha="right", va="center", fontsize=10)

    # PMOS pair (top)
    def draw_pmos(cx, drain_x, gate_from_x, name):
        ax.plot([cx, cx], [36, 42], "k", lw=1.5)
        ax.add_patch(Rectangle((cx - 3, 33), 6, 4, fill=False, lw=1.5))
        ax.text(cx, 35, "P\n80µ/0.28µ×8", ha="center", va="center", fontsize=8)
        ax.plot([cx, cx], [33, 28], "k", lw=1.5)
        ax.plot([cx - 5, cx - 3], [35, 35], "k", lw=1.5)
        ax.plot([cx, cx], [42, 46], "k", lw=1.5)  # source→Vrect
        ax.plot([cx, drain_x], [28, 28], "k", lw=1.5)
        ax.text(cx, 43, "S", fontsize=7)
    draw_pmos(30, 30, 0, "MPP1")
    draw_pmos(70, 70, 0, "MPP2")

    # NMOS pair (bottom)
    def draw_nmos(cx, drain_x, name):
        ax.plot([cx, cx], [14, 20], "k", lw=1.5)
        ax.add_patch(Rectangle((cx - 3, 17), 6, 4, fill=False, lw=1.5))
        ax.text(cx, 19, "N\n40µ/0.28µ×8", ha="center", va="center", fontsize=8)
        ax.plot([cx, cx], [17, 6], "k", lw=1.5)      # source→Vss
        ax.plot([cx, cx], [21, 28], "k", lw=1.5)     # drain→RF node
        ax.plot([cx - 5, cx - 3], [19, 19], "k", lw=1.5)  # gate
    draw_nmos(30, 30, "MNN1")
    draw_nmos(70, 70, "MNN2")

    # RFP node (left column drain) and RFN node (right column drain)
    ax.plot([30, 30], [28, 28], "k", lw=1.5)
    ax.plot([30, 15], [28, 28], "k", lw=1.5)
    ax.text(12, 28, "RFP", ha="right", va="center", fontsize=10, fontweight="bold")

    ax.plot([70, 85], [28, 28], "k", lw=1.5)
    ax.text(88, 28, "RFN", ha="left", va="center", fontsize=10, fontweight="bold")

    # cross-coupled gate connections: gate of left pair ← RFN, gate of right pair ← RFP
    ax.plot([25, 25], [35, 19], "k", lw=1.2, linestyle="--")   # PMOS/NMOS common gate at cx=25
    ax.plot([25, 70], [10.5, 10.5], "k", lw=1.2, linestyle="--")
    ax.plot([70, 70], [10.5, 10.5], "k", lw=1.2, linestyle="--")
    # simplification: label gates as gate_n and gate_p
    ax.text(25, 41, "gate_n", fontsize=8, color="#b91c1c")
    ax.text(65, 41, "gate_p", fontsize=8, color="#b91c1c")

    ax.text(50, 1, "Alternating conduction of PMOS/NMOS pairs delivers rectified V_rect above 2·Vth_eff", ha="center", fontsize=9, style="italic", color="#374151")

    fig.tight_layout()
    out = REPORT / "fig_schematic_rectifier.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print("wrote", out)


# --------------------------------------------------------------------------
# 2d) Dickson charge pump schematic
# --------------------------------------------------------------------------
def make_pump():
    fig, ax = plt.subplots(figsize=(11, 4.5), dpi=180)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 45)
    ax.axis("off")

    ax.text(50, 42, "3-Stage Dickson Charge Pump + Storage",
            ha="center", fontsize=12, fontweight="bold")

    # top rail (diodes)
    ax.plot([5, 90], [30, 30], "k", lw=1.5)

    # 3 diode-connected NMOS stages
    diode_x = [15, 40, 65]
    node_names = ["V_rect", "n1", "n2", "V_out"]
    prev_x = 5
    for i, dx in enumerate(diode_x):
        ax.add_patch(Rectangle((dx - 3, 27), 6, 6, fill=False, lw=1.5))
        ax.text(dx, 30, f"MCP{i+1}\n16µ/0.28µ", ha="center", va="center", fontsize=8)
        # diode-connect line: gate tied to drain
        ax.plot([dx - 4, dx - 3], [32, 32], "k", lw=1.2)
        ax.plot([dx - 4, dx - 4], [32, 34.5], "k", lw=1.2)
        ax.plot([dx - 4, dx + 3], [34.5, 34.5], "k", lw=1.2)
    ax.text(5, 34, node_names[0], fontsize=9)
    ax.text(25, 34, node_names[1], fontsize=9)
    ax.text(50, 34, node_names[2], fontsize=9)
    ax.text(78, 34, node_names[3], fontsize=9)

    # coupling caps: CCP1 rfp→n1, CCP2 rfn→n2, CCP3 rfp→vout
    cap_pairs = [(25, "RFP"), (50, "RFN"), (75, "RFP")]
    for cx, clk in cap_pairs:
        ax.plot([cx, cx], [30, 20], "k", lw=1.2)
        ax.plot([cx - 3, cx + 3], [20, 20], "k", lw=2)
        ax.plot([cx - 3, cx + 3], [18, 18], "k", lw=2)
        ax.plot([cx, cx], [18, 10], "k", lw=1.2)
        ax.text(cx + 3.5, 19, "1.2 pF", fontsize=8)
        ax.plot([cx, cx], [10, 4], "k--", lw=0.8)
        ax.text(cx, 3, clk, ha="center", fontsize=8, color="#b91c1c")

    # storage cap Cstore at Vout to Vss
    ax.plot([90, 90], [30, 20], "k", lw=1.5)
    ax.plot([87, 93], [20, 20], "k", lw=2.2)
    ax.plot([87, 93], [18, 18], "k", lw=2.2)
    ax.plot([90, 90], [18, 8], "k", lw=1.5)
    ax.plot([85, 95], [8, 8], "k", lw=1.5)
    ax.text(94, 19, "C_store\n20 pF", ha="left", va="center", fontsize=9)
    ax.text(94, 8, "V_ss", ha="left", va="center", fontsize=9)

    ax.text(50, 0.5, "Each stage pumps up ~Vpk−Vth_eff; three stages boost V_rect toward V_out ≥ 1.2 V", ha="center", fontsize=9, style="italic", color="#374151")

    fig.tight_layout()
    out = REPORT / "fig_schematic_pump.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print("wrote", out)


# --------------------------------------------------------------------------
# 3) Annotated layout image
# --------------------------------------------------------------------------
def annotate_layout():
    src = LAYOUT / "iris_layout.png"
    im = Image.open(src).convert("RGB")
    W, H = im.size

    draw = ImageDraw.Draw(im, "RGBA")

    # try large font
    try:
        font_lg = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size=int(H * 0.028))
        font_md = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size=int(H * 0.020))
        font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=int(H * 0.016))
    except Exception:
        font_lg = ImageFont.load_default()
        font_md = ImageFont.load_default()
        font_sm = ImageFont.load_default()

    # region definitions in fractional coords, (x0,y0,x1,y1)
    # each block label placed at (lbl_x, lbl_y) fractional
    regions = [
        # (name, x0, y0, x1, y1, color rgba, lbl_frac)
        ("Matching Network\n(external L-C)",         0.02, 0.11, 0.22, 0.42, (59, 130, 246, 55), (0.03, 0.12)),
        ("Injection-Assisted\nStartup Bias",         0.22, 0.11, 0.55, 0.42, (245, 158, 11, 55), (0.35, 0.12)),
        ("Cross-Coupled\nRectifier (PMOS / NMOS)",   0.08, 0.42, 0.55, 0.75, (239, 68, 68, 55), (0.10, 0.44)),
        ("Dickson Pump\nStage Caps",                 0.08, 0.75, 0.60, 0.97, (139, 92, 246, 55), (0.10, 0.77)),
        ("Charge-Pump\nDiodes",                      0.55, 0.11, 0.75, 0.55, (16, 185, 129, 55), (0.56, 0.13)),
        ("Storage Capacitor\n(20 pF)",               0.68, 0.55, 0.96, 0.90, (219, 39, 119, 55), (0.70, 0.57)),
    ]

    ports = [
        ("VIN+ (rfp)", 0.10, 0.065, "top"),
        ("VIN− (rfn)", 0.24, 0.065, "top"),
        ("VRECT",      0.50, 0.065, "top"),
        ("VOUT",       0.83, 0.485, "right"),
        ("VSS",        0.10, 0.955, "left"),
    ]

    # translucent boxes + labels
    for name, x0, y0, x1, y1, color, lbl_frac in regions:
        rx0, ry0, rx1, ry1 = int(x0 * W), int(y0 * H), int(x1 * W), int(y1 * H)
        # filled translucent
        draw.rectangle([rx0, ry0, rx1, ry1], fill=color, outline=(color[0], color[1], color[2], 255), width=4)

        # place label at explicit fractional location so it doesn't collide with port dots (which live at y<0.10)
        lx, ly = int(lbl_frac[0] * W), int(lbl_frac[1] * H)
        bbox = draw.multiline_textbbox((lx, ly), name, font=font_md, spacing=2)
        pad = 6
        draw.rectangle([bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad],
                       fill=(255, 255, 255, 235), outline=(color[0], color[1], color[2], 255), width=2)
        draw.multiline_text((lx, ly), name, font=font_md, fill=(color[0] // 2, color[1] // 2, color[2] // 2, 255), spacing=2)

    # port callouts
    for name, x, y, side in ports:
        cx, cy = int(x * W), int(y * H)
        r = int(H * 0.010)
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(0, 0, 0, 255), width=3, fill=(255, 255, 0, 220))
        offsets = {
            "top": (-int(W * 0.035), -int(H * 0.035)),
            "bottom": (0, int(H * 0.018)),
            "right": (int(W * 0.018), -int(H * 0.008)),
            "left": (int(W * 0.02), -int(H * 0.008)),
        }
        ox, oy = offsets[side]
        tx, ty = cx + ox, cy + oy
        bbox = draw.textbbox((tx, ty), name, font=font_sm)
        pad = 4
        draw.rectangle([bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad],
                       fill=(0, 0, 0, 220))
        draw.text((tx, ty), name, font=font_sm, fill=(255, 255, 255, 255))
        # thin connector line
        draw.line([(cx, cy), ((bbox[0] + bbox[2]) // 2, (bbox[1] + bbox[3]) // 2)],
                  fill=(0, 0, 0, 255), width=2)

    # title bar at bottom (moved into image so it never gets clipped)
    title = "IRIS — Annotated Physical Layout (500 µm × 500 µm, GF180MCU)"
    tb = draw.textbbox((0, 0), title, font=font_lg)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    bx0 = (W - tw) // 2
    by0 = int(H * 0.005)
    draw.rectangle([bx0 - 14, by0 - 6, bx0 + tw + 14, by0 + th + 12], fill=(0, 0, 0, 220))
    draw.text((bx0, by0), title, font=font_lg, fill=(255, 255, 255, 255))

    out = LAYOUT / "iris_layout_annotated.png"
    im.save(out, "PNG")
    print("wrote", out)


if __name__ == "__main__":
    make_architecture()
    make_matching()
    make_bias()
    make_rectifier()
    make_pump()
    annotate_layout()
