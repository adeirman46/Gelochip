"""
Generate architecture_overview.pdf — PixelatedRF pipeline explanation.
Run: python generate_architecture_pdf.py
"""
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.patheffects as pe
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

OUT = Path(__file__).parent / 'architecture_overview.pdf'

# ── Colour palette ─────────────────────────────────────────────────────────────
C_FWD   = '#2E86AB'   # forward: steel blue
C_INV   = '#E84855'   # inverse: red
C_TANDEM= '#3BB273'   # tandem: green
C_CVAE  = '#F18F01'   # cVAE decoder: orange
C_DATA  = '#6C757D'   # data: grey
C_LIGHT = '#F0F4F8'   # light background
C_DARK  = '#1A1A2E'   # dark text
C_SE    = '#9B5DE5'   # SE block: purple
C_MS    = '#00BBF9'   # multi-scale: cyan


# ── Helper drawing functions ───────────────────────────────────────────────────

def rbox(ax, cx, cy, w, h, label, fc='#4A90D9', tc='white', fs=9,
         ec=None, lw=1.5, alpha=1.0, bold=True):
    ec = ec or fc
    p = FancyBboxPatch((cx - w/2, cy - h/2), w, h,
                       boxstyle='round,pad=0.04',
                       facecolor=fc, edgecolor=ec, linewidth=lw, alpha=alpha)
    ax.add_patch(p)
    ax.text(cx, cy, label, ha='center', va='center', fontsize=fs,
            color=tc, fontweight='bold' if bold else 'normal',
            wrap=True, multialignment='center')

def arrow(ax, x1, y1, x2, y2, c='#444444', lw=1.5, label='', fs=7):
    ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle='->', color=c, lw=lw,
                                mutation_scale=12))
    if label:
        mx, my = (x1+x2)/2, (y1+y2)/2
        ax.text(mx+0.02, my, label, fontsize=fs, color=c, va='center')

def title_page(fig):
    ax = fig.add_subplot(111)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis('off')
    fig.patch.set_facecolor(C_DARK)

    ax.text(0.5, 0.82, 'PixelatedRF', ha='center', va='center',
            fontsize=42, color='white', fontweight='bold')
    ax.text(0.5, 0.73, 'Architecture Deep Dive', ha='center', va='center',
            fontsize=24, color='#A8DADC')
    ax.text(0.5, 0.64, 'Forward Surrogate  ·  Inverse MCL Transformer  ·  Tandem Training',
            ha='center', va='center', fontsize=14, color='#CCC')

    ax.axhline(0.60, xmin=0.15, xmax=0.85, color='#A8DADC', lw=1.5)

    bullets = [
        (C_FWD,   'Phase A — Forward Surrogate',
                   'Layout (12×12) → CNN → S₁₁ at 81 frequencies'),
        (C_INV,   'Phase B — Inverse MCL Transformer',
                   'Target S₁₁ → K parallel heads → best-of-K layout'),
        (C_TANDEM,'Tandem Loss',
                   'Frozen Forward guides the Inverse during training'),
    ]
    for i, (c, title, sub) in enumerate(bullets):
        y = 0.50 - i * 0.12
        rect = FancyBboxPatch((0.12, y-0.04), 0.76, 0.09,
                              boxstyle='round,pad=0.02',
                              facecolor=c, edgecolor='none', alpha=0.25)
        ax.add_patch(rect)
        ax.plot([0.14, 0.14], [y-0.02, y+0.02], color=c, lw=4)
        ax.text(0.17, y+0.01, title, fontsize=12, color='white', fontweight='bold', va='center')
        ax.text(0.17, y-0.02, sub,   fontsize=9,  color='#BBB',  va='center')

    ax.text(0.5, 0.06, 'gelochip · PixelatedRF pipeline · v3',
            ha='center', fontsize=9, color='#666')


