#!/usr/bin/env python3
"""Generate the AnoaChip RLM + Autoresearch system-design PDF.

Documents (1) the current Recursive-Language-Model agent design, (2) how it coordinates with the
Postgres(pgvector) + MinIO knowledge store, and (3) the 'autoresearch' upgrade — applying the
self-improving auto-kernel-generation idea (AutoKernel / KernelBench / Reflexion-style loops) to
RTL generation so the recursive agent gets smarter every run.

    uv run python scripts/make_design_pdf.py   ->  docs/AnoaChip_RLM_Autoresearch_Design.pdf
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "AnoaChip_RLM_Autoresearch_Design.pdf"

GOLD = "#c2872e"
GOLD_L = "#f3e2c0"
INK = "#1b2230"
BLUE = "#2f6fb0"
BLUE_L = "#dbe8f5"
GREEN = "#168a4c"
GREEN_L = "#d4ecdd"
RED = "#cf3b46"
GREY = "#6b6453"
GREY_L = "#ece8df"
PURPLE = "#7a4fb0"
PURPLE_L = "#e7ddf3"


def _fig():
    fig = plt.figure(figsize=(11.69, 8.27))  # A4 landscape
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
    ax.set_xlim(0, 100); ax.set_ylim(0, 100)
    return fig, ax


def box(ax, x, y, w, h, text, fc=GOLD_L, ec=GOLD, fs=9, bold=False, tc=INK, round=0.02):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0.2,rounding_size={round*100}",
                                fc=fc, ec=ec, lw=1.4, mutation_aspect=0.5))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs,
            color=tc, weight="bold" if bold else "normal", wrap=True)


def arrow(ax, x1, y1, x2, y2, color=GREY, lw=1.6, style="-|>"):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style, mutation_scale=14,
                                 color=color, lw=lw, shrinkA=2, shrinkB=2))


def header(ax, title, sub=""):
    ax.add_patch(FancyBboxPatch((0, 92), 100, 8, boxstyle="square,pad=0", fc=INK, ec="none"))
    ax.text(4, 96, title, ha="left", va="center", fontsize=16, color="white", weight="bold")
    if sub:
        ax.text(96, 96, sub, ha="right", va="center", fontsize=9, color=GOLD_L)
    ax.text(4, 2.2, "AnoaChip  ·  RLM + Autoresearch system design", ha="left", va="center",
            fontsize=7.5, color=GREY)


def bullets(ax, x, y, items, fs=8.6, dy=3.0, w=44, color=INK):
    for i, it in enumerate(items):
        ax.text(x, y - i * dy, "•", ha="left", va="top", fontsize=fs, color=GOLD, weight="bold")
        ax.text(x + 1.6, y - i * dy, it, ha="left", va="top", fontsize=fs, color=color, wrap=True)


# ── page 1 — cover ───────────────────────────────────────────────────────────
def cover(pdf):
    fig, ax = _fig()
    ax.add_patch(FancyBboxPatch((0, 0), 100, 100, boxstyle="square,pad=0", fc=INK, ec="none"))
    ax.text(50, 70, "AnoaChip", ha="center", fontsize=46, color="white", weight="bold")
    ax.text(50, 62, "Recursive-Language-Model agent  +  Autoresearch", ha="center", fontsize=17,
            color=GOLD)
    ax.text(50, 55, "self-improving prompt → RTL → GDSII, on a local model", ha="center",
            fontsize=12, color="#9fb0c4")
    for i, (t, c) in enumerate([("RLM deep agents", GOLD), ("pgvector + MinIO memory", BLUE),
                                ("autoresearch loop", GREEN)]):
        box(ax, 17 + i * 23, 38, 21, 7, t, fc="#222a38", ec=c, tc="white", fs=8.8, bold=True)
    ax.text(50, 26, "System Design Document", ha="center", fontsize=13, color="white", weight="bold")
    ax.text(50, 21, "current architecture · knowledge-store coordination · the autoresearch upgrade",
            ha="center", fontsize=9.5, color="#9fb0c4")
    ax.text(50, 9, "Local model only (Ollama qwen3.5)   ·   gf180 PDK   ·   LibreLane RTL→GDSII",
            ha="center", fontsize=8.5, color=GREY_L)
    pdf.savefig(fig); plt.close(fig)


# ── page 2 — current RLM pipeline + node anatomy ─────────────────────────────
def page_current(pdf):
    fig, ax = _fig()
    header(ax, "1 · Current RLM design — fixed graph, every node a deep agent", "as built today")
    ax.text(4, 88, "The orchestration is a FIXED pipeline graph; each LLM node is upgraded into a "
            "Recursive-Language-Model (RLM) deep agent (planning + on-disk tools + sub-LLM delegation).",
            fontsize=9.2, color=INK, wrap=True)
    stages = [("Plan", GOLD_L, GOLD), ("Generate", GOLD_L, GOLD), ("Decompose", GOLD_L, GOLD),
              ("Testbench", GOLD_L, GOLD), ("Write", GOLD_L, GOLD), ("Simulate", BLUE_L, BLUE),
              ("Lint", BLUE_L, BLUE), ("Harden→GDS", GREEN_L, GREEN)]
    x0, y0, w, h = 3.5, 70, 11, 7
    for i, (t, fc, ec) in enumerate(stages):
        bx = x0 + i * 12
        box(ax, bx, y0, w, h, t, fc=fc, ec=ec, fs=8.4, bold=True)
        if i < len(stages) - 1:
            arrow(ax, bx + w, y0 + h / 2, bx + 12, y0 + h / 2, color=GREY)
    arrow(ax, x0 + 5.5 * 12 + w / 2, y0, x0 + 4 * 12 + w / 2, y0 - 0.1, color=RED, style="-|>")
    ax.annotate("", xy=(x0 + 4 * 12 + w / 2, y0 - 4), xytext=(x0 + 5.5 * 12 + w / 2, y0 - 4),
                arrowprops=dict(arrowstyle="-|>", color=RED, lw=1.6))
    ax.text(x0 + 4.8 * 12, y0 - 6.2, "self-correct loop:  sim/lint fail → fix_design / fix_testbench → re-run",
            ha="center", fontsize=7.6, color=RED, style="italic")

    # node anatomy
    box(ax, 4, 40, 44, 18, "", fc="#fbfaf6", ec=GOLD, round=0.015)
    ax.text(26, 56, "Anatomy of ONE deep-agent node", ha="center", fontsize=10, color=INK, weight="bold")
    bullets(ax, 6, 53, [
        "write_todos — plan the multi-step work",
        "file tools — list / read_file_disk (SLICE) / grep_files /",
        "   write_file_disk (auto-repair + compile-check on write)",
        "llm_query — delegate ONE focused sub-task to a fresh LLM call",
        "task — spawn a heavier sub-agent",
        "run_python / pip_install — compute LUTs / NN weights (data-driven)",
    ], fs=8.0, dy=2.55)

    box(ax, 52, 40, 44, 18, "", fc="#fbfaf6", ec=BLUE, round=0.015)
    ax.text(74, 56, "RLM operating loop", ha="center", fontsize=10, color=INK, weight="bold")
    bullets(ax, 54, 53, [
        "PEEK, don't swallow — grep / read slices of big context",
        "DELEGATE — sub-LLM calls & sub-agents keep the window small",
        "BUILD UP in files — RTL lives on disk, not in the prompt",
        "VERIFY — compile-on-write + static audit + closure compile",
        "ANCHOR-AND-ADAPT — copy the closest GitHub module, edit to spec",
    ], fs=8.0, dy=2.55, color=INK)

    # deterministic gates strip
    box(ax, 4, 24, 92, 11, "", fc=GREY_L, ec=GREY, round=0.01)
    ax.text(50, 33, "Deterministic gates (verilog_check) — make a 9B local model reliable",
            ha="center", fontsize=9.5, color=INK, weight="bold")
    gates = ["compile-on-write\n(iverilog -g2012)", "static cross-module\naudit", "closure compile\n(top cone only)",
             "multi-file\nauto-fix", "error→fix lesson\ncapture"]
    for i, g in enumerate(gates):
        box(ax, 6 + i * 18, 25.5, 16, 5.5, g, fc="white", ec=GREY, fs=7.4)
    ax.text(50, 18, "Key property:  the model never holds the whole design at once — it peeks, delegates, "
            "and writes to disk, while deterministic checks catch errors at write-time, not 10 modules later.",
            ha="center", fontsize=8.6, color=INK, style="italic", wrap=True)
    ax.text(50, 13.5, "Local model only (Ollama qwen3.5) · deepagents framework · the graph orchestrates, "
            "each node's brain is an RLM.", ha="center", fontsize=8.2, color=GREY)
    pdf.savefig(fig); plt.close(fig)


# ── page 3 — knowledge-store coordination ────────────────────────────────────
def page_memory(pdf):
    fig, ax = _fig()
    header(ax, "2 · Knowledge-store coordination — Postgres(pgvector) + MinIO", "the RLM's long-term memory")
    ax.text(4, 88, "Everything the agent sees or makes is stored two ways: the RAW FILE as a blob in MinIO, "
            "and a queryable ROW (with its embedding vector) in Postgres. One row carries catalog + vector, "
            "so semantic recall combines with SQL filters in a single query.", fontsize=9.0, color=INK, wrap=True)

    # agent
    box(ax, 6, 62, 26, 12, "RLM deep agent\n(any pipeline node)", fc=GOLD_L, ec=GOLD, fs=9.5, bold=True)
    # postgres
    box(ax, 68, 70, 26, 11, "Postgres + pgvector\nknowledge(row + embedding)", fc=BLUE_L, ec=BLUE, fs=9, bold=True)
    # minio
    box(ax, 68, 54, 26, 11, "MinIO (S3)\nblobs: RTL / GDS / PDF / refs", fc=PURPLE_L, ec=PURPLE, fs=9, bold=True)

    # remember
    arrow(ax, 32, 70, 68, 75, color=BLUE)
    ax.text(50, 78.5, "remember(kind,text,…) → embed → INSERT row", ha="center", fontsize=7.8, color=BLUE)
    arrow(ax, 32, 66, 68, 60, color=PURPLE)
    ax.text(50, 62.5, "put_object(key) → blob", ha="center", fontsize=7.8, color=PURPLE)
    # recall
    arrow(ax, 68, 72, 32, 67.5, color=GREEN)
    ax.text(50, 70.5, "recall(query) → ORDER BY embedding <=> q  (top-k)", ha="center", fontsize=7.8, color=GREEN)

    ax.text(6, 47, "What gets stored (kind-tagged rows + blobs):", fontsize=9.4, color=INK, weight="bold")
    bullets(ax, 6, 44, [
        "design  — every VERIFIED RTL design (reusable, recallable)",
        "code    — RTL / TB source files",
        "fix     — error→fix LESSONS (the self-improvement signal)",
        "research / paper / reference — crawled GitHub + papers digests",
        "gds     — hardened layouts (ingested for tape-out reuse)",
        "ip      — the IP library (peripherals, cores, memory, crypto…)",
    ], fs=8.2, dy=2.7)

    box(ax, 52, 16, 44, 30, "", fc="#fbfaf6", ec=GREEN, round=0.015)
    ax.text(74, 44, "How the recursive loop USES the store", ha="center", fontsize=9.6, color=INK, weight="bold")
    bullets(ax, 54, 41, [
        "BEFORE generate — recall the 3 closest error→fix",
        "   lessons + the nearest verified design (the anchor)",
        "DURING generate — a broken→clean write saves a NEW",
        "   fix lesson immediately (kind='fix')",
        "AFTER a verified run — ingest the whole design so the",
        "   next prompt can recall it",
        "DEFENSIVE — if the DB/bucket is down, every call no-ops",
        "   and the agent keeps running on the local file flow",
    ], fs=7.9, dy=2.85, color=INK)
    ax.text(50, 10, "Net effect:  the store is the agent's MEMORY — recall makes each new design start from the "
            "closest prior knowledge; remember makes every solved problem permanent.", ha="center",
            fontsize=8.6, color=INK, style="italic", wrap=True)
    pdf.savefig(fig); plt.close(fig)


# ── page 4 — autoresearch concept ────────────────────────────────────────────
def page_autoresearch(pdf):
    fig, ax = _fig()
    header(ax, "3 · The Autoresearch upgrade — self-improving RTL generation", "auto-kernel-gen, applied to RTL")
    ax.text(4, 88.5, "Insight: projects that auto-generate OPTIMAL KERNELS (AutoKernel, KernelBench, and "
            "Reflexion / Self-Refine self-improving agents) close a research→generate→evaluate→reflect→learn "
            "loop. RTL generation is the same shape — so we make the loop EXPLICIT and feed it from the store.",
            fontsize=9.0, color=INK, wrap=True)

    # recursive loop diagram (pentagon-ish cycle)
    cx, cy, r = 30, 50, 18
    nodes = [
        ("RESEARCH\nGitHub/papers/error", GOLD_L, GOLD, 90),
        ("GENERATE\nanchor-and-adapt RTL", BLUE_L, BLUE, 18),
        ("EVALUATE\nsim / lint / harden", GREEN_L, GREEN, -54),
        ("REFLECT\nwhy did it fail?", "#fde0e0", RED, -126),
        ("LEARN\nstore fix lesson", PURPLE_L, PURPLE, 162),
    ]
    import math
    pts = []
    for t, fc, ec, ang in nodes:
        x = cx + r * math.cos(math.radians(ang)) - 7
        y = cy + r * math.sin(math.radians(ang)) - 3.5
        box(ax, x, y, 14, 7, t, fc=fc, ec=ec, fs=7.2, bold=True)
        pts.append((x + 7, y + 3.5))
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        arrow(ax, a[0], a[1], b[0], b[1], color=GREY, lw=1.5)
    ax.text(cx, cy, "recursive\nself-improvement", ha="center", va="center", fontsize=8.5,
            color=INK, weight="bold", style="italic")

    ax.text(54, 78, "What changes vs. today", fontsize=10, color=INK, weight="bold")
    bullets(ax, 54, 75, [
        "PROACTIVE research — before generating, search GitHub +",
        "   papers for the architecture AND its known pitfalls,",
        "   crawl them (SearXNG + crawl4ai) into a research digest",
        "TARGETED research-on-failure — when sim/lint/harden fails,",
        "   research the EXACT error message, not just the topic",
        "REFLECTION — turn each failure into a written lesson:",
        "   symptom → broken pattern → correct fix",
        "ACCUMULATION — lessons + verified designs grow in the store,",
        "   so the agent gets measurably better every run",
        "PROMOTION — a memory-keeper distils raw lessons into per-",
        "   topic knowledge summaries (Tier-2 knowledge)",
    ], fs=7.8, dy=2.45)

    box(ax, 4, 8, 92, 14, "", fc=GREY_L, ec=GREY, round=0.01)
    ax.text(50, 19.5, "Why this works for RTL (same as for kernels)", ha="center", fontsize=9.6,
            color=INK, weight="bold")
    cols = [("Kernel codegen", "search ops + perf tricks → emit kernel → benchmark → reflect on slow paths → cache"),
            ("RTL generation (ours)", "research design + pitfalls → adapt RTL → sim/lint/harden → reflect on errors → store fix")]
    for i, (h, t) in enumerate(cols):
        ax.text(8 + i * 46, 16, h, fontsize=8.8, color=GOLD if i else BLUE, weight="bold")
        ax.text(8 + i * 46, 13, t, fontsize=7.7, color=INK, wrap=True)
    ax.text(50, 9.6, "Verifiable reward signal (compile / sim-pass / DRC-clean / timing-met) is what makes the "
            "self-improvement loop converge — exactly the role a benchmark plays for kernels.",
            ha="center", fontsize=8.0, color=INK, style="italic", wrap=True)
    pdf.savefig(fig); plt.close(fig)


# ── page 5 — integration + roadmap ───────────────────────────────────────────
def page_integration(pdf):
    fig, ax = _fig()
    header(ax, "4 · Integration & roadmap — autoresearch on top of today's stack", "what to build")
    ax.text(4, 88, "The autoresearch loop bolts onto the EXISTING graph and the EXISTING pg/MinIO store — no "
            "re-architecture. Each box below is incremental.", fontsize=9.2, color=INK, wrap=True)

    lanes = [
        ("Already in place", GREEN, [
            "RLM deep-agent nodes (peek / delegate / build-up)",
            "web research (SearXNG + crawl4ai) → anchor clone",
            "error→fix lessons saved + recalled (kind='fix')",
            "pgvector recall + MinIO blobs, live ingest per step",
            "verilog_check deterministic gates + self-correct loop",
        ]),
        ("Autoresearch upgrade", GOLD, [
            "research-on-failure: search the exact error string",
            "structured reflection: symptom→broken→fix template",
            "research budget controller (how deep to dig per step)",
            "lesson dedup + ranking by past usefulness",
            "memory-keeper: distil lessons → topic knowledge.md",
        ]),
        ("Stretch", PURPLE, [
            "clone & study auto-kernel / self-improving-agent repos",
            "   into the store as 'method' knowledge",
            "auto-curated IP library feedback (this hardening run)",
            "cross-design transfer: reuse a verified sub-block",
            "offline self-play: regenerate past designs, keep wins",
        ]),
    ]
    for i, (title, color, items) in enumerate(lanes):
        x = 4 + i * 31.5
        box(ax, x, 30, 29, 50, "", fc="#fbfaf6", ec=color, round=0.015)
        ax.add_patch(FancyBboxPatch((x, 74), 29, 6, boxstyle="square,pad=0", fc=color, ec="none"))
        ax.text(x + 14.5, 77, title, ha="center", va="center", fontsize=10, color="white", weight="bold")
        bullets(ax, x + 1.5, 71, items, fs=7.7, dy=3.4, w=27)

    box(ax, 4, 9, 92, 16, "", fc=INK, ec="none", round=0.01)
    ax.text(50, 21.5, "One-line summary", ha="center", fontsize=10.5, color=GOLD, weight="bold")
    ax.text(50, 16.8, "AnoaChip is already a recursive, memory-backed RTL agent. 'Autoresearch' makes its research",
            ha="center", fontsize=8.8, color="white")
    ax.text(50, 13.6, "PROACTIVE and its failures REFLECTIVE, and routes both through the pg/MinIO store — so every",
            ha="center", fontsize=8.8, color="white")
    ax.text(50, 10.4, "design it builds makes the next one smarter, the same way auto-kernel generators improve with use.",
            ha="center", fontsize=8.8, color="white")
    pdf.savefig(fig); plt.close(fig)


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(OUT) as pdf:
        cover(pdf)
        page_current(pdf)
        page_memory(pdf)
        page_autoresearch(pdf)
        page_integration(pdf)
        d = pdf.infodict()
        d["Title"] = "AnoaChip — RLM + Autoresearch System Design"
        d["Author"] = "AnoaChip"
    print(f"✓ wrote {OUT}  ({OUT.stat().st_size // 1024} KB, 5 pages)")


if __name__ == "__main__":
    main()
