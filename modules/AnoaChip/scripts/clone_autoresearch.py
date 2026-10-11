#!/usr/bin/env python3
"""Autoresearch — clone & study self-improvement / auto-codegen method repos into the knowledge
store, so the recursive RLM agent can RECALL self-improvement techniques while it works.

Same idea as the auto-kernel generators (AutoKernel, KernelBench) and self-improving agents
(Reflexion, Self-Refine): the loop gets smarter by reading prior METHOD knowledge. This shallow-
clones a curated set of method repos, extracts the human-written docs (README + docs/*.md — the
*approach*, not the code), and ingests each as a ``kind='method'`` row (text + embedding → Postgres,
blob → MinIO). The planner/generator then recalls these alongside the error→fix lessons.

Run it when the box is free (it loads the embeddings model) — e.g. after a harden batch.

    uv run python scripts/clone_autoresearch.py            # clone + ingest the catalog
    uv run python scripts/clone_autoresearch.py --list     # show the catalog
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src" / "anoa_chip"))

# Curated method repos — auto-codegen, self-improving agents, and LLM-for-RTL technique.
CATALOG = [
    # ── self-improving / reflective agents (the autoresearch loop itself) ──
    {"name": "reflexion", "repo": "https://github.com/noahshinn/reflexion",
     "topic": "self-improving agent: verbal reinforcement / reflect-on-failure loop"},
    {"name": "self-refine", "repo": "https://github.com/madaan/self-refine",
     "topic": "iterative self-refinement: generate → feedback → refine"},
    {"name": "language-agent-tree-search", "repo": "https://github.com/lapisrocks/LanguageAgentTreeSearch",
     "topic": "LATS: search + reflection over agent trajectories"},
    # ── auto kernel / code generation (optimal-codegen analogue of RTL gen) ──
    {"name": "autokernel", "repo": "https://github.com/OAID/AutoKernel",
     "topic": "automatic high-performance operator/kernel code generation"},
    {"name": "kernelbench", "repo": "https://github.com/ScalingIntelligence/KernelBench",
     "topic": "LLM-generated CUDA kernels, benchmarked (verifiable reward)"},
    # ── LLM for RTL / Verilog (domain method + benchmarks) ──
    {"name": "verilog-eval", "repo": "https://github.com/NVlabs/verilog-eval",
     "topic": "VerilogEval: evaluating LLM Verilog generation"},
    {"name": "rtllm", "repo": "https://github.com/hkust-zhiyao/RTLLM",
     "topic": "RTLLM: open benchmark for LLM RTL generation"},
    {"name": "chip-chat", "repo": "https://github.com/...",  # placeholder kept optional below
     "topic": "conversational hardware design with LLMs", "optional": True},
    # ── agent frameworks / planning that our deep agents build on ──
    {"name": "deepagents", "repo": "https://github.com/langchain-ai/deepagents",
     "topic": "deep-agent framework: planning + sub-agents + file tools (our node brain)"},
]

DOC_GLOBS = ["README*", "readme*", "docs/*.md", "doc/*.md", "*.md"]


def _run(cmd, timeout=300):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout + p.stderr
    except Exception as e:  # noqa: BLE001
        return 1, str(e)


def study_one(mem, entry: dict) -> int:
    name, repo, topic = entry["name"], entry["repo"], entry["topic"]
    if "..." in repo:
        print(f"   – {name}: no canonical repo — skipped"); return 0
    print(f"\n── {name}  ({topic})\n   {repo}")
    tmp = Path(tempfile.mkdtemp(prefix=f"ar_{name}_"))
    clone = tmp / "repo"
    rc, log = _run(["git", "clone", "--depth", "1", repo, str(clone)])
    if rc != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        print(f"   ⚠️  clone failed — skipped"); return 0
    # gather the human-written docs (the APPROACH), cap size
    docs, seen = [], set()
    for g in DOC_GLOBS:
        for p in sorted(clone.glob(g)):
            if p.is_file() and p.name not in seen and p.stat().st_size < 200_000:
                seen.add(p.name)
                try:
                    docs.append(f"### {p.name}\n" + p.read_text(errors="replace"))
                except Exception:  # noqa: BLE001
                    pass
    body = ("\n\n".join(docs))[:18000] or f"(no docs found in {repo})"
    n = 0
    if mem is not None:
        rid = mem.remember(
            "method",
            f"METHOD/TECHNIQUE: {topic}\nSource repo: {repo}\n\n{body}",
            design="autoresearch", source=f"method:{repo}", title=f"{name} — {topic}",
            tags=f"method autoresearch self-improvement {name}")
        n = 1 if rid else 0
        print(f"   ✓ ingested method '{name}' → knowledge store ({len(body)} chars of docs)")
    shutil.rmtree(tmp, ignore_errors=True)
    return n


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args()
    cat = [e for e in CATALOG if not args.only or e["name"] in set(args.only)]
    if args.list:
        for e in cat:
            print(f"  {e['name']:28s} {e['repo']}")
        return
    from memory_store import get_memory
    mem = get_memory()
    if not mem.enabled:
        print("knowledge store offline (docker compose up -d) — nothing ingested."); return
    total = sum(study_one(mem, e) for e in cat)
    print(f"\n═══ studied {total} method repo(s) → kind='method' in the knowledge store.")
    print("The planner/generator now recall these as self-improvement techniques (see app.py).")


if __name__ == "__main__":
    main()