def page_overview(fig):
    ax = fig.add_subplot(111)
    ax.set_xlim(0, 10); ax.set_ylim(0, 7); ax.axis('off')
    ax.set_facecolor(C_LIGHT)

    ax.text(5, 6.6, 'Pipeline Overview', ha='center', fontsize=18,
            fontweight='bold', color=C_DARK)
    ax.text(5, 6.25, 'Two-phase tandem training — forward trained first, inverse trained second.',
            ha='center', fontsize=10, color='#555')

    # ── Phase A row ────────────────────────────────────────────────────────────
    ax.text(0.3, 5.6, 'PHASE A', fontsize=9, fontweight='bold', color=C_FWD)
    # Boxes
    rbox(ax, 1.2, 5.0, 1.4, 0.7, 'Layout\n(12×12 binary)', fc=C_DATA, fs=8)
    rbox(ax, 3.2, 5.0, 1.8, 0.7, 'Forward\nSurrogate\n(CNN v3)', fc=C_FWD, fs=8)
    rbox(ax, 5.5, 5.0, 1.6, 0.7, 'Predicted S₁₁\n(81 freq, dB)', fc=C_DATA, fs=8)
    rbox(ax, 7.5, 5.0, 1.6, 0.7, 'Ground-truth\nS₁₁ (dataset)', fc=C_DATA, fs=8)
    rbox(ax, 9.2, 5.0, 1.3, 0.7, 'MSE Loss\n(shape-aware)', fc='#E07B39', fs=8)
    # Arrows
    arrow(ax, 1.95, 5.0, 2.3, 5.0, C_FWD)
    arrow(ax, 4.1,  5.0, 4.7, 5.0, C_FWD)
    arrow(ax, 6.3,  5.0, 6.7, 5.0, c='#888')
    arrow(ax, 8.3,  5.0, 8.55, 5.0, c='#888')
    ax.text(5, 4.35, '✓ Forward model saved & FROZEN after Phase A',
            ha='center', fontsize=9, color=C_FWD,
            bbox=dict(fc='#EAF4FB', ec=C_FWD, boxstyle='round,pad=0.3'))

    ax.axhline(4.1, xmin=0.02, xmax=0.98, color='#CCC', lw=1, ls='--')

    # ── Phase B row ────────────────────────────────────────────────────────────
    ax.text(0.3, 3.9, 'PHASE B', fontsize=9, fontweight='bold', color=C_INV)
    rbox(ax, 1.2, 3.2, 1.6, 0.7, 'Target S₁₁\n(from dataset)', fc=C_DATA, fs=8)
    rbox(ax, 3.2, 3.2, 1.8, 0.7, 'Inverse MCL\n(K=8 heads)', fc=C_INV, fs=8)
    rbox(ax, 5.5, 3.2, 1.6, 0.7, 'Generated\nLayout (soft)', fc=C_CVAE, fs=8)
    rbox(ax, 7.5, 3.2, 1.8, 0.7, '▶ Frozen\nForward', fc=C_FWD, fs=8, alpha=0.6)
    rbox(ax, 9.2, 3.2, 1.3, 0.7, 'Tandem\nLoss', fc=C_TANDEM, fs=8)
    # Arrows
    arrow(ax, 2.0,  3.2, 2.3,  3.2, C_INV)
    arrow(ax, 4.1,  3.2, 4.7,  3.2, C_INV)
    arrow(ax, 6.3,  3.2, 6.6,  3.2, c=C_CVAE)
    arrow(ax, 8.4,  3.2, 8.55, 3.2, c=C_TANDEM)
    # Also feed target back for tandem comparison
    ax.annotate('', xy=(9.2, 2.82), xytext=(1.2, 2.82),
                arrowprops=dict(arrowstyle='->', color='#888', lw=1, linestyle='dotted', mutation_scale=12))
    ax.text(5, 2.72, 'Target S₁₁ also compared in tandem loss',
            ha='center', fontsize=7.5, color='#888', style='italic')

    ax.axhline(2.4, xmin=0.02, xmax=0.98, color='#CCC', lw=1, ls='--')

    # ── Inference row ──────────────────────────────────────────────────────────
    ax.text(0.3, 2.2, 'INFERENCE', fontsize=9, fontweight='bold', color=C_TANDEM)
    rbox(ax, 1.5, 1.5, 1.8, 0.7, 'Design spec\n(target S₁₁)', fc=C_DATA, fs=8)
    rbox(ax, 3.8, 1.5, 1.8, 0.7, 'Inverse MCL\n(K=8 heads)', fc=C_INV, fs=8)
    rbox(ax, 6.0, 1.5, 1.6, 0.7, 'Binary Layout\n(binarized)', fc=C_CVAE, fs=8)
    rbox(ax, 8.2, 1.5, 1.6, 0.7, 'GDS / Tape-out', fc='#555', fs=8)
    arrow(ax, 2.4, 1.5, 2.9, 1.5, C_INV)
    arrow(ax, 4.7, 1.5, 5.2, 1.5, C_INV)
    arrow(ax, 6.8, 1.5, 7.4, 1.5, c='#555')

    ax.text(5, 0.5,
            'Key insight: the Inverse does NOT improve the Forward.\n'
            'The Forward is used as a differentiable simulator to train the Inverse.',
            ha='center', fontsize=9, color='#333',
            bbox=dict(fc='#FFF3CD', ec='#F0A500', boxstyle='round,pad=0.4'))


