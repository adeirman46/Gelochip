"""
Generate notebooks/kaizen_architecture/architecture.pdf — the Kaizen RAG system.

A 2-page block diagram (overview + agent loop). Run:
    .venv/bin/python scripts/generate_kaizen_pdf.py
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

OUT = Path(__file__).resolve().parents[1] / "notebooks" / "kaizen_architecture" / "architecture.pdf"

DARK = "#0d1117"; ACC = "#6ea8fe"; ACC2 = "#a78bfa"
OK = "#3fb950"; WARN = "#d29922"; FAIL = "#f85149"; CARD = "#1c2230"


def box(ax, x, y, w, h, label, fc=CARD, tc="#e6edf3", fs=9, ec=ACC):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.06",
                                fc=fc, ec=ec, lw=1.4))
    ax.text(x + w / 2, y + h / 2, label, ha="center", va="center", color=tc,
            fontsize=fs, fontweight="bold", zorder=5)


def arrow(ax, x1, y1, x2, y2, c="#8b97a7", lw=1.6, label="", fs=7):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=14,
                                 color=c, lw=lw, shrinkA=2, shrinkB=2, zorder=4))
    if label:
        ax.text((x1 + x2) / 2, (y1 + y2) / 2 + 0.12, label, ha="center", color=c, fontsize=fs)


def _ax(fig):
    ax = fig.add_subplot(111); ax.set_xlim(0, 10); ax.set_ylim(0, 10)
    ax.axis("off"); fig.patch.set_facecolor(DARK); ax.set_facecolor(DARK)
    return ax


def container(ax, x, y, w, h, title, ec):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.06",
                                fc="#11161f", ec=ec, lw=1.6))
    ax.text(x + 0.2, y + h - 0.22, title, ha="left", va="center", color=ec,
            fontsize=10, fontweight="bold", zorder=5)


def page_overview(fig):
    ax = _ax(fig)
    ax.text(5, 9.5, "Gelochip Kaizen", ha="center", color=ACC, fontsize=20, fontweight="bold")
    ax.text(5, 9.05, "Self-correcting RAG agent for gf180 RF/mmWave chip generation",
            ha="center", color=ACC2, fontsize=11)

    # Web layer ----------------------------------------------------------------
    container(ax, 0.6, 7.45, 8.8, 1.25, "Gelochip Studio  ·  FastAPI + SSE web UI", ACC2)
    for i, t in enumerate(["Prompt→GDSII", "IP Library\n(drag-drop)", "Padframe", "Pin-Connect\nagent"]):
        box(ax, 0.85 + i * 2.15, 7.55, 1.95, 0.6, t, fc=CARD, ec=ACC2, fs=8)
    arrow(ax, 5, 7.45, 5, 6.95)

    # Agent --------------------------------------------------------------------
    container(ax, 0.6, 4.95, 8.8, 2.0, "Kaizen LangGraph agent  ·  LLM: qwen3.5:9b (Ollama)", ACC)
    steps = ["plan", "research\n→temp RAG", "retrieve", "generate", "test\nDRC+TB",
             "critic", "persist", "summarize"]
    for i, s in enumerate(steps):
        bx = 0.78 + i * 1.07
        box(ax, bx, 5.75, 0.98, 0.62, s, fc=CARD, ec=ACC, fs=6.8)
        if i:
            arrow(ax, bx - 0.09, 6.06, bx, 6.06)
    ax.text(5, 5.25, "error_feedback  ◀──  critic   (fail → write lesson → regenerate)",
            ha="center", color=WARN, fontsize=8.5)

    arrow(ax, 2.6, 4.95, 2.6, 4.25, label="retrieve")
    arrow(ax, 7.0, 4.95, 7.0, 4.25, label="exec")

    # Knowledge + executor -----------------------------------------------------
    container(ax, 0.6, 2.3, 4.4, 1.95, "ChromaDB  ·  local all-MiniLM-L6-v2", OK)
    for i, (t, c) in enumerate([("1  glayout_knowledge", OK), ("2  rf_theory", OK),
                                ("3  error_feedback (empty→grows)", WARN)]):
        box(ax, 0.85, 3.35 - i * 0.5, 3.9, 0.42, t, fc=CARD, ec=c, fs=8)
    box(ax, 5.6, 2.3, 3.8, 1.95, "Executor → gf180\nMagic DRC + ngspice\nAC/transient vs theory\n→ GDS + plots",
        fc="#11161f", ec=ACC, fs=9.5)

    box(ax, 0.6, 0.7, 8.8, 1.0,
        "15 DRC-clean blocks in data/circuits/  ·  switch · follower · mirror · amplifier · 2-stage",
        fc=CARD, ec=OK, fs=9.5)
    arrow(ax, 5, 2.3, 5, 1.7)


def page_loop(fig):
    ax = _ax(fig)
    ax.text(5, 9.4, "The Kaizen self-correction loop", ha="center", color=ACC, fontsize=16,
            fontweight="bold")
    ax.text(5, 8.9, "1 % better every run — corrections injected as in-context feedback, not gradients",
            ha="center", color=ACC2, fontsize=9)

    nodes = [("Prompt", 5, 7.9, ACC2), ("Plan + Retrieve\n(3 collections)", 5, 6.7, ACC),
             ("Generate\npure-glayout code", 5, 5.5, ACC), ("Test:\nbuild → Magic DRC", 5, 4.3, ACC),
             ("Critic\nDRC clean?", 5, 3.1, WARN)]
    for t, x, y, c in nodes:
        box(ax, x - 1.5, y - 0.45, 3.0, 0.9, t, fc=CARD, ec=c, fs=9)
    for i in range(len(nodes) - 1):
        arrow(ax, 5, nodes[i][2] - 0.45, 5, nodes[i + 1][2] + 0.45)

    box(ax, 5 - 1.5, 1.2, 3.0, 0.9, "Summarize + show GDS", fc=CARD, ec=OK, fs=9)
    arrow(ax, 3.5, 3.1, 1.3, 3.1, c=OK, label="pass")
    box(ax, 0.3, 1.2, 2.0, 1.4, "✓ DRC clean\n+ theory match\n→ IP library", fc=CARD, ec=OK, fs=8)
    arrow(ax, 1.3, 1.2, 4.0, 1.5, c=OK)

    box(ax, 7.2, 3.7, 2.4, 1.4, "error_feedback\nwrite lesson\n(error → fix)", fc=CARD, ec=FAIL, fs=8.5)
    arrow(ax, 6.5, 3.1, 7.2, 3.9, c=FAIL, label="fail")
    arrow(ax, 8.4, 5.1, 6.5, 5.5, c=FAIL, label="retrieved next run")


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(OUT) as pdf:
        for page in (page_overview, page_loop):
            fig = plt.figure(figsize=(11, 8.5))
            page(fig)
            pdf.savefig(fig, facecolor=DARK); plt.close(fig)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