def page_forward(fig):
    ax = fig.add_subplot(111)
    ax.set_xlim(0, 10); ax.set_ylim(0, 9); ax.axis('off')
    ax.set_facecolor(C_LIGHT)

    ax.text(5, 8.65, 'Forward Surrogate  —  Architecture v3', ha='center',
            fontsize=17, fontweight='bold', color=C_FWD)
    ax.text(5, 8.3, 'CoordConv  +  SE-ResNet  +  Multi-scale Aggregation  →  S₁₁',
            ha='center', fontsize=10, color='#555')

    # ── Left: architecture diagram ─────────────────────────────────────────────
    col = 2.0
    y = 7.7
    dy = 0.9

    def fbox(label, fc, y_val, sub='', width=3.2):
        rbox(ax, col, y_val, width, 0.60, label, fc=fc, fs=8.5)
        if sub:
            ax.text(col, y_val - 0.38, sub, ha='center', fontsize=7,
                    color='#666', style='italic')

    # Input
    rbox(ax, col, y, 3.2, 0.6, 'Input: 12×12 binary layout', fc=C_DATA, fs=8.5)
    arrow(ax, col, y - 0.3, col, y - dy + 0.3, C_FWD)
    y -= dy

    # CoordConv
    fbox('CoordConv', '#9B59B6', y, 'Adds row & col coords → 3 input channels')
    ax.text(col + 1.8, y, '(1ch→3ch)', fontsize=7.5, color='#9B59B6', va='center')
    arrow(ax, col, y - 0.3, col, y - dy + 0.3, C_FWD)
    y -= dy

    # Stage 1
    fbox('Stage 1  –  SE-ResBlock × 2', C_SE, y, '12×12 spatial  |  32 channels')
    arrow(ax, col, y - 0.3, col, y - dy + 0.3, C_FWD)
    y -= dy

    # Downsample + Stage 2
    fbox('Stride-2 Conv  →  Stage 2  –  SE-ResBlock × 2', C_FWD, y, '6×6 spatial  |  64 channels')
    arrow(ax, col, y - 0.3, col, y - dy + 0.3, C_FWD)
    y -= dy

    # Downsample + Stage 3
    fbox('Stride-2 Conv  →  Stage 3  –  SE-ResBlock × 2', C_FWD, y, '3×3 spatial  |  128 channels')
    arrow(ax, col, y - 0.3, col, y - dy + 0.3, C_FWD)
    y -= dy

    # Multi-scale
    rbox(ax, col, y, 3.2, 0.7,
         'Multi-scale Aggregation\nGAP(f1,32) + GAP(f2,64) + flatten(f3,1152) → 1248',
         fc=C_MS, fs=8)
    arrow(ax, col, y - 0.35, col, y - dy + 0.3, C_FWD)
    y -= dy

    # MLP head
    fbox('MLP Head  –  Linear(1248→512) + 4×ResBlock1D', C_FWD, y, 'dropout=0.25  LayerNorm  GELU')
    arrow(ax, col, y - 0.3, col, y - dy + 0.3, C_FWD)
    y -= dy * 0.8

    # Output
    rbox(ax, col, y, 3.2, 0.6, 'Output: S₁₁ at 81 frequencies (dB)', fc=C_DATA, fs=8.5)

    # ── Right: technique explanations ─────────────────────────────────────────
    rx = 6.5
    techniques = [
        (C_SE, 'SE Block (Squeeze-and-Excitation)',
         'After each ResBlock, learns WHICH channels\nmatter for this specific layout.\n'
         'E.g. "this layout has a 5 GHz resonance →\namplify channels encoding that pattern."'),
        ('#9B59B6', 'CoordConv',
         'Adds row/col coordinate channels [-1,+1].\nA pixel at (0,0) vs (6,6) has completely\n'
         'different EM coupling to the feed point.\nPlain CNN cannot distinguish position.'),
        (C_MS, 'Multi-scale Aggregation',
         'f1 (12×12) → global antenna topology\nf2 (6×6) → mid-scale resonance context\n'
         'f3 (3×3) → fine spatial resonance detail\nAll 3 concatenated: 1248-dim vector.'),
        ('#E07B39', 'Shape-aware Loss',
         'Deep dips get 3× weight (vs flat MSE).\nGradient matching enforces correct\n'
         'resonance edge slopes → sharper dips.\nResult: val MSE dropped 0.23 → 0.10.'),
    ]
    for i, (c, title, desc) in enumerate(techniques):
        ty = 7.6 - i * 1.85
        rect = FancyBboxPatch((rx - 0.1, ty - 1.2), 3.5, 1.55,
                              boxstyle='round,pad=0.08',
                              facecolor=c, edgecolor='none', alpha=0.12)
        ax.add_patch(rect)
        ax.plot([rx - 0.05, rx - 0.05], [ty - 1.05, ty + 0.2],
                color=c, lw=3)
        ax.text(rx + 0.15, ty + 0.1, title, fontsize=9, color=C_DARK,
                fontweight='bold', va='top')
        ax.text(rx + 0.15, ty - 0.15, desc, fontsize=7.8, color='#444',
                va='top', linespacing=1.4)

    # Param count box
    rbox(ax, col, 0.45, 3.2, 0.55,
         '~5M parameters  |  val MSE 0.10  |  GroupNorm throughout',
         fc='#2C3E50', fs=8)


def se_block_detail(ax, cx, cy, label='SE Block'):
    """Draw a small SE block diagram."""
    w, h = 2.2, 1.4
    rbox(ax, cx, cy, w, h, '', fc='#F8F0FF', ec=C_SE, lw=1.5, tc='white')
    ax.text(cx, cy + 0.5, label, ha='center', fontsize=7.5,
            color=C_SE, fontweight='bold')
    # internal
    rbox(ax, cx - 0.55, cy - 0.05, 0.7, 0.4, 'GAP', fc=C_SE, fs=7, tc='white')
    rbox(ax, cx,        cy - 0.05, 0.7, 0.4, 'FC\nGELU', fc=C_SE, fs=7, tc='white')
    rbox(ax, cx + 0.55, cy - 0.05, 0.7, 0.4, 'FC\nσ', fc=C_SE, fs=7, tc='white')
    arrow(ax, cx - 0.2, cy - 0.05, cx - 0.35, cy - 0.05, C_SE, lw=1)
    arrow(ax, cx + 0.35, cy - 0.05, cx + 0.2, cy - 0.05, C_SE, lw=1)
    ax.text(cx, cy - 0.52, '× (scale channels)', ha='center', fontsize=6.5, color='#666')


def page_inverse(fig):
    ax = fig.add_subplot(111)
    ax.set_xlim(0, 10); ax.set_ylim(0, 9); ax.axis('off')
    ax.set_facecolor(C_LIGHT)

    ax.text(5, 8.65, 'Inverse Design  —  Multi-Choice Learning (K=8 heads)', ha='center',
            fontsize=17, fontweight='bold', color=C_INV)
    ax.text(5, 8.3,
            'K parallel decoder heads solve the ONE-TO-MANY inverse problem (no latent z)',
            ha='center', fontsize=10, color='#555')

    # ── Training diagram (best-of-K tandem) ─────────────────────────────────────
    ax.text(0.4, 7.85, 'TRAINING  (best-of-K tandem)', fontsize=10, fontweight='bold', color=C_INV)
    ax.text(0.4, 7.55,
            'Target S₁₁ → K candidate layouts → frozen Forward → only the BEST head\n'
            'is penalised (best-of-K), so each head specialises on a different solution.',
            fontsize=8.5, color='#444')

    rbox(ax, 1.1, 6.1, 1.5, 0.65, 'Target S₁₁\n(81)', fc=C_DATA, fs=8)
    rbox(ax, 3.0, 6.1, 1.6, 0.65, 'S₁₁ encoder\n(1D CNN)', fc='#8E44AD', fs=8)
    arrow(ax, 2.65, 6.42, 2.95, 6.42, '#8E44AD', lw=1.2)
    rbox(ax, 5.0, 6.1, 1.5, 0.65, 'shared trunk\n(ResMLP×3)', fc=C_INV, fs=8)
    arrow(ax, 4.65, 6.42, 4.95, 6.42, C_INV, lw=1.2)
    rbox(ax, 6.9, 6.1, 1.5, 0.65, 'K=8 heads\n(parallel)', fc=C_CVAE, fs=8)
    arrow(ax, 6.55, 6.42, 6.85, 6.42, C_CVAE, lw=1.2)
    rbox(ax, 8.8, 6.1, 1.1, 0.65, 'K layouts', fc=C_DATA, fs=8)
    arrow(ax, 8.45, 6.42, 8.75, 6.42, C_CVAE, lw=1.2)
    rbox(ax, 6.9, 5.0, 1.5, 0.55, 'frozen Forward\n(surrogate)', fc=C_FWD, fs=8)
    arrow(ax, 9.3, 6.1, 8.4, 5.55, C_FWD, lw=1.2)
    rbox(ax, 4.6, 5.0, 1.7, 0.55, 'best-of-K\ntandem loss', fc=C_TANDEM, fs=8)
    arrow(ax, 6.85, 5.27, 6.35, 5.27, C_TANDEM, lw=1.2)

    ax.axhline(4.6, xmin=0.03, xmax=0.97, color='#CCC', lw=1, ls='--')

    # ── Inference diagram (best-of-K) ──────────────────────────────────────────
    ax.text(0.4, 4.35, 'INFERENCE  (best-of-K)', fontsize=10, fontweight='bold', color=C_CVAE)
    ax.text(0.4, 4.05,
            'One forward pass yields all K candidate layouts; pick the one whose\n'
            'surrogate S₁₁ best matches the target. Deterministic — no sampling.',
            fontsize=8.5, color='#444')

    rbox(ax, 1.2, 3.0, 1.5, 0.65, 'Target S₁₁\n(spec)', fc=C_DATA, fs=8)
    rbox(ax, 3.1, 3.0, 1.7, 0.65, 'trunk + K heads', fc=C_CVAE, fs=8)
    arrow(ax, 2.75, 3.32, 3.05, 3.32, C_CVAE, lw=1.2)
    rbox(ax, 5.3, 3.0, 1.6, 0.65, 'K binary\nlayouts', fc=C_DATA, fs=8)
    arrow(ax, 4.85, 3.32, 5.25, 3.32, C_CVAE, lw=1.2)
    rbox(ax, 7.4, 3.0, 1.5, 0.65, 'Forward →\npick best', fc=C_FWD, fs=8)
    arrow(ax, 6.95, 3.32, 7.35, 3.32, C_FWD, lw=1.2)
    rbox(ax, 9.3, 3.0, 1.0, 0.65, 'Best\nlayout', fc=C_TANDEM, fs=8)
    arrow(ax, 8.95, 3.32, 9.25, 3.32, C_FWD, lw=1.2)

    ax.axhline(2.4, xmin=0.03, xmax=0.97, color='#CCC', lw=1, ls='--')

    # ── Why MCL (not VAE) ──────────────────────────────────────────────────────
    ax.text(5.0, 2.1, 'Why MCL (not a VAE / plain network)?', ha='center',
            fontsize=10, fontweight='bold', color=C_INV)
    choices = [
        ('One-to-many problem',
         'Many layouts produce the same S₁₁ curve.\n'
         'A deterministic net averages them → blurry grey pixels.\n'
         'K competing heads each lock onto a distinct crisp solution.'),
        ('Best-of-K = the metric',
         'Loss penalises only the best head, exactly matching the\n'
         'best-of-K eval metric. No latent z, no posterior collapse,\n'
         'no KL tuning — just K specialised decoders.'),
    ]
    for i, (title, desc) in enumerate(choices):
        x = 0.7 + i * 4.8
        ax.add_patch(FancyBboxPatch((x - 0.2, 0.2), 4.1, 1.45, boxstyle='round,pad=0.1',
                                    facecolor=C_INV, edgecolor='none', alpha=0.1))
        ax.text(x + 1.85, 1.5, title, ha='center', fontsize=9, color=C_INV, fontweight='bold')
        ax.text(x + 0.0, 1.2, desc, fontsize=7.8, color='#333', va='top', linespacing=1.4)


def page_tandem(fig):
    ax = fig.add_subplot(111)
    ax.set_xlim(0, 10); ax.set_ylim(0, 9); ax.axis('off')
    ax.set_facecolor(C_LIGHT)

    ax.text(5, 8.65, 'Tandem Training  —  How the 3 Networks Interact',
            ha='center', fontsize=17, fontweight='bold', color=C_TANDEM)

    # ── Tandem diagram ────────────────────────────────────────────────────────
    ax.text(0.5, 8.1, 'The fundamental problem: inverse design has no direct loss signal.',
            fontsize=9.5, color='#333')
    ax.text(0.5, 7.78,
            'We cannot directly compute "how wrong" a layout is — we need to simulate it first.\n'
            'The forward surrogate acts as a fast differentiable simulator for training the inverse.',
            fontsize=8.5, color='#555')

    # Training batch input
    rbox(ax, 1.1, 6.6, 1.5, 0.6, 'Dataset\nbatch', fc=C_DATA, fs=8)
    ax.text(0.55, 6.1, '(layout, S₁₁)\npairs', fontsize=7.5, color='#777',
            ha='center')

    # Split arrows
    arrow(ax, 1.85, 6.75, 2.8, 7.1, C_INV,    lw=1.5)  # layout → encoder
    arrow(ax, 1.85, 6.6,  2.8, 6.6, C_INV,    lw=1.5)  # S11 → decoder/encoder
    arrow(ax, 1.85, 6.45, 2.8, 6.1, C_TANDEM, lw=1.5)  # target for loss

    # Encoder
    rbox(ax, 3.5, 7.1, 1.2, 0.55, 'Encoder\n(trainable)', fc=C_INV, fs=8)
    arrow(ax, 4.1, 7.1, 4.7, 6.8, C_INV, lw=1.5)
    ax.text(4.4, 7.05, 'μ,σ', fontsize=7.5, color=C_INV)

    # Reparameterize + z
    rbox(ax, 5.1, 6.6, 1.1, 0.55, 'z = μ+σε', fc='#8E44AD', fs=8)
    arrow(ax, 4.1, 6.6, 4.55, 6.6, C_INV, lw=1.5)

    # Decoder
    rbox(ax, 6.5, 6.6, 1.3, 0.55, 'Decoder\n(trainable)', fc=C_CVAE, fs=8)
    arrow(ax, 5.65, 6.6, 5.85, 6.6, C_CVAE, lw=1.5)

    # Generated layout
    rbox(ax, 8.0, 6.6, 1.2, 0.55, 'Generated\nlayout (soft)', fc='#BDC3C7', fs=8)
    arrow(ax, 7.15, 6.6, 7.4, 6.6, c='#888', lw=1.5)

    # Frozen forward
    rbox(ax, 8.0, 5.5, 1.5, 0.65, '❄ Frozen\nForward Net', fc=C_FWD, fs=8.5, alpha=0.7)
    arrow(ax, 8.0, 6.32, 8.0, 5.83, c=C_FWD, lw=1.5)
    ax.text(8.45, 5.9, '(no grad\nupdates)', fontsize=7, color=C_FWD, style='italic')

    # Predicted S11
    rbox(ax, 6.3, 5.5, 1.2, 0.55, 'Predicted\nS₁₁', fc=C_DATA, fs=8)
    arrow(ax, 7.25, 5.5, 6.9, 5.5, c=C_TANDEM, lw=1.5)

    # Target S11 (for tandem loss)
    rbox(ax, 4.5, 5.5, 1.2, 0.55, 'Target\nS₁₁', fc=C_DATA, fs=8)
    ax.annotate('', xy=(4.5, 5.83), xytext=(2.8, 6.1),
                arrowprops=dict(arrowstyle='->', color=C_TANDEM, lw=1.2, linestyle='--', mutation_scale=12))

    # Loss components
    rbox(ax, 2.5, 5.5, 1.5, 0.65, 'Tandem\nMSE Loss', fc=C_TANDEM, fs=8)
    arrow(ax, 5.1, 5.5, 4.25, 5.5, C_TANDEM, lw=1.5)
    arrow(ax, 3.85, 5.5, 3.25, 5.5, C_TANDEM, lw=1.2)

    # Backprop
    ax.annotate('', xy=(6.5, 6.32), xytext=(2.5, 5.17),
                arrowprops=dict(arrowstyle='<-', color=C_INV, lw=2,
                                connectionstyle='arc3,rad=0.35'))
    ax.text(4.0, 4.75, 'Backprop through Decoder & Encoder  (NOT through Forward)',
            fontsize=8.5, color=C_INV, ha='center', fontweight='bold')

    ax.axhline(4.35, xmin=0.03, xmax=0.97, color='#CCC', lw=1, ls='--')

    # ── Loss breakdown ────────────────────────────────────────────────────────
    ax.text(5, 4.1, 'Training Loss Breakdown  (Phase B)', ha='center',
            fontsize=12, fontweight='bold', color=C_DARK)

    loss_terms = [
        (C_INV,    'BCE × 0.1',
                   'Layout reconstruction\n(weak — allows the decoder\nto generate different valid\nlayouts, not just the gt one)'),
        ('#8E44AD', 'KL × β(cyclical)',
                   'Latent space regularization\n(cyclical β: 0→0.5 per 20ep\nprevents posterior collapse;\nencoder stays engaged)'),
        (C_TANDEM, 'Shape-aware × 3.0',
                   'EM performance matching\n(MAIN objective — upweights\ndeep resonance dips + enforces\ncorrect resonance slopes)'),
    ]
    for i, (c, term, desc) in enumerate(loss_terms):
        x = 1.3 + i * 3.1
        rect = FancyBboxPatch((x - 0.1, 0.3), 2.8, 3.5,
                              boxstyle='round,pad=0.1',
                              facecolor=c, edgecolor='none', alpha=0.12)
        ax.add_patch(rect)
        ax.plot([x - 0.05, x + 2.75], [3.55, 3.55], color=c, lw=2)
        ax.text(x + 1.35, 3.7, term, ha='center', fontsize=11,
                color=c, fontweight='bold')
        ax.text(x + 0.05, 3.35, desc, fontsize=8, color='#333',
                va='top', linespacing=1.5)


def page_correlation(fig):
    ax = fig.add_subplot(111)
    ax.set_xlim(0, 10); ax.set_ylim(0, 9); ax.axis('off')
    ax.set_facecolor(C_LIGHT)

    ax.text(5, 8.65, 'Key Question: How Do the 3 Networks Relate?',
            ha='center', fontsize=17, fontweight='bold', color=C_DARK)

    # ── Big answer ────────────────────────────────────────────────────────────
    rect = FancyBboxPatch((0.5, 7.7), 9.0, 0.75,
                          boxstyle='round,pad=0.1',
                          facecolor='#FFF3CD', edgecolor='#F0A500', lw=2)
    ax.add_patch(rect)
    ax.text(5, 8.07,
            '⚠  The Inverse does NOT improve the Forward.  '
            'The Forward is FIXED after Phase A.',
            ha='center', fontsize=11, color='#7D4800', fontweight='bold')

    # ── Dependency diagram ────────────────────────────────────────────────────
    ax.text(5, 7.35, 'Dependency & Data Flow', ha='center', fontsize=12,
            fontweight='bold', color=C_DARK)

    # Forward
    rect = FancyBboxPatch((0.3, 6.1), 2.8, 0.9, boxstyle='round,pad=0.1',
                          facecolor=C_FWD, edgecolor='none', alpha=0.2)
    ax.add_patch(rect)
    ax.text(1.7, 6.7, 'Forward Surrogate', ha='center', fontsize=10,
            color=C_FWD, fontweight='bold')
    ax.text(1.7, 6.35, 'Trained on (layout → S₁₁)\nindependently of inverse',
            ha='center', fontsize=8, color='#444')

    # Frozen arrow
    ax.annotate('', xy=(4.3, 6.55), xytext=(3.1, 6.55),
                arrowprops=dict(arrowstyle='->', color=C_FWD, lw=2))
    ax.text(3.7, 6.7, 'frozen &\nprovides\ngradients', ha='center',
            fontsize=7.5, color=C_FWD, style='italic')

    # Inverse
    rect = FancyBboxPatch((4.3, 6.1), 2.8, 0.9, boxstyle='round,pad=0.1',
                          facecolor=C_INV, edgecolor='none', alpha=0.2)
    ax.add_patch(rect)
    ax.text(5.7, 6.7, 'Inverse MCL', ha='center', fontsize=10,
            color=C_INV, fontweight='bold')
    ax.text(5.7, 6.35, 'Uses frozen Forward as\ndifferentiable simulator',
            ha='center', fontsize=8, color='#444')

    # System
    ax.annotate('', xy=(8.0, 6.55), xytext=(7.1, 6.55),
                arrowprops=dict(arrowstyle='->', color=C_TANDEM, lw=2))
    rect = FancyBboxPatch((8.0, 6.1), 1.7, 0.9, boxstyle='round,pad=0.1',
                          facecolor=C_TANDEM, edgecolor='none', alpha=0.2)
    ax.add_patch(rect)
    ax.text(8.85, 6.65, 'Design\nSystem', ha='center', fontsize=9,
            color=C_TANDEM, fontweight='bold')
    ax.text(8.85, 6.25, '(together)', ha='center', fontsize=7.5, color='#555')

    ax.axhline(5.85, xmin=0.03, xmax=0.97, color='#DDD', lw=1, ls='--')

    # ── Three questions ───────────────────────────────────────────────────────
    questions = [
        ('Does the Inverse make\nthe Forward BETTER?',
         'NO.',
         'The Forward is FROZEN during Phase B.\n'
         'Its weights never change.\n'
         'Only the Inverse (encoder + decoder)\nreceives gradient updates.',
         '#E74C3C'),
        ('Does the Forward make\nthe Inverse BETTER?',
         'YES — critically.',
         'The Inverse CANNOT be trained without\nthe Forward. There is no direct loss on\n'
         'a layout — you need to simulate it first.\n'
         'Better Forward → more accurate gradient signal → better Inverse.',
         '#27AE60'),
        ('Why not just skip\nthe Inverse?',
         'Speed.',
         'Forward alone tells you S₁₁ from layout.\n'
         'Inverse lets you DESIGN: give a target S₁₁,\n'
         'get a layout instantly — without running\n'
         'thousands of expensive EM simulations.',
         '#2980B9'),
    ]

    for i, (q, ans, exp, c) in enumerate(questions):
        x = 0.4 + i * 3.25
        rect = FancyBboxPatch((x, 0.4), 3.0, 5.1,
                              boxstyle='round,pad=0.12',
                              facecolor=c, edgecolor='none', alpha=0.08)
        ax.add_patch(rect)
        ax.plot([x + 0.05, x + 2.95], [5.25, 5.25], color=c, lw=2)
        ax.text(x + 1.5, 5.42, q, ha='center', fontsize=9, color=C_DARK,
                fontweight='bold', va='center')
        ax.text(x + 1.5, 4.85, ans, ha='center', fontsize=16,
                color=c, fontweight='bold')
        ax.text(x + 0.12, 4.5, exp, fontsize=8.2, color='#333',
                va='top', linespacing=1.5)

    # ── Training order summary ─────────────────────────────────────────────────
    ax.text(5, 0.2, 'Training order is strictly sequential:  '
            'Phase A (Forward, ~2.5h)  →  Phase B (Inverse, ~1.5h)  →  Inference',
            ha='center', fontsize=8.5, color='#555',
            bbox=dict(fc='white', ec='#CCC', boxstyle='round,pad=0.3'))


# ── Build PDF ──────────────────────────────────────────────────────────────────
with PdfPages(OUT) as pdf:
    pages = [
        (title_page,    'Title'),
        (page_overview, 'Overview'),
        (page_forward,  'Forward Surrogate'),
        (page_inverse,  'Inverse MCL'),
        (page_tandem,   'Tandem Training'),
        (page_correlation, 'Correlation'),
    ]
    for fn, name in pages:
        is_title = (name == 'Title')
        fig = plt.figure(figsize=(14, 10), facecolor=C_DARK if is_title else C_LIGHT)
        fn(fig)
        pdf.savefig(fig, bbox_inches='tight', facecolor=fig.get_facecolor())
        plt.close(fig)
        print(f'  Page: {name}')

    d = pdf.infodict()
    d['Title']   = 'PixelatedRF Architecture Overview'
    d['Author']  = 'Gelochip'
    d['Subject'] = 'Forward Surrogate + Inverse MCL Transformer + Tandem Training'

print(f'\nSaved → {OUT}')
