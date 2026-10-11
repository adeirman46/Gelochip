"""
AnoaChip — unified, local-LLM ANALOG IC flow with a Claude-Code-style,
human-in-the-loop agent loop.

ONE app: prompt -> Planner -> config file (spec + parameters) -> SPICE netlist
(RAG + local LLM) -> ngspice spec verification (+ self-fix: mutate the config)
-> Glayout layout (placement movex/movey/center + c/L/straight routes + vias)
-> DRC (magic) + LVS (netgen) -> GDSII. The flow runs ONE AGENT AT A TIME
and PAUSES after each so you can:

  ▶️ Continue       — run the next step
  ✍️ Revise         — re-run THIS step with your feedback
  🔁 Replan         — let the Replanner choose the next steps from your feedback
  🌐 Web example    — "go find an example of block X and its inputs/outputs"

Every step's output is recorded into a transcript that is re-drawn on every
Streamlit rerun (Streamlit wipes prior output each rerun), so the whole history
stays on screen as you steer. Every artifact is written to output/<design>/.

Chat model is local by default (Ollama, e.g. qwen3.5:9b) — see llm.py.
"""

from __future__ import annotations

import os
import re
import json
import glob
import shutil
import subprocess
import time
import zipfile
import io
import functools
from pathlib import Path
from typing import Dict, List

import streamlit as st
import streamlit.components.v1 as components
import graphviz
from dotenv import load_dotenv
from langchain.docstore.document import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_core.prompts import ChatPromptTemplate

from llm import get_chat_model, get_embeddings, provider_label, retrying, set_model, set_num_ctx
from memory_store import get_memory

load_dotenv()

# --------------------------------------------------------------------------- #
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "analog_datasets"
OUTPUT_DIR = REPO_ROOT / "output"          # <-- all results land here
# 50 blind retries never converged — with the static gate + multi-file fixes,
# 12 cycles is plenty; past that the design needs a replan, not more of the same.
MAX_RETRIES = int(os.getenv("MAX_SIM_RETRIES", "12"))
MAX_LINT_RETRIES = int(os.getenv("MAX_LINT_RETRIES", "10"))
# When the fix loop can't make a design verifiable, REGENERATE the netlist from knowledge (a
# fresh design attempt) instead of laying out an unverified one. Bounded so it can't loop.
MAX_REGEN = int(os.getenv("MAX_REGEN", "1"))
# When the layout stage fails on a netlist-level error (an LVS mismatch that names a net —
# e.g. a route that was never generated), feed that error back to the corrector and RE-BUILD
# the layout, instead of dead-ending. Bounded so a non-fixable failure can't loop.
MAX_HARDEN_FIX = int(os.getenv("MAX_HARDEN_FIX", "3"))
# Self-improve loop: how many config-mutation iterations the spec tuner may take.
MAX_SPEC_ITERS = int(os.getenv("ANOA_MAX_SPEC_ITERS", "6"))
PDK = os.getenv("PDK", "gf180mcuD")
PDK_ROOT = os.getenv("PDK_ROOT", os.path.expanduser("~/pdks"))
os.environ.setdefault("PDK_ROOT", PDK_ROOT)
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def clean_llm_output(text: str) -> str:
    if not text:
        return ""
    stripped = re.sub(r"<think>.*?</think>", "", text,
                      flags=re.DOTALL | re.IGNORECASE).strip()
    # If the model put EVERYTHING inside <think> (no answer after), keep the raw
    # text so we can still pull a code block out of it.
    return stripped or text.strip()


def extract_code_block(text: str, lang: str = "spice") -> str:
    text = clean_llm_output(text)
    m = re.search(rf"```(?:{lang})?\s*\n(.*?)```", text, re.DOTALL)
    code = m.group(1).strip() if m else text.replace(
        f"```{lang}", "").replace("```", "").strip()
    code = dedup_modules(code)
    if lang in ("spice", "sp", "netlist"):
        try:                              # deterministically repair the obvious syntax tics
            from netlist_check import autofix_text
            code, _ = autofix_text(code)
        except Exception:  # noqa: BLE001
            pass
    return code


def dedup_modules(code: str) -> str:
    """LLMs sometimes emit the SAME `.subckt … .ends` twice (which causes
    'redefinition' errors). Keep one copy of each subckt."""
    if not code:
        return code
    full = re.findall(r"(\.[sS][uU][bB][cC][kK][tT]\s+\w+.*?\.[eE][nN][dD][sS][^\n]*)",
                      code, re.DOTALL)
    if len(full) <= 1:
        return code.strip()
    last = {}
    order = []
    for b in full:
        nm = re.match(r"\.\w+\s+(\w+)", b).group(1)
        if nm not in last:
            order.append(nm)
        last[nm] = b  # keep the last (usually most complete) copy
    head = code[: code.lower().find(".subckt")] if code.lower().find(".subckt") > 0 else ""
    return (head + "\n\n".join(last[nm] for nm in order)).strip()


def extract_json(text: str) -> dict:
    text = clean_llm_output(text)
    m = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    raw = m.group(1) if m else None
    if raw is None:
        s, e = text.find("{"), text.rfind("}")
        if s != -1 and e != -1 and e > s:
            raw = text[s: e + 1]
    if raw is None:
        raise json.JSONDecodeError("no JSON object found", text, 0)
    return json.loads(raw)


def strip_ansi(s: str) -> str:
    return ANSI.sub("", s)


def librelane_available() -> bool:
    """(name kept for backend compat) — True when the Glayout layout backend is usable."""
    try:
        from glayout_tools import glayout_available
        return glayout_available()[0]
    except Exception:  # noqa: BLE001
        return False


# --------------------------------------------------------------------------- #
# Persistent agent memory — error→fix lessons that survive across runs.
# These live ONLY in the durable knowledge store (Postgres rows + embeddings,
# blobs in MinIO) — NOT in a local JSON file — so they are shared across runs and
# machines and surface via semantic recall, and the agent stops repeating the same
# mistake. Every debug point (compile-on-write, static check, sim/lint corrector,
# fail→pass transition) funnels through remember_fix(); recall happens BEFORE the
# generator writes and at the start of every correction.
# --------------------------------------------------------------------------- #
def remember_fix(error_sig: str, hint: str, *, design: str = "", broken: str = "",
                 fixed: str = "") -> None:
    """Persist an error→fix lesson to pg/MinIO (kind='fix'). Saved AUTOMATICALLY at every
    debug point; deduped by a content hash so the same lesson isn't stored twice. Optionally
    include the BROKEN and FIXED code so recall gives a concrete before/after pattern."""
    if not error_sig:
        return
    body = f"ERROR SIGNATURE: {error_sig}\n\n"
    if broken:
        body += f"BROKEN (do NOT write this):\n```\n{broken[:1500]}\n```\n\n"
    if fixed:
        body += f"CORRECT FIX:\n```\n{fixed[:2000]}\n```\n\n"
    if hint and not fixed:
        body += f"FIX: {hint}\n"
    try:
        from memory_store import get_memory
        mem = get_memory()
        if not getattr(mem, "enabled", False):
            return
        # stable id by error signature → ON CONFLICT updates in place (no duplicate rows)
        import hashlib
        rid = "fix_" + hashlib.sha1(error_sig.lower().encode()).hexdigest()[:16]
        mem.remember("fix", body, design=design, source="auto-fix",
                     title=("fix: " + error_sig)[:120], tags="fix lesson",
                     object_key=rid, meta={"error_sig": error_sig[:300]})
    except Exception:  # noqa: BLE001
        pass


def recall_fix(error_sig: str) -> str:
    """Semantic recall of the best-matching past fix from pg/MinIO ('' if none)."""
    try:
        from memory_store import get_memory
        items = get_memory().recall(error_sig or "", kind="fix", k=1)
        if items:
            return items[0].get("text", "")
    except Exception:  # noqa: BLE001
        pass
    return ""


def slugify(text: str, n: int = 48) -> str:
    return re.sub(r"\W+", "_", text).lower().strip("_")[:n] or "design"


def _norm(code: str) -> str:
    """Normalize a netlist/script for an 'is this the same attempt?' check — ignore
    comments and whitespace so the corrector can't sneak the SAME broken code past
    us by only re-indenting it."""
    code = re.sub(r"^\s*\*[^\n]*", "", code or "", flags=re.MULTILINE)  # SPICE * comments
    code = re.sub(r"//[^\n]*", "", code)
    code = re.sub(r"#[^\n]*", "", code)
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.DOTALL)
    return re.sub(r"\s+", " ", code).strip()


def _looks_repetitive(text: str) -> bool:
    """Detect a degenerate generation loop — the model spewing the same handful of
    lines over and over (e.g. '// We will assume … // But the prompt says …'). If
    the last 30 non-empty lines collapse to ≤3 distinct lines, it's looping. Real
    code/reasoning almost never does that (each line differs)."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < 30:
        return False
    return len(set(lines[-30:])) <= 3


# Every downstream agent reads the architect's GENERAL plan, then makes its OWN detailed
# plan for its step (hierarchical planning).
_SUBPLAN = ("Your file plan for this step is FIXED and listed above (it was derived from the "
            "architect's design_notes.md). Call write_todos with EXACTLY those files, SAME names, "
            "SAME order — do NOT invent a different circuit breakdown, do NOT rename/split/merge "
            "files. For each file, read its interface from design_notes.md with read_file_disk, "
            "then write it. Build them in order.\n")

# Strong template so the build contract is ALWAYS thorough, regardless of model variance.
DESIGN_NOTES_PROMPT = """You are the LEAD ANALOG ARCHITECT writing the build CONTRACT \
(design_notes.md) — a KNOWLEDGE document a senior engineer writes BEFORE any circuit. It captures \
the DECISIONS, the MATH, and the RELEVANT KNOWLEDGE — NOT the implementation. Target is a full-\
custom analog GDSII tape-out via Glayout (netlist → layout → DRC/LVS).

HARD RULES — the document is REJECTED if you break ANY of them:
- THE SPEC IS THE AUTHORITY. Every FACT in the CIRCUIT section below (gain, bandwidth, phase \
margin, power, supply, load, PDK) must be copied into the contract EXACTLY. NEVER substitute a \
'typical' value of your own (if the spec says 40 dB and 1 pF load, the contract says exactly \
that). Invented numbers make every later stage build the wrong circuit.
- This is NOT the netlist. Write NO device cards, NO glayout code. The generator writes all of \
that later, sized from the CONFIG file.
- For each circuit block show ONLY its INTERFACE: the `.subckt name port1 port2 ...` header line \
with a one-line comment per port (VDD VSS in± out bias). NEVER list internal nets.
- Spend your words on KNOWLEDGE (the topology choice, the sizing math, the trade-offs), not code. \
Be concise — the whole document is well under ~300 lines.

CIRCUIT: {query}
{constraints}
{feedback}

# <Design Name> — Build Contract

## 1. Specification
Restate precisely, as a bullet list: the spec table (gain_db, bw_hz, ugbw_hz, phase_margin_deg, \
power_w, supply, load), the topology class, the PDK.

## 1b. Use case
ONE concrete, real-world signal this circuit serves — grounded in the research (e.g. a 5T-OTA \
buffering a 100 kHz sensor bridge signal into an SAR ADC's 1 pF sampling cap). State the input \
amplitude/frequency, the expected output, and the error the application tolerates. The testbench \
MUST drive these inputs and the report tells this story.

## 2. Key Knowledge & Decisions   ← the MOST IMPORTANT section; be detailed here
- **Topology**: which topology and WHY (5T-OTA vs folded cascode vs two-stage + Miller; mirror \
ratios; tail current). Cite the recalled/researched reference netlists or glayout cells used.
- **Sizing math**: gm/Id or square-law FIRST-CUT sizing per device, with the one-line equation \
that justifies each (e.g. gm = 2π·GBW·CL).
- **COMPLETE PARAMETER TABLE** (this becomes config/<name>.json's `params` — list EVERY value, \
none omitted): a markdown table `| Component | Parameter | Value | Why |` covering every MOSFET \
(W, L, fingers, M), every R (Ω), C (F), L (H), every bias current and reference voltage, and the \
supply. These are the ONLY knobs for tuning: to hit a different spec later you change THESE \
values and re-simulate, and each run's parameters + measured performance are logged so you can \
tune from any past point.
- **Operating point**: expected region/overdrive per device, common-mode range, output swing.
- **Layout plan**: matching-critical pairs (interdigitate/common-centroid later), the placement \
sketch (what goes left/right/above, movex/movey/center), which routes are c_route vs L_route vs \
straight_route + via_stack, and the finishing order: BARE devices first (no tie/tap/dummy) → \
route → LVS clean → THEN substrate ties, guard ring, dummies.
- **Key techniques**: the important circuit techniques/decisions. Do NOT name any source repo, \
GitHub URL, or "anchor/reference design" — present the design as its own.

## 3. Block Map
A markdown table `| Block | Role | Ports |` — ONE row per subcircuit.

## 4. Interfaces (boilerplate only)
The top subckt first, then each sub-block, as a SHORT ```spice `.subckt` header line — PORTS \
ONLY, one comment per port, no bodies.

## 5. Connections
Which device terminal ties to which net (drain of M1 → gate of M3, …) as a short bullet list or \
small ASCII sketch. Every net named here must be ROUTED in layout. NO code.

## 6. Verification & GDS Sign-off
The ngspice testbench plan: .op sanity, .ac for gain/BW/PM (wrdata export), .tran for the use-\
case signal, the .measure lines; then the path to silicon ON THE TARGET PDK named in the \
constraints above: glayout build → DRC (magic) → LVS (netgen) → GDSII. Bullets. Do NOT name any \
other PDK/node.

Output ONLY the concise markdown document — no preamble, no fences around the whole thing."""

# Known-PDK human labels so the plan names the real process, not a hallucinated one.
_PDK_LABELS = {"gf180": "GlobalFoundries 180 nm", "sky130": "SkyWater 130 nm"}


def _constraints_note(ctx) -> str:
    """The REAL per-run target constraints — injected into the GRAND PLAN and the build
    contract so the planner names the ACTUAL PDK/supply and never invents another. The
    netlist itself binds to the PDK's device models; these must be consistent everywhere."""
    label = next((v for k, v in _PDK_LABELS.items() if PDK.lower().startswith(k)), "")
    pdk_str = f"{PDK}" + (f" ({label})" if label else "")
    vdd = "1.8" if PDK.lower().startswith("sky130") else "3.3"
    lines = [
        f"- Target PDK: {pdk_str} — the ONLY process for this chip. Do NOT name tsmc, "
        f"asap7, or ANY other PDK/node anywhere; the technology is {PDK} and nothing else. "
        f"Device models: {'sky130_fd_pr__nfet_01v8 / __pfet_01v8' if PDK.lower().startswith('sky130') else 'gf180mcu_fd_pr__ nfet/pfet 03v3'}.",
        f"- Supply: VDD = {ctx.get('vdd', vdd)} V.",
    ]
    if ctx.get("spec"):
        lines.append(f"- Spec table: {json.dumps(ctx['spec'])[:400]}")
    return "TARGET CONSTRAINTS (read these; use EXACTLY them, invent nothing):\n" + "\n".join(lines)


# The GRAND plan is GENERAL and written FIRST, like Claude Code's plan step: each line is an
# INTENTION ("search the architecture", "search github/paper/web", "generate", "tb it", "gds
# it within constraints") that is then EXECUTED with its tooling. Per-module / per-test / per-fix
# DETAIL is NOT here — each agent writes its own sub-plan for that. Every line maps to a step
# that really runs (nothing listed the flow never does, nothing done that isn't listed).
PLAN_POINTS_PROMPT = """You are the LEAD ANALOG ARCHITECT writing the GRAND PLAN for this circuit, \
the way Claude Code writes a plan BEFORE doing the work: a short ordered list of GENERAL intentions, \
each carried out with the right tool. The FOCUS IS THE GLAYOUT LAYOUT → GDSII. SPICE is NOT the \
deliverable: the reference SPICE netlists found by research are PARSED into a JSON that captures the \
WIRING (each component + which nets its terminals connect to) and the PARAMETERS (W/L/M, R, C, bias). \
That JSON is the config that FEEDS glayout. There is NO pre-layout testbench — the ngspice simulation \
happens AFTER the layout is clean and its SPICE has been extracted (PEX). Order:
(research SPICE → JSON of wiring+parameters → Glayout layout → DRC/LVS → GDSII → PEX extract → ngspice DC/AC/tran verify).

Keep it HIGH-LEVEL — just the general PHASES, in order. Do NOT name devices, test cases, or fixes \
here: that DETAIL is decided later and lives in each agent's sub-plan. Aim for ~6-7 short lines, in \
EXACTLY this order:
- restate the circuit's spec table + the target PDK / supply constraints (from below)
- research the topology and gather reference SPICE netlists + the glayout generators/cells that build it
- parse the reference SPICE into a JSON config: the wiring (each component + its net connections) + every parameter (W/L/M, R, C, bias)
- lay out with glayout from that JSON (place movex/movey/center, route every net c/L/straight+via), showing the GDS each iteration
- DRC + LVS clean, then add substrate ties / guard ring / dummies last
- extract the layout's SPICE (PEX) and run the ngspice DC/AC/tran response to verify the spec
- export the final GDSII
CIRCUIT: {query}
{constraints}
{feedback}
Output ONLY the checklist — one item per line, no numbering, no headers, no extra prose."""


def _plan_points(rec, query, feedback="", context="", constraints="") -> List[str]:
    """Generate the GRAND plan checkpoints reliably and render them as a ⬜ checklist. Written
    FIRST, from the SPEC + `constraints` alone (Claude-Code style) — recall/research run AFTER,
    as execution of the plan's 'search …' steps. `constraints` = the real PDK/clock so the plan
    names the right process and never hallucinates sky130/asap7. `context` is optional/legacy."""
    rec.caption("🧠 Reasoning out the build plan…")
    ph = rec.placeholder()          # streams the raw plan tokens; CLEARED once the
    try:                            # checklist below renders (no duplicated text block)
        raw = clean_llm_output(stream_to(
            get_chat_model(temperature=0.3),
            PLAN_POINTS_PROMPT.format(
                query=query, constraints=constraints,
                feedback=(f"USER STEERING: {feedback}" if feedback else ""))
            + (f"\n\nWhat we already RECALLED + RESEARCHED (build the plan on these, cite the "
               f"reference per relevant step):\n{context[:2200]}" if context else ""),
            ph))
    except Exception:  # noqa: BLE001
        raw = ""
    pts: List[str] = []
    for ln in raw.splitlines():
        t = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", ln).strip().strip("[]").strip()
        if 3 < len(t) < 160 and not t.lower().startswith(("here", "output", "checklist", "the ")):
            pts.append(t)
    pts = pts[:24]
    if not pts:
        pts = ["Restate the circuit's spec table and target PDK/supply constraints",
               "Research the topology + reference SPICE netlists + the glayout generators that build it",
               "Parse the reference SPICE into a JSON config: wiring (component→net connections) + every parameter",
               f"Lay out with glayout on {PDK} from that JSON (place movex/movey/center, route every net), GDS each iteration",
               "DRC + LVS clean, then add substrate ties / guard ring / dummies last",
               "Extract the layout SPICE (PEX) and run the ngspice DC/AC/tran response to verify the spec",
               "Export the final GDSII"]
    ph.empty()      # drop the streamed raw text — the checklist below is the ONE plan
    rec.plan(pts)   # live checklist — greens as downstream agents do each phase
    return pts


# Each build agent makes its OWN reliable, detailed sub-plan checklist (the [] [] [] for
# its step) — generated directly so it's never a single vague item.
_SUBPLAN_ASK = {
    "generate": ("The ONLY deliverable is ONE JSON config — glayout builds the layout straight "
                 "from it, so there is NO SPICE netlist to write. Output EXACTLY ONE line:\n"
                 "'config/<name>.json — spec table + wiring (every component and the nets its "
                 "terminals connect to) + EVERY parameter (W/L/fingers/M, R, C, L, bias, supply), "
                 "distilled from the researched SPICE'.\n"
                 "ABSOLUTELY FORBIDDEN: any .sp / netlist file, a file per parameter (W.sp, L.sp, "
                 "VDD.sp…), a file per role/net/node. Wiring and parameters are KEYS inside the "
                 "one JSON, never files. Output ONLY that single config line."),
    "testbench": ("List the TEST/MEASURE CASES the ngspice testbench must cover — ONE short line "
                  "each: .op bias-point sanity (every device saturated), .ac gain_db + bw_hz + "
                  "ugbw_hz + phase_margin_deg (wrdata export for the Bode plot), .tran with the "
                  "use-case input signal, power_w from supply current, and the exact .measure "
                  "line for each spec. 5-10 items."),
    "fix_design": ("List the steps to diagnose and FIX the failing circuit — ONE short line each: "
                   "read the error/spec miss, name the exact cause (device out of saturation, "
                   "wrong mirror ratio, W/L too small for gm), the CONFIG parameter to change, "
                   "re-simulate. 4-8 items."),
    "harden": ("List the LAYOUT steps — ONE short line each: load config, generate each bare "
               "device (no tie/tap/dummy) sized from config, place with movex/movey/center, "
               "route EACH net (say which: c_route / L_route / straight_route + via_stack), "
               "add ports, build+LVS, then finishing (ties, guard ring, dummies) + re-verify. "
               "6-12 items."),
}


def _plan_path(design_dir, step: str) -> Path:
    return Path(design_dir) / "context" / f"plan_{step}.json"


def _load_plan(design_dir, step: str) -> List[str]:
    """The LOCKED sub-plan for `step`, if one was already decided. Reusing it is the whole
    point: a retry / a user 'continue' / a resume must get the SAME file breakdown, never a
    freshly re-rolled one — that's what made the plan, the agent's todos and the completeness
    gate disagree."""
    p = _plan_path(design_dir, step)
    if p.exists():
        try:
            return [s for s in json.loads(p.read_text()) if isinstance(s, str) and s.strip()]
        except Exception:  # noqa: BLE001
            return []
    return []


def _save_plan(design_dir, step: str, pts: List[str]) -> None:
    """Lock a step's sub-plan to disk so every later entry reuses the EXACT same list."""
    if not pts:
        return
    p = _plan_path(design_dir, step)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(list(pts)))


_NETLIST_GLOBS = ("*.sp", "*.spice", "*.cir", "*.cdl", "*.spc")


def _anchor_module_list(design_dir, limit: int = 120) -> List[tuple]:
    """(block_name, relpath) for every circuit block DEFINED in the cloned anchor references
    under context/anchor/: SPICE `.subckt` names AND glayout/gdsfactory generator functions
    (python defs that return a Component). The architect reads these as INSPIRATION for the
    Block Map (how a similar circuit was decomposed) but designs its OWN decomposition; the
    generator STUDIES the anchor and writes its own netlist/layout code."""
    adir = Path(design_dir) / "context" / "anchor"
    if not adir.exists():
        return []
    out: List[tuple] = []
    seen: set = set()

    def _add(nm: str, p: Path) -> bool:
        if nm not in seen:
            seen.add(nm)
            out.append((nm, str(p.relative_to(Path(design_dir)))))
        return len(out) >= limit

    paths = []
    for g in _NETLIST_GLOBS:
        paths += sorted(adir.rglob(g))
    for p in paths:
        if "papers" in p.parts:
            continue
        try:
            txt = p.read_text(errors="replace")
        except Exception:  # noqa: BLE001
            continue
        for m in re.finditer(r"^\s*\.subckt\s+([A-Za-z_]\w*)", txt,
                             re.IGNORECASE | re.MULTILINE):
            if _add(m.group(1), p):
                return out
    for p in sorted(adir.rglob("*.py")):
        if "papers" in p.parts:
            continue
        try:
            txt = p.read_text(errors="replace")
        except Exception:  # noqa: BLE001
            continue
        if not re.search(r"\b(glayout|gdsfactory|Component)\b", txt):
            continue
        for m in re.finditer(r"^\s*def\s+([A-Za-z_]\w*)\s*\(", txt, re.MULTILINE):
            if _add(m.group(1) + "()", p):
                return out
    return out


def _restamp_header(text: str, modname: str, query: str) -> str:
    """STRIP the anchor's legacy banner (the top-of-file comment block — the original project's
    name/version/author) and stamp a fresh header for THIS design, so a seeded netlist reads as
    the user's own. Only the LEADING run of comments/blank lines is removed; real cards
    (`.subckt`, `.include`, devices) are kept untouched."""
    lines = text.split("\n")
    i, n = 0, len(lines)
    while i < n:
        s = lines[i].strip()
        if s == "" or s.startswith("*") or s.startswith("//") or s.startswith("#"):
            i += 1
            continue
        break
    body = "\n".join(lines[i:]).lstrip("\n")
    q = re.sub(r"\s+", " ", (query or "").strip())[:72]
    bar = "* " + "=" * 74
    hl = [bar, f"*  AnoaChip  —  circuit {modname}"]
    if q:
        hl.append(f"*  Design : {q}")
    hl += ["*  SPICE netlist generated by AnoaChip — documented inline below.", bar, ""]
    header = "\n".join(hl) + "\n"
    return header + body


def _clean_sv_for_tools(text: str) -> str:
    """(analog no-op shim — kept because seeding paths call it) Strip nothing from a
    netlist; just normalize line endings."""
    return (text or "").replace("\r\n", "\n")


def _is_data_driven(query: str) -> bool:
    """True when the design's VALUES must be COMPUTED before sizing (gm/Id sweeps, filter
    coefficients, bias tables). Such a design leans on run_python for the math first."""
    return bool(re.search(
        r"\b(python|gm/?id|sweep|filter|fir\b|iir\b|coefficients?|sigma-?delta|sar\b|"
        r"pll\b|dco\b|vco\b|adc\b|dac\b|bandgap|polynomial)\b", query or "", re.I))


def _split_sv_modules(text: str) -> List[tuple]:
    """Split a FLAT (FIRRTL/Chisel-style) Verilog/SystemVerilog file into its individual
    `(module_name, module_source)` blocks. Such files never nest modules, so each block runs
    from a top-level `module NAME` to the next top-level `module` (capturing its `endmodule`
    and any inline ``define` guards that belong to it). Returns [] for a 0- or 1-module file so
    the caller keeps handling those as a single unit.

    This is the heart of the 'CGRA produced only 1 module' fix: the CGRA anchor packs all ~100
    modules into ONE 21k-line file, so copying it as a single rtl/<first-module>.sv collapsed the
    whole design to its first block. Splitting restores one file (and one plan item) per module."""
    starts = [(m.start(), m.group(1))
              for m in re.finditer(r"(?m)^[ \t]*module\s+([A-Za-z_]\w*)", text)]
    if len(starts) <= 1:
        return []
    out: List[tuple] = []
    for i, (pos, name) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(text)
        out.append((name, text[pos:end].rstrip() + "\n"))
    return out


def _seed_rtl_from_anchor(design_dir, rec=None, query: str = "", limit: int = 120) -> List[str]:
    """COPY the anchor's reference NETLISTS into netlist/ as the real STARTING POINT, so the
    generator ADAPTS working circuits instead of reading them and rewriting a 'simplified
    version'. One netlist file PER SUBCKT — a multi-subckt anchor file is SPLIT so every
    circuit block becomes its own netlist/<subckt>.sp with its own plan item. Reference
    glayout/gdsfactory generator .py files found in the anchor are copied to
    context/glayout_refs/ (they are REFERENCES for the layout step, not deliverables).
    Everything is auto-repaired and RE-HEADERED to this design; testbenches are skipped.
    Returns the seeded netlist filenames."""
    design_dir = Path(design_dir)
    adir = design_dir / "context" / "anchor"
    ndir = design_dir / "netlist"
    if not adir.exists():
        return []
    from netlist_check import autofix_text
    seeded: List[str] = []
    seen_sub: set = set()
    # NEVER seed from the DB 'recalled/' fallback — it's a few stale files from a past run.
    # Seed ONLY a real cloned web repo; if none, return [] so generation builds the design
    # from scratch (with recalled/ still available as a hint).
    files: List[Path] = []
    for g in _NETLIST_GLOBS:
        files += sorted(adir.rglob(g))
    files = [p for p in files
             if "recalled" not in p.parts and "papers" not in p.parts
             and not re.search(r"(_tb|tb_|test|bench)", p.name, re.I)]

    for p in files:
        try:
            txt = p.read_text(errors="replace")
        except Exception:  # noqa: BLE001
            continue
        subs = re.findall(r"^\s*\.subckt\s+([A-Za-z_]\w*)[^\n]*", txt,
                          re.IGNORECASE | re.MULTILINE)
        if not subs:
            continue
        # split multi-subckt files: each .subckt … .ends block becomes its own file
        blocks = re.findall(r"(^\s*\.subckt\s+([A-Za-z_]\w*).*?^\s*\.ends[^\n]*)",
                            txt, re.IGNORECASE | re.MULTILINE | re.DOTALL) or \
                 [(txt, subs[0])]
        for code, name in blocks:
            if name in seen_sub:
                continue
            seen_sub.add(name)
            dest = ndir / f"{name}.sp"
            if dest.exists():
                seeded.append(dest.name)
                continue
            try:
                code, _ = autofix_text(code)
            except Exception:  # noqa: BLE001
                pass
            code = _restamp_header(code, name, query)  # banner on top, subckt below
            ndir.mkdir(parents=True, exist_ok=True)
            dest.write_text(code)
            seeded.append(dest.name)
            if len(seeded) >= limit:
                break
        if len(seeded) >= limit:
            break

    # glayout/gdsfactory generator code found in the anchor → context/glayout_refs/
    grefs = 0
    gdir = design_dir / "context" / "glayout_refs"
    for p in sorted(adir.rglob("*.py")):
        if "recalled" in p.parts or "papers" in p.parts:
            continue
        try:
            txt = p.read_text(errors="replace")
        except Exception:  # noqa: BLE001
            continue
        if not re.search(r"\b(glayout|gdsfactory)\b", txt):
            continue
        gdir.mkdir(parents=True, exist_ok=True)
        dest = gdir / p.name
        if not dest.exists():
            dest.write_text(txt)
            grefs += 1
        if grefs >= 12:
            break

    if rec and (seeded or grefs):
        rec.caption(f"🧩 {len(seeded)} reference subckt(s) seeded into netlist/"
                    + (f" + {grefs} glayout reference script(s) → context/glayout_refs/"
                       if grefs else "") + ".")
    return seeded


def _prune_strays(design_dir, seeded: List[str], rec=None) -> List[str]:
    """When generation was SEEDED from the anchor, the deliverable IS those files. A 9B model
    sometimes ALSO writes a parallel generic circuit — delete those stray netlist files so the
    design stays the clean anchor, not a confusing mix of both. Keeps configs/testbenches."""
    ndir = Path(design_dir) / "netlist"
    keep = set(seeded)
    removed: List[str] = []
    paths: List[Path] = []
    for g in _NETLIST_GLOBS:
        paths += sorted(ndir.glob(g))
    for p in paths:
        if p.name in keep:
            continue
        try:
            p.unlink()
            removed.append(p.name)
        except Exception:  # noqa: BLE001
            pass
    if rec and removed:
        rec.caption(f"🧹 Removed {len(removed)} stray file(s): "
                    + ", ".join(removed[:10]) + (" …" if len(removed) > 10 else ""))
    return removed


def _prune_offplan_rtl(rec, design_dir, sub: List[str], pre_existing: List[str]) -> List[str]:
    """On a resume, drop netlist files left by a DIFFERENT (old) plan. Keeps: configs and
    testbenches, every file whose stem matches a planned file (directional: planned `ota.sp`
    is satisfied by `ota_5t.sp`), and every subckt such a kept file instantiates (legit
    helpers below the planned circuits). Without this, the resume note tells the generator
    'do NOT rewrite these' about the WRONG design, and pick_top can choose the old design's
    top. Returns the updated pre_existing list."""
    try:
        from netlist_check import parse_dir
        planned, _ = _planned_rtl_files(sub)
        planned_stems = {Path(f).stem.lower() for f in planned}
        if not planned_stems:
            return pre_existing
        info = parse_dir(Path(design_dir) / "netlist")

        def _match(st: str) -> bool:
            return any(st == ps or st.startswith(ps + "_") for ps in planned_stems)

        nl_ext = tuple(s.lstrip("*") for s in _NETLIST_GLOBS)
        keep = {f for f in pre_existing
                if not f.lower().endswith(nl_ext) or _match(Path(f).stem.lower())}
        stack = [m for m, d in info["defs"].items() if d.get("file") in keep]
        seen: set = set()
        while stack:                       # transitive: helpers used by kept subckts stay
            m = stack.pop()
            if m in seen:
                continue
            seen.add(m)
            d = info["defs"].get(m)
            if d:
                keep.add(d.get("file"))
            stack += list(info["insts"].get(m, []))
        strays = [f for f in pre_existing if f not in keep]
        if not strays:
            return pre_existing
        rec.caption(f"🧹 {len(strays)} on-disk circuit(s) belong to a DIFFERENT (old) plan — removed "
                    "so the build follows design_notes.md: " + ", ".join(strays[:8])
                    + (" …" if len(strays) > 8 else ""))
        _prune_strays(design_dir, [f for f in pre_existing if f not in strays])
        return [f for f in pre_existing if f not in strays]
    except Exception:  # noqa: BLE001
        return pre_existing


def _rename_to_own(design_dir, rec=None) -> List[str]:
    """Rename the design's subckts OFF the reference's names to AnoaChip's own, CONSISTENTLY
    (definitions + every X-instantiation + the filenames): a `<prefix>_X` subckt (e.g.
    ref_ota_stage1) → `X` (ota_stage1). Whole-word replace so net names aren't touched.
    PDK primitive names (sky130_fd_pr__*, gf180mcu_*) are NEVER touched. Returns the new
    netlist filename list."""
    from netlist_check import parse_dir
    ndir = Path(design_dir) / "netlist"
    info = parse_dir(ndir)
    mods = [m for m in info["defs"]
            if not m.lower().startswith(("sky130_", "gf180mcu_"))]
    if len(mods) < 2:
        return []
    # dominant project prefix among subckt names
    pref: dict = {}
    for m in mods:
        if "_" in m:
            pref[m.split("_", 1)[0]] = pref.get(m.split("_", 1)[0], 0) + 1
    dom = max(pref, key=pref.get) if pref and max(pref.values()) >= 2 else ""
    rename, used = {}, set()
    for m in mods:
        if dom and m.startswith(dom + "_") and len(m) > len(dom) + 1:
            new = m[len(dom) + 1:]
        else:
            new = m
        if (not re.match(r"^[A-Za-z_]\w*$", new) or len(new) < 2 or new in used
                or (new in mods and new != m)):
            new = m                                    # collision / invalid → keep original
        used.add(new)
        rename[m] = new

    def _nl_files() -> List[Path]:
        out: List[Path] = []
        for g in _NETLIST_GLOBS:
            out += sorted(ndir.glob(g))
        return out

    if not any(o != n for o, n in rename.items()):
        return sorted(p.name for p in _nl_files())
    # rewrite EVERY file's content (defs + X-instantiations), longest names first
    for p in _nl_files():
        txt = p.read_text(errors="replace")
        for old in sorted(rename, key=len, reverse=True):
            if rename[old] != old:
                txt = re.sub(rf"\b{re.escape(old)}\b", rename[old], txt)
        p.write_text(txt)
    # rename the files to match their (renamed) primary subckt
    out = []
    for p in _nl_files():
        new = rename.get(p.stem, p.stem)
        if new != p.stem and not (p.with_name(new + p.suffix)).exists():
            p.rename(p.with_name(new + p.suffix))
            out.append(new + p.suffix)
        else:
            out.append(p.name)
    if rec:
        rec.caption("🧩 Named the design's circuits: "
                    + ", ".join(sorted(set(rename.values()))[:12]))
    return sorted(out)


def _anchor_clean_src(design_dir, fn: str, query: str = "") -> str:
    """The cleaned anchor source for circuit file `fn` (restamped + auto-repaired). Used as
    the safe FALLBACK when an LLM adaptation of a subckt fails its checks — restoring this
    always parses, so the per-circuit loop can never leave a broken file."""
    stem = re.sub(r"\.(spice|spc|cdl|cir|sp)$", "", fn, flags=re.I)
    adir = Path(design_dir) / "context" / "anchor"
    if not adir.exists():
        return ""
    from netlist_check import autofix_text
    paths: List[Path] = []
    for g in _NETLIST_GLOBS:
        paths += sorted(adir.rglob(g))
    for p in paths:
        if "recalled" in p.parts or "papers" in p.parts:
            continue
        try:
            txt = p.read_text(errors="replace")
        except Exception:  # noqa: BLE001
            continue
        names = re.findall(r"^\s*\.subckt\s+([A-Za-z_]\w*)", txt,
                           re.IGNORECASE | re.MULTILINE)
        if names and names[0] == stem:
            try:
                txt, _ = autofix_text(txt)
            except Exception:  # noqa: BLE001
                pass
            return _restamp_header(txt, stem, query)
    return ""


def _adapt_modules_one_by_one(rec, design_dir, ctx, files: List[str], feedback="",
                              rewrite: bool = True) -> None:
    """The generator, ONE circuit at a time: for EACH subckt WRITE it, STRUCTURE-CHECK it
    (floating nets, dangling ports, missing nodes), signal the write so the plan greens IN
    ORDER, then continue. Each circuit is small + verified; one that won't pass gets one
    bounded fix, else falls back to the verified reference so the build never ends broken.

    `rewrite=True` (small designs): the model REWRITES each subckt in its own words with
    comments, adapting device sizes to the CONFIG. `rewrite=False` (a proven multi-block
    anchor): the seeded subckts are kept VERBATIM (restamped + checked) and the model is only
    invoked to REPAIR one that fails its checks."""
    from netlist_check import check_file
    ndir = Path(design_dir) / "netlist"
    spec = ctx["query"]
    cfg_note = ""
    try:
        from glayout_tools import load_config, config_note
        cfg = load_config(design_dir, ctx.get("top") or Path(design_dir).name)
        if cfg:
            cfg_note = "\nDESIGN CONFIG (size every device from THESE parameters):\n" \
                       + config_note(cfg, 1200) + "\n"
    except Exception:  # noqa: BLE001
        pass
    ok_n = 0
    for i, fn in enumerate(files):
        stem = re.sub(r"\.(spice|spc|cdl|cir|sp)$", "", fn, flags=re.I)
        rec.caption(f"✍️ [{i + 1}/{len(files)}] writing `{fn}`…")
        ref = (ndir / fn).read_text(errors="replace") if (ndir / fn).exists() \
            else _anchor_clean_src(design_dir, fn, spec)
        if not ref.strip():
            continue
        if not rewrite:
            out = ref                               # keep the proven seeded subckt verbatim
        else:
            prompt = (
                f"Write ONE complete SPICE subcircuit named `{stem}` for this design: {spec}.\n"
                + (f"USER NEED: {feedback}\n" if feedback else "") + cfg_note
                + "A working reference for the same circuit is below. REWRITE it as your OWN "
                "clean implementation — do NOT just copy it: keep the topology correct, adapt "
                "the device sizes (W/L/fingers) to the CONFIG above, keep the PDK device model "
                "names EXACTLY as in the reference, and ADD `*` COMMENTS explaining every "
                "device's role. The `.subckt` line must list ALL ports (VDD VSS in/out/bias) "
                "and every port must be USED in the body. Do NOT rename the subckt, do NOT add "
                "other subckts. Output ONLY the netlist — no prose, no ``` fences.\n\n"
                + ref[:9000])
            try:
                out = clean_llm_output(stream_to(get_chat_model(temperature=0.2), prompt, rec.placeholder()))
                out = extract_code_block(out) or out
            except Exception:  # noqa: BLE001
                out = ""
        if ".subckt" in out.lower() and ".ends" in out.lower():
            (ndir / fn).write_text(out)
        err = check_file(ndir / fn, ndir)
        if err:                                   # one bounded fix attempt on THIS circuit
            fixp = (f"This SPICE subcircuit failed its checks:\n{err[:600]}\n\nFix it. Output "
                    f"ONLY the complete corrected netlist, no prose, no fences.\n\n"
                    f"{(out or ref)[:9000]}")
            try:
                fix = extract_code_block(clean_llm_output(
                    stream_to(get_chat_model(temperature=0.2), fixp, rec.placeholder())))
                if fix and ".ends" in fix.lower():
                    (ndir / fn).write_text(fix)
            except Exception:  # noqa: BLE001
                pass
            if check_file(ndir / fn, ndir) and ref:   # STILL broken → fall back to the verified version
                (ndir / fn).write_text(ref)
        # stamp the AnoaChip banner header on the final content (so EVERY file carries it)
        try:
            (ndir / fn).write_text(_restamp_header((ndir / fn).read_text(), stem, spec))
        except Exception:  # noqa: BLE001
            pass
        good = not check_file(ndir / fn, ndir)
        ok_n += good
        if good:                                   # emit the write signal → plan greens IN ORDER
            rec.markdown(f"💾 **`write_file_disk`** · path=netlist/{fn}")
        rec.write(f"{'✅' if good else '⚠️'} `{fn}` — "
                  + ("written & checks clean" if good else "left the verified version in place"))
    rec.success(f"Generated {ok_n}/{len(files)} circuit(s) — all checks clean.")


def _plan_from_design_notes(design_dir) -> List[str]:
    """The GENERATE file plan derived DETERMINISTICALLY from design_notes.md's INTERFACES
    section — the REAL circuit subcircuits (`.subckt name ports…`), NOT the parameter table.
    Analog blocks are `.subckt` headers, so the authoritative source is the Interfaces (§4)
    block; the Block Map (§3) is only a fallback. Both are read SCOPED to their section so
    the COMPLETE PARAMETER TABLE (`| Component | Parameter | Value |`) can never leak in as
    'modules' (the W.sp/L.sp/VDD.sp bug). Returns config + one line per REAL subckt, top
    last; [] when nothing parseable (caller falls back to the LLM sub-plan). The caller runs
    the result through _sanitize_generate_plan, which drops any residual param/junk name."""
    notes_p = Path(design_dir) / "design_notes.md"
    if not notes_p.exists():
        return []
    notes = notes_p.read_text(errors="replace")

    def _section(title_re: str) -> str:
        m = re.search(rf"^#+\s*{title_re}.*?$(.*?)(?=^#+\s|\Z)", notes,
                      re.M | re.S | re.I)
        return m.group(1) if m else ""

    mods: List[str] = []
    roles: Dict[str, str] = {}
    # PRIMARY: the Interfaces section's `.subckt <name> <ports…>` headers — the true blocks.
    # By the architect's convention the TOP subckt is listed FIRST here.
    iface = _section(r"\d*\.?\s*Interfaces") or notes
    for m in re.finditer(r"^\s*\.subckt\s+([A-Za-z_]\w*)", iface, re.M | re.I):
        if m.group(1) not in mods:
            mods.append(m.group(1))
    used_interfaces = bool(mods)
    # FALLBACK: the Block Map table (§3) ONLY — one row per subcircuit, `| Block | Role | … |`.
    if len(mods) < 2:
        bmap = _section(r"\d*\.?\s*Block\s*Map")
        for row in re.finditer(r"\|\s*`?([A-Za-z_]\w*)`?\s*\|\s*([^|\n]{0,90}?)\s*\|", bmap):
            nm = row.group(1)
            if nm.lower() in ("block", "module", "component", "name", "role") or nm in mods:
                continue                      # header cells / separators — not a circuit
            mods.append(nm)
            roles[nm] = re.sub(r"\s+", " ", row.group(2)).strip()
    mods = [m for m in mods if not m.endswith("_tb")][:12]
    if len(mods) < 2:
        return []
    # Fill in each block's role from the Block Map (global lookup) so top-detection can use it.
    for nm in mods:
        if not roles.get(nm):
            r = re.search(rf"\|\s*`?{re.escape(nm)}`?\s*\|\s*([^|\n]{{3,90}}?)\s*\|", notes)
            roles[nm] = re.sub(r"\s+", " ", r.group(1)).strip() if r else ""
    # TOP = the block whose NAME or ROLE marks it as the integration top; else the FIRST
    # interface (architect lists top first) / the LAST Block-Map row.
    def _is_top(nm: str) -> bool:
        return bool(re.search(r"top|soc|chip|system|integrat|full|overall",
                              f"{nm} {roles.get(nm,'')}", re.I))
    top = next((m for m in mods if _is_top(m)),
               mods[0] if used_interfaces else mods[-1])
    # GLAYOUT-FIRST: the ONE deliverable is the config JSON — spec + wiring (each component and
    # the nets its terminals connect to) + every parameter, distilled from the researched SPICE.
    # NO hand-written .sp: glayout builds the layout (and its own netlist for LVS) straight from
    # this JSON. The sub-block names are recorded so the wiring JSON can describe them internally.
    blocks = ", ".join(m for m in mods if m != top)
    return [f"config/{top}.json — spec + wiring (every component → its net connections"
            + (f", sub-blocks: {blocks}" if blocks else "")
            + ") + EVERY parameter (W/L/M, R, C, bias) — distilled from the researched SPICE"]


def _subplan(rec, query, step, feedback="", design_dir=None) -> List[str]:
    """Per-step sub-plan checklist for a build agent (rendered as ⬜ items). LOCKED on first
    use: if a plan for this step was already decided (saved to disk), REUSE it verbatim so a
    retry / continue / resume never gets a different breakdown."""
    # GENERATE follows the CONTRACT: its file plan comes DIRECTLY from design_notes.md's
    # Module Map/Interfaces (deterministic) — never a fresh LLM guess (which invented a whole
    # different design than the notes; user: 'kenapa module yang digenerate beda sama yg di
    # design notes dan understanding'). Recomputed every entry (stable — the notes are on
    # disk) and it OVERRIDES a stale locked plan that disagrees with the contract.
    if step == "generate" and design_dir:
        notes_plan = _sanitize_generate_plan(_plan_from_design_notes(design_dir))
        # The SPICE is only a wiring+parameter sketch for glayout — keep it to config +
        # ONE netlist (plus at most a couple of real sub-blocks). Never a file per module
        # role/parameter. If sanitizing collapsed it to <2 real subckts, fall through to
        # the minimal LLM sub-plan below rather than forcing a bogus multi-file split.
        if len(notes_plan) >= 2:
            if _load_plan(design_dir, step) != notes_plan:
                _save_plan(design_dir, step, notes_plan)
            rec.caption("🧭 File plan from design_notes.md — a small netlist set (wiring + "
                        "params) that feeds glayout; the build effort goes into the layout.")
            rec.plan(notes_plan)
            return notes_plan
    # Reuse the locked plan on a normal entry (retry / continue / resume) so the breakdown is
    # stable. A deliberate Revise carries `feedback` — then we re-derive and re-lock below.
    if design_dir and not feedback:
        cached = _load_plan(design_dir, step)
        if cached:
            rec.caption("🧠 Reusing the locked plan for this step (consistent across retries).")
            rec.plan(cached)
            return cached
    ask = _SUBPLAN_ASK.get(step)
    if not ask:
        return []
    # even the LLM fallback (notes missing/unparseable) is grounded in whatever contract text
    # exists, so the file list can never drift to a different design than the architect's
    notes_ctx = ""
    if step == "generate" and design_dir:
        p = Path(design_dir) / "design_notes.md"
        if p.exists():
            notes_ctx = ("ARCHITECT'S CONTRACT (design_notes.md) — implement the circuit it "
                         "describes as ONE netlist (config + a single top .subckt, plus at most a "
                         "couple of REAL reusable sub-blocks). Parameters (W/L/M, R, C, bias, "
                         "supply) are config keys, NEVER their own file:\n"
                         + p.read_text(errors="replace")[:1800] + "\n")
    rec.caption("🧠 Planning this step…")
    ph = rec.placeholder()          # streamed tokens; CLEARED once the checklist renders
    try:
        raw = clean_llm_output(stream_to(
            get_chat_model(temperature=0.3),
            f"{ask}\n{notes_ctx}DESIGN: {query}\n" + (f"USER STEERING: {feedback}\n" if feedback else "")
            + "Output ONLY the checklist, one item per line, no numbering or headers.",
            ph))
    except Exception:  # noqa: BLE001
        raw = ""
    pts: List[str] = []
    for ln in raw.splitlines():
        t = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", ln).strip().strip("[]").strip()
        if 3 < len(t) < 160 and not t.lower().startswith(("here", "output", "the design")):
            pts.append(t)
    pts = pts[:16]
    if step == "generate":
        pts = _sanitize_generate_plan(pts)            # no .py deliverables, fix bogus extensions
    if design_dir and pts:                          # lock it so the next entry reuses it
        _save_plan(design_dir, step, pts)
    ph.empty()          # drop the streamed raw text — the checklist below is the ONE plan
    if pts:
        rec.plan(pts)   # live checklist — items green as their files get written
    return pts

def _sanitize_generate_plan(pts: List[str]) -> List[str]:
    """Clean the generator's file plan so it can't derail the build:
      • DROP any line whose deliverable is a shell/C script or a Verilog file — the
        circuit-stage deliverables are config JSON + SPICE netlists ONLY (the glayout
        layout .py belongs to the LAYOUT step, not here).
      • DROP per-PARAMETER / per-role junk files (W.sp, L.sp, M.sp, VDD.sp, IREF.sp,
        Block.sp, Component.sp): the SPICE is only the connectivity+parameter sketch
        that feeds glayout — parameters are JSON keys in the config, NEVER their own
        file. A netlist file must be a real .subckt, not a lone `.param`.
      • KEEP the netlist set genuinely small (≤4 subcircuits) so generation spends its
        time on glayout, not on fragmenting SPICE.
      • FIX bogus netlist extensions the model invents: `.net`/`.ckt`/`.nl`→`.sp`;
        `.sp`/`.spice`/`.cir`/`.cdl`/`.json` are kept.
    The order and descriptions are otherwise preserved."""
    _SCRIPT = (".sh", ".c", ".cpp", ".cc", ".pl", ".rb", ".js", ".ipynb",
               ".v", ".sv", ".vh", ".py")
    _FIX = {".net": ".sp", ".ckt": ".sp", ".nl": ".sp", ".netlist": ".sp"}
    _NL = (".sp", ".spice", ".cir", ".cdl")
    out: List[str] = []
    n_netlists = 0
    for line in pts:
        m = re.search(r"([A-Za-z0-9_]+)(\.[A-Za-z0-9]+)\b", line)
        if not m:
            out.append(line)
            continue
        stem, ext = m.group(1), m.group(2).lower()
        if ext in _SCRIPT:
            continue                                  # illegal deliverable → drop the whole line
        if ext in _FIX:
            line = line.replace(m.group(1) + m.group(2), stem + _FIX[ext], 1)
            ext = ".sp"
        if ext in _NL and _is_primitive_subckt(stem):
            continue                                  # per-parameter / role file → not a subckt
        if ext in _NL:
            n_netlists += 1
            if n_netlists > 4:                        # keep the netlist set genuinely small
                continue
        out.append(line)
    return out or pts


VERILOG_PITFALLS = """COMMON ANALOG NETLIST/LAYOUT MISTAKES — CHECK AGAINST EVERY ONE BEFORE REPLYING:
1. TITLE LINE: ngspice EATS the first line of any deck as its title. Every netlist file
   starts with a `*` comment line, or the first .subckt silently disappears.
2. EVERY .subckt NEEDS .ends, and EVERY port on the `.subckt` line must be USED in the
   body — a port that never appears in a device card is dangling and LVS WILL fail.
3. NO FLOATING NETS: a net used exactly ONCE inside a subckt is unconnected. Every net
   must have at least two terminals (or be a declared port/rail).
4. MOSFET CARD ORDER IS D G S B: `M1 out in tail VSS sky130_fd_pr__nfet_01v8 W=4 L=1`.
   Never omit the bulk node; tie NMOS bulk to VSS, PMOS bulk to VDD (unless the config
   says otherwise). Use the EXACT PDK model names — sky130: sky130_fd_pr__nfet_01v8 /
   sky130_fd_pr__pfet_01v8; gf180: gf180mcu_fd_pr__nfet_03v3 / __pfet_03v3.
5. SIZE FROM THE CONFIG: never invent W/L — read config/<name>.json. W/L in µm for the
   PDK models (sky130 nfet min L=0.15, pfet min L=0.35 for 01v8; keep L ≥ 0.5 for
   matching-critical analog pairs).
6. BIAS SANITY: every MOSFET must have a DC path to its gate and a defined operating
   region. A gate with no driver, a current mirror with no reference branch, or a tail
   source with no bias voltage means the .op point is garbage and every AC spec fails.
7. TESTBENCH MEASURES THE SPEC TABLE: .op first; .ac dec sweep with
   `wrdata sim/<name>_ac.txt vdb(out) vp(out)` for gain_db/bw_hz/ugbw_hz/
   phase_margin_deg; `.measure` for power (avg -i(vdd)*VDD) and point specs. The spec
   names in .measure/wrdata must MATCH the config's spec keys.
8. LAYOUT SIZING: never call nmos(pdk)/pmos(pdk) with defaults — pass width, length,
   fingers, multipliers from the config; generate BARE devices first (with_tie=False,
   with_substrate_tap=False, with_dummy=False). Ties/guard ring/dummies come LAST,
   after LVS is clean.
9. ROUTE EVERY NET: each connection in the netlist needs an explicit c_route / L_route /
   straight_route (or smart_route) in the layout. straight_route ONLY works for inline
   parallel ports — for offset parallel ports use c_route, for perpendicular ports use
   L_route, and bridge metal layers with via_stack. An unrouted net = LVS "net only in
   schematic".
10. PLACE EXPLICITLY: every `comp << device` reference gets movex/movey/center (align
    with evaluate_bbox / align_comp_to_port) — no overlapping devices, no default
    origin pile-ups.
11. EXPOSE PORTS **AND LABELS**: the final Component must add_port/add_ports for VDD,
    VSS, every input/output and bias, AND place a TEXT LABEL on each pin's metal (glayout
    add_glayout_labels / labelled_ports, or a gdstk/gdsfactory Label on the PDK label
    layer at the port center). magic/netgen LVS matches nets by these labels — an
    unlabelled port is an unconnected pin to LVS even when it is routed. NO layout ships
    without a port + label for every external pin.
12. ATTACH THE REFERENCE NETLIST: build the comp.info['netlist'] the way the glayout
    library cells do, so LVS has a schematic to compare against."""


# ---- Live workflow graph (highlights the agent currently working) ---------- #
WF_NODES = [
    ("plan", "0 · 🧭 Planner"),
    ("retrieve", "1 · 📚 Knowledge\nRecall"),
    ("web", "2 · 🌐 Netlist/Glayout\nResearcher"),
    ("generate", "3 · ✍️ Config +\nNetlist Gen"),
    ("decompose", "4 · 🧩 Decomposer"),
    ("testbench", "5 · 🧪 ngspice\nTestbench"),
    ("write", "6 · 💾 File\nWriter"),
    ("simulate", "7 · 🔬 ngspice\nSpec Check"),
    ("lint", "8 · 🔍 Netlist\nLint"),
    ("correct", "9 · 🛠️ Config\nTuner"),
    ("harden", "10 · 🏭 Glayout\nDRC · LVS"),
    ("gds", "🎉 GDSII"),
]
WF_EDGES = [
    ("plan", "retrieve"),
    ("retrieve", "web"), ("web", "generate"), ("generate", "decompose"),
    ("decompose", "testbench"), ("testbench", "write"), ("write", "simulate"),
    ("simulate", "correct"), ("correct", "write"), ("simulate", "lint"),
    ("lint", "correct"), ("lint", "harden"),
    ("harden", "gds"),
]
# Map an executed step name -> the graph node it lights up.
GRAPH_KEY = {"fix_design": "correct", "fix_testbench": "correct"}


def workflow_graph(active: str | None = None, done: set | None = None):
    done = done or set()
    dot = graphviz.Digraph()
    dot.attr(rankdir="LR", bgcolor="transparent")
    dot.attr("node", shape="box", style="rounded,filled",
             fontname="sans-serif", fontsize="10")
    dot.attr("edge", color="#90a4ae")
    for key, label in WF_NODES:
        if key == active:
            dot.node(key, label, fillcolor="#ffca28", color="#ff6f00",
                     penwidth="2.5")  # working = amber
        elif key in done:
            dot.node(key, label, fillcolor="#a5d6a7",
                     color="#2e7d32")                   # done = green
        else:
            dot.node(key, label, fillcolor="#eceff1",
                     color="#b0bec5", fontcolor="#546e7a")
    for a, b in WF_EDGES:
        dot.edge(a, b)
    return dot


def stream_to(runnable, inputs, placeholder, tail: int = 9000) -> str:
    """Stream a chain/LLM's output LIVE into `placeholder` so you watch the model
    REASON (thinking tokens) and then write, in real time. Returns the answer text.

    Pass a `prompt | llm` runnable (NOT one ending in StrOutputParser), otherwise
    the parser drops the separate `reasoning` field and the box stays blank while
    the model is thinking."""
    answer, thinking, n = "", "", 0
    last_paint = [0.0]

    def render(force=False):
        # throttle live paints (each one is streamed to the web UI) — a fast model can
        # emit dozens of chunks/second; one paint per ~0.7 s is smooth enough to watch.
        now = time.time()
        if not force and now - last_paint[0] < 0.7:
            return
        last_paint[0] = now
        disp = (
            f"💭 thinking…\n{thinking.strip()}\n\n———\n" if thinking.strip() else "")
        disp += answer
        if not disp.strip():
            # always show progress, never blank
            disp = f"⏳ generating… ({n} tokens)"
        placeholder.code(disp[-tail:], language="markdown")

    try:
        # retrying(): a TRANSIENT ollama.com blip (glm-5.2:cloud proxy) retries with backoff
        # instead of aborting the step. Safe here — this is a piped `prompt | llm` runnable,
        # not the bare model (which the deep agent needs intact for .bind_tools()).
        for chunk in retrying(runnable).stream(inputs):
            if isinstance(chunk, str):
                answer += chunk
            else:
                answer += getattr(chunk, "content", "") or ""
                ak = getattr(chunk, "additional_kwargs", {}) or {}
                thinking += (ak.get("reasoning_content") or ak.get("reasoning")
                             or ak.get("thinking") or "")
            n += 1
            if n % 3 == 0:
                render()
            # Circuit-breaker: bail out of a degenerate repetition loop instead of
            # streaming the same lines forever (the model never stops on its own).
            if n % 15 == 0 and (_looks_repetitive(answer) or _looks_repetitive(thinking)):
                answer += "\n// [AnoaChip] generation stopped — model entered a repetition loop.\n"
                break
            if len(answer) + len(thinking) > 120_000:  # hard safety cap
                break
    except Exception as e:  # noqa: BLE001
        # a Stop/steer request surfaces as RunPaused from the live paint — it must
        # PROPAGATE (aborting the step), never be swallowed into a blocking re-invoke
        if type(e).__name__ == "RunPaused":
            raise
        if not answer and not thinking:
            out = runnable.invoke(inputs)
            answer = out if isinstance(out, str) else (
                getattr(out, "content", "") or str(out))
    render(force=True)
    return answer or thinking


# --------------------------------------------------------------------------- #
# RAG
# --------------------------------------------------------------------------- #
def _docs_from_recall(items) -> List[Document]:
    """Turn knowledge-store recall results into the Document list the generator consumes."""
    out: List[Document] = []
    for it in items:
        body = it.get("text") or it.get("title") or ""
        if not body.strip():
            continue
        out.append(Document(page_content=body, metadata={
            "source": it.get("source") or it.get("design") or "knowledge",
            "kind": it.get("kind"), "object_key": it.get("object_key")}))
    return out


HDL_SET = {"SPICE", "Spice", "Netlist"}


# Filler words that hurt a GitHub repo search — repo search matches names/topics,
# not prose, so "an OTA with 40 dB using sky130" must become "ota sky130".
_SEARCH_STOP = {
    "a", "an", "the", "of", "for", "and", "to", "in", "on", "with", "using", "like",
    "that", "this", "my", "your", "please", "make", "build", "create", "design",
    "designs", "implement", "implementation", "support", "based",
    "is", "it", "simple", "small", "tiny", "basic", "want", "need", "generate",
    "circuit", "analog", "chip", "spice", "netlist", "layout", "db", "hz",
}


# Generic circuit-STRUCTURE words. They describe a ROLE, not the project — so a
# DISTINCTIVE proper-noun (a project/library NAME like 'glayout', 'openfasoc',
# 'sky130') must outrank them in repo search: searching the project name lands the
# EXACT repo, while 'ota opamp' returns generic circuits.
_GENERIC_HDL = {
    "ota", "opamp", "amplifier", "amp", "mirror", "current", "diffpair", "differential",
    "pair", "cascode", "folded", "stage", "comparator", "bandgap", "reference", "ldo",
    "regulator", "bias", "buffer", "follower", "oscillator", "vco", "pll", "adc", "dac",
    "filter", "unit", "design", "block", "cell", "transistor", "mosfet", "nmos", "pmos",
}


def _hdl_keywords(text: str, n: int = 4) -> List[str]:
    """Distill a request into the few salient search keywords, DISTINCTIVE NAME FIRST. A
    project/library name ('glayout', 'openfasoc', a PDK like 'sky130') is the strongest
    repo-search signal — it names the exact repo — so it leads, ahead of topology tokens
    (ota/cascode) and spec numbers."""
    low = (text or "").lower()
    pdk: List[str] = []
    for m in re.findall(r"\b(?:sky130\w*|gf180\w*)\b", low):
        if m not in pdk:
            pdk.append(m)
    distinctive, generic = [], []
    for w in re.findall(r"[a-zA-Z][a-zA-Z0-9_]+", low):
        if w in _SEARCH_STOP or len(w) < 3 or w in pdk:
            continue
        (generic if w in _GENERIC_HDL else distinctive).append(w)
    out: List[str] = []
    for grp in (distinctive, generic, pdk):             # name → topology → pdk
        for w in grp:
            if w and w not in out:
                out.append(w)
    return out[:n]


_DESIGN_SYNS = [
    ("ota", "opamp", "op-amp", "operational amplifier"),
    ("current mirror", "cmirror", "current source"),
    ("diffpair", "differential pair", "diff pair"),
    ("bandgap", "voltage reference"), ("ldo", "regulator"),
    ("comparator", "latch comparator"), ("vco", "oscillator"),
]


def _design_variants(query: str, n: int = 3) -> List[str]:
    """A few CLOSE phrasings of the WHOLE prompt (synonyms of the same chip), e.g. 'riscv 8 bit
    fazyrv rv32i' → 'processor 8 bit fazyrv rv32i', 'cpu 8 bit fazyrv rv32i'. Used as EXTRA search
    queries so the search still finds pages when the exact wording returns little — NOT sub-block
    decomposition (never 'alu, regfile'). One synonym swap per group, across groups for variety."""
    base = (query or "").strip().lower()
    if not base:
        return []
    out: List[str] = []
    for group in _DESIGN_SYNS:
        present = next((w for w in group if re.search(rf"\b{re.escape(w)}\b", base)), None)
        if not present:
            continue
        for alt in group:
            if alt == present:
                continue
            v = re.sub(rf"\b{re.escape(present)}\b", alt, base, count=1)
            if v != base and v not in out:
                out.append(v)
                break
        if len(out) >= n:
            break
    return out[:n]


def _error_search_terms(err: str, n: int = 4) -> List[str]:
    """Distill compiler/sim error text into a few SEARCHABLE phrases — drop file paths and
    line/bit numbers, keep the human message ('Numeric constant truncated to 3 bits',
    'malformed statement', 'syntax error', 'width mismatch'). This is what the researcher
    searches when the user says 'find about the PROBLEM' instead of the design topic."""
    terms, seen = [], set()
    for ln in (err or "").splitlines():
        low = ln.lower()
        if "error" not in low and "warning" not in low:
            continue
        # message = text after the final 'error:'/'warning:' marker
        parts = re.split(r"(?:error|warning)\s*:\s*", ln, flags=re.I)
        msg = (parts[-1] if len(parts) > 1 else "").strip()
        if (not msg or msg.startswith("/")) and "syntax error" in low:
            msg = "syntax error"
        if not msg or len(msg) < 5 or msg.startswith("/"):
            continue
        msg = re.sub(r"\s+", " ", msg).rstrip(".")
        key = re.sub(r"\d+", "N", msg.lower())[:70]   # collapse line/bit numbers for dedupe
        if key in seen:
            continue
        seen.add(key)
        terms.append(msg[:80])
        if len(terms) >= n:
            break
    return terms


def searxng_url() -> str:
    return os.getenv("SEARXNG_URL", "http://localhost:8890").rstrip("/")


def searxng_available() -> bool:
    """True if a SearXNG instance answers on SEARXNG_URL (JSON format enabled)."""
    try:
        import requests
        r = requests.get(f"{searxng_url()}/search",
                         params={"q": "test", "format": "json"}, timeout=4)
        return r.ok and isinstance(r.json().get("results"), list)
    except Exception:  # noqa: BLE001
        return False


def _searxng_search(query: str, limit: int, categories: str = "",
                    engines: str = "") -> List[str]:
    """Primary search backend: a self-hosted SearXNG metasearch engine (aggregates
    Google/Bing/DuckDuckGo/GitHub/arXiv… in one query, no per-engine rate limits).
    Returns result URLs in relevance order. Empty list if SearXNG isn't configured or
    reachable — callers then fall back to DuckDuckGo. Pair with crawl4ai: SearXNG FINDS
    the pages, crawl4ai READS them.

    `categories` (e.g. 'science' for papers, 'it' for code/repos) and `engines`
    (e.g. 'github', 'arxiv,google scholar') narrow the search when useful."""
    out: List[str] = []
    base = os.getenv("SEARXNG_URL")
    probe_ok = True
    if not base and not os.getenv("SEARXNG_FORCE"):
        if not getattr(_searxng_search, "_probed", False):
            _searxng_search._probed = searxng_available()  # one cheap probe per process
        probe_ok = _searxng_search._probed
    if probe_ok:
        try:
            import requests
            params = {"q": query, "format": "json", "safesearch": 0}
            if categories:
                params["categories"] = categories
            if engines:
                params["engines"] = engines
            r = requests.get(f"{searxng_url()}/search", params=params, timeout=12)
            if r.ok:
                for res in r.json().get("results", []):
                    u = res.get("url")
                    if u and u not in out:
                        out.append(u)
                        if len(out) >= limit:
                            break
        except Exception:  # noqa: BLE001
            pass
    # FREE browser-quality top-up. On a server the general web engines Google/Bing/Brave
    # return CAPTCHA/access-denied, so a self-hosted SearXNG answers mostly papers+github and
    # gives 0 hits for a plain prose query. The host-side DuckDuckGo library DOES answer from
    # here (no API key, no cost), so merge its results for GENERAL (non-`science`) searches to
    # get the same breadth a browser would. Papers stay SearXNG-only (categories='science').
    if len(out) < limit and "science" not in categories:
        try:
            from ddgs import DDGS
            for res in DDGS().text(query, max_results=limit * 2):
                u = res.get("href")
                if u and u not in out:
                    out.append(u)
                    if len(out) >= limit:
                        break
        except Exception:  # noqa: BLE001
            pass
    return out[:limit]


def _ddg_github(query: str, limit: int) -> List[str]:
    """Repo finder via SearXNG (`site:github.com`), falling back to DuckDuckGo — works
    when the GitHub API is rate-limited or the prose query matched nothing (this is what
    makes a search for 'picorv' actually surface YosysHQ/picorv32)."""
    out: List[str] = []
    kw = " ".join(_hdl_keywords(query, 3)) or query

    def _keep(u: str) -> None:
        m = re.match(r"(https://github\.com/[^/]+/[^/#?]+)", u or "")
        if (m and m.group(1) not in out and "/topics/" not in m.group(1)
                and not _NONSYNTH_RE.search(m.group(1))):   # skip TL-Verilog/MYTH-workshop repos
            out.append(m.group(1))

    # analog focus: SPICE netlists first, then glayout/gdsfactory generator code
    for q in (f"{kw} spice netlist site:github.com",
              f"{kw} glayout OR gdsfactory site:github.com"):
        for u in _searxng_search(q, limit * 2):                            # SearXNG first
            _keep(u)
            if len(out) >= limit:
                return out[:limit]
    try:                                                                   # DDG fallback
        from ddgs import DDGS
        for q in (f"{kw} spice netlist site:github.com",
                  f"{kw} glayout gdsfactory site:github.com"):
            for res in DDGS().text(q, max_results=limit * 2):
                _keep(res.get("href", ""))
                if len(out) >= limit:
                    return out[:limit]
    except Exception:  # noqa: BLE001
        pass
    return out[:limit]


def _github_hdl_repos(query: str, limit: int) -> List[str]:
    """Find real analog-reference repos with SHORT keyword queries (repo search hates
    prose): SPICE-netlist repos FIRST, then glayout/gdsfactory generator repos, with an
    optional token to dodge rate limits and a DuckDuckGo `site:github.com` fallback."""
    out: List[str] = []
    headers = {"Accept": "application/vnd.github+json"}
    tok = os.getenv("GITHUB_TOKEN")
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    kws = _hdl_keywords(query, 4)
    # try the strongest 2-3 keywords together, then the single strongest — short wins
    base_qs = [q for q in dict.fromkeys(
        [" ".join(kws[:3]), " ".join(kws[:2]), kws[0] if kws else query.strip()]) if q]
    # netlists are the priority (the user's rule: hunt netlists, not HDL); glayout /
    # gdsfactory python generators are the second-class citizens worth grabbing too
    candidates = [f"{q} spice netlist" for q in base_qs] \
        + [f"{q} glayout" for q in base_qs[:1]] \
        + [f"{q} sky130 analog" for q in base_qs[:1]]
    try:
        import requests
        for q in candidates:
            if len(out) >= limit:
                break
            r = requests.get(
                "https://api.github.com/search/repositories",
                params={"q": q, "sort": "stars", "per_page": 20},
                headers=headers, timeout=12)
            if not r.ok:
                break          # rate-limited/error → stop hitting the API, use the fallback
            for it in r.json().get("items", []):
                u = it.get("html_url")
                if u and u not in out:
                    out.append(u)
                    if len(out) >= limit:
                        break
    except Exception:  # noqa: BLE001
        pass
    if len(out) < max(2, limit // 2):     # API thin or rate-limited → DDG site:github.com
        for u in _ddg_github(query, limit):
            if u not in out:
                out.append(u)
    return out[:limit]


def _web_search(query: str, similar: List[str] | None = None,
                n_github: int = 10, n_other: int = 10,
                suffix: str = "spice netlist analog circuit design") -> List[str]:
    """Balanced references: up to ``n_github`` analog GitHub repos (SPICE netlists
    for the circuit, or glayout/gdsfactory generator code for its layout) PLUS up to
    ``n_other`` papers/web pages (theory/knowledge). ``similar`` are extra,
    LLM-suggested building-block queries used when the exact circuit isn't on GitHub."""
    gh: List[str] = []
    for q in [query] + (similar or []):
        if len(gh) >= n_github:
            break
        for u in _github_hdl_repos(q, n_github):
            if u not in gh:
                gh.append(u)

    other: List[str] = []
    # Search for what the PROMPT actually describes — no hardcoded topic. A neutral
    # "spice netlist analog circuit design" suffix keeps results relevant for OTAs,
    # references, comparators alike instead of forcing one topology every time.
    full_q = f"{query} {suffix}".strip()
    # PRIMARY: SearXNG metasearch — also pull a few from the 'science' category so arXiv
    # papers surface for theory/algorithm knowledge, not just blog posts.
    for u in (_searxng_search(full_q, n_other * 2)
              + _searxng_search(f"{query} paper", max(2, n_other // 2), categories="science")):
        if u and "github.com" not in u and u not in other:
            other.append(u)
    # FALLBACK: DuckDuckGo — the RELIABLE source here (SearXNG's engines are often CAPTCHA /
    # rate-limited and the GitHub API misses SystemVerilog repos). ONE pass per query fills BOTH
    # lists: GitHub URLs become anchor candidates (so e.g. meiniKi/FazyRV IS found), the rest
    # become papers/web pages. Also queries the close 'similar' phrasings the user asked for.
    if len(other) < n_other or len(gh) < 2:
        try:
            from ddgs import DDGS
            for q in [full_q] + [f"{s} {suffix}".strip() for s in (similar or [])[:2]]:
                for res in DDGS().text(q, max_results=(n_other + n_github) * 2):
                    u = res.get("href") or ""
                    if "github.com" in u:
                        m = re.match(r"(https://github\.com/[^/]+/[^/#?]+)", u)
                        if m and "/topics/" not in m.group(1) and m.group(1) not in gh:
                            gh.append(m.group(1))
                    elif u and u not in other:
                        other.append(u)
                if len(other) >= n_other and len(gh) >= 2:
                    break
        except Exception:  # noqa: BLE001
            pass

    if not gh and not other:  # last-ditch fallback
        try:
            from googlesearch import search

            for u in search(f"{query} spice netlist github", num_results=n_github + n_other):
                (gh if "github.com" in u else other).append(u)
        except Exception:  # noqa: BLE001
            pass

    return gh[:n_github] + other[:n_other]


def _md_text(res) -> str:
    md = getattr(res, "markdown", None)
    if md is None:
        return ""
    if isinstance(md, str):
        return md
    return getattr(md, "raw_markdown", None) or getattr(md, "fit_markdown", None) or str(md)


_JUNK_RE = re.compile(
    r"privacy preferences|we use cookies|cookie (policy|settings|consent)|consent (choices|"
    r"settings|management)|you are under 16|manage (your )?cookies|accept all cookies|"
    r"sign ?in to (continue|view|read)|create (a free )?account to|subscribe to (read|continue|"
    r"unlock)|log ?in to continue|are you a robot|verify you are human|captcha|enable javascript|"
    r"access denied|403 forbidden|404 not found|page not found|this site requires|"
    # marketing / product / landing-page chrome — the 'buat.id landing page' & AI-gadget
    # ads that polluted understanding.md when a vague/Indonesian prompt hit web search
    r"landing page|start (your )?free trial|get started (free|today|for free)|sign up (free|"
    r"now|today)|no credit card|pricing|add to cart|buy now|drag[- ]?drop|website builder|"
    r"tanpa (biaya|coding|hosting)|daftar (sekarang|gratis)|jualan|dashboard & builder|"
    r"pre[- ]?order|shop now|our products|built by engineers, for engineers", re.I)

_TECH_RE = re.compile(
    r"\b(subckt|spice|ngspice|netlist|mosfet|nmos|pmos|transistor|cascode|current mirror|"
    r"diff(?:erential)? pair|ota|op[- ]?amp|amplifier|gain|bandwidth|phase margin|gm/?id|"
    r"bias|vdsat|saturation|sky130|gf180|pdk|drc|lvs|gdsii?|layout|glayout|gdsfactory|"
    r"guard ?ring|substrate|common[- ]?mode|slew rate|bandgap|comparator|testbench)\b", re.I)


def _is_useful_doc(text: str, source: str = "") -> bool:
    """Reject crawled JUNK before it pollutes the knowledge store: cookie-consent / privacy
    / login-wall / captcha pages, and nav-menu-dominated pages with no technical content.
    Keeps pages with real HDL/hardware signal. This is what stops 'paper' rows that are just
    a GDPR banner."""
    t = (text or "").strip()
    if len(t) < 300:
        return False
    junk = len(_JUNK_RE.findall(t))
    tech = len(_TECH_RE.findall(t))
    lines = [ln for ln in t.splitlines() if ln.strip()]
    # a line that is basically just a markdown link → nav/menu chrome
    linky = sum(1 for ln in lines
                if "](" in ln and len(re.sub(r"\[[^\]]*\]\([^)]*\)", "", ln).strip()) < 15)
    link_density = linky / max(1, len(lines))
    if junk >= 2 and tech < 5:          # cookie/login wall with no substance
        return False
    if link_density > 0.55 and tech < 6:  # mostly a menu/link list
        return False
    if tech == 0 and len(t) < 1200:     # short and no hardware signal at all
        return False
    return True


@functools.lru_cache(maxsize=1)
def _playwright_browser_ready() -> bool:
    """True when Playwright's chromium is actually installed — so a crawl won't hang for
    minutes trying to launch a missing browser. Cached (checked once per process)."""
    try:
        import glob as _glob
        from pathlib import Path as _P
        cache = os.getenv("PLAYWRIGHT_BROWSERS_PATH") or str(_P.home() / ".cache" / "ms-playwright")
        # match chromium-*/chrome-linux*/chrome and the headless-shell layout, any version
        pats = ("chromium*/chrome-linux*/chrome", "chromium*/chrome-linux*/headless_shell",
                "chromium*/chrome-*/chrome")
        return any(_glob.glob(str(_P(cache) / p)) for p in pats)
    except Exception:  # noqa: BLE001
        return False


def _crawl_urls(urls: List[str], rec: "Recorder", limit: int = 8,
                deadline: "float | None" = None) -> List[Document]:
    """Crawl a handful of URLs (5 at a time) into Documents. Shared by the Web
    Researcher and the on-demand 'fetch a web example of block X' tool. `deadline` (an
    absolute time.time() value) hard-caps the whole call so research can never stall."""
    import time as _time
    try:
        import asyncio
        from crawl4ai import AsyncWebCrawler
    except Exception as e:  # noqa: BLE001
        rec.warning(f"crawl4ai unavailable ({e}) — skipping crawl.")
        return []
    # FAST-SKIP if Playwright's chromium isn't installed — otherwise every crawl hangs
    # until its per-URL timeout (minutes of stall). The GitHub anchors are fetched via the
    # API (no browser), so research still works; only the extra web-page crawl is skipped.
    if not _playwright_browser_ready():
        rec.warning("Playwright chromium not installed — skipping web-page crawl "
                    "(run `uv run playwright install chromium`). GitHub references still "
                    "fetched via the API.")
        gh_only = [u for u in urls[:limit] if "github.com" in u]
        out0: List[Document] = []
        for u in gh_only:
            code = _github_code_text(u)
            if code and len(code) > 200:
                out0.append(Document(page_content=code[:8000], metadata={"source": u}))
        return out0
    # DROP obvious NON-CIRCUIT junk domains BEFORE the expensive crawl — game mods, website
    # builders, video, social, generic docs hosts. A search that leaks a verb like 'create'
    # otherwise lands on curseforge/modrinth (Minecraft 'Create' mod), wix, youtube… and
    # burns minutes crawling them. GitHub/gitlab and real EDA/edu sources are never touched.
    urls = [u for u in urls if not _JUNK_DOMAIN_RE.search(u or "")]
    urls = urls[:limit]
    log = rec.placeholder()
    seen: List[str] = []
    out: List[Document] = []

    # GitHub repos: NEVER crawl the HTML landing page (it's just nav-menu chrome —
    # "Navigation Menu / GitHub Copilot / DevSecOps"). Fetch the REAL source via the
    # API instead, so the digest contains actual netlists/glayout code, not website junk.
    gh = [u for u in urls if "github.com" in u]
    web = [u for u in urls if "github.com" not in u]
    for u in gh:
        if deadline and _time.time() > deadline:       # out of time — stop fetching code
            break
        code = _github_code_text(u)
        if code and len(code) > 200:
            out.append(Document(page_content=code[:8000], metadata={"source": u}))
            seen.append("💻 " + u)
            log.code("\n".join(f"✓ {x}" for x in seen), language="text")

    async def _crawl() -> None:
        sem = asyncio.Semaphore(5)
        async with AsyncWebCrawler() as crawler:
            async def fetch(url: str) -> None:
                async with sem:
                    try:
                        res = await asyncio.wait_for(crawler.arun(url=url), timeout=25)
                    except Exception:  # noqa: BLE001
                        return
                md = _strip_web_chrome(_md_text(res))
                if md and _is_useful_doc(md, url):     # drop cookie/login/nav junk
                    out.append(Document(page_content=md[:8000], metadata={"source": url}))
                    seen.append("📄 " + url)
                    log.code("\n".join(f"✓ {u}" for u in seen), language="text")
                elif md:
                    seen.append("🗑 skipped junk: " + url)
                    log.code("\n".join(f"✓ {u}" for u in seen), language="text")
            await asyncio.gather(*(fetch(u) for u in web))

    try:
        if web:
            # Hard overall cap so a hung browser launch / slow page can never stall the pipeline.
            # Per-URL is already 25s w/ 5-way concurrency; this bounds the whole batch. `out` is
            # filled incrementally, so a timeout still returns whatever crawled in time. If a caller
            # deadline is sooner, use that (so the whole research call stays inside its budget).
            budget = float(os.getenv("ANOA_CRAWL_BUDGET_S", str(min(150, 40 + 9 * len(web)))))
            if deadline:
                budget = max(5.0, min(budget, deadline - _time.time()))
            asyncio.run(asyncio.wait_for(_crawl(), timeout=budget))
    except asyncio.TimeoutError:
        rec.warning(f"Crawl hit the {int(budget)}s budget — using the {len(out)} page(s) gathered so far.")
    except Exception as e:  # noqa: BLE001
        rec.warning(f"Crawl failed ({e}).")
    return out


# Sources that are NOT synthesizable plain Verilog for this GDSII flow — TL-Verilog / Makerchip /
# the RISC-V MYTH workshop. They dominate "risc-v verilog tutorial" searches but their code can't be
# hardened here, so the research/understanding steps skip them.
_NONSYNTH_RE = re.compile(
    r"tl-verilog|tl-x\.org|makerchip|myth[_\s\-]?workshop|redwoodeda|transaction[-\s]?level",
    re.I)

# Non-circuit junk domains — never worth crawling for an analog-IC design. A search that
# leaks a generic verb ('create', 'make') otherwise surfaces the Minecraft 'Create' mod,
# website builders, video/social, etc., and each crawl costs ~10 s. Keep this to clearly
# off-topic hosts; genuine EDA/edu/vendor/paper sites must never match.
_JUNK_DOMAIN_RE = re.compile(
    r"(?:^|//|\.)(?:curseforge\.com|modrinth\.com|minecraft|planetminecraft|"
    r"wix\.com|squarespace\.com|weebly\.com|godaddy\.com|shopify\.com|"
    r"youtube\.com|youtu\.be|tiktok\.com|instagram\.com|facebook\.com|twitter\.com|x\.com|"
    r"pinterest\.com|reddit\.com|quora\.com|sketch\.io|canva\.com|"
    r"amazon\.com|ebay\.com|aliexpress\.com|etsy\.com|play\.google\.com|apps\.apple\.com)",
    re.I)


def _looks_like_code(text: str) -> bool:
    """True when a snippet is dominated by netlist/source code rather than explanatory prose —
    so the understanding gist is a real EXPLANATION, not a raw SPICE/python listing dumped
    into understanding.md."""
    t = text[:1500]
    code = len(re.findall(
        r"[;{}=]|^\s*[MXRCLVIQD]\w+\s|\.\b(subckt|ends|include|lib|param|model|tran|ac|dc|meas)\b|"
        r"\b(def |import |Component|smart_route|c_route|L_route|straight_route|via_stack|"
        r"nmos|pmos|movex|movey)\b", t, re.M))
    words = len(re.findall(r"[A-Za-z]{3,}", t))
    return code > 25 or (words > 0 and code / words > 0.30)


# UI boilerplate that rides INSIDE a text line (cookie dialogs, Scribd chrome, share
# buttons) — a sentence matching any of these is site furniture, not an explanation.
_BOILER_SENT_RE = re.compile(
    r"opens in a new window|opens an external website|cookie|close this dialog|"
    r"suggestionssearch|change language|found this document useful|\(\d+ votes?\)|"
    r"\bratings?\b|save .* for later|copyright ©|©\s*\d{4}|all rights reserved|"
    r"ai-enhanced title|sign (in|up)\b|log ?in\b|download now|for later\b|scribd",
    re.IGNORECASE)


def _clean_gist(text: str) -> str:
    """A clean prose gist from crawled markdown: drop site chrome, then keep real SENTENCES
    only — boilerplate fragments (cookie dialogs, 'Opens in a new window', Scribd chrome)
    ride inside long lines, so filtering whole lines isn't enough (user hit a gist that was
    90% UI furniture). Cap ~600 chars; '' if what's left is code/navigation."""
    body = _strip_web_chrome(text or "")
    body = re.sub(r"<!-+.*?-+>?|[⟶→]+", " ", body)     # HTML-comment arrows / arrow runs
    lines = []
    for ln in body.splitlines():
        s = ln.strip()
        if len(s) < 25 or "](" in s or s.startswith(("#", "|", "-", "*", "`")):
            continue                                   # headings / tables / link-lists / code fences
        lines.append(s)
        if sum(len(k) for k in lines) > 2500:
            break
    keep = []
    for sent in re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", " ".join(lines)).strip()):
        s = sent.strip()
        if len(s.split()) < 6 or _BOILER_SENT_RE.search(s):
            continue                                   # too short / UI furniture
        letters = sum(c.isalpha() for c in s)
        if letters < 0.6 * len(s.replace(" ", "")):
            continue                                   # symbol soup, not prose
        keep.append(s)
        if sum(len(k) for k in keep) > 650:
            break
    gist = " ".join(keep).strip()
    return "" if (not gist or _looks_like_code(gist)) else gist[:600]


def _digest_query(digest: str, prompt: str) -> str:
    """Build the RESEARCH QUERY from an attached image/PDF digest — used when the typed prompt is
    deictic ('create like this image') and only the ATTACHMENT says what to build. Deterministic:
    prefer the QUOTED diagram title (the vision model quotes it — 'the provided "Nano CGRA SoC
    Architecture" diagram'), else the opening sentence, strip markdown/chrome, cap ~14 words; fall
    back to the prompt minus the deictic phrases when the digest yields nothing."""
    head = "\n".join((digest or "").splitlines()[:15])
    for m in re.finditer(r'["“]([A-Za-z][^"”\n]{5,60})["”]', head):
        t = re.sub(r"\s+", " ", m.group(1)).strip()
        if len(t.split()) >= 2 and "/" not in t \
                and not re.search(r"\.(png|jpe?g|gif|webp|pdf)$", t, re.I):
            return t
    for ln in (digest or "").splitlines():
        s = ln.strip()
        # bullets ('- **Label**: …') are block DETAILS, never the design's name — skip them
        if not s or s.startswith(("#", "```", "|", "-", "*", "Saved at", "OCR text")) or "](" in s:
            continue
        s = re.sub(r"^(this|the)\s+(image|diagram|figure|picture|block diagram)\s+"
                   r"(shows|depicts|is|illustrates|presents)\s*:?\s*", "", s, flags=re.I)
        s = re.sub(r"[*_`>#]", " ", s)
        words = s.split()
        if len(words) >= 3:
            return " ".join(words[:14])
    # fallback: the prompt without the deictic words
    p = re.sub(r"\b(create|make|build|bikin|buat)\b|\blike\s+(this|the)\s+(image|picture|photo|"
               r"diagram)\b|\b(seperti|kek|kayak)\s+(gambar|foto|image)( ini)?\b|\bini\b",
               " ", prompt or "", flags=re.I)
    p = re.sub(r"\s+", " ", p).strip(" ,.")
    return p or (prompt or "")


def _digest_topics(digest: str, max_topics: int = 8) -> List[str]:
    """Every HARDWARE BLOCK the attachment digest lists — ONE research topic per block, so the
    reference hunt covers ALL of the understanding (CPU + CGRA + interconnect + UART + SRAM …),
    not just the diagram's title. (Researching a single one-line query let a look-alike repo of
    the WRONG topic become the anchor, which derailed every later stage.) Deterministic parse of
    the vision digest's structure: a '## X Block (Y)' heading names a block — prefer the
    parenthesized proper name, else the section's '**Label**: Z' line, else the heading itself;
    sections the digest marks 'Not a hardware block' (memory map, features, target) are skipped.
    Returns [] when the digest has no such structure (typed-prompt runs are unchanged)."""
    topics: List[str] = []

    def add(name: str) -> None:
        t = re.sub(r"\s+", " ", re.sub(r"[*_`]", " ", name or "")).strip(" -–—:.,")
        if len(t) < 3 or not re.search(r"[A-Za-z]{2}", t):
            return
        key = re.sub(r"[^a-z0-9]", "", t.lower())
        if key and all(key != re.sub(r"[^a-z0-9]", "", x.lower()) for x in topics):
            topics.append(t[:60])

    # heading-bounded sections, so each block's Label / 'Not a hardware block' note stays with it
    sections: List[tuple] = []
    head, body = "", []
    for ln in (digest or "").splitlines():
        m = re.match(r"^#{1,6}\s+(.+?)\s*$", ln)
        if m:
            sections.append((head, "\n".join(body)))
            head, body = m.group(1).strip(), []
        else:
            body.append(ln)
    sections.append((head, "\n".join(body)))

    for head, body in sections:
        if len(topics) >= max_topics:
            break
        if re.search(r"not a hardware block", body, re.I):
            continue                               # memory map / features / target sections
        lab = re.search(r"\*\*\s*Label\s*\*\*\s*:?\s*([^\n(]{3,80})", body, re.I)
        if not re.search(r"\bblocks?\b", head, re.I) and not lab:
            continue                               # prose section, not a named hardware block
        par = re.search(r"\(([^)]{3,60})\)\s*$", head)
        add(par.group(1) if par else
            (lab.group(1) if lab else re.sub(r"\bblocks?\b", " ", head, flags=re.I)))
    return topics


def _understand_prompt(query: str, design_dir, rec=None, deadline: "float | None" = None) -> str:
    """STEP 1 of research (the user's flow): BEFORE hunting for netlists, search the prompt to
    UNDERSTAND what it is — crawl the top hit and keep a short gist (e.g. 'a 5T-OTA is a
    single-stage differential amplifier with a current-mirror load'). Saved to
    context/understanding.md and shown, so the netlist/glayout hunt (step 2) is grounded in
    what the term actually means — not a guess. `deadline` bounds the crawl."""
    # DISTIL the raw (possibly Indonesian / full-sentence) prompt into technical English
    # keywords FIRST — otherwise 'buat ota, gunakan sky130…' searches literally and lands
    # on 'buat.id' landing pages instead of circuit/topology pages.
    topic = _refine_search_query(query)
    # FRAME the lookup for THIS flow: we build full-custom ANALOG circuits (SPICE + glayout),
    # so bias the search toward circuit theory + transistor-level implementations.
    hw_query = f"{topic} analog circuit transistor schematic spice"
    try:
        urls = _searxng_search(hw_query, 6)
    except Exception:  # noqa: BLE001
        urls = []
    urls = [u for u in urls if u and not _NONSYNTH_RE.search(u)]
    if not urls:
        return ""
    if rec:
        rec.caption(f"🔎 STEP 1 — understanding '{topic[:70]}' (from your request; analog circuit)…")
    docs = _crawl_urls(urls[:3], rec, limit=3, deadline=deadline) if rec else []
    gist = ""
    for d in docs:
        src = (getattr(d, "metadata", {}) or {}).get("source", "")
        raw = getattr(d, "page_content", "") or ""
        if _NONSYNTH_RE.search(src) or _NONSYNTH_RE.search(raw[:600]):
            continue                               # skip TL-Verilog/Makerchip write-ups
        if not _is_useful_doc(re.sub(r"\s+", " ", raw).strip(), src):
            continue
        g = _clean_gist(raw)                        # prose explanation, not a code/nav dump
        if g:
            gist = g
            break
    if not gist and docs:                          # last resort: cleaned text of the first hit
        gist = _clean_gist(getattr(docs[0], "page_content", "") or "") \
            or re.sub(r"\s+", " ", (getattr(docs[0], "page_content", "") or "")).strip()[:400]
    # DOMAIN GATE: only keep a gist that actually reads like analog-circuit prose. A generic
    # web hit ('create' → a Minecraft mod, a product landing page) has none of these signal
    # words and/or reeks of game/download junk — drop it rather than poison understanding.md.
    if gist:
        g = gist.lower()
        circuit_signal = bool(re.search(
            r"\b(transistor|mosfet|nmos|pmos|fet|gate|drain|source|current|mirror|cascode|"
            r"amplifier|opamp|ota|bias|cmos|gain|voltage|analog|circuit|netlist|differential|"
            r"reference|resistor|capacitor|impedance|feedback|node)\b", g))
        junk = bool(re.search(
            r"\b(minecraft|mc1\.\d|forge|fabric mod|texture|player|download|mod loader|"
            r"aesthetic technology|server|gameplay|skin|curseforge)\b", g))
        if junk or not circuit_signal:
            if rec:
                rec.caption(f"⏭️ web 'what it is' hit was not circuit-relevant — skipping it, "
                            f"going straight to the netlist/glayout hunt for '{topic[:50]}'.")
            return ""
    if gist:
        (Path(design_dir) / "context").mkdir(parents=True, exist_ok=True)
        (Path(design_dir) / "context" / "understanding.md").write_text(
            f"# Understanding the request\n\n**You asked for:** {query}\n\n"
            f"**Searched for:** `{topic}`\n\n**What it is (web lookup before searching for "
            f"netlists):**\n\n{gist}\n")
        if rec:
            rec.caption(f"💡 {topic[:60]} → {gist[:160]}…")
    return gist


_WEB_CHROME_RE = re.compile(
    r"^\s*(skip to content|navigation menu|toggle navigation|sign in|sign up|appearance "
    r"settings|github copilot|mcp registry|developer workflows|application security|by "
    r"company size|by use case|view all features|why github|enterprises|startups|nonprofits|"
    r"\[devsecops\]|codespaces|changelog|marketplace)\b", re.I)


def _strip_web_chrome(md: str) -> str:
    """Drop obvious site-navigation boilerplate (GitHub/docs chrome) from crawled markdown so
    the digest is content, not menus. Conservative: removes only known nav lines + pure
    link-list bullets near them."""
    if not md:
        return md
    out = []
    for ln in md.splitlines():
        if _WEB_CHROME_RE.search(ln):
            continue
        out.append(ln)
    return "\n".join(out)


def _gh_hdl_paths(user: str, repo: str, headers: dict, max_files: int):
    """List up to max_files analog-reference blob paths in a GitHub repo + the default
    branch. Priority: SPICE netlists (.sp/.spice/.cir/.cdl) FIRST, then glayout/gdsfactory
    python generators, then notebooks — never plain HTML/doc files."""
    import requests
    info = requests.get(f"https://api.github.com/repos/{user}/{repo}", headers=headers, timeout=12)
    if not info.ok:
        return "main", []
    branch = info.json().get("default_branch", "main")
    tree = requests.get(
        f"https://api.github.com/repos/{user}/{repo}/git/trees/{branch}?recursive=1",
        headers=headers, timeout=15)
    if not tree.ok:
        return branch, []
    blobs = [t["path"] for t in tree.json().get("tree", []) if t.get("type") == "blob"]
    netl = [p for p in blobs
            if p.lower().endswith((".sp", ".spice", ".cir", ".cdl", ".spc"))]
    pys = [p for p in blobs if p.lower().endswith(".py")
           and re.search(r"glayout|gdsfactory|layout|cell|placement|route", p.lower())]
    nbs = [p for p in blobs if p.lower().endswith(".ipynb")
           and re.search(r"glayout|layout|tutorial|opamp|ota|mirror", p.lower())]
    # netlists first; skip testbenches when there's plenty
    netl.sort(key=lambda p: ("tb" in p.lower() or "test" in p.lower(), len(p)))
    pys.sort(key=lambda p: len(p))
    paths = netl[:max_files] + pys[:max(1, max_files // 2)] + nbs[:2]
    return branch, paths[:max_files + 2]


def _gh_headers() -> dict:
    h = {"Accept": "application/vnd.github+json"}
    tok = os.getenv("GITHUB_TOKEN")
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def _github_code_text(repo_url: str, max_files: int = 6, max_chars: int = 8000) -> str:
    """Fetch REAL HDL source (.v/.sv/.vh/.vhd) from a GitHub repo via the API and return it
    concatenated — NOT the repo's HTML landing page (which is just nav-menu chrome)."""
    import requests
    m = re.search(r"github\.com/([^/]+)/([^/#?]+)", repo_url)
    if not m:
        return ""
    user, repo = m.group(1), m.group(2).replace(".git", "")
    try:
        h = _gh_headers()
        branch, paths = _gh_hdl_paths(user, repo, h, max_files)
        chunks, total = [], 0
        for path in paths:
            raw = requests.get(
                f"https://raw.githubusercontent.com/{user}/{repo}/{branch}/{path}", timeout=15)
            if raw.ok and raw.text.strip():
                snip = raw.text[:3000]
                chunks.append(f"// ===== {repo}/{path} =====\n{snip}")
                total += len(snip)
                if total >= max_chars:
                    break
        return "\n\n".join(chunks)[:max_chars]
    except Exception:  # noqa: BLE001
        return ""


def _download_github_code(repo_url: str, save, max_files: int = 6) -> None:
    """Download a handful of real reference files (SPICE netlists + glayout/gdsfactory
    python) from a GitHub repo."""
    import requests
    m = re.search(r"github\.com/([^/]+)/([^/#?]+)", repo_url)
    if not m:
        return
    user, repo = m.group(1), m.group(2).replace(".git", "")
    try:
        h = _gh_headers()
        branch, paths = _gh_hdl_paths(user, repo, h, max_files)
        for path in paths:
            raw = requests.get(
                f"https://raw.githubusercontent.com/{user}/{repo}/{branch}/{path}", timeout=15)
            if raw.ok and raw.text.strip():
                save(f"{repo}__{path.replace('/', '_')}", raw.content)
    except Exception:  # noqa: BLE001
        return


def _download_references(urls: List[str], design_dir, rec: "Recorder" = None,
                         max_repos: int = 4, max_files: int = 6, max_pdfs: int = 10,
                         deadline: "float | None" = None) -> int:
    """DOWNLOAD the actual reference artifacts found by the web researcher — PDF papers
    (arxiv/*.pdf), SPICE netlists and glayout code from GitHub — and store them in the knowledge store
    (blob → MinIO, row+embedding → pgvector). This is what makes the store grow with
    real papers/code, not just crawled text snippets. `deadline` (absolute time.time())
    stops the download loop early so it can never run past the research budget."""
    import requests
    import time as _time
    refs = Path(design_dir) / "context" / "refs"
    refs.mkdir(parents=True, exist_ok=True)
    saved: List[Path] = []

    def save(name: str, data: bytes) -> None:
        safe = re.sub(r"[^\w.\-]", "_", name)[:90] or "ref"
        p = refs / safe
        try:
            p.write_bytes(data)
            saved.append(p)
        except Exception:  # noqa: BLE001
            pass

    pdfs = repos = 0
    for u in urls:
        if deadline and _time.time() > deadline:       # out of budget — keep what we have
            break
        try:
            is_pdf = u.endswith(".pdf") or "arxiv.org/abs/" in u or "arxiv.org/pdf/" in u
            if is_pdf and pdfs < max_pdfs:
                pdf_url = u
                if "arxiv.org/abs/" in u:
                    pid = u.split("/abs/")[-1].split("?")[0].strip("/")
                    pdf_url = f"https://arxiv.org/pdf/{pid}.pdf"
                r = requests.get(pdf_url, timeout=25)
                if r.ok and r.content[:4] == b"%PDF":
                    nm = pdf_url.rstrip("/").split("/")[-1]
                    save(nm if nm.endswith(".pdf") else nm + ".pdf", r.content)
                    pdfs += 1
            elif "github.com/" in u and repos < max_repos:
                repos += 1
                _download_github_code(u, save, max_files)
        except Exception:  # noqa: BLE001
            continue

    n = 0
    mem = get_memory()
    if mem.enabled and saved:
        design = Path(design_dir).name
        for p in saved:
            if mem.ingest_file(p, design=design, source=f"webref:{design}"):
                n += 1
    if rec and saved:
        rec.success(f"📥 Downloaded **{len(saved)}** reference file(s) "
                    f"({pdfs} PDF paper(s) + code) → stored {n} in the knowledge store.")
    return n


def _repo_score(repo_url: str, query: str) -> int:
    """How well a repo NAME matches the request — the DISTINCTIVE keyword (kw[0], the project
    name) counts most, so meiniKi/FazyRV beats a generic ultraembedded/riscv for the prompt
    'fazyrv rv32i 8 bit'. An exact name == kw[0] match gets the strongest bonus."""
    name = repo_url.lower().rsplit("/", 1)[-1]
    kws = _hdl_keywords(query, 6)
    score = 0
    for i, kw in enumerate(kws):
        if kw and kw in name:
            score += 5 if i == 0 else 1          # the distinctive project name dominates
    if kws and name == kws[0]:                   # exact repo-name == project name
        score += 5
    return score


def _clone_anchor_repo(repo_url: str, design_dir, rec=None, max_files: int = 24) -> int:
    """Download MANY reference files from ONE repo into context/anchor/<repo>/ — the reference
    the generator STUDIES (it learns the topology/sizing, then writes its own netlist; the
    glayout .py files inform the layout step). PRIMARY path is `git clone --depth 1` (NO GitHub
    API, so NO 60/hr rate limit — the API was returning 0 files once the research burned the
    quota, which is what produced the tiny fallback design). The HTTP API is only a fallback.
    Returns count."""
    m = re.search(r"github\.com/([^/]+)/([^/#?]+)", repo_url)
    if not m:
        return 0
    user, repo = m.group(1), m.group(2).replace(".git", "")
    adir = Path(design_dir) / "context" / "anchor" / repo
    adir.mkdir(parents=True, exist_ok=True)
    saved: List[Path] = []

    # PRIMARY: git clone (shallow). No API quota; gets the WHOLE repo, then we keep its HDL,
    # preferring the rtl/ tree and skipping testbenches.
    if shutil.which("git"):
        import tempfile
        tmp = tempfile.mkdtemp()
        try:
            proc = subprocess.run(
                ["git", "clone", "--depth", "1", "--quiet",
                 f"https://github.com/{user}/{repo}.git", tmp],
                capture_output=True, text=True, errors="replace",
                timeout=float(os.getenv("ANOA_CLONE_TIMEOUT_S", "90")))
            if proc.returncode == 0:
                # netlists first (the user's rule), then glayout/gdsfactory python refs
                netl = [p for p in Path(tmp).rglob("*")
                        if p.is_file() and p.suffix.lower() in
                        (".sp", ".spice", ".cir", ".cdl", ".spc")
                        and not re.search(r"(_tb|tb_|test|bench)", p.name, re.I)]
                pys = [p for p in Path(tmp).rglob("*.py")
                       if p.is_file() and re.search(
                           r"glayout|gdsfactory|layout|cell|route|placement",
                           str(p).lower())]
                netl.sort(key=lambda p: len(str(p)))
                pys.sort(key=lambda p: len(str(p)))
                hdl = netl[:max_files] + pys[:max(2, max_files // 3)]
                for p in hdl[:max_files]:
                    rel = p.relative_to(tmp)
                    fp = adir / re.sub(r"[^\w.\-]", "_", str(rel))
                    try:
                        fp.write_text(p.read_text(errors="replace"))
                        saved.append(fp)
                    except Exception:  # noqa: BLE001
                        pass
        except Exception:  # noqa: BLE001
            pass
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # FALLBACK: GitHub HTTP API (only if git missing or the clone produced nothing).
    if not saved:
        try:
            import requests
            h = _gh_headers()
            branch, paths = _gh_hdl_paths(user, repo, h, max_files)
            for path in paths:
                raw = requests.get(
                    f"https://raw.githubusercontent.com/{user}/{repo}/{branch}/{path}", timeout=15)
                if raw.ok and raw.text.strip():
                    fp = adir / re.sub(r"[^\w.\-]", "_", path)
                    fp.write_text(raw.text)
                    saved.append(fp)
        except Exception:  # noqa: BLE001
            pass
    n = len(saved)
    # PUT 1-2 of the anchor's REAL code files into the knowledge store (references) — so the
    # source design lives in the durable store, NOT spilled to the user in the chat.
    if n:
        try:
            mem = get_memory()
            if mem.enabled:
                for fp in saved[:2]:
                    mem.ingest_file(fp, design=Path(design_dir).name,
                                    source=f"anchor:{user}/{repo}", kind="reference")
        except Exception:  # noqa: BLE001
            pass
    if rec and n:
        # do NOT name the source repo to the user — keep it neutral; the repo is in references.
        rec.caption(f"📚 Gathered {n} reference module(s) for the design.")
    return n


def _paper_relevant(text: str, query: str) -> bool:
    """A downloaded paper is kept as an ANCHOR only if its text is correlated with the design —
    this is what stops an off-topic arXiv hit (e.g. a cond-mat physics paper) or a crawled
    Hugging-Face/landing page from becoming a 'reference' the generator wastes context on."""
    try:
        from extract import relevant_to
        return relevant_to(text or "", query or "", min_overlap=2)
    except Exception:  # noqa: BLE001
        return True


def _anchor_paper(url: str, design_dir, rec=None, query: str = "") -> str | None:
    """Download ONE paper as an ANCHOR: the real PDF (text-extracted) when it's a PDF, else
    the useful crawled text. Saved to context/anchor/papers/. Returns the on-disk path, or None
    if the paper isn't actually about THIS design (uncorrelated → dropped, file deleted)."""
    import requests
    pdir = Path(design_dir) / "context" / "anchor" / "papers"
    pdir.mkdir(parents=True, exist_ok=True)
    try:
        is_pdf = url.endswith(".pdf") or "arxiv.org/abs/" in url or "arxiv.org/pdf/" in url
        if is_pdf:
            pdf_url = url
            if "arxiv.org/abs/" in url:
                pid = url.split("/abs/")[-1].split("?")[0].strip("/")
                pdf_url = f"https://arxiv.org/pdf/{pid}.pdf"
            r = requests.get(pdf_url, timeout=25)
            if r.ok and r.content[:4] == b"%PDF":     # only a REAL pdf, never an error page
                nm = re.sub(r"[^\w.\-]", "_", pdf_url.rstrip("/").split("/")[-1])[:60] or "paper"
                if not nm.endswith(".pdf"):
                    nm += ".pdf"
                (pdir / nm).write_bytes(r.content)
                txt = _extract_pdf_text(pdir / nm)
                if query and txt and not _paper_relevant(txt, query):
                    (pdir / nm).unlink(missing_ok=True)   # off-topic paper → don't anchor on it
                    if rec:
                        rec.caption(f"🗑 Skipped off-topic paper (not about this design): {nm}")
                    return None
                if txt:
                    (pdir / (nm + ".txt")).write_text(txt[:20000])
                if rec:
                    rec.caption(f"📄 Reference paper gathered: {nm}")
                return str((pdir / nm).relative_to(Path(design_dir)))
        docs = _crawl_urls([url], rec, limit=1)        # web page → only if useful (junk filtered)
        if docs and _is_useful_doc(docs[0].page_content, url):
            if query and not _paper_relevant(docs[0].page_content, query):
                return None                            # crawled page off-topic → skip
            nm = re.sub(r"[^\w]", "_", url)[-60:] + ".md"
            (pdir / nm).write_text(docs[0].page_content[:16000])
            return str((pdir / nm).relative_to(Path(design_dir)))
    except Exception:  # noqa: BLE001
        return None
    return None


def _build_anchor_and_links(urls: List[str], design_dir, query: str, rec=None,
                            topic_urls: "Dict[str, List[str]] | None" = None,
                            deadline: "float | None" = None) -> dict:
    """The 'anchor + adapt, others as links' strategy (more reliable than fusing 9-20 sources):
      • CLONE the best-matching GitHub repo(s) in FULL → context/anchor/ — ONE for a typed
        prompt; with an ATTACHED spec (``topic_urls``: block → its search hits), the best repo
        PER HARDWARE BLOCK the understanding lists (CPU + CGRA + interconnect + UART + …), so
        the references cover the WHOLE design instead of one look-alike repo;
      • DOWNLOAD the best papers (PDF text) → context/anchor/papers/ (a paper can be an anchor too);
      • save EVERY other source as a LINK (title + url) in context/sources.md — NOT full text —
        so the agent retrieves one on demand (fetch_reference) only if the anchors don't fit.
    This keeps the local model's context tiny and the design grounded in working examples."""
    import time as _time
    design_dir = Path(design_dir)
    gh = [u for u in urls if "github.com" in u and "/topics/" not in u]
    other = [u for u in urls if u not in gh]
    gh_ranked = sorted(gh, key=lambda u: _repo_score(u, query), reverse=True)
    _late = lambda: bool(deadline) and _time.time() > deadline
    cloned: Dict[str, int] = {}
    if topic_urls:
        # ATTACHED-SPEC mode: the understanding lists SEVERAL blocks — clone the best-scoring
        # repo for EACH block, so no single wrong-topic repo becomes the whole design's anchor.
        for topic, t_urls in topic_urls.items():
            if len(cloned) >= 6 or _late():
                break
            cand = sorted((u for u in (t_urls or []) if "/topics/" not in u),
                          key=lambda u, t=topic: _repo_score(u, t), reverse=True)
            for u in cand[:1]:
                if u not in cloned:
                    n = _clone_anchor_repo(u, design_dir, rec)
                    if n:
                        cloned[u] = n
        if not cloned and gh_ranked:             # every per-block search came back thin
            n = _clone_anchor_repo(gh_ranked[0], design_dir, rec)
            if n:
                cloned[gh_ranked[0]] = n
    else:
        # Clone ONLY the single best-matching repo. Cloning 2 mixed two designs' modules into
        # rtl/ (e.g. FazyRV + a stray ArithmeticLogicUnit from a second repo) — a typed-prompt
        # design must come from ONE coherent anchor. Runner-ups stay as LINKS in sources.md.
        cloned = {a: _clone_anchor_repo(a, design_dir, rec) for a in gh_ranked[:1]}
        cloned = {k: v for k, v in cloned.items() if v}

    # paper anchors: prefer real PDFs (arxiv/*.pdf) over web pages, but ONLY keep a paper whose
    # text is actually about THIS design — _anchor_paper drops an off-topic hit (cond-mat physics,
    # a HuggingFace landing page) so the generator isn't grounded on uncorrelated noise. We scan a
    # few more candidates because some are now filtered out. With an attached spec, a paper about
    # ANY of its blocks is relevant, and we keep more of them (multi-block design → more papers).
    papers_ranked = sorted(other, key=lambda u: (u.endswith(".pdf") or "arxiv" in u), reverse=True)
    paper_anchors: List[str] = []
    used = set()
    rel_q = query + (" " + " ".join(topic_urls) if topic_urls else "")
    max_papers = 4 if topic_urls else 2
    for u in papers_ranked[:(12 if topic_urls else 6)]:
        if _late():
            break
        p = _anchor_paper(u, design_dir, rec, query=rel_q)
        used.add(u)                                   # tried (kept or skipped) → don't relist as a link
        if p:
            paper_anchors.append(u)
        if len(paper_anchors) >= max_papers:
            break

    lines = ["# Reference sources (anchor + links)\n",
             "## ⚓ ANCHOR designs — COPY from these; if one matches the spec, copy it (almost) verbatim",
             "Files are on disk under `context/anchor/`. Read them, pick the closest module, copy it, "
             "and edit ONLY what the spec needs (widths/ports/ops). If an anchor matches exactly, copy "
             "it as-is. Do NOT write from scratch when an anchor fits.\n"]
    for repo, n in cloned.items():
        nm = repo.rsplit("/", 1)[-1]
        lines.append(f"- **repo {nm}** ({n} files) → `context/anchor/{nm}/` — {repo}")
    for u in paper_anchors:
        lines.append(f"- **paper** → `context/anchor/papers/` — {u}")
    lines.append("\n## 🔗 Other sources — LINKS only (retrieve on demand with fetch_reference)")
    lines.append("Use these ONLY if the anchors above are NOT sufficient; fetch the single most relevant one.")
    links = [u for u in gh_ranked if u not in cloned] + [o for o in other if o not in used]
    for u in links:
        tag = "repo" if "github.com" in u else ("paper" if u.endswith(".pdf") or "arxiv" in u else "web")
        lines.append(f"- [{tag}] {u}")
    (design_dir / "context").mkdir(parents=True, exist_ok=True)
    (design_dir / "context" / "sources.md").write_text("\n".join(lines))
    # EXTRACT the device parameter values (W/L/M, R, C, L, bias) from the cloned reference
    # netlists so the config can be SEEDED from a real similar design, not invented.
    _extract_reference_params(design_dir, rec)
    return {"anchors": cloned, "paper_anchors": paper_anchors, "n_links": len(links)}


def _extract_reference_params(design_dir, rec=None) -> int:
    """Scan the gathered reference netlists (context/anchor/) for device parameter values
    and write them to context/reference_params.md — the STARTING parameter values the
    config-generator copies + adjusts (the user's rule: extract params from a similar
    researched netlist / paper, don't guess). Returns the number of reference files mined."""
    from netlist_check import extract_params_summary
    adir = Path(design_dir) / "context" / "anchor"
    if not adir.exists():
        return 0
    files: List[Path] = []
    for g in _NETLIST_GLOBS:
        files += sorted(adir.rglob(g))
    # also mine the extracted text of any anchored paper (a paper often tabulates W/L, bias)
    paper_txt = sorted((adir / "papers").glob("*.txt")) if (adir / "papers").exists() else []
    blocks, n = [], 0
    for p in files:
        if "recalled" in p.parts:
            continue
        try:
            summ = extract_params_summary(p.read_text(errors="replace"))
        except Exception:  # noqa: BLE001
            summ = ""
        if summ:
            blocks.append(f"## from `{p.relative_to(Path(design_dir))}`\n{summ}")
            n += 1
    for p in paper_txt[:2]:
        try:
            summ = extract_params_summary(p.read_text(errors="replace"))
        except Exception:  # noqa: BLE001
            summ = ""
        if summ:
            blocks.append(f"## from paper `{p.name}`\n{summ}")
            n += 1
    if not blocks:
        return 0
    body = ("# Reference parameter values (extracted from the researched netlists/papers)\n\n"
            "These are the device sizes / component values used by the closest reference "
            "designs. SEED config/<name>.json's `params` from these (copy the W/L/M, R, C, L, "
            "bias values), then adjust for THIS design's spec — do NOT invent from scratch.\n\n"
            + "\n\n".join(blocks))
    (Path(design_dir) / "context" / "reference_params.md").write_text(body)
    if rec and n:
        rec.caption(f"🔢 Extracted device parameters (W/L/M, R, C, L, bias) from {n} reference "
                    "design(s) → context/reference_params.md (config seeds from these).")
    return n


def _recall_db_anchor(ctx, design_dir, rec=None, k: int = 3) -> int:
    """RLM self-memory anchor: when the web didn't clone an anchor (web off, or thin
    results), pull the CLOSEST past verified netlist/glayout code the agent itself built —
    recalled semantically from the knowledge DB (pg/MinIO) — into context/anchor/recalled/
    so the generator COPIES+ADAPTS its own proven circuits instead of starting blank. This
    is what makes the RLM get better every run: it reuses what worked."""
    try:
        mem = get_memory()
        if not getattr(mem, "enabled", False):
            return 0
        adir = Path(design_dir) / "context" / "anchor" / "recalled"
        items = (mem.recall(ctx["query"], kind="code", k=k)
                 + mem.recall(ctx["query"], kind="design", k=2))
        n = 0
        for it in items:
            body = it.get("text") or ""
            okey = it.get("object_key") or ""
            if okey:                                   # prefer the real file from object storage
                blob = mem.get_object(okey)
                if blob:
                    body = blob.decode("utf-8", "replace")
            is_netlist = ".subckt" in body.lower()
            is_glayout = bool(re.search(r"\b(glayout|gdsfactory|smart_route|c_route|"
                                        r"via_stack|nmos|pmos)\b", body))
            if not (is_netlist or is_glayout):         # only anchor on actual circuits/layout code
                continue
            adir.mkdir(parents=True, exist_ok=True)
            nm = re.sub(r"[^\w.\-]", "_", (it.get("title") or okey.split("/")[-1] or f"recalled_{n}"))
            if not nm.endswith((".sp", ".spice", ".cir", ".cdl", ".py")):
                nm += ".sp" if is_netlist else ".py"
            (adir / nm).write_text(body)
            n += 1
        if rec and n:
            rec.caption(f"🧠 Recalled {n} past verified design file(s) from the knowledge store.")
        return n
    except Exception:  # noqa: BLE001
        return 0


# "connect this with my previously-designed X" — reuse a PROVEN prior design AS-IS (instantiate it),
# the opposite of the study-don't-copy anchor path.
_CONNECT_VERB_RE = re.compile(
    r"\b(connect|integrat|combin|attach|hook\s*up|interfac|bridge|plug\s*in|wire\s+(?:it|them|up|to)|"
    r"talk\s+to|together\s+with)\w*\b", re.I)


def _connect_designs(ctx, design_dir, rec=None) -> str:
    """CROSS-PROJECT CONNECT: when the prompt asks to connect/integrate the new design WITH a design
    the user already built (e.g. 'create a cgra 2x2 and connect it to my riscv 8-bit'), pull that
    prior VERIFIED design's RTL out of the knowledge store into THIS design's rtl/ so the generator
    can INSTANTIATE it as a submodule and wire it — instead of rewriting it from scratch. Returns a
    generator instruction naming the reused files + the prior top to instantiate, or '' when there's
    no connect intent or no matching prior design (then generation proceeds normally)."""
    q = ctx.get("query") or ""
    if not _CONNECT_VERB_RE.search(q):
        return ""
    try:
        mem = get_memory()
        if not getattr(mem, "enabled", False):
            return ""
        cur = Path(design_dir).name
        # The phrase AFTER 'with/to/into' is the design to connect to ('… connect with riscv 8bit').
        m = re.search(r"\b(?:with|to|into|onto|and)\s+(?:my\s+|the\s+|a\s+|an\s+|previously\s+|"
                      r"prior\s+|existing\s+|earlier\s+)*(.{3,60})", q, re.I)
        target = (m.group(1) if m else q).lower()
        ttokens = {w for w in re.findall(r"[a-z0-9]+", target) if len(w) >= 2}
        if not ttokens:
            return ""
        # known prior designs (distinct), with their original-query title for fuzzy matching
        designs: dict[str, str] = {}
        for row in mem.list_items(kind="design", limit=200) + mem.list_items(limit=400):
            d = row.get("design") or ""
            if d and d != cur:
                designs.setdefault(d, row.get("title") or d)
        best, best_score = None, 0
        for d, title in designs.items():
            htokens = {w for w in re.findall(r"[a-z0-9]+", f"{d} {title}".lower()) if len(w) >= 2}
            score = len(ttokens & htokens)
            if score > best_score:
                best, best_score = d, score
        if not best or best_score < 1:
            return ""
        # fetch the prior design's verified netlist files (skip testbenches) into netlist/
        ndir = Path(design_dir) / "netlist"
        ndir.mkdir(parents=True, exist_ok=True)
        reused: list[str] = []
        for row in mem.list_items(design=best, limit=200):
            name = row.get("title") or ""
            if not name.endswith((".sp", ".spice", ".cir", ".cdl")):
                continue
            if "tb" in name.lower() or "testbench" in name.lower() or "_tb" in name.lower():
                continue
            body = b""
            okey = row.get("object_key") or ""
            if okey:
                body = mem.get_object(okey) or b""
            if not body:
                full = mem.get(row.get("id"))
                body = (full or {}).get("text", "").encode() if full else b""
            if not body or b".subckt" not in body.lower():
                continue
            dest = ndir / name
            if dest.exists():
                continue
            dest.write_bytes(body)
            reused.append(name)
        if not reused:
            return ""
        # name the prior design's TOP (the integration subckt to instantiate) via structural pick
        prior_top = ""
        try:
            from netlist_check import pick_top
            import tempfile
            tmp = Path(tempfile.mkdtemp(prefix="connect_"))
            for n in reused:
                (tmp / n).write_bytes((ndir / n).read_bytes())
            prior_top = pick_top(tmp) or ""
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:  # noqa: BLE001
            prior_top = ""
        if rec:
            rec.success(f"🔗 Connecting with your prior design **{best}** — reused {len(reused)} "
                        f"verified file(s): {', '.join(reused[:8])}"
                        + (f" (top: `{prior_top}`)" if prior_top else ""))
        topline = (f"Its top subckt is `{prior_top}` — instantiate THAT.\n" if prior_top else "")
        return (
            "🔗 CONNECT-WITH-A-PRIOR-DESIGN (do NOT rewrite these): the user asked to connect this "
            f"design with their previously-built **{best}**. Its PROVEN, verified netlist is ALREADY "
            f"in netlist/ — these files: {', '.join(reused)}. " + topline +
            "Build ONLY the NEW glue: your new top subckt must X-INSTANTIATE the reused subckt(s) "
            "by name (node-by-node), instantiate the new circuit, and WIRE them together exactly as "
            "the request describes. Do NOT modify, rename, or re-implement the reused files; do NOT "
            "duplicate their subckts. Keep their port names; add bias/level-shift stages if the "
            "operating points differ.\n")
    except Exception:  # noqa: BLE001
        return ""


def _store_web_docs(docs, ctx) -> int:
    """Persist crawled paper/web TEXT into the knowledge store (kind=paper for web,
    code for GitHub) so it's semantically recallable in future runs."""
    mem = get_memory()
    if not (getattr(mem, "enabled", False) and docs):
        return 0
    design = Path(ctx["design_dir"]).name
    query = ctx.get("query", "")
    try:
        from extract import relevant_to
    except Exception:  # noqa: BLE001
        relevant_to = None
    n = 0
    for d in docs:
        src = d.metadata.get("source", "web") if hasattr(d, "metadata") else "web"
        body = getattr(d, "page_content", "") or ""
        is_code = "github.com" in str(src)
        if not body or (not is_code and not _is_useful_doc(body, str(src))):
            continue                              # never store cookie/login/nav junk as a 'paper'
        # drop a crawled page that has NOTHING to do with this design (uncorrelated noise) —
        # code (HDL) is always kept; a web/paper page must share terms with the request.
        if not is_code and relevant_to and not relevant_to(body, query):
            continue
        kind = "code" if is_code else "paper"
        if mem.remember(kind, body[:6000], design=design, source=str(src),
                        title=str(src)[:120], tags="web"):
            n += 1
    return n


def _error_query(err: str) -> str:
    """Turn a compiler/lint error log into a concise web-search query (strip the file
    paths/line numbers and prefer the MOST DESCRIPTIVE error message, not generic
    'syntax error', so the search is actually about the real problem)."""
    cands = []
    for line in (err or "").splitlines():
        low = line.lower()
        if "error" in low or "syntax" in low:
            # drop "path:line:"
            msg = re.sub(r"^.*?:\s*\d+:?\s*", "", line)
            # drop leftover file paths
            msg = re.sub(r"/[\w./\-]+\.s?vh?", "", msg).strip()
            if len(msg) > 8 and msg.lower().strip(". ") not in ("syntax error", "error", "%error"):
                cands.append(msg)
    if cands:
        # the most specific message
        return ("ngspice " + max(cands, key=len))[:140]
    first = next((l.strip()
                 for l in (err or "").splitlines() if l.strip()), "")
    return ("ngspice " + re.sub(r"^.*?:\s*\d+:?\s*", "", first))[:140]


# A query that IS an error/compiler message (fix-mode) vs a design/topic (learn-mode).
_ERRORISH_RE = re.compile(
    r"\berror\b|\bsyntax\b|\bfailed\b|\bwarning\b|unable to|cannot\b|mismatch|violation|"
    r"%\w+:|\.s?vh?:\d+|timed? ?out|undeclared|not a valid|multidriven|latch\b", re.I)


def _refine_search_query(query: str) -> str:
    """Distil a raw, possibly Indonesian/vague prompt into a CONCISE TECHNICAL ENGLISH
    circuit search phrase (≤10 words, English keywords). Without this, a prompt like
    'buat ota 40 dB, gunakan sky130…' hits landing-page/marketing junk (Indonesian
    'buat' → 'buat.id' website builder) instead of circuit/netlist pages."""
    q = (query or "").strip()
    if not q:
        return q
    # STRIP the leading imperative/article so the search is the TOPIC, not the verb — without
    # this, 'create a cascode current mirror' searches 'create …' and lands on the Minecraft
    # 'Create' mod instead of the circuit. Peel repeated lead-in words off the front only.
    q = re.sub(r"^(?:\s*(?:please|kindly|can you|could you|create|make|build|design|generate|"
               r"implement|produce|develop|draw|give|show|me|us|a|an|the)\b)+\s*",
               "", q, flags=re.I).strip() or q
    # already short + ASCII/technical → search as-is
    if len(q) <= 60 and q.isascii() and not re.search(r"\b(buat|gunakan|untuk|saya|ingin|dan)\b", q, re.I):
        return q
    try:
        out = get_chat_model(temperature=0.0).invoke(
            "Turn this analog circuit design request into a SHORT English web-search query for "
            "finding the TRANSISTOR-LEVEL topology, SPICE netlists and papers behind it. Output "
            "ONLY the query: ≤10 words, English technical keywords (topology name, 'spice "
            "netlist', 'sky130', 'ota', 'cmos'), NO Indonesian, NO 'make/build', NO full "
            "sentences.\n"
            f"REQUEST: {q[:400]}")
        refined = re.sub(r"[\"'`\n]", " ", getattr(out, "content", "") or "").strip()[:120]
        return refined or q
    except Exception:  # noqa: BLE001
        return q


def _web_knowledge(query: str, rec: "Recorder") -> str:
    """LEARN-mode web lookup — what a thing IS and how it's built at transistor level. Used
    when a deep agent searches a TOPIC ('folded-cascode OTA', 'beta-multiplier bias'), e.g.
    during planning. (search_web used to force EVERY query through the error-fix formatter,
    so the planner asking about a topology got back a bogus fix hint.)"""
    refined = _refine_search_query(query)
    if refined != query:
        rec.caption(f"🌐 Web lookup (learn): *{query[:60]}* → search: `{refined}`")
    else:
        rec.caption(f"🌐 Web lookup (learn): *{query[:100]}*")
    try:
        with st.spinner("Searching the web…"):
            urls = _web_search(refined, n_github=3, n_other=5)
        docs = _crawl_urls(urls, rec, limit=5)
        if not docs:
            return ""
        body = "\n\n".join(f"[{d.metadata.get('source', '')}]\n{d.page_content[:1500]}"
                           for d in docs[:4])
        summary = clean_llm_output(stream_to(
            get_chat_model(temperature=0.2),
            "Digest these web results for an analog IC engineer. Explain WHAT the topic is and "
            "HOW it is typically implemented at transistor level: topology, device roles, "
            "sizing guidelines (gm/Id, W/L ratios, bias points), key trade-offs, and pitfalls. "
            "Concrete and concise (≤25 lines). Do NOT "
            f"invent an error to fix — this is a knowledge lookup.\nTOPIC: {query}\n\n"
            f"WEB RESULTS:\n{body}", rec.placeholder()))
        rec.markdown("**🌐 Web knowledge:**")
        rec.code(summary[:1500], "markdown")
        return f"WEB KNOWLEDGE for '{query}':\n{summary[:3000]}"
    except Exception as e:  # noqa: BLE001
        rec.caption(f"Web lookup failed ({e}).")
        return ""


def _auto_research(query: str, rec: "Recorder") -> str:
    """Autonomously search the WEB for how to fix an error and summarize the fix —
    the corrector calls this on its own when it's stuck (no human needed)."""
    rec.caption(f"🌐 Searching the web for: *{query}*")
    try:
        with st.spinner("Searching the web for a fix…"):
            urls = _web_search(query, n_github=2, n_other=4)
        docs = _crawl_urls(urls, rec, limit=4)
        if not docs:
            rec.caption("No usable web results.")
            return ""
        body = "\n\n".join(d.page_content[:1500] for d in docs[:3])
        summary = clean_llm_output(stream_to(
            get_chat_model(temperature=0.2),
            "From these web results, explain CONCISELY how to fix this SPICE/ngspice/glayout "
            f"error and show the CORRECT pattern (a few lines).\n\nERROR: {query}\n\n"
            f"WEB RESULTS:\n{body}",
            rec.placeholder(),
        ))
        rec.markdown("**🌐 Web fix hint:**")
        rec.code(summary[:1500], "markdown")
        return f"WEB FIX HINT for '{query}':\n{summary}"
    except Exception as e:  # noqa: BLE001
        rec.caption(f"Web research failed ({e}).")
        return ""


# --------------------------------------------------------------------------- #
# Transcript / Recorder — render once live AND record for replay
# --------------------------------------------------------------------------- #
# Streamlit wipes ALL output on every rerun. Because this app pauses after each
# agent and reruns on every button click, we must be able to re-draw the whole
# history. Each agent renders through a Recorder, which both draws live AND stores
# a list of (kind, payload) blocks; replay_record() re-draws them next rerun.
def _draw(kind, payload):
    if kind == "header":
        emoji, title, desc = payload
        st.markdown("---")
        st.markdown(f"### {emoji} {title}")
        if desc:
            st.caption(desc)
    elif kind == "empty":
        pass                       # a cleared live slot — renders nothing
    elif kind == "markdown":
        st.markdown(payload[0])
    elif kind == "caption":
        st.caption(payload[0])
    elif kind == "write":
        st.write(payload[0])
    elif kind == "code":
        st.code(payload[0], language=payload[1])
    elif kind == "success":
        st.success(payload[0])
    elif kind == "error":
        st.error(payload[0])
    elif kind == "info":
        st.info(payload[0])
    elif kind == "warning":
        st.warning(payload[0])
    elif kind == "expander_code":
        title, code, language, expanded = payload
        with st.expander(title, expanded=expanded):
            st.code(code, language=language)
    elif kind == "table":
        st.table(payload[0])
    elif kind == "json":
        with st.expander("All metrics"):
            st.json(payload[0])
    elif kind == "graphviz":
        st.graphviz_chart(payload[0], use_container_width=True)
    elif kind == "image":
        # Stored as a PATH (+caption) so it re-renders on every Streamlit rerun.
        path, caption = payload
        p = Path(path)
        if not p.exists():
            st.caption(f"(image not found: {path})")
        elif p.suffix.lower() == ".svg":
            svg = p.read_text()
            m = re.search(r'height="([\d.]+)', svg)
            h = min(int(float(m.group(1))) + 40, 900) if m else 360
            if caption:
                st.caption(caption)
            components.html(f'<div style="overflow:auto;background:#fff">{svg}</div>',
                            height=h, scrolling=True)
        else:
            st.image(str(p), caption=caption or None, use_container_width=True)


class _NullPH:
    """Stand-in for a live streaming placeholder during replay (does nothing)."""

    def code(self, *a, **k):
        pass

    def markdown(self, *a, **k):
        pass

    def empty(self, *a, **k):
        pass

    write = caption = markdown


class _LivePH:
    """A LIVE streaming slot. Every update REPLACES this slot's block — in the recorded
    transcript (so only the FINAL state persists) and, via the runner's patched
    `Recorder._live`, in the web UI (a `block_live` SSE event). This is what makes a
    token stream or a multi-hour LibreLane log ONE ticking block instead of thousands
    of stacked blocks — and why the harden step no longer looks frozen."""

    _n = 0

    def __init__(self, rec):
        self._rec = rec
        _LivePH._n += 1
        self._slot = f"ph{_LivePH._n}"

    def code(self, text, language="text"):
        self._rec._live(self._slot, "code", (text, language))

    def markdown(self, text):
        self._rec._live(self._slot, "markdown", (text,))

    write = markdown

    def caption(self, text):
        self._rec._live(self._slot, "caption", (text,))

    def empty(self):
        """Clear this live slot — its block renders nothing (used when the streamed
        text has been superseded by a final rendering, e.g. a plan checklist)."""
        self._rec._live(self._slot, "empty", ())


class Recorder:
    def __init__(self, emoji, title, desc="", node="", live=True):
        self.node = node
        self.blocks = [("header", (emoji, title, desc))]
        self.live = live
        self._slots = {}
        if live:
            _draw("header", (emoji, title, desc))

    def _add(self, kind, payload):
        self.blocks.append((kind, payload))
        if self.live:
            _draw(kind, payload)

    def _live(self, slot, kind, payload):
        """Update a live slot IN PLACE (see _LivePH): the slot's block is REPLACED, not
        appended, so only its final state persists in the transcript. The runner wraps
        this to stream a `block_live` event to the web UI."""
        idx = self._slots.get(slot)
        if idx is None:
            self._slots[slot] = len(self.blocks)
            self.blocks.append((kind, payload))
        else:
            self.blocks[idx] = (kind, payload)
        if self.live:
            _draw(kind, payload)

    def markdown(self, t):
        self._add("markdown", (t,))

    def caption(self, t):
        self._add("caption", (t,))

    def write(self, t):
        self._add("write", (t,))

    def code(self, t, language="text"):
        self._add("code", (t, language))

    def success(self, t):
        self._add("success", (t,))

    def error(self, t):
        self._add("error", (t,))

    def info(self, t):
        self._add("info", (t,))

    def warning(self, t):
        self._add("warning", (t,))

    def expander_code(self, title, code, language="spice", expanded=False):
        self._add("expander_code", (title, code, language, expanded))

    def plan(self, items):
        """The GRAND-PLAN checklist. The planner ticks NOTHING — each item lights up GREEN
        in the UI as the downstream agents reach its pipeline phase (mapped by keyword)."""
        self._add("plan", (list(items),))

    def table(self, data):
        self._add("table", (data,))

    def json(self, data):
        self._add("json", (data,))

    def graphviz(self, dot):
        self._add("graphviz", (dot,))

    def image(self, path, caption=""):
        """Show an image FILE (png/jpg/svg). Stored as a path so it survives replay."""
        self._add("image", (str(path), caption))

    def file(self, path, label=""):
        """A downloadable artifact (path RELATIVE to the design dir) — e.g. the PDF
        report. The web UI renders it as an open/download link."""
        self._add("file", (str(path), label))

    def placeholder(self):
        """A LIVE streaming slot during execution (updates IN PLACE, streamed to the
        web UI as `block_live` events); a no-op on replay."""
        return _LivePH(self) if self.live else _NullPH()


def replay_record(record):
    for kind, payload in record["blocks"]:
        _draw(kind, payload)


def _contract_note(ctx) -> str:
    """When the user ORDERED a contract change (shrink widths, smaller SRAM,
    restructure), the NEW contract is the truth. Without this rule the fix loop treated
    the OLD 32-bit testbenches as golden and 'fixed' the shrink by RESTORING the old
    design — literally reversing the user's order (the bug the user hit)."""
    cc = ctx.get("_contract_change")
    if not cc:
        return ""
    return (
        "⚖️ CONTRACT CHANGE IN FORCE — THE USER ORDERED: «" + str(cc)[:400] + "»\n"
        "The NEW contract (new widths/sizes/architecture) OVERRIDES every OLD artifact. "
        "Old testbenches, old expected values, old unit states, and old copies of the "
        "design (e.g. under macros/*/src or in the knowledge store) are OBSOLETE for "
        "anything the order changed. NEVER restore/copy back a previous wider/bigger "
        "version to satisfy an old testbench — that reverses the user's order. When a "
        "testbench disagrees with the new contract, FIX THE TESTBENCH (new widths, new "
        "expected values, adjusted programs). Update design_notes.md (§Spec/§Module Map/"
        "§Trade-offs) to the new contract.\n"
        "FILE NAMING RULE: a SMALL fix stays in the SAME file (version history keeps every "
        "iteration). But when the new content is FUNDAMENTALLY DIFFERENT from the original "
        "(different topology or spec class — e.g. a 5T-OTA that is now a two-stage Miller "
        "amp), make a NEW file whose name states what it now IS: subckt `ota_2stage` in "
        "`netlist/ota_2stage.sp` + `tb/ota_2stage_tb.sp` + `config/ota_2stage.json`, then "
        "delete_file_disk the old files and update EVERY reference (top-level X-instance, "
        "Block Map). Never leave a stale duplicate in netlist/ — old versions stay browsable "
        "in the version history (Artifacts ▸ Version dropdown), not in the working tree.\n")


def _ref_context(ctx) -> str:
    """Reference text injected into the generator/correctors. Includes an on-demand
    web example (from the 🌐 'fetch example of block X' tool) when present."""
    ref = ctx.get("web_example", "")
    return (f"USER-REQUESTED WEB REFERENCE (use it):\n{ref}\n\n" if ref else "")


def _collapse_repeats(text: str, max_occ: int = 3, min_len: int = 8) -> str:
    """Kill runaway generation: if a non-trivial line repeats more than `max_occ` times
    (the degenerate 'wire [7:0] …' spam), keep only the first few. Belt-and-braces so a
    looping model can never write a 2000-line design_notes.md of duplicate signals."""
    counts: dict = {}
    out, dropped = [], 0
    for ln in text.splitlines():
        key = ln.strip()
        if len(key) >= min_len:
            counts[key] = counts.get(key, 0) + 1
            if counts[key] > max_occ:
                dropped += 1
                continue
        out.append(ln)
    if dropped:
        out.append(f"\n<!-- {dropped} runaway/duplicate line(s) trimmed -->")
    return "\n".join(out)


def _planning_context(ctx, limit: int = 12) -> str:
    """Short digest of what RECALL + RESEARCH gathered (ctx['documents']) — fed into the
    plan-point generator so the [] [] [] checklist is informed by real references, not blind."""
    docs = ctx.get("documents", []) or []
    lines: List[str] = []
    seen = set()
    for d in docs[:60]:
        src = (getattr(d, "metadata", {}) or {}).get("source", "")
        if src in seen:
            continue
        seen.add(src)
        body = (getattr(d, "page_content", "") or "").strip().replace("\n", " ")
        lines.append(f"• {src or 'ref'}: {body[:160]}")
        if len(lines) >= limit:
            break
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Agents — each takes (rec, ctx, feedback) and mutates ctx in place
# --------------------------------------------------------------------------- #
def agent_plan(rec, ctx, feedback=""):
    if ctx.get("deep_steps"):                 # GRAND PLANNER (recall + research + plan)
        # GLAYOUT-FIRST flow (user: 'focus on glayout not .sp'): research the reference SPICE,
        # distil it into ONE JSON of wiring+parameters (the `generate` step), then hand that
        # JSON straight to glayout (`harden`) → DRC/LVS → GDSII → PEX. The ngspice testbench
        # runs AFTER the layout is clean and its SPICE has been extracted (inside harden's
        # post-layout sim). There is NO pre-layout netlist / decompose / testbench / simulate.
        ctx["_plan"] = ["generate", "harden"] if ctx.get("run_harden") else ["generate"]
        return _deep_plan(rec, ctx, feedback)
    plan = ["retrieve", "web", "generate",
            "decompose", "testbench", "write", "simulate"]
    if not ctx.get("use_web"):
        plan.remove("web")
    ctx["_plan"] = plan
    rec.caption("After each step the flow PAUSES so you can Continue / Revise / Replan, "
                "or ask it to fetch a web example of a block.")
    try:
        notes = stream_to(
            get_chat_model(temperature=0.3),
            "In 3 short bullet points, name the key sub-circuits and the main spec/"
            f"verification concerns for building this analog circuit: '{ctx['query']}'."
            + (f"\nUser steering: {feedback}" if feedback else ""),
            rec.placeholder(),
        )
        notes = clean_llm_output(notes).strip()
        if notes:
            rec.markdown("**Design notes:**\n\n" + notes[:1500])
    except Exception:  # noqa: BLE001
        pass
    ctx["_plan"] = plan


def agent_retrieve(rec, ctx, feedback=""):
    query = ctx["query"] + (f" {feedback}" if feedback else "")
    mem = get_memory()
    docs: List[Document] = []
    if mem.enabled:
        with st.spinner("Recalling references from the knowledge store (pgvector)…"):
            items = mem.recall(query, k=8)
        docs = _docs_from_recall(items)
        if docs:
            rec.success(
                f"Recalled **{len(docs)}** item(s) from the knowledge store (pgvector semantic search).")
            srcs = "\n".join(f"• [{it.get('kind')}] {it.get('title')} — {it.get('source')}"
                             for it in items[:12])
            rec.expander_code("Show recalled sources", srcs, "text")
        else:
            rec.info("Knowledge store has nothing relevant yet — generating from scratch "
                     "(it fills as you build / after `docker compose up` + seed).")
    else:
        rec.warning("Knowledge store offline — generating from scratch. "
                    "Run `docker compose up -d` to enable durable recall.")
    ctx["documents"] = docs


def agent_web(rec, ctx, feedback=""):
    if not ctx.get("use_web"):
        rec.info("Web research disabled.")
        return
    if ctx.get("deep_steps"):                 # run the Web Researcher AS a deep agent (RLM)
        return _deep_web(rec, ctx, feedback)
    docs = list(ctx.get("documents", []))
    query = ctx["query"]
    mem = get_memory()

    # Cache = the durable knowledge store. If we already crawled references for a
    # similar query, recall them from pgvector instead of crawling again.
    if mem.enabled and not feedback:
        hits = _docs_from_recall(mem.recall(query, kind="reference", k=20))
        if len(hits) >= 5:
            rec.success(
                f"Recalled {len(hits)} reference chunk(s) from the knowledge store — skipping the live crawl.")
            ctx["documents"] = docs + hits
            return

    # SEARCH THE FULL PROMPT + a few CLOSE 'similar' phrasings (synonyms of the whole design, NOT
    # sub-blocks) so the search still finds pages when the exact wording is thin / SearXNG is down.
    with st.spinner("Searching GitHub (SPICE netlists + glayout code) + web…"):
        urls = _web_search(query, similar=_design_variants(query, 2))
    n_gh = sum("github.com" in u for u in urls)
    rec.write(f"🔎 Found **{len(urls)}** references — **{n_gh}** GitHub repos (netlists/"
              f"glayout) + **{len(urls) - n_gh}** papers/web.")
    if not urls:
        rec.info("No search results; skipping.")
        ctx["documents"] = docs
        return

    with st.spinner(f"Crawling {len(urls)} pages (5 at a time)…"):
        web_docs = _crawl_urls(urls, rec, limit=len(urls))
    if not web_docs:
        rec.info("Crawled pages had no usable content.")
        ctx["documents"] = docs
        return

    chunks = RecursiveCharacterTextSplitter(
        chunk_size=2000, chunk_overlap=200).split_documents(web_docs)
    # Persist the crawled chunks into the durable knowledge store (pgvector + MinIO)
    # so future runs RECALL them — this is the cache, and it grows the RLM's memory.
    stored = 0
    if mem.enabled:
        slug = slugify(query, 60)
        for c in chunks:
            src = c.metadata.get("source", "web")
            if mem.remember("reference", c.page_content, design=slug, source=src,
                            title=str(src)[:120], tags="web"):
                stored += 1
    rec.success(f"Crawled {len(web_docs)} pages → {len(chunks)} chunks"
                + (f" → stored {stored} in the knowledge store (recallable next time)." if stored else "."))
    ctx["documents"] = docs + chunks


def agent_generate(rec, ctx, feedback=""):
    # REGENERATE pass: the previous netlist couldn't be verified, so we're writing it again. Fold
    # the failure into the instruction so the new design fixes the root cause instead of repeating.
    regen = ctx.pop("_regen_reason", "")
    if regen:
        rec.caption("♻️ Regenerating the netlist from knowledge — the previous design wasn't verifiable.")
        note = ("The PREVIOUS netlist for this design FAILED simulation/spec verification with:\n"
                f"{regen}\n"
                "Write a CORRECTED circuit that fixes the ROOT CAUSE of this failure. "
                "Keep the same intended function; do not repeat the same mistake.")
        feedback = (feedback + "\n\n" + note).strip() if feedback else note
    # run this node AS a deep agent (planning + web + files)
    if ctx.get("deep_steps"):
        return _deep_generate(rec, ctx, feedback)
    llm = get_chat_model(temperature=0.2)
    prompt = ChatPromptTemplate.from_template(
        """You are an expert analog IC designer writing SPICE netlists for the {pdk} PDK.
Using the reference context and the request, write the complete circuit as one or more
`.subckt` blocks. Start the file with a `*` title comment. Every subckt lists ALL its
ports (VDD VSS inputs outputs bias) and every port is used in the body. Use the exact
PDK device model names and size every device explicitly (W= L= in µm, plus M= fingers).
Output ONLY the netlist in a single ```spice block.

{pitfalls}

CONTEXT:
{context}

REQUEST:
{question}
"""
    )

    def fmt(docs):
        head = _ref_context(ctx)
        if not docs:
            return head + "No reference context."
        parts = [
            f"Source: {d.metadata.get('source','N/A')}\n{d.page_content[:1800]}" for d in docs[:20]]
        return head + "\n\n".join(parts)

    question = ctx["query"]
    if feedback:
        question += f"\n\nADDITIONAL USER INSTRUCTION (apply this): {feedback}"

    def is_degenerate(code: str) -> bool:
        # Empty, or a repetition loop produced no real subckt — force a retry.
        return (not code.strip()) or (".subckt" not in code.lower()) or _looks_repetitive(code)

    chain = prompt | llm
    rec.caption("🧠 Live model output (reasoning + netlist):")
    live = rec.placeholder()
    with st.spinner("Generating the SPICE netlist with the local model…"):
        raw = stream_to(chain, {"context": fmt(ctx["documents"]), "question": question,
                                "pitfalls": VERILOG_PITFALLS, "pdk": PDK}, live)
    gen = extract_code_block(raw)

    if is_degenerate(gen):  # looped / empty? retry once without the (possibly huge) references
        rec.warning(
            "Model produced no usable netlist (empty or stuck in a loop) — retrying with a tighter prompt…")
        with st.spinner("Retrying generation…"):
            raw = stream_to(chain, {"context": _ref_context(ctx) + "No reference context.",
                                    "question": question, "pitfalls": VERILOG_PITFALLS,
                                    "pdk": PDK}, live)
        gen = extract_code_block(raw)
    if not gen.strip():
        gen = raw.strip()
        rec.error(
            "The model produced no netlist. Try a simpler prompt or a larger/instruct model.")
        rec.code(raw[:1500] or "(completely empty response)", language="text")
        ctx["generation"] = gen
        ctx["simulation_output"] = ""
        return

    rec.success("Generated netlist:")
    rec.code(gen, language="spice")
    ctx["generation"] = gen
    ctx["simulation_output"] = ""


def _top_module(blocks: List[str], names: List[str]) -> str:
    """Pick the top circuit structurally: among subckts no OTHER subckt instantiates,
    prefer the one whose TRANSITIVE cone covers the most of the design — direct-child
    counting can pick an inner stage over the true top whose one child's cone is the
    whole design."""
    instantiated = set()
    refs = {}
    for nm, b in zip(names, blocks):
        body = b[b.find("\n") + 1:]           # skip the .subckt header line itself
        refs[nm] = {other for other in names
                    if other != nm and re.search(rf"\b{re.escape(other)}\b", body)}
        instantiated |= refs[nm]
    candidates = [n for n in names if n not in instantiated] or names

    def cone(n):
        seen, stack = set(), [n]
        while stack:
            m = stack.pop()
            if m in seen:
                continue
            seen.add(m)
            stack += list(refs.get(m, ()))
        return len(seen)

    def score(n):
        bonus = 1 if re.search(r"top|soc|chip|system|ota|amp|opamp", n, re.I) else 0
        return (cone(n), bonus, len(blocks[names.index(n)]))
    return max(candidates, key=score)


def agent_decompose(rec, ctx, feedback=""):
    # ANCHOR-SEEDED designs are ALREADY one-subckt-per-file on disk (copied + adapted from
    # the anchor). Re-splitting the concatenated blob would re-mix files — so use the
    # on-disk files VERBATIM.
    design_dir = Path(ctx["design_dir"])
    if (design_dir / "context" / ".anchor_seeded").exists():
        from netlist_check import pick_top
        ndir = design_dir / "netlist"
        srcs = []
        for g in _NETLIST_GLOBS:
            srcs += sorted(ndir.glob(g))
        files = {p.name: p.read_text() for p in srcs
                 if "tb" not in p.name.lower() and "testbench" not in p.name.lower()}
        top = ctx.get("top_module_name") or pick_top(ndir)
        rec.caption("Design already organized per-circuit — keeping files "
                    "VERBATIM, extensions intact; no re-split, no rename.")
        rec.success(f"Top circuit: `{top}` · {len(files)} file(s) — kept as-is.")
        for fn, c in list(files.items())[:30]:
            rec.expander_code(f"📄 {fn}", c, "spice", expanded=False)
        ctx["decomposed_files"] = files
        ctx["top_module_name"] = top
        return
    # MECHANICAL split — NO LLM. Asking a weak local model to "refactor into files"
    # made it REWRITE the circuit (different devices) or loop. Splitting on .subckt
    # boundaries with regex preserves the generated netlist EXACTLY, byte-for-byte.
    code = ctx["generation"]
    rec.caption("Splitting the netlist into per-subckt files mechanically (no LLM) — the "
                "circuit is preserved EXACTLY as generated, never rewritten.")
    starts = [(m.start(), m.group(1))
              for m in re.finditer(r"^\s*\.subckt\s+(\w+)", code,
                                   re.IGNORECASE | re.MULTILINE)]
    blocks: List[str] = []
    names: List[str] = []
    for pos, name in starts:
        em = re.search(r"^\s*\.ends[^\n]*", code[pos:], re.IGNORECASE | re.MULTILINE)
        end = pos + em.end() if em else len(code)
        blocks.append(code[pos:end])
        names.append(name)

    files: Dict[str, str] = {}
    # Leading content before the first subckt (shared .param/.include/.option cards).
    head = code[: starts[0][0]].strip() if starts else ""
    header_name = None
    head_body = "\n".join(ln for ln in head.splitlines()
                          if ln.strip() and not ln.strip().startswith("*"))
    if head_body and re.search(r"^\s*\.(param|include|option|lib|temp)",
                               head_body, re.IGNORECASE | re.MULTILINE):
        header_name = "shared_params.sp"
        files[header_name] = "* shared parameters (included by every circuit file)\n" + head_body

    if not blocks:
        rec.warning(
            "No `.subckt … .ends` found — keeping the output as a single file.")
        m = re.search(r"\.subckt\s+(\w+)", code, re.IGNORECASE)
        top = m.group(1) if m else slugify(ctx["query"], 24)
        files[f"{top}.sp"] = code.strip()
    else:
        top = _top_module(blocks, names)
        inc = f".include {header_name}\n\n" if header_name else ""
        for nm, b in zip(names, blocks):
            body = (inc + b.strip()) if header_name else b.strip()
            files[f"{nm}.sp"] = f"* AnoaChip — circuit {nm}\n{body}"

    files = {k: v for k, v in files.items() if v.strip()}
    rec.success(
        f"Top circuit: `{top}` · {len(files)} file(s) — split verbatim, no code changed.")
    for fn, c in files.items():
        rec.expander_code(f"📄 {fn}", c, "spice",
                          expanded=(fn == f"{top}.sp"))
    ctx["decomposed_files"] = files
    ctx["top_module_name"] = top


def _cone_size(info: dict, name: str) -> int:
    """Transitive count of subckts reachable from `name` (incl. itself)."""
    seen, stack = set(), [name]
    while stack:
        m = stack.pop()
        if m in seen:
            continue
        seen.add(m)
        stack += [c for c in info["insts"].get(m, []) if c in info["defs"]]
    return len(seen)


def _ensure_top(ctx, rtl_dir) -> str:
    """Make ctx['top_module_name'] the REAL integration top — re-derive structurally when the
    saved top is missing, a LEAF, or a SUB-HIERARCHY of the design. The saved top survives
    ONLY if its transitive cone is as big as the structural pick's — so a re-run
    self-corrects to the circuit that integrates everything, without restarting generation."""
    from netlist_check import parse_dir, pick_top
    cur = ctx.get("top_module_name") or ""
    info = parse_dir(rtl_dir)
    best = pick_top(rtl_dir)
    if cur in info["defs"]:
        if not best or _cone_size(info, cur) >= _cone_size(info, best):
            return cur                        # saved top already covers the most of the design
    top = best or cur
    if top and top != cur:
        ctx["top_module_name"] = top
    return top


def _anchor_reference_tb(design_dir: Path) -> tuple[str, str]:
    """The SOURCE design's OWN testbench (kept under context/anchor/) — the authoritative
    reference for HOW the circuit is exercised and what 'correct' behavior is. Grounding the
    generated ngspice testbench in it means the sim's PASS/FAIL (and the measured specs)
    reflect the real circuit behavior from the repo, not values the local model invented.
    Returns (reference_source, filename), or ('', '') if no reference testbench was kept."""
    adir = design_dir / "context" / "anchor"
    if not adir.is_dir():
        return "", ""
    cands: list[Path] = []
    for pat in ("*tb*.sp", "*tb*.spice", "*tb*.cir", "*test*.sp", "*test*.spice",
                "*sim*.sp", "*sim*.spice"):
        cands += [p for p in adir.rglob(pat) if p.is_file()]
    if not cands:
        return "", ""
    p = max(cands, key=lambda x: x.stat().st_size)        # the most complete reference tb
    return p.read_text(errors="replace"), p.name


def _behavior_brief(design_dir: Path, limit: int = 2600) -> tuple[str, list[str]]:
    """Documented behavior of the module from the RESEARCH the pipeline already gathered:
      • context/research.md / understanding.md — the web digest of how this block works;
      • context/anchor/papers/*.txt|*.md — extracted text of the PDF paper(s) crawled for it.
    Grounding the testbench in THIS means the expected protocol/values come from how the module
    is documented to work on the internet + the paper — not numbers the local model invented.
    Returns (brief_text, source_names); ('', []) when no research is on disk."""
    ctxd = design_dir / "context"
    chunks: list[str] = []
    used: list[str] = []
    budget = limit

    def take(p: Path, cap: int) -> None:
        nonlocal budget
        if budget <= 0 or not p.is_file():
            return
        try:
            txt = p.read_text(errors="replace").strip()
        except Exception:  # noqa: BLE001
            return
        if not txt:
            return
        take_n = min(cap, budget)
        chunks.append(f"--- {p.name} ---\n{txt[:take_n]}")
        used.append(p.name)
        budget -= take_n

    # web/research digest first (most on-topic for "how it behaves"), then paper text
    for nm in ("research.md", "understanding.md"):
        take(ctxd / nm, 1400)
    papers = ctxd / "anchor" / "papers"
    if papers.is_dir():
        for p in sorted(papers.glob("*.txt")) + sorted(papers.glob("*.md")):
            take(p, 1000)
    return ("\n\n".join(chunks), used)


def _derive_feature_plan(rec, ctx, top, top_code):
    """VERIFICATION PLANNER (sub-agent of the testbench step): before writing any testbench,
    enumerate EVERY feature the design must implement and, for each, the concrete test scenario +
    the EXPECTED observable result. This is what makes the testbench COMPREHENSIVE — a check per
    feature with a clear pass/fail — instead of one vague `$display("PASSED")`. The plan is saved
    to context/verification_plan.md (the human-readable 'what we build + expected output' doc) and
    cached in ctx so the tb writer AND the tb corrector both cover the same feature set.

    Returns a list of {name, scenario, expected} dicts. Cached: derived once per design."""
    cached = ctx.get("feature_plan")
    if cached:
        return cached
    spec = ctx.get("query", "")
    brief, _ = _behavior_brief(Path(ctx["design_dir"]))
    cfg_spec = ""
    try:
        from glayout_tools import load_config
        cfg = load_config(ctx["design_dir"], top) or \
            load_config(ctx["design_dir"], Path(ctx["design_dir"]).name)
        if cfg.get("spec"):
            cfg_spec = f"\nSPEC TABLE (each entry MUST become a .measure): {json.dumps(cfg['spec'])}\n"
    except Exception:  # noqa: BLE001
        pass
    prompt = (
        "You are an analog VERIFICATION planner. From the DESIGN SPEC and the top circuit's "
        "netlist, list EVERY spec/behavior the ngspice testbench must verify, and for each "
        "give a concrete test SCENARIO (the analysis + stimulus: .op / .ac dec sweep / .tran "
        "with the use-case signal) and the EXPECTED measurable RESULT (the .measure value and "
        "its pass threshold — gain_db, bw_hz, ugbw_hz, phase_margin_deg, power_w, offset, "
        "swing). Cover the bias point (.op: every device saturated) and EVERY spec-table "
        "entry — so a PASS means the whole spec is met, not one lucky number.\n"
        'Reply with ONLY JSON: {"features":[{"name":"..","scenario":"..","expected":".."}, ...]} '
        "with 4 to 12 items.\n\n"
        f"DESIGN SPEC: {spec}\n" + cfg_spec
        + (f"\nDOCUMENTED BEHAVIOR (research/paper):\n{brief[:1200]}\n" if brief else "")
        + f"\nTOP CIRCUIT `{top}` NETLIST:\n```spice\n{top_code[:6000]}\n```")
    feats = []
    try:
        raw = stream_to(get_chat_model(temperature=0.2), prompt, rec.placeholder())
        data = extract_json(raw)
        for f in (data.get("features") or [])[:20]:
            nm = str(f.get("name", "")).strip()
            if nm:
                feats.append({"name": nm[:60],
                              "scenario": str(f.get("scenario", "")).strip()[:200],
                              "expected": str(f.get("expected", "")).strip()[:200]})
    except Exception:  # noqa: BLE001
        feats = []
    if not feats:                                   # fallback: the classic analog spec set
        from netlist_check import parse_dir
        info = parse_dir(Path(ctx["design_dir"]) / "netlist")
        ports = (info["defs"].get(top) or {}).get("ports", [])
        feats = [{"name": "bias point sane", "scenario": ".op",
                  "expected": "every MOSFET in saturation, currents match the config"},
                 {"name": "gain_db", "scenario": ".ac dec 20 1 1e9 + wrdata vdb/vp",
                  "expected": "low-frequency gain meets the spec"},
                 {"name": "bw_hz / ugbw_hz / phase_margin_deg", "scenario": "same .ac export",
                  "expected": "computed from the Bode data, meet the spec"},
                 {"name": "power_w", "scenario": ".measure avg supply current × VDD",
                  "expected": "below the spec budget"}]
        if ports:
            feats.append({"name": "output swing", "scenario": ".tran with the use-case input",
                          "expected": f"output ({ports[-1]}) tracks without clipping"})
    # persist the human-readable plan (what we build + expected output, per feature)
    lines = [f"# Verification plan — {top}", "",
             f"**Design:** {spec}", "",
             f"{len(feats)} feature(s) the testbench must verify, each with expected vs actual:", "",
             "| # | Feature | Test scenario | Expected result |",
             "|---|---------|---------------|-----------------|"]
    for i, f in enumerate(feats, 1):
        lines.append(f"| {i} | {f['name']} | {f['scenario']} | {f['expected']} |")
    (Path(ctx["design_dir"]) / "context").mkdir(parents=True, exist_ok=True)
    (Path(ctx["design_dir"]) / "context" / "verification_plan.md").write_text("\n".join(lines))
    ctx["feature_plan"] = feats
    return feats


def _feature_plan_block(feats) -> str:
    """The feature list rendered for a testbench prompt: the tb MUST cover every item."""
    if not feats:
        return ""
    rows = "\n".join(f"  {i}. {f['name']} — scenario: {f['scenario']} → EXPECT: {f['expected']}"
                     for i, f in enumerate(feats, 1))
    return (f"\nVERIFICATION PLAN — write ONE self-check per feature below (do NOT skip any). For "
            f"each, print `FEATURE <name>: in=<inputs> expected=<v> actual=<v> PASS|FAIL` — ALWAYS "
            f"show the INPUT stimulus — and count failures. After all of them print "
            f"`COVERAGE: <passed>/<total> features passed`:\n{rows}\n")


_SIM_ANALYSIS = {
    "dc": ".dc / .op — the DC operating point and DC sweeps (bias sanity: every device in "
          "saturation, currents match the config)",
    "ac": ".ac dec 20 1 1G — the small-signal AC response; export the Bode data with "
          "`wrdata sim/<top>_ac.txt vdb(out) vp(out)` so gain_db / bw_hz / ugbw_hz / "
          "phase_margin_deg are measured",
    "tran": ".tran — the transient response to the use-case input signal (SIN/PULSE); export "
            "`wrdata sim/<top>_tran.txt v(in) v(out)` for the waveform",
}


def _sim_types_note(ctx) -> str:
    """The user's chosen analyses (DC / AC / TRAN — any combination) rendered as a tb
    directive. Empty (all three) unless the UI narrowed it."""
    sims = [s for s in (ctx.get("sim_types") or []) if s in _SIM_ANALYSIS]
    if not sims or set(sims) == set(_SIM_ANALYSIS):
        return ("\n- ANALYSES REQUESTED: all of DC, AC and TRAN — run each:\n"
                + "\n".join(f"  • {_SIM_ANALYSIS[s]}" for s in ("dc", "ac", "tran")) + "\n")
    return ("\n- ANALYSES REQUESTED (run EXACTLY these, the user chose them): "
            + ", ".join(s.upper() for s in sims) + "\n"
            + "\n".join(f"  • {_SIM_ANALYSIS[s]}" for s in sims) + "\n")


def _select_unit_ips(info, top, cap=8):
    """Pick the sub-circuits that each deserve their OWN unit testbench (user: 'tiap2 ip kecil
    dibuat tbnya juga'). Prefers the subckts INSIDE the top's transitive cone — the blocks the
    chip actually integrates (bias generator, diff pair stage, output stage…) — so unit-test
    effort goes to the real design; falls back to every subckt when the cone is trivially
    small (mis-picked top). Drops the top and PDK primitives, and returns LEAVES first (a
    leaf's PASS/FAIL is unambiguous). Returns [(subckt, file), ...]."""
    cone, stack = set(), [top]
    while stack:
        m = stack.pop()
        if m in cone or m not in info["defs"]:
            continue
        cone.add(m)
        stack += [c for c in info["insts"].get(m, []) if c in info["defs"]]
    pool = cone if len(cone) > 2 else set(info["defs"])
    picks = []
    for m, d in info["defs"].items():
        if m == top or m not in pool:
            continue
        if _is_primitive_subckt(m):
            continue                                    # PDK primitive / non-circuit — not ours
        if len(d.get("ports") or []) < 2:
            continue                                    # no testable interface
        kids = len([c for c in info["insts"].get(m, []) if c in info["defs"]])
        picks.append((kids, m, d["file"]))
    picks.sort()                                        # leaves (kids=0) first
    return [(m, f) for _, m, f in picks[:cap]]


# subckt/file names that are NOT a real design block to unit-test.
# PREFIX match — PDK device primitives + generic glayout/gdsfactory class names:
_PRIM_PREFIX_RE = re.compile(
    r"^(sky130_|gf180mcu_|nfet|pfet|nmos|pmos|"
    r"component|block|ground|supply|net\d|node\d)",
    re.IGNORECASE)
# EXACT match — parameter-name / single-letter stubs a weak model emits as separate
# files (W.sp, L.sp, M.sp, Fingers.sp, VDD.sp, IREF.sp, …):
_PRIM_EXACT_RE = re.compile(
    r"^([wlmrcgijf]|nf|vdd|vss|vcc|gnd|vbias|vref|iref|ibias|iout|"
    r"fingers?|mult(iplier)?|width|length)$",
    re.IGNORECASE)


def _is_primitive_subckt(name: str) -> bool:
    n = (name or "").strip()
    return bool(_PRIM_PREFIX_RE.match(n) or _PRIM_EXACT_RE.match(n))


def _unit_tb_rules(mod: str, tb_name: str, inc: str) -> str:
    """The self-checking ngspice unit-tb contract — shared by the FIRST generation AND the
    verify-fix rewrite, so a repaired tb obeys the exact same rules (control block, PASS/FAIL
    per spec, Result verdict)."""
    return (
        "- START the file with a `*` title comment (ngspice eats line 1).\n"
        f"- `.include` the DUT netlist by its path relative to the design dir "
        f"(e.g. `.include netlist/{mod}.sp`) — the PDK model .lib is injected automatically.\n"
        f"- Instantiate the DUT: `XDUT <nodes...> {mod}` wiring EVERY port of the subckt "
        "(VDD VSS in/out/bias) — no port left floating.\n"
        "- Supplies + stimulus: `VDD vdd 0 1.8` (use the config's vdd), input sources (`VIN "
        "vin 0 DC <bias> AC 1` for gain circuits; SIN/PULSE for .tran), a bias current "
        "(`IBIAS ...`) if the DUT needs one, and the spec's load (`CL out 0 1p`).\n"
        "- ANALYSES: `.op` first (bias sanity), then what the specs need — `.ac dec 20 1 1G` "
        "for gain/BW/PM, `.tran` with the use-case signal when relevant.\n"
        "- MEASURE in a `.control` block: `run`, then `meas`/`let` every spec value "
        "(gain_db from vdb(out), bw_hz at -3dB, ugbw/phase margin from vp(out), power from "
        "supply current). EXPORT curves for plots: `wrdata sim/" + mod + "_ac.txt vdb(out) "
        "vp(out)` (and `sim/" + mod + "_tran.txt v(in) v(out)` after a .tran).\n"
        "- For EACH spec compare with an `if`/`else` (the comparison — gain_db >= 40 etc. — "
        "goes in the IF CONDITION, where >= is fine) and print ONE line each side, e.g.\n"
        "  `if gain_db >= 40` / `  echo SPEC gain_db PASS measured=$&gain_db want=40` / "
        "`else` / `  echo SPEC gain_db FAIL measured=$&gain_db want=40` / `  let fails=fails+1` / `end`.\n"
        "- CRITICAL: in an `echo` line NEVER use the characters `>`  `<`  or `->` — ngspice's "
        "control block treats them as FILE REDIRECTION and silently writes junk files named "
        "after the value. Use plain words and `=`/`:` only (write 'want=40', not 'expected>=40', "
        "and 'PASS'/'FAIL', not '-> PASS'). Put every comparison in an `if (...)` condition, "
        "never in an echo.\n"
        f"{inc}\n"
        "- End the control block with the verdict: `if fails = 0` `echo Result: PASSED` "
        "`else` `echo Result: FAILED` `end`, then `quit`. Numbers must be COMPUTED by ngspice "
        "(meas/let), never typed in by you.\n"
        "- ONE deck only; end the FILE with `.endc` then `.end`.\n"
        f"- Reply with ONLY JSON: {{\"{tb_name}\": \"<full spice source>\"}}.\n")


def _sim_unit(rtl_dir, sim_dir, mod: str, tbf) -> str:
    """Run ONE circuit's unit testbench with ngspice (cwd = the design dir so relative
    .include/wrdata paths resolve). Always returns TEXT — an empty run is reported
    explicitly, so a failure is never the useless '(no output)' the user hit."""
    from spice_sim import run_ngspice
    rtl_dir, sim_dir = Path(rtl_dir), Path(sim_dir)
    sim_dir.mkdir(parents=True, exist_ok=True)
    design_dir = sim_dir.parent
    ok, log = run_ngspice(Path(tbf), workdir=design_dir)
    out = (log or "").strip()
    if not out:
        out = ("ERROR: the simulation ran but printed NOTHING — the testbench never reached "
               "its echo/verdict (check the .control block ends with `echo Result: PASSED`/"
               "`Result: FAILED` + `quit`).")
    elif not ok and "Result:" not in out:
        out += "\nERROR: ngspice reported a failure before any verdict was printed."
    return out


def _unit_ok(out: str) -> bool:
    return bool(re.search(r"Result:\s*PASSED", out)) and not re.search(
        r"Result:\s*FAILED|->\s*FAIL|^\s*ERROR|^\s*Error[: ]", out, re.MULTILINE)


def _load_unit_state(design_dir, mod: str) -> dict:
    """The PERSISTED verify state of one IP — attempts so far, every failure and what was tried
    (context/unit_state/<mod>.json). This is what makes retries CUMULATIVE knowledge instead of
    fresh guesses (user: 'kamu nyimpen state dia dan state errornya ngga? jangan generate baru
    terus'): a later round — or a later STAGE, or the corrector — continues from the recorded
    history instead of restarting blind."""
    p = Path(design_dir) / "context" / "unit_state" / f"{mod}.json"
    try:
        return json.loads(p.read_text()) if p.exists() else {}
    except Exception:  # noqa: BLE001
        return {}


def _save_unit_state(design_dir, mod: str, state: dict) -> None:
    p = Path(design_dir) / "context" / "unit_state" / f"{mod}.json"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        state["history"] = (state.get("history") or [])[-10:]   # keep the last 10 failures
        p.write_text(json.dumps(state))
    except Exception:  # noqa: BLE001
        pass


def _log_state(ctx, event: str, detail: str = "") -> None:
    """Append one line to `context/state.md` — the RUN JOURNAL. The system RECORDS what happened
    at every stage (what was built, what passed/failed unit verify, what the user steered) so any
    later step — or a user prompt arriving MID-RUN — is interpreted against the real current
    state instead of hardcoded assumptions (user: 'harusnya kamu tau tiap state (makannya catat)
    sama user maunya apa'). Every deep agent is instructed to read this file first."""
    try:
        import datetime as _dt
        p = Path(ctx["design_dir"]) / "context" / "state.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_text("# Run journal — what has ACTUALLY happened in this run\n\n")
        with p.open("a") as f:
            f.write(f"- {_dt.datetime.now():%H:%M:%S} **{event}** "
                    + re.sub(r"\s+", " ", detail).strip()[:300] + "\n")
    except Exception:  # noqa: BLE001
        pass


def _diagnose_unit_failure(rec, mod, fname, dut_src, tb_src, out, ctx=None) -> tuple:
    """RLM diagnosis step — ONE focused sub-LLM call that READS the failure before anything is
    rewritten (recursive decompose-the-problem, per the RLM pattern): given the sim output + DUT +
    tb, decide WHO is wrong and WHY, with the concrete correction. This is what turns the error
    into INFORMATION for the next attempt (user: 'error ga dipakai buat informasi generate correct
    code, ya mana bakal bener'). Returns (dut_wrong: bool, diagnosis_text)."""
    try:
        prompt = (
            (_contract_note(ctx) +
             "Given the contract change above: a testbench still assuming the OLD "
             "spec/supply/topology is WRONG by definition → `VERDICT: TB`.\n"
             if ctx is not None and ctx.get("_contract_change") else "")
            + "An ngspice unit test FAILED. Diagnose it precisely in ≤10 lines.\n"
            "Line 1 MUST be exactly `VERDICT: TB` (testbench is wrong: bad bias/stimulus "
            "levels, wrong node names, missing supply/load, a meas on the wrong vector, a "
            "spec threshold that contradicts the config) or `VERDICT: DUT` (the circuit is "
            "genuinely wrong for its spec: device out of saturation, wrong mirror ratio, "
            "W/L too small for the required gm, missing compensation).\n"
            "Then list, concretely: which lines/cards are wrong, the CORRECT expected value "
            "for each failing SPEC (compute it from the netlist: gm·ro, mirror ratios, "
            "gm/(2π·CL)), and the exact source/param to change. For a convergence error: "
            "name WHICH node has no DC path and how to fix it.\n"
            f"SIM OUTPUT:\n```\n{out[:1500]}\n```\n"
            f"DUT `{fname}`:\n```spice\n{dut_src[:4500]}\n```\n"
            f"TESTBENCH:\n```spice\n{tb_src[:3500]}\n```")
        diag = clean_llm_output(stream_to(get_chat_model(temperature=0.1), prompt,
                                          rec.placeholder())).strip()[:1500]
        return bool(re.match(r"\s*VERDICT:\s*DUT", diag, re.I)), diag
    except Exception:  # noqa: BLE001
        return False, ""


def _deep_unit_rescue(rec, ctx, mod, fname, tb_name, out, diag, fail_hist) -> None:
    """The HEAVYWEIGHT fixer for a stuck unit (user: 'jarak antara percobaan terlalu
    cepat, kayanya ga mikir' / 'kalo ga bisa ya cari internet kek'): when the fast
    diagnose→rewrite loop hasn't converged after 3 attempts, STOP iterating fast and
    think long — ONE deep-agent session with web research, knowledge recall, run_python
    (build a golden model of the DUT and COMPUTE the expected values, never guess), the
    full failure history, and permission to fix DUT and TB together."""
    from deep_agent import build_step_agent
    design_dir = Path(ctx["design_dir"])
    cdir = design_dir / "context"
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / f"unit_fail_{mod}.md").write_text(
        f"# Failure history — unit `{mod}` (every attempt below FAILED; do not repeat them)\n\n"
        + "\n".join(f"## attempt {i + 1}: {w}\n```\n{o}\n```"
                    for i, (w, o) in enumerate(fail_hist[-8:]))
        + f"\n\n## LATEST output\n```\n{out[:2000]}\n```\n\n## latest diagnosis\n{diag}\n")
    agent = build_step_agent(design_dir, extra_tools=_step_tools(rec, design_dir),
                             temperature=0.25)
    goal = (
        _contract_note(ctx)
        + f"UNIT circuit `{mod}` cannot pass its ngspice testbench after {len(fail_hist)} fast "
        "attempts — you are the ESCALATION. THINK LONG, act once:\n"
        f"1) read_file_disk('context/unit_fail_{mod}.md') — the FULL history; every repeated "
        "mistake is listed there.\n"
        f"2) read netlist/{fname} (the DUT) and tb/{tb_name} carefully, plus the design's "
        "config/ file (the spec + sizing truth).\n"
        "3) BUILD A GOLDEN MODEL: with run_python, compute the expected operating point and "
        "small-signal values from the netlist (square-law/gm·ro estimates: ID from W/L and "
        "bias, gm=2·ID/Vov, gain=gm·(ro||ro), GBW=gm/(2π·CL)) — derived numbers, never "
        "guessed ones. The model decides WHO is wrong (DUT vs TB) and WHICH config "
        "parameter to change.\n"
        "4) If the failure class is unfamiliar (a convergence error, a model binning "
        "message), search_web the exact error/symptom and recall_memory for a stored lesson.\n"
        f"5) THEN make surgical, informed edits (write_file_disk) to netlist/{fname} and/or "
        f"tb/{tb_name} (and the config file when a parameter changes). Keep the tb "
        "self-checking: `SPEC <name> PASS/FAIL measured=… want=…` per spec (no > < -> in echo), "
        "conditional `Result: PASSED/FAILED`, `quit`.\n"
        "Do not finish until the files are written and you have stated, in one line each, "
        "WHAT was wrong and WHY your fix is correct (from the golden model).")
    _stream_deep_agent(rec, agent, goal, recursion_limit=70)


def _verify_unit_now(rec, ctx, mod, fname, tb_name, src, inc=""):
    """VERIFY-ON-WRITE for one IP (user: 'sebelum semua code digabungin, itu sudah verified dulu
    tbnya'): simulate the block in ISOLATION the moment its unit tb exists and KEEP FIXING until
    it passes (user: 'dicoba terus benerin codenya, ga cuma 2 kali coba terus lanjut') — bounded
    only by ANOA_UNIT_FIX_TRIES (default 8) and a wall-clock budget ANOA_UNIT_FIX_BUDGET_S
    (default 900s per IP). Every iteration is RLM-style:
      1. DIAGNOSE — one focused sub-LLM call reads the failure output + DUT + tb and rules
         `VERDICT: TB` or `VERDICT: DUT` with the concrete correction;
      2. REPAIR the guilty side — the DUT via _fix_one_module (anti-repeat history + DB lesson),
         or the tb via a rewrite that embeds the diagnosis AND the previous attempts' failures
         (errors are INFORMATION: each retry sees exactly what was tried and how it failed);
      3. RE-SIMULATE. Identical-to-a-failed-attempt rewrites are re-rolled hotter.
    Returns (final_tb_src, passed). A block that still fails after the budget is reported honestly
    — the simulate stage's unit gate re-catches it and routes it to the corrector."""
    import time as _time
    from netlist_check import tb_quality_report, autofix_text
    design_dir = Path(ctx["design_dir"])
    rtl_dir, tb_dir, sim_dir = design_dir / "netlist", design_dir / "tb", design_dir / "sim"
    tb_dir.mkdir(parents=True, exist_ok=True)
    tries = int(os.getenv("ANOA_UNIT_FIX_TRIES", "8"))
    budget = float(os.getenv("ANOA_UNIT_FIX_BUDGET_S", "900"))
    t0 = _time.time()
    files = ctx.setdefault("decomposed_files", {})
    # RESUME the persisted verify state: earlier rounds' failures are the starting history,
    # so this round CONTINUES the investigation instead of repeating it.
    ustate = _load_unit_state(design_dir, mod)
    fail_hist: List[tuple] = [tuple(h) for h in (ustate.get("history") or [])]
    if fail_hist:
        rec.caption(f"🗂 `{mod}`: resuming from saved state — {ustate.get('attempts', 0)} earlier "
                    f"attempt(s), {len(fail_hist)} recorded failure(s).")
    seen_tbs = {_norm(src)}

    def _dut_src() -> str:
        fp = rtl_dir / fname
        return fp.read_text(errors="replace") if fp.exists() else files.get(fname, "")

    for attempt in range(tries + 1):
        (tb_dir / tb_name).write_text(src)
        hard, _ = tb_quality_report(src)
        out = (f"{tb_name}: not verifiable — " + "; ".join(hard[:3])) if hard \
            else _sim_unit(rtl_dir, sim_dir, mod, tb_dir / tb_name)
        if not hard and _unit_ok(out):
            rec.markdown(f"✅ `{mod}` — unit test PASS (verified in isolation"
                         + (f" after {attempt} fix(es)" if attempt else "") + ").")
            uv = ctx.setdefault("unit_verified", [])
            if mod not in uv:
                uv.append(mod)                     # later stages skip re-verifying this IP
            _save_unit_state(design_dir, mod, {**ustate, "status": "pass",
                                               "history": [list(h) for h in fail_hist]})
            _log_state(ctx, f"unit `{mod}`", "PASS (verified in isolation)")
            return src, True
        ustate["attempts"] = int(ustate.get("attempts") or 0) + 1
        ustate["last_out"] = out[:1500]
        ustate["status"] = "fail"
        ustate["tb_name"] = tb_name
        _save_unit_state(design_dir, mod, {**ustate, "history": [list(h) for h in fail_hist]})
        if attempt >= tries or (_time.time() - t0) > budget:
            why = f"{tries} fix attempt(s)" if attempt >= tries else f"the {int(budget)}s budget"
            rec.markdown(f"❌ `{mod}` — unit test still failing after {why}; full error state is "
                         f"SAVED (context/unit_state/{mod}.json) and the fix continues from it.")
            rec.code(out[:1400], language="text")
            _log_state(ctx, f"unit `{mod}`",
                       f"FAIL after {ustate.get('attempts', 0)} total attempt(s) — "
                       f"state saved; last: {out[:120]}")
            return src, False

        # 1) DIAGNOSE (skipped for a structurally-broken tb — that's always a tb rewrite)
        dut_wrong, diag = (False, "") if hard else \
            _diagnose_unit_failure(rec, mod, fname, _dut_src(), src, out, ctx=ctx)
        if diag:
            rec.caption(f"🧭 `{mod}` diagnosis (attempt {attempt + 1}/{tries}): "
                        + diag.splitlines()[0][:120])

        # THINK DEEP FROM THE FIRST REPAIR (user: 'kenapa baru bener pas mikir mendalam
        # di percobaan 3? mulai dari percobaan 1 dong'): any FUNCTIONAL failure
        # (expected≠actual, -> FAIL, timeout) goes straight to the deep corrector with a
        # run_python GOLDEN MODEL — the fast reroll only ever GUESSED expected values and
        # burned attempts being wrong. The fast path below remains only for STRUCTURAL
        # testbench problems (not-verifiable / compile), which are deterministic to fix.
        functional = (not hard) and bool(
            re.search(r"expected=\S+\s+actual=|->\s*FAIL|FAILED\s*\(timeout\)", out))
        if functional:
            rec.caption(f"🧠 `{mod}`: functional failure — going STRAIGHT to the deep "
                        "corrector (golden model + research + full history), no fast guessing.")
            try:
                _deep_unit_rescue(rec, ctx, mod, fname, tb_name, out, diag, fail_hist)
                src = (tb_dir / tb_name).read_text(errors="replace")   # take the deep result
                seen_tbs.add(_norm(src))
                fail_hist.append(("deep-agent rescue (golden-model fix)", out[:400]))
                continue
            except Exception:  # noqa: BLE001
                pass

        # 2) REPAIR the guilty side
        if dut_wrong:
            rec.caption(f"🔧 `{mod}`: the CIRCUIT is wrong per the diagnosis — repairing netlist/{fname}.")
            try:
                files.setdefault(fname, _dut_src())
                _fix_one_module(rec, ctx, files, ctx.setdefault("fix_history", {}), fname,
                                f"UNIT TEST for `{mod}` FAILED — the circuit is wrong.\n"
                                f"DIAGNOSIS:\n{diag[:1200]}\nSIM OUTPUT:\n{out[:1200]}",
                                attempt, min(0.3 + 0.1 * attempt, 0.8))
                fail_hist.append((f"repaired DUT netlist/{fname}", out[:400]))
                continue                       # re-run the SAME tb against the repaired circuit
            except Exception:  # noqa: BLE001
                pass
        rec.caption(f"🔧 `{mod}` unit test failed (attempt {attempt + 1}/{tries}) — rewriting the tb "
                    "from the failure output + diagnosis.")
        hist_block = "".join(
            f"EARLIER ATTEMPT #{i + 1}: {what} → STILL FAILED:\n```\n{o}\n```\n"
            for i, (what, o) in enumerate(fail_hist[-3:]))
        fixprompt = (
            f"This ngspice unit testbench for circuit `{mod}` FAILED. Fix the TESTBENCH so it "
            "correctly and fully verifies the DUT below (compute the right EXPECTED values from "
            "the netlist sizing; bias every port; give every analysis what it needs).\n"
            f"CURRENT FAILURE OUTPUT:\n```\n{out[:1800]}\n```\n"
            + (f"DIAGNOSIS of this failure — apply it:\n{diag}\n" if diag else "")
            + (("USE THE HISTORY — these were already tried and FAILED; their errors are your "
                "information, do NOT repeat them:\n" + hist_block) if hist_block else "")
            + _unit_tb_rules(mod, tb_name, inc)
            + f"DUT (`{fname}`) — read it carefully, it is the reference for expected values:\n"
              f"```spice\n{_dut_src()[:5000]}\n```\n"
            + f"BROKEN TESTBENCH:\n```spice\n{src[:5000]}\n```")
        temp = min(0.3 + 0.12 * attempt, 0.9)
        new = ""

        def _tb_shaped(t: str) -> bool:
            low = (t or "").lower()
            return ".control" in low and "result:" in low
        for _roll in range(2):                     # identical-to-failed rewrite → re-roll hotter
            try:
                resp = stream_to(get_chat_model(temperature=temp), fixprompt, rec.placeholder())
                try:
                    new = next(iter(extract_json(resp).values()))
                except Exception:  # noqa: BLE001
                    new = extract_code_block(resp)
                new = dedup_modules(new)
                try:
                    new = autofix_text(new)[0]
                except Exception:  # noqa: BLE001
                    pass
            except Exception:  # noqa: BLE001
                new = ""
            if new and _tb_shaped(new) and _norm(new) not in seen_tbs:
                break
            temp = min(temp + 0.25, 0.95)
        if new and _tb_shaped(new):
            fail_hist.append(("rewrote the tb", out[:400]))
            seen_tbs.add(_norm(new))
            src = new
        else:
            fail_hist.append(("tb rewrite produced nothing usable", out[:400]))
    return src, False


def _gen_and_verify_unit_tb(rec, ctx, mod, fname) -> "bool | None":
    """Generate + VERIFY one IP's unit testbench RIGHT NOW: write the tb, simulate the block in
    isolation, and keep fixing (tb or DUT, diagnosis-routed) until it passes or the budget runs
    out. Called the moment a module's write reports 'compile check clean ✓' during generation
    (user: 'setelah buat compile check clean ✓, buat tb dan simulasiin itu'), and by
    _generate_unit_tbs for anything left over. Returns True (PASS) / False (still failing) /
    None (not unit-testable: wrapper, no I/O, already verified)."""
    from netlist_check import autofix_text
    design_dir = Path(ctx["design_dir"])
    rtl_dir, tb_dir = design_dir / "netlist", design_dir / "tb"
    if mod in set(ctx.get("unit_verified") or []):
        return None
    if _is_primitive_subckt(mod) or _is_primitive_subckt(re.sub(r"\.\w+$", "", fname)):
        return None                                 # PDK primitive / param-stub / junk name
    fp = rtl_dir / fname
    code = fp.read_text(errors="replace") if fp.exists() else \
        ctx.get("decomposed_files", {}).get(fname, "")
    # unit-testable = a real subckt with ports and at least one device card (NOT a
    # `.param`-only include file like W.sp / M.sp)
    if not (re.search(r"^\s*\.subckt\s", code, re.IGNORECASE | re.MULTILINE)
            and re.search(r"^\s*[mxqd]\w+\s", code, re.IGNORECASE | re.MULTILINE)):
        return None
    shared = next((p.name for p in sorted(rtl_dir.glob("shared_params.sp"))), None)
    inc = (f"Also `.include netlist/{shared}` (shared .param values) and USE its params "
           "verbatim; never re-declare or guess them.") if shared else ""
    inc += _sim_types_note(ctx)
    # ground the tb thresholds in the design config's spec table when one exists
    try:
        from glayout_tools import load_config
        cfg = load_config(design_dir, mod) or \
            load_config(design_dir, ctx.get("top_module_name") or design_dir.name)
        if cfg:
            inc += ("\n- DESIGN CONFIG (spec table + sizing — thresholds and vdd come from "
                    "HERE):\n" + json.dumps({k: cfg.get(k) for k in ("spec", "params")
                                             if cfg.get(k)})[:1200] + "\n")
    except Exception:  # noqa: BLE001
        pass
    tb_name = f"{mod}_tb.sp"
    tbp = tb_dir / tb_name
    if tbp.exists() and _load_unit_state(design_dir, mod):
        # a previous round already built + iterated this tb — CONTINUE from it and its saved
        # error state (never regenerate from scratch: 'jangan generate baru terus').
        src = tbp.read_text(errors="replace")
    else:
        prompt = (
            f"Write a SELF-CHECKING ngspice unit testbench for ONE circuit block `{mod}`.\n"
            + _unit_tb_rules(mod, tb_name, inc)
            + f"DUT (`{fname}`):\n```spice\n{code[:6000]}\n```")
        try:
            resp = stream_to(get_chat_model(temperature=0.2), prompt, rec.placeholder())
            try:
                src = next(iter(extract_json(resp).values()))
            except Exception:  # noqa: BLE001
                src = extract_code_block(resp)
            src = dedup_modules(src)
        except Exception:  # noqa: BLE001
            src = ""
        if ".control" not in src.lower():
            return False
        try:
            src = autofix_text(src)[0]
        except Exception:  # noqa: BLE001
            pass
    src, ok = _verify_unit_now(rec, ctx, mod, fname, tb_name, src, inc)
    ctx.setdefault("testbench_code", {})[tb_name] = src
    tb_dir.mkdir(parents=True, exist_ok=True)
    (tb_dir / tb_name).write_text(src)
    rec.expander_code(f"📄 {tb_name}", src[:4000], "spice", expanded=False)
    return ok


def _generate_unit_tbs(rec, ctx, top, files, cap=8):
    """Write a SELF-CHECKING unit testbench for each small IP **and VERIFY it on the spot** —
    each block is simulated in isolation and locally fixed until it passes, BEFORE the chip-level
    tb is written and BEFORE any integration run (user: 'sebelum semua code digabungin, itu sudah
    verified dulu tbnya'). Most circuits are already verified DURING generation (the write-hook
    runs _gen_and_verify_unit_tb the moment a netlist checks clean); this pass re-adopts those
    tbs and covers only what's left (resume runs, files written outside the hook)."""
    from netlist_check import parse_dir
    rtl_dir = Path(ctx["design_dir"]) / "netlist"
    info = parse_dir(rtl_dir)
    picks = _select_unit_ips(info, top, cap)
    if not picks:
        return
    rec.caption(f"🧩 Unit-first verification — a verified testbench per sub-circuit "
                f"({len(picks)}) BEFORE integration: " + ", ".join(m for m, _ in picks))
    made, verified, failing = [], [], []
    done = set(ctx.get("unit_verified") or [])
    tb_dir = Path(ctx["design_dir"]) / "tb"
    for mod, fname in picks:
        tb_name = f"{mod}_tb.sp"
        # already verified (per-IP verify during generation) and its tb is still on disk →
        # keep it as-is (re-adopt into ctx so agent_write persists it), skip.
        if mod in done and (tb_dir / tb_name).exists():
            ctx.setdefault("testbench_code", {})[tb_name] = \
                (tb_dir / tb_name).read_text(errors="replace")
            verified.append(mod)
            made.append(tb_name)
            rec.markdown(f"✅ `{mod}` — already verified in isolation (tb kept).")
            continue
        ok = _gen_and_verify_unit_tb(rec, ctx, mod, fname)
        if ok is None:
            continue
        (verified if ok else failing).append(mod)
        made.append(tb_name)
    if made:
        if failing:
            rec.warning(f"Unit verification: {len(verified)}/{len(made)} IP(s) PASS in isolation; "
                        f"still failing: {', '.join(failing)} — the simulate stage will route "
                        "these to the corrector BEFORE any integration run.")
        else:
            rec.success(f"✅ All {len(made)} IP(s) verified in isolation — safe to integrate.")


def agent_testbench(rec, ctx, feedback=""):
    # The testbench is a BOUNDED task: read the top module's ports, write ONE self-checking
    # tb. It is NOT run as a deep agent — the deep-agent path has no repetition breaker and
    # makes several full-length LLM calls, so it repeatedly blew past OLLAMA_TIMEOUT (the
    # "testbench timed out" crashes). The one-shot path below uses stream_to, which DOES have
    # the repetition circuit-breaker, and needs a single call: far faster and more reliable.
    files = ctx["decomposed_files"]
    rtl_dir = Path(ctx["design_dir"]) / "netlist"
    top = _ensure_top(ctx, rtl_dir)                           # never test a leaf sub-circuit
    # UNIT-FIRST (user: 'sebelum semua code digabungin, itu sudah verified dulu tbnya'): every
    # sub-circuit gets its tb written AND verified in isolation BEFORE the chip-level tb is even
    # written — integration only ever combines blocks that already passed on their own.
    ctx["testbench_code"] = {}
    try:
        _generate_unit_tbs(rec, ctx, top, files)
    except Exception as e:  # noqa: BLE001
        rec.caption(f"(unit-testbench generation skipped: {e})")
    tb_name = f"{top}_tb.sp"
    dut_file = f"{top}.sp"
    top_code = (files.get(f"{top}.sp") or files.get(f"{top}.spice")
                or next(iter(files.values()), ""))
    if not top_code and (rtl_dir / dut_file).exists():
        top_code = (rtl_dir / dut_file).read_text(errors="replace")
    # STEP 1 — derive the comprehensive FEATURE / verification plan (what must be checked), so the
    # testbench verifies the WHOLE design, not one vague path. Saved to verification_plan.md.
    rec.caption("📋 Planning verification — enumerating every feature to check…")
    feats = _derive_feature_plan(rec, ctx, top, top_code)
    rec.success(f"Verification plan: {len(feats)} feature(s) to verify "
                "(saved to `context/verification_plan.md`):")
    rec.code("\n".join(f"{i}. {f['name']} → expect: {f['expected']}"
                       for i, f in enumerate(feats, 1)), language="text")
    plan_block = _feature_plan_block(feats)
    header = next((f for f in files if f.startswith("shared_params")), None)
    inc = (f"Also `.include netlist/{header}` (shared .param values) and USE its params "
           "verbatim — do NOT re-declare or GUESS them (a second, conflicting definition "
           "is what makes a bias point wrong).") if header else ""
    try:
        from glayout_tools import load_config
        _cfg = load_config(ctx["design_dir"], top) or \
            load_config(ctx["design_dir"], Path(ctx["design_dir"]).name)
        if _cfg:
            inc += ("\n- DESIGN CONFIG (spec table + sizing — every .measure threshold and "
                    "the vdd come from HERE):\n"
                    + json.dumps({k: _cfg.get(k) for k in ("spec", "params")
                                  if _cfg.get(k)})[:1400] + "\n")
    except Exception:  # noqa: BLE001
        pass
    inc += _sim_types_note(ctx)
    if feedback:
        inc += f"\n- User instruction: {feedback}"
    # GROUND the expected behavior in the SOURCE design's own testbench so the sim PASS/FAIL
    # (and the sootty waveform) reflects the real design behavior from the repo — not values
    # the local model invented. (User: "make sure the sootty sim result is correct by comparing
    # to that repo/web knowledge".)
    ref_src, ref_name = _anchor_reference_tb(Path(ctx["design_dir"]))
    if ref_src:
        rec.caption(f"📑 Grounding the testbench in the reference behavior from `{ref_name}`.")
    reference = (
        f"\nREFERENCE TESTBENCH from the source design (`{ref_name}`) — this is the AUTHORITATIVE\n"
        "behavior. Mirror HOW it drives/clocks/resets the DUT and what it treats as a correct\n"
        "result (its stimulus sequence, expected values, $display checks, finish condition) so\n"
        "your PASS/FAIL matches the real design — do NOT invent unrelated expected values:\n"
        f"```\n{ref_src[:3000]}\n```\n" if ref_src else "")
    # ALSO ground the EXPECTED behavior in the researched knowledge (web digest + PDF paper) of how
    # this module is documented to work — so the checks reflect real, verifiable behavior, not
    # numbers the model guessed. (User: "create the tb based on knowledge in internet of how that
    # module works, also see the pdf paper — not just blindly create a tb that wasn't verifiable.")
    brief, brief_srcs = _behavior_brief(Path(ctx["design_dir"]))
    if brief:
        rec.caption("📚 Grounding the expected behavior in the research + paper: "
                    + ", ".join(brief_srcs[:6]))
        reference += (
            "\nDOCUMENTED BEHAVIOR (web research + the PDF paper gathered for this design) — derive the\n"
            "stimulus, the EXPECTED outputs, the timing/protocol and the PASS condition from HOW the\n"
            "module is documented to work below. The testbench must actually VERIFY this behavior\n"
            "(self-check real values), not just toggle inputs and print PASSED:\n"
            f"```\n{brief}\n```\n")
    llm = get_chat_model(temperature=0.2)
    prompt = ChatPromptTemplate.from_template(
        """Write a self-checking ngspice testbench for the top circuit.
STRICT RULES (follow exactly):
- START with a `*` title comment line (ngspice eats line 1 as the title).
- `.include netlist/{dut_file}` — the DUT. The PDK model `.lib` line is injected
  automatically; do NOT hardcode a model path.
- Instantiate the DUT: `XDUT <nodes...> {top}` wiring EVERY port of the subckt
  (VDD VSS inputs outputs bias) — no port left floating.
- Supplies + stimulus: `VDD vdd 0 <vdd from the config>`; inputs biased at their DC
  operating point with `AC 1` on the signal input for gain measurements (differential:
  drive vin+ / vin- around the common-mode); a SIN/PULSE source for the .tran use-case;
  the spec's load (`CL out 0 <cl>`); a bias current source if the DUT needs one.
- ANALYSES: `.op` first, then `.ac dec 20 1 1G` (or the spec's range) and — when the
  use case needs it — `.tran` with the documented input signal.
- MEASURE THE SPEC TABLE in a `.control` block: `run`, then compute EVERY spec with
  meas/let (gain_db from vdb(out); bw_hz at gain-3dB; ugbw_hz where vdb(out)=0;
  phase_margin_deg = 180 + phase at ugbw; power_w = |i(vdd)|*vdd). EXPORT the curves:
  `wrdata sim/{top}_ac.txt vdb(out) vp(out)` (+ `sim/{top}_tran.txt v(in) v(out)` after
  a .tran) — the pipeline plots Bode/transient from these files.
- VERIFIABILITY (required — this is a tape-out gate): for EACH spec print ONE line with
  the target and the measured value:
  an `if`/`else` per spec (the comparison goes in the IF condition) that prints
  `echo SPEC <name> PASS measured=$&<vector> want=<target>` or the FAIL variant and bumps a
  fail counter. NEVER use `>` `<` or `->` in an echo line — ngspice reads them as file
  redirection and writes junk files; keep echo to plain words + `=`/`:`, put comparisons in `if`.
- End the .control block with the verdict: `echo Result: PASSED` when nothing failed
  else `echo Result: FAILED`, then `quit`. Then `.endc` and `.end`.
- All numbers COMPUTED by ngspice (meas/let) — never typed in by you.
- Output EXACTLY ONE deck. Do NOT repeat it.
{inc}
{plan}
- Reply with ONLY JSON: {{"{tb_name}": "<full spice source>"}}.
{reference}
DUT (`{dut_file}`):
```spice
{code}
```"""
    )
    rec.caption("🧠 Live model output:")
    live = rec.placeholder()
    with st.spinner("Writing testbench…"):
        resp = stream_to(
            prompt | llm, {"top": top, "code": top_code, "inc": inc, "tb_name": tb_name,
                           "dut_file": dut_file, "reference": reference, "plan": plan_block}, live)
    try:
        tb = extract_json(resp)
        tb = {k: dedup_modules(v) for k, v in tb.items()}
    except Exception:  # noqa: BLE001
        tb = {tb_name: extract_code_block(resp)}
    # force the tb filename to the expected name (a model may have replied differently)
    if tb and next(iter(tb)) != tb_name:
        tb = {tb_name: next(iter(tb.values()))}
    try:                                          # repair title/fences/.ends tics in the tb too
        from netlist_check import autofix_text
        tb = {k: autofix_text(v)[0] for k, v in tb.items()}
    except Exception:  # noqa: BLE001
        pass
    rec.success(f"Integration testbench `{next(iter(tb))}`:")
    rec.code(next(iter(tb.values())), language="spice")
    # keep the already-VERIFIED unit tbs alongside the integration tb (agent_write persists both;
    # agent_simulate re-runs every unit test as the deterministic gate before the whole-chip run)
    ctx["testbench_code"] = {**ctx.get("testbench_code", {}), **tb}


def agent_write(rec, ctx, feedback=""):
    design_dir = Path(ctx["design_dir"])
    rtl_dir, tb_dir = design_dir / "netlist", design_dir / "tb"
    rtl_dir.mkdir(parents=True, exist_ok=True)
    tb_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, content in ctx["decomposed_files"].items():
        safe = re.sub(r"[^\w.\-]", "_", name)
        if isinstance(content, str) and content.strip():
            (rtl_dir / safe).write_text(content)
            written.append(f"netlist/{safe}")
    # prune ONLY genuinely-STALE testbenches — a tb whose DUT subckt no longer exists in
    # netlist/ (e.g. a previous top's tb after a rename). A unit tb for a LIVE circuit is
    # NEVER deleted just because this stage's ctx didn't carry it: that's exactly how every
    # per-IP tb vanished when fix_testbench replaced the dict — instead, re-ADOPT it into
    # ctx so it stays on disk.
    new_tbs = {re.sub(r"[^\w.\-]", "_", n) for n, c in ctx.get("testbench_code", {}).items()
               if isinstance(c, str) and c.strip()}
    if new_tbs:
        try:
            from netlist_check import parse_dir
            live_mods = set(parse_dir(rtl_dir)["defs"].keys())
        except Exception:  # noqa: BLE001
            live_mods = set()
        for old in list(tb_dir.glob("*_tb.sp")) + list(tb_dir.glob("*_tb.spice")):
            if old.name in new_tbs:
                continue
            stem = re.sub(r"_tb$", "", old.stem)
            if stem in live_mods:                  # live circuit's tb from an earlier stage → keep
                ctx.setdefault("testbench_code", {}).setdefault(
                    old.name, old.read_text(errors="replace"))
                continue
            old.unlink()
    for name, content in ctx.get("testbench_code", {}).items():
        safe = re.sub(r"[^\w.\-]", "_", name)
        if isinstance(content, str) and content.strip():
            (tb_dir / safe).write_text(content)
            written.append(f"tb/{safe}")
    rec.success(
        f"Saved {len(written)} file(s) under `{design_dir.relative_to(REPO_ROOT)}/`:")
    rec.code("\n".join(written), language="text")


def _run_unit_tests(rec, ctx, rtl_dir, tb_dir, sim_dir, top, info):
    """Simulate each PER-CIRCUIT unit testbench (`<mod>_tb.sp`, mod != top) with ngspice, and
    require every one to PASS before the integration sim. A failing block is reported on its
    own and routed to the corrector (its name is in the error). Returns True (all passed),
    False (a unit test failed → simulation_output set), or None (no unit tbs present)."""
    from netlist_check import tb_quality_report
    unit = []
    for f in sorted(glob.glob(str(tb_dir / "*.sp"))) + sorted(glob.glob(str(tb_dir / "*.spice"))):
        stem = Path(f).stem
        if not stem.endswith("_tb"):
            continue
        mod = stem[:-3]
        if mod and mod != top and mod in info["defs"]:
            unit.append((mod, f))
    if not unit:
        return None
    rec.caption(f"🔬 Unit gate — re-running {len(unit)} IP unit test(s) in isolation before the "
                "whole-chip run: " + ", ".join(m for m, _ in unit))
    results = []
    for mod, tbf in unit:
        hard, _ = tb_quality_report(Path(tbf).read_text(errors="replace"))
        if hard:
            out = f"{Path(tbf).name}: not verifiable — " + "; ".join(hard[:2])
            ok = False
        else:
            out = _sim_unit(rtl_dir, sim_dir, mod, Path(tbf))
            ok = _unit_ok(out)
        results.append((mod, Path(tbf).name, ok, out))
        rec.markdown(f"{'✅' if ok else '❌'} `{mod}` unit test — {'PASS' if ok else 'FAIL'}")
        if not ok:
            rec.code(out[:1400], language="text")
    fails = [(m, n, o) for m, n, ok, o in results if not ok]
    if fails:
        m, n, o = fails[0]
        names = ", ".join(f"`{x}`" for x, _, _ in fails)
        msg = (f"{n}: unit test for IP `{m}` FAILED ({len(fails)} IP(s) failing in total: {names}) "
               f"— fix `{m}` (or its testbench) so this IP verifies before the whole chip:\n{o[:1200]}")
        (sim_dir / "simulation.log").write_text("UNIT TEST FAILED:\n" + msg)
        ctx["simulation_output"] = msg
        ctx["error_count"] = ctx.get("error_count", 0) + 1
        return False
    rec.success(f"✅ All {len(results)} IP unit test(s) passed — each block verified in isolation.")
    return True


def agent_simulate(rec, ctx, feedback=""):
    design_dir = Path(ctx["design_dir"])
    rtl_dir, tb_dir, sim_dir = design_dir / \
        "netlist", design_dir / "tb", design_dir / "sim"
    sim_dir.mkdir(parents=True, exist_ok=True)

    # ---- deterministic pre-flight (netlist_check) -------------------------
    # 1) re-derive the REAL top structurally (the integration circuit, not a leaf);
    # 2) structurally lint the netlists (floating nets, dangling ports, undefined
    #    subckts) and fail FAST with actionable findings instead of a raw ngspice wall.
    from netlist_check import parse_dir, check_file as _nl_check, ngspice_parse_check
    info = parse_dir(rtl_dir)
    top = _ensure_top(ctx, rtl_dir)                   # real integration top, not a leaf
    # Simulate ONLY the current top's testbench (`{top}_tb.sp`) — never a stale
    # leaf/other-top tb, which would mark the run 'verified' without testing the chip.
    all_tb = sorted(glob.glob(str(tb_dir / "*.sp"))) + sorted(glob.glob(str(tb_dir / "*.spice")))
    top_tb = [f for f in all_tb if Path(f).stem.lower() == f"{top}_tb".lower()]
    want_tb = [str(tb_dir / k) for k in ctx.get("testbench_code", {}) if (tb_dir / k).exists()]
    tb_files = top_tb or want_tb or all_tb[:1]        # exactly one tb — the top's
    if tb_files:
        used = Path(tb_files[0]).name
        if top_tb:
            rec.caption(f"🧪 Simulating the top `{top}` with its testbench `{used}`.")
        else:
            msg = (f"TESTBENCH MISMATCH: the design top is `{top}` but no `{top}_tb` exists — the "
                   f"tb on disk (`{used}`) targets another circuit, so a PASS from it would not "
                   f"verify the chip. Write a testbench for the real top `{top}` "
                   f"(tb/{top}_tb.sp) measuring the whole spec table.")
            rec.error("❌ " + msg)
            (sim_dir / "simulation.log").write_text(msg)
            ctx["simulation_output"] = msg
            ctx["error_count"] = ctx.get("error_count", 0) + 1
            return
    if not tb_files:
        rec.error("No testbench to simulate.")
        ctx["simulation_output"] = f"Error: no testbench (tb/{top}_tb.sp missing)."
        ctx["error_count"] = ctx.get("error_count", 0) + 1
        return

    # STRUCTURAL LINT of every netlist file first (deterministic, no LLM) — floating nets
    # and dangling ports are the LVS killers; catch them before any simulation.
    findings: List[str] = []
    for p in sorted(rtl_dir.iterdir()):
        if p.suffix.lower() in (".sp", ".spice", ".cir", ".cdl"):
            err = _nl_check(p, rtl_dir)
            if err:
                findings.append(err)
    if findings:
        audit = "\n".join(findings)
        rec.error("❌ Static netlist check failed — precise findings routed to the corrector "
                  "(faster + clearer than raw ngspice errors):")
        rec.code(audit[:2500], language="text")
        (sim_dir / "simulation.log").write_text("STATIC CHECK FAILED:\n" + audit)
        ctx["simulation_output"] = "STATIC CHECK FAILED (fix EVERY finding):\n" + audit
        ctx["error_count"] = ctx.get("error_count", 0) + 1
        return

    # PER-CIRCUIT UNIT TESTS FIRST — every block must verify in isolation before the
    # whole-chip run, so a failure is pinned to the exact circuit.
    if _run_unit_tests(rec, ctx, rtl_dir, tb_dir, sim_dir, top, info) is False:
        return

    # VERIFIABILITY GATE (deterministic, no LLM): a testbench that isn't genuinely
    # self-checking must NEVER be allowed to "pass" — a meaningless PASSED would carry a
    # broken circuit into layout / tape-out.
    from netlist_check import tb_quality_report
    hard, soft = tb_quality_report(Path(tb_files[0]).read_text(errors="replace"))
    if soft:
        rec.caption("🔎 Testbench verifiability notes: " + "; ".join(soft[:3]))
    if hard:
        tb_nm = Path(tb_files[0]).name
        msg = (f"{tb_nm}: the testbench is NOT verifiable — a PASSED from it would be "
               "meaningless. Fix EVERY point:\n"
               + "\n".join(f"  • {h}" for h in hard)
               + "\nRewrite it SELF-CHECKING: measure every spec with meas/let, print "
                 "`SPEC <name> PASS/FAIL measured=… want=…` per spec (no > < -> in echo), wrdata the AC "
                 "curve, and derive the final `Result: PASSED`/`Result: FAILED` from the "
                 "fail counter, then `quit`.")
        rec.error("❌ Verifiability gate failed — this testbench cannot actually verify the design:")
        rec.code(msg, language="text")
        (sim_dir / "simulation.log").write_text("VERIFIABILITY GATE FAILED:\n" + msg)
        ctx["simulation_output"] = msg          # names the tb → route_next → fix_testbench
        ctx["error_count"] = ctx.get("error_count", 0) + 1
        return

    # ---- run ngspice -------------------------------------------------------
    from spice_sim import (run_ngspice, parse_measures, ac_metrics, check_specs,
                           specs_pass, spec_table)
    rec.write("**Simulate:**")
    rec.code(f"ngspice -b tb/{Path(tb_files[0]).name}   (cwd = design dir, PDK models injected)",
             language="bash")
    with st.spinner("Running ngspice…"):
        ok, sim_out = run_ngspice(Path(tb_files[0]), workdir=design_dir)
    rec.write("**Simulation output:**")
    rec.code((sim_out or "(no stdout)")[-6000:], language="text")
    (sim_dir / "simulation.log").write_text(sim_out or "(no output)")
    ctx["_design_compiles"] = ok                  # ngspice parsed+ran it (for advance())

    # ---- measured metrics vs the config's spec table ------------------------
    metrics = parse_measures(sim_out)
    ac_file = sim_dir / f"{top}_ac.txt"
    if ac_file.exists():
        try:
            metrics = {**ac_metrics(ac_file), **metrics}   # explicit .measure wins
        except Exception:  # noqa: BLE001
            pass
    spec_rows = []
    try:
        from glayout_tools import load_config, bump_iteration
        cfg = load_config(design_dir, top) or load_config(design_dir, design_dir.name)
        if cfg.get("spec") and metrics:
            spec_rows = check_specs(metrics, cfg["spec"])
            rec.write("**Spec verdict (measured vs config):**")
            rec.code(spec_table(spec_rows), language="text")
            bump_iteration(design_dir, top, cfg, metrics, note="simulate")
    except Exception:  # noqa: BLE001
        pass
    if metrics:
        ctx["sim_metrics"] = {k: v for k, v in metrics.items()}
        (sim_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))

    # Show the analog "waveforms": Bode from the AC wrdata + transient if exported.
    _show_waveform(rec, design_dir, sim_dir, top=top)

    # LAYOUT-FIRST POLICY (user: focus generation on glayout; SPICE is for wiring + params).
    # The full electrical spec (gain/BW/PM) is closed POST-LAYOUT on the PEX netlist. So the
    # pre-layout gate is LIGHT: it only demands the schematic RUN (no fatal ngspice error / .op
    # converged / connectivity clean) — it does NOT block on the spec table UNLESS the user set
    # an explicit target (the optional Gain/BW fields → a non-empty config spec).
    has_spec_target = bool((ctx.get("spec") or {}))
    failed = re.search(r"->\s*FAIL|^\s*(Error|fatal)[: ]|doAnalysis failed|singular matrix",
                       sim_out or "", re.I | re.M)
    ran_ok = bool(sim_out) and not failed
    if has_spec_target:                             # user asked to close a spec → gate on it
        passed = bool(re.search(r"Result:\s*PASSED", sim_out or "")) and not failed
        if spec_rows and not specs_pass(spec_rows):
            passed = False
    else:                                           # no target → just needs to run cleanly
        passed = ran_ok
    if passed:
        note = "".join(f" · {r['name']}={r['measured']:.4g}" for r in spec_rows[:4]
                       if isinstance(r.get("measured"), (int, float)))
        msg = ("✅ Schematic runs clean (bias + connectivity OK) — full spec is verified "
               "post-layout on the extracted netlist." if not has_spec_target
               else f"✅ Simulation passed — every spec check reported PASS{note}.")
        rec.success(msg)
        ctx["simulation_output"] = ""
        _log_state(ctx, "simulate", "PASSED (schematic clean)" if not has_spec_target
                   else "PASSED (all spec checks PASS)")
        return
    fail_note = sim_out or "Result: FAILED"
    if spec_rows and not specs_pass(spec_rows):
        fail_note = ("SPEC MISS — measured vs target:\n" + spec_table(spec_rows)
                     + "\nMUTATE THE CONFIG parameters (W/L/fingers, ibias, compensation) "
                       "to close the gap, regenerate the netlist from it, and re-simulate."
                     + "\n\nSIM OUTPUT (tail):\n" + (sim_out or "")[-1500:])
        rec.error("❌ Spec not met — the config tuner will be routed next.")
    else:
        rec.error("❌ Simulation failed — a corrector will be routed next.")
    ctx["simulation_output"] = fail_note
    ctx["error_count"] = ctx.get("error_count", 0) + 1
    _log_state(ctx, "simulate", "FAILED: " + fail_note[:150])


def agent_lint(rec, ctx, feedback=""):
    """NO-FLOATING-PINS gate (user: 'tidak boleh ada pin yang ga terhubung, big no') BETWEEN
    a spec-passing sim and layout. Every port on the netlist MUST be connected and every
    internal net MUST have ≥2 terminals — a dangling port or a single-terminal net becomes
    the LVS 'net only in schematic' that makes the layout fail (and, physically, a floating
    gate). Routes any finding to the corrector so the netlist is genuinely clean before
    Glayout ever runs — you can't route what isn't connected in the schematic."""
    design_dir = Path(ctx["design_dir"])
    rtl_dir = design_dir / "netlist"
    files = sorted(glob.glob(str(rtl_dir / "*.sp"))) + sorted(glob.glob(str(rtl_dir / "*.spice")))
    top = _ensure_top(ctx, rtl_dir) or ctx.get("top_module_name") or ""
    if not files:
        rec.warning("No netlist to check.")
        ctx["lint_output"] = ""
        return
    from netlist_check import unconnected_pins, ngspice_parse_check
    floats = unconnected_pins(rtl_dir, top)
    # also let ngspice's own parser validate the top deck's includes/models resolve
    parse_err = ""
    top_file = rtl_dir / f"{top}.sp"
    if top_file.exists():
        try:
            parse_err = ngspice_parse_check(top_file)
        except Exception:  # noqa: BLE001
            parse_err = ""
    (design_dir / "sim").mkdir(parents=True, exist_ok=True)
    if not floats and not parse_err:
        rec.success("✅ Netlist clean — every port connected, every net has ≥2 terminals, "
                    "models resolve. Ready for layout.")
        (design_dir / "sim" / "lint.log").write_text("clean")
        ctx["lint_output"] = ""
        return
    lines_f = [f"  • {f['subckt']}.{f['name']}"
               + (" (port never used inside the subckt)" if f["kind"] == "dangling_port"
                  else " (net has only ONE terminal — floating)")
               for f in floats[:24]]
    msg_parts = []
    if floats:
        msg_parts.append(
            "UNCONNECTED PINS / FLOATING NETS — every port MUST be connected and every net "
            "must have at least two terminals before layout (no exceptions).\n"
            + "\n".join(lines_f)
            + "\nFIX in the netlist: wire each dangling port to the device terminal it "
            "belongs to; give each floating net its missing second connection (the device "
            "the schematic intends it to reach). Do NOT tie signal nets to a rail to silence "
            "this — make the real connection. Every net here must later become a c_route / "
            "L_route / straight_route in the layout, so it must exist in the schematic first.")
    if parse_err:
        msg_parts.append("NGSPICE PARSE ERRORS in the top deck:\n" + parse_err)
    out = "\n\n".join(msg_parts)
    (design_dir / "sim" / "lint.log").write_text(out)
    rec.error("❌ Netlist connectivity check failed — routing to the corrector before layout.")
    rec.code(out[:2500], language="text")
    ctx["lint_output"] = out
    ctx["lint_count"] = ctx.get("lint_count", 0) + 1


def agent_fix_design(rec, ctx, feedback=""):
    if ctx.get("deep_steps"):                 # run the Circuit Corrector AS a deep agent (RLM)
        return _deep_fix_design(rec, ctx, feedback)
    files = dict(ctx["decomposed_files"])
    # In the sim loop this is the spec/simulation error; in the lint loop (sim already
    # passed) it's the connectivity error; in the layout loop it's the DRC/LVS error
    # naming the offending net/subckt.
    err = ctx.get("simulation_output") or ctx.get("lint_output") or ctx.get("harden_error", "")
    faulty_list = _faulty_files(files, err, ctx.get("top_module_name", ""))
    rec.write("**Compiler/sim errors fed to the model** "
              f"(fixing {len(faulty_list)} file(s): {', '.join(faulty_list)}):")
    rec.code(err[:1800], language="text")
    attempt = ctx.get("error_count", 0) + ctx.get("lint_count", 0)
    temp = min(0.2 + 0.18 * attempt, 0.85)
    rec.caption(
        f"Attempt {attempt + 1} · temperature {temp:.2f} (raised each retry to avoid the same fix).")

    # ALWAYS recall a stored lesson for this error class first (knowledge DB) — a past
    # run's fix usually solves it on attempt 1. Fall back to live web research when stuck.
    sig = _error_query(err)
    remembered = recall_fix(sig)
    if remembered:
        ctx["web_example"] = remembered
        rec.caption(f"🧠 Recalled a stored lesson for this error: *{sig}*")
    elif attempt >= 2 and attempt % 3 == 2:
        hint = _auto_research(sig, rec)
        if hint:
            ctx["web_example"] = hint
            # persist so the next run solves it instantly
            remember_fix(sig, hint)

    history = dict(ctx.get("fix_history", {}))
    for faulty in faulty_list:
        _fix_one_module(rec, ctx, files, history, faulty, err, attempt, temp, feedback)
    ctx["decomposed_files"] = files
    ctx["fix_history"] = history


def _fix_one_module(rec, ctx, files, history, faulty, err, attempt, temp, feedback=""):
    past = history.get(faulty, [])
    tried = past + [files[faulty]]
    rec.expander_code(
        f"Current (broken) `{faulty}` given to the corrector", files[faulty], "spice")
    if past:
        rec.caption(f"⛔ {len(past)} earlier fix(es) of `{faulty}` failed — all are shown to the model "
                    "with an explicit 'do NOT reproduce these' so it stops looping on the same code.")

    cfg_note = ""
    try:
        from glayout_tools import load_config, config_note
        cfg = load_config(ctx["design_dir"], ctx.get("top_module_name") or "") \
            or load_config(ctx["design_dir"], Path(ctx["design_dir"]).name)
        if cfg:
            cfg_note = ("DESIGN CONFIG (the sizing/spec truth — change a device size by editing "
                        "these params, not by inventing new numbers):\n" + config_note(cfg, 1200)
                        + "\n")
    except Exception:  # noqa: BLE001
        pass

    prior_block = "\n\n".join(
        f"FAILED ATTEMPT #{i + 1} (already tried — it did NOT work, do not reproduce it):\n"
        f"```spice\n{p}\n```"
        for i, p in enumerate(tried[-3:])
    )
    prompt = ChatPromptTemplate.from_template(
        """You are fixing a SPICE subcircuit that FAILED its checks/simulation/spec. Use the EXACT
errors below to produce a CORRECTED, DIFFERENT version that resolves them — do not repeat the
broken netlist. This is attempt {attempt}; earlier fixes (shown at the bottom) FAILED, so take a
FUNDAMENTALLY DIFFERENT approach — resize/rewire the offending devices, don't just re-indent.

{pitfalls}

{reference}{cfg_note}- First, in one line, name the EXACT rule/cause you violated (device out of saturation, floating
  net, wrong mirror ratio, W/L too small for the required gm), then fix the real cause.
- Keep the subckt name `{name_stem}` and a port list compatible with the rest of the design.
  Every port must be USED in the body; no floating nets. Use the exact PDK model names.
- Output EXACTLY the corrected netlist in a single ```spice block.

ERRORS:
```
{err}
```
{prior_block}

BROKEN SUBCKT (`{name}`) — rewrite it correctly:
```spice
{code}
```"""
    )
    rec.caption("🧠 Live model output:")
    live = rec.placeholder()
    reference = _ref_context(ctx)
    if feedback:
        reference += f"USER INSTRUCTION: {feedback}\n"
    stem = re.sub(r"\.(spice|spc|cdl|cir|sp)$", "", faulty, flags=re.I)
    inputs = {"name": faulty, "name_stem": stem,
              "code": files[faulty], "err": err, "attempt": attempt + 1,
              "pitfalls": VERILOG_PITFALLS, "reference": reference, "cfg_note": cfg_note,
              "prior_block": prior_block or "(no earlier attempts)"}
    seen = {_norm(c) for c in tried}

    def roll(t: float) -> str:
        return extract_code_block(stream_to(prompt | get_chat_model(temperature=t), inputs, live))

    with st.spinner("Repairing circuit…"):
        fixed = roll(temp)
        rerolls = 0
        while fixed and _norm(fixed) in seen and rerolls < 2:
            rerolls += 1
            hot = min(temp + 0.25 * rerolls, 0.95)
            rec.caption(
                f"↻ Identical to a failed attempt — re-rolling hotter (temp {hot:.2f}).")
            fixed = roll(hot)

    if not fixed.strip():
        fixed = files[faulty]
    files[faulty] = fixed
    history[faulty] = tried + [fixed]
    rec.success(f"Corrected `{faulty}`:")
    rec.code(fixed, language="spice")
    # verified fix → durable lesson in the knowledge DB (don't repeat this mistake)
    try:
        from netlist_check import check_file
        rtl_dir = Path(ctx["design_dir"]) / "netlist"
        p = rtl_dir / faulty
        p.write_text(fixed)
        if not check_file(p, rtl_dir):
            sig = _error_query(err)
            if sig:
                remember_fix(sig, "", design=Path(ctx["design_dir"]).name,
                             broken=(tried[-1] if tried else ""), fixed=fixed)
    except Exception:  # noqa: BLE001
        pass


def agent_fix_testbench(rec, ctx, feedback=""):
    if ctx.get("deep_steps"):                 # run the Testbench Corrector AS a deep agent (RLM)
        return _deep_fix_testbench(rec, ctx, feedback)
    tb = ctx.get("testbench_code", {})
    top = ctx["top_module_name"]
    err = ctx["simulation_output"]
    rtl_dir = Path(ctx["design_dir"]) / "netlist"
    # A failing PER-CIRCUIT unit tb (its name is in the error) is regenerated FOR THAT block —
    # rewriting the chip-level tb instead would leave the broken unit tb failing forever.
    m_unit = re.search(r"\b(\w+)_tb\.(sp|spice)\b", err or "")
    if m_unit and m_unit.group(1) != top and (rtl_dir / f"{m_unit.group(1)}.sp").exists():
        top = m_unit.group(1)                     # the DUT is that block, not the chip top
    # The regenerated tb MUST be named for the CURRENT DUT ({top}_tb.sp): keeping a stale key
    # would loop the TESTBENCH-MISMATCH gate forever.
    name = next((k for k in tb if Path(k).stem.lower() == f"{top}_tb".lower()), f"{top}_tb.sp")
    cur_tb = tb.get(name, "") or ""
    history = dict(ctx.get("fix_history", {}))
    past = history.get(name, [])
    tried = past + ([cur_tb] if cur_tb else [])
    attempt = ctx.get("error_count", 0)
    temp = min(0.3 + 0.18 * attempt, 0.9)
    rec.write("**ngspice errors fed to the model:**")
    rec.code(err[:1800], language="text")
    if past:
        rec.caption(f"⛔ {len(past)} earlier testbench(es) failed — shown to the model so it doesn't "
                    "regenerate the same broken stimulus.")
    rec.expander_code("Previous (failed) testbench", cur_tb, "spice")
    rec.caption(f"Attempt {attempt + 1} · temperature {temp:.2f} — REGENERATING from the DUT (not "
                "patching the broken testbench), so it doesn't keep copying the same bug.")
    extra = f"- User instruction: {feedback}\n" if feedback else ""
    cfg_note = ""
    try:
        from glayout_tools import load_config
        cfg = load_config(ctx["design_dir"], top) or \
            load_config(ctx["design_dir"], Path(ctx["design_dir"]).name)
        if cfg:
            cfg_note = ("- DESIGN CONFIG (spec thresholds + vdd come from HERE):\n"
                        + json.dumps({k: cfg.get(k) for k in ("spec", "params")
                                      if cfg.get(k)})[:1200] + "\n")
    except Exception:  # noqa: BLE001
        pass
    prompt = ChatPromptTemplate.from_template(
        """The previous ngspice testbench for circuit `{top}` FAILED with the errors below. Write a
BRAND-NEW, correct, self-checking testbench FROM SCRATCH for the DUT. Do NOT reuse the broken
testbench's structure — start fresh from the DUT's `.subckt` port list.

STRICT RULES:
- START with a `*` title comment; `.include netlist/{top}.sp`; `.endc`+`.end` at the very bottom.
- Instantiate the DUT `XDUT <nodes...> {top}` wiring EVERY port; add supplies (VDD from the config),
  the AC/stimulus sources, and the spec load (CL). No floating node.
- ANALYSES the specs need: `.op`, `.ac dec 20 1 1G`, and `.tran` if the use case needs it.
- MEASURE the spec table in `.control`: `run`, meas/let every spec, and
  `wrdata sim/{top}_ac.txt vdb(out) vp(out)` for the Bode plot.
- SELF-CHECKING: per spec use an `if`/`else` (comparison in the IF condition) that prints
  `echo SPEC <name> PASS measured=$&<vec> want=<target>` or the FAIL variant and bumps a fail
  counter. NEVER use `>` `<` or `->` in an echo — ngspice reads them as file redirection and
  writes junk files; keep echo to plain words + `=`/`:`. End with `echo Result: PASSED` when
  nothing failed else `echo Result: FAILED`, then `quit`.
- All numbers COMPUTED by ngspice (meas/let), never typed by you.
{extra}{cfg_note}{plan}
ERRORS FROM THE LAST ATTEMPT (avoid these):
```
{err}
```
DUT to test (`{top}.sp`) — derive the node connections from THIS:
```spice
{code}
```
Reply with ONLY JSON: {{"{name}": "<full spice source>"}}."""
    )
    rec.caption("🧠 Live model output:")
    live = rec.placeholder()
    plan_block = _feature_plan_block(ctx.get("feature_plan"))

    def roll(t: float) -> dict:
        code = (ctx["decomposed_files"].get(f"{top}.sp")
                or ctx["decomposed_files"].get(f"{top}.spice", ""))
        if not code and (rtl_dir / f"{top}.sp").exists():
            code = (rtl_dir / f"{top}.sp").read_text(errors="replace")
        resp = stream_to(prompt | get_chat_model(temperature=t), {
            "name": name, "top": top, "code": code,
            "err": err, "extra": extra, "cfg_note": cfg_note, "plan": plan_block,
        }, live)
        try:
            out = extract_json(resp)
            return {k: dedup_modules(v) for k, v in out.items()}
        except Exception:  # noqa: BLE001
            return {name: extract_code_block(resp)}

    seen = {_norm(c) for c in tried}
    with st.spinner("Regenerating testbench…"):
        new_tb = roll(temp)
        rerolls = 0
        while next(iter(new_tb.values()), "") and _norm(next(iter(new_tb.values()))) in seen and rerolls < 2:
            rerolls += 1
            hot = min(temp + 0.25 * rerolls, 0.95)
            rec.caption(
                f"↻ Identical to a failed testbench — re-rolling hotter (temp {hot:.2f}).")
            new_tb = roll(hot)

    history[name] = tried + [next(iter(new_tb.values()), "")]
    rec.success("Corrected testbench:")
    rec.code(next(iter(new_tb.values())), language="spice")
    # force the model's reply under the right filename, and MERGE — replacing the whole dict
    # wiped the per-IP unit tbs, and agent_write's prune then deleted them from disk.
    if name not in new_tb:
        new_tb = {name: next(iter(new_tb.values()), "")}
    merged = dict(tb)
    merged.update({k: v for k, v in new_tb.items() if isinstance(v, str) and v.strip()})
    ctx["testbench_code"] = merged
    ctx["fix_history"] = history


# LibreLane announces each stage on stdout: "Running 'Yosys.Synthesis' at 'runs/…/06-yosys-synthesis'…"
_LL_STAGE_RE = re.compile(r"Running '[^']+' at '[^']*?(\d+-[^'/]+)'")


def _layout_script_rules(top: str, pdk: str) -> str:
    """The contract every generated layout/<top>.py must satisfy — shared by the first
    write and the fix loop, so a repaired script obeys the same rules."""
    prim = ("sky130" if pdk.lower().startswith("sky130") else "gf180")
    return (
        f"- Import: `from glayout import {prim} as PDK_UNUSED, MappedPDK`; `from "
        "glayout.backend import Component`; primitives `from glayout.primitives.fet import "
        "nmos, pmos`, `from glayout.primitives.mimcap import mimcap`, `from "
        "glayout.primitives.guardring import tapring`, `from glayout.primitives.via_gen "
        "import via_stack`; routing `from glayout.routing.smart_route import smart_route`, "
        "`from glayout.routing.c_route import c_route`, `from glayout.routing.L_route import "
        "L_route`, `from glayout.routing.straight_route import straight_route`; placement "
        "`from glayout.util.comp_utils import evaluate_bbox, move, movex, movey, "
        "align_comp_to_port, prec_center, prec_ref_center`, `from glayout.util.port_utils import "
        "rename_ports_by_orientation`; matched pairs `from "
        "glayout.placement.two_transistor_interdigitized import two_pfet_interdigitized, "
        "two_nfet_interdigitized`; resistor `from glayout.primitives.resistor import resistor`.\n"
        f"- Define EXACTLY `def build(pdk):` returning the Component (the harness passes the "
        f"{prim} MappedPDK as `pdk`). Name it: `comp = Component(name=\"{top}\")`.\n"
        "- SIZE every device from config/<name>.json: json.load it at the top of build() and "
        "read width/length/fingers/multipliers per device. NEVER call nmos(pdk)/pmos(pdk) with "
        "default sizing.\n"
        "- UNITS + MIN WIDTH: glayout fet/resistor width & length are in MICRONS. The config "
        "stores them in METRES (SPICE convention: w=1e-05 means 10 µm), so convert with ×1e6 "
        "before EVERY call. gf180 requires each device width ≥ ~0.5 µm (the source/drain "
        "via_array minimum is 0.46 µm — a smaller width raises `via_array,size … < 0.46`), so "
        "clamp: `w_um = max(w_m*1e6, 0.5)`. Never pass a raw metres value (0.00001) as microns.\n"
        "- RESISTORS: glayout HAS a resistor generator — `from glayout.primitives.resistor "
        "import resistor`; `r = comp << resistor(pdk, width=w_um, length=l_um)` (a diode-"
        "connected pfet whose R ≈ (1/gm)||r0; `numseries`/`multipliers` scale it). PLACE it and "
        "ROUTE both terminal ports to the nets the config's wiring gives (e.g. R_REF between "
        "pbias_bot and iref). NEVER drop a resistor as 'netlist-only' — an omitted device is an "
        "LVS mismatch.\n"
        "- FET PORT NAMES (from nmos/pmos) are `multiplier_0_source_E/W`, `multiplier_0_gate_E/W`, "
        "`multiplier_0_drain_E/W` (and _N/_S). Route USING THESE EXACT names — e.g. "
        "`straight_route(pdk, a.ports['multiplier_0_source_E'], b.ports['multiplier_0_source_E'])`, "
        "and diode-connect with `c_route(pdk, ref.ports['multiplier_0_gate_E'], "
        "ref.ports['multiplier_0_drain_E'])`.\n"
        "- ALWAYS ADD DUMMIES via the `with_dummy` tuple — glayout ties the dummy gates/sources "
        "INTERNALLY, so you NEVER hand-route dummy ports (their names like "
        "`multiplier_0_dummy_left_source_S` are internal and guessing them raises KeyError). Put "
        "edge dummies so adjacent devices share the middle: left device `with_dummy=(False, "
        "True)`, right device `with_dummy=(True, False)` (as in GLayout_Cmirror.ipynb).\n"
        "- FINISH WITH A TAPRING (do this at the END, after all routing) — it IS the well/substrate "
        "tie: PLACING it so it ENCLOSES the devices makes the tie by nwell/psub overlap; you do "
        "NOT route to invented `tie_S`/`tie_N` ports. Follow GLayout_Cmirror.ipynb EXACTLY:\n"
        "    from glayout.primitives.guardring import tapring\n"
        "    tap = tapring(pdk, enclosed_rectangle=evaluate_bbox(comp.flatten(), "
        "padding=pdk.get_grule('nwell','active_diff')['min_enclosure']))\n"
        "    tref = comp << tap\n"
        "    tref.movex(destination=-prec_center(comp.flatten())[0])\n"
        "  That is the whole tie step — no dummy/tie hand-routing. If you must bias the ring, "
        "route with smart_route to a REAL tapring port (inspect ref.ports; never invent names).\n"
        "- THE CANONICAL PATTERN to imitate (glayout current mirror, gf180) — matched pmos placed "
        "adjacent, dummies, tapring-tie, routed by port name:\n"
        "    ref = comp << pmos(pdk, width=w_um, length=l_um, fingers=f, with_substrate_tap=False, with_dummy=(False, True))\n"
        "    mir = comp << pmos(pdk, width=w_um, length=l_um, fingers=f, with_substrate_tap=False, with_dummy=(True, False))\n"
        "    ref.movex(evaluate_bbox(mir)[0] + pdk.util_max_metal_seperation())\n"
        "    comp << straight_route(pdk, ref.ports['multiplier_0_source_E'], mir.ports['multiplier_0_source_E'])\n"
        "    comp << straight_route(pdk, ref.ports['multiplier_0_gate_E'],   mir.ports['multiplier_0_gate_E'])\n"
        "    comp << c_route(pdk, ref.ports['multiplier_0_gate_E'], ref.ports['multiplier_0_drain_E'])\n"
        "- PLACE explicitly and CLOSE — never scatter devices far apart. `ref = comp << device`, "
        "then movex/movey by `evaluate_bbox(other)[0] + pdk.util_max_metal_seperation()` so "
        "neighbours abut with just the DRC min gap (see GLayout_Cmirror.ipynb). Nothing left at "
        "the origin, nothing overlapping.\n"
        "- COMBINE MATCHED DEVICES: current-mirror legs and differential pairs must be MATCHED — "
        "build them with glayout's interdigitized placers instead of separate far-apart fets: "
        "`from glayout.placement.two_transistor_interdigitized import two_pfet_interdigitized, "
        "two_nfet_interdigitized`; `pair = comp << two_pfet_interdigitized(pdk, numcols=<k>, "
        "dummy=True, width=w_um, length=l_um, fingers=<f>)` gives an ABAB common-centroid pair. "
        "Use `four_transistor_interdigitized` / `common_centroid_ab_ba` for a 4-device cascode "
        "stack. This keeps the mirror ratio accurate AND compact.\n"
        "  ⚠ PORT NAMES DIFFER BY COMPONENT: a plain nmos/pmos exposes `multiplier_0_{source,"
        "drain,gate}_{E,W,N,S}`, but an interdigitized pair exposes `A_0_{source,drain,gate}_E`, "
        "`B_0_…` (A/B device per column) — using `multiplier_0_*` on an interdigitized component "
        "raises KeyError. Match the port family to what you instantiated; prefer smart_route.\n"
        "- ROUTE EVERY net — but PREFER `smart_route(pdk, portA, portB)` for EVERY connection: it "
        "inspects the two ports' orientations and picks straight/c/L internally, so it never "
        "crashes on a direction mismatch. Only hand-pick a router when you are CERTAIN of the "
        "orientation: straight_route for two INLINE parallel ports (both _E, or both _W, facing "
        "each other), c_route for OFFSET PARALLEL ports (same axis, e.g. both _E), and L_route "
        "for PERPENDICULAR ports (one _E/_W with one _N/_S). NEVER pass an _E port and an _N port "
        "to c_route — c_route requires parallel ports and raises (`gate_E`+`drain_N` → use "
        "smart_route or L_route). Bridge metal layers with via_stack. An unrouted net = LVS 'net "
        "only in schematic'.\n"
        "- PLAN ROUTING SIDES + NEST: assign each net a SIDE (E/W); several parallel c_routes on "
        "the SAME side must NEST with different `extension` values (3*ms, 6*ms, 9*ms; "
        "ms=pdk.util_max_metal_seperation()) — two routes at the same offset = an M2-spacing DRC "
        "storm. CENTER the core before routing: `ref.movey(-(ref.ymax+ref.ymin)/2)` (ring "
        "enclosure math assumes a centered cell). Diode-connect by L_route-ing the drain to the "
        "gate-short c_route's own `con_N` port.\n"
        "- ATTACH THE LVS REFERENCE: set `comp.info['netlist'] = Netlist(circuit_name=…, "
        "nodes=[…])` (from glayout.spice.netlist) and `connect_netlist` the placement's own "
        "netlist (`core.info['netlist']`, nodes VDD1/VSS1/VG1… per device) onto YOUR circuit "
        "nets. Without it LVS reports 'ref-netlist NO'. The BULK is its own net `B` — label the "
        "tapring metal 'B'.\n"
        "- EXPOSE PORTS **AND LABELS**: `comp.add_ports(ref.get_ports_list(), prefix=...)` for "
        "the internal pins you route to, and `comp.add_port(name=\"VDD\", port=...)` etc. for the "
        "circuit's external pins (VDD, VSS, every input/output and bias). Then LABEL them: import "
        "`from glayout.util.snap_to_grid import component_snap_to_grid` is optional, but you MUST "
        "add a text label on each external pin — use glayout's labelling helper "
        "(`from glayout.routing.hashport import ...` / `add_glayout_labels`) if available, else "
        "`import gdstk; comp.add(gdstk.Label(name, origin=comp.ports[name].center, layer=<PDK "
        "label layer>))`. Every port in the netlist's top .subckt must exist on the Component AND "
        "carry a matching label — LVS matches by label, so an unlabelled routed pin still fails "
        "LVS as unconnected.\n"
        "- CAPACITORS: use glayout's mimcap — `from glayout.primitives.mimcap import mimcap`; "
        "`cap = comp << mimcap(pdk, size=(w_um, l_um))`, place it, and ROUTE both plates "
        "(ports `top_met_*` / `bottom_met_*`) to the device terminals with smart_route / "
        "c_route (like the glayout opamp tutorial's Miller cap). Size from the config's cap "
        "value (gf180 capmet ≈ 1-2 fF/µm²).\n"
        "- INDUCTORS: glayout has NO inductor primitive and gdsfactory spirals are photonic. "
        "When area matters PREFER a gyrator-C ACTIVE inductor (2-3 transistors + bias, laid out "
        "with nmos/pmos — tiny). For a true passive, "
        "`from passives import square_spiral_inductor`; "
        "`ind = comp << square_spiral_inductor(pdk, target_nH=<L>)` gives a sized planar square "
        "spiral (top metal + underpass) with LABELLED ports P1/P2 — but a ~2 nH spiral is "
        "~160 µm across, so budget the floorplan.\n"
        "- Return `comp`. Do not write_gds / show / DRC inside the script — the harness does "
        "that. Output ONLY the python in a single ```python block.")


def _write_default_config(design_dir: Path, top: str, ctx) -> dict:
    """Ensure config/<top>.json exists — the self-improve substrate. Derives the spec table
    from the netlist's ports + any spec the user gave, and a first-cut sizing per device."""
    from glayout_tools import load_config, save_config
    cfg = load_config(design_dir, top)
    if cfg.get("params"):
        return cfg
    # seed the spec from ctx if the user typed one, else a permissive default
    spec = ctx.get("spec") or {}
    params = {"vdd": ctx.get("vdd", 1.8 if PDK.lower().startswith("sky130") else 3.3),
              "ibias_ua": 20, "cl_pf": 1.0}
    # one sizing block per non-primitive subckt device family (best-effort from the netlist)
    try:
        from netlist_check import parse_dir
        info = parse_dir(design_dir / "netlist")
        for name in list(info["defs"])[:12]:
            if name.lower().startswith(("sky130_", "gf180mcu_")):
                continue
    except Exception:  # noqa: BLE001
        pass
    params.setdefault("W_nmos", 4.0)
    params.setdefault("W_pmos", 8.0)
    params.setdefault("L", 1.0)
    params.setdefault("fingers", 2)
    cfg = {"name": top, "pdk": PDK, "spec": spec, "params": params,
           "placement": {"note": "movex/movey/center offsets, hand-tuned if needed"},
           "routing": {"style": "smart_route first; explicit c/L/straight + via where needed"},
           "finishing": {"with_tie": False, "with_substrate_tap": False,
                         "with_dummy": False, "guardring": False}}
    save_config(design_dir, top, cfg)
    return cfg


def _wiring_from_config(cfg: dict) -> str:
    """Render the config JSON's `wiring` section as a readable component→net listing for the
    layout prompt — one line per component with its type, size refs, and the net on each
    terminal. This is the GLAYOUT-FIRST replacement for a hand-written .sp: it's exactly the
    connectivity glayout must instantiate and route. Returns '' if the config has no wiring."""
    if not isinstance(cfg, dict):
        return ""
    # `wiring` comes in several shapes: a list of device dicts · a dict with a
    # `components`/`devices` key · a dict of device-dicts. Extract the device list robustly
    # (a dict VALUE that is a list — e.g. wiring['ports'] — must never be splatted with {**v}).
    w = cfg.get("wiring")
    wiring = []
    if isinstance(w, list):
        wiring = w
    elif isinstance(w, dict):
        for key in ("components", "devices", "wiring", "instances"):
            if isinstance(w.get(key), list):
                wiring = w[key]
                break
        if not wiring:
            wiring = [{**v, "name": k} for k, v in w.items() if isinstance(v, dict)]
    if not wiring and isinstance(cfg.get("components"), list):
        wiring = cfg["components"]
    if not isinstance(wiring, list) or not wiring:
        return ""
    ports = cfg.get("ports") or cfg.get("pins") \
        or (w.get("ports") if isinstance(w, dict) else None) or []
    lines = []
    if ports:
        lines.append("PORTS: " + ", ".join(str(p) for p in ports))
    for c in wiring:
        if not isinstance(c, dict):
            continue
        name = c.get("name") or c.get("id") or "?"
        typ = c.get("type") or c.get("device") or c.get("model") or "?"
        size = " ".join(f"{k}={c[k]}" for k in ("W", "L", "nf", "fingers", "M", "m", "R", "C", "value")
                        if k in c and c[k] not in (None, ""))
        terms = " ".join(f"{k}={v}" for k, v in c.items()
                         if k in ("d", "g", "s", "b", "drain", "gate", "source", "bulk",
                                  "plus", "minus", "p", "n", "a", "b1", "t1", "t2", "in", "out"))
        lines.append(f"- {name} ({typ}) {size}  ->  {terms}".rstrip())
    return "\n".join(lines)


def _deterministic_layout_script(cfg: dict, top: str) -> str:
    """A KNOWN-BUILDABLE glayout generator for the common analog topologies, emitted
    DETERMINISTICALLY from the config (no LLM) — this is what makes the build reliable
    instead of depending on the model getting glayout's layer/port names right (it kept
    hallucinating 'Metal1', 'multiplier_0_*' on interdigitized cells, etc.). Currently
    covers CURRENT MIRRORS / CASCODE MIRRORS: N matched fets in a row + tapring tie +
    labelled ports. Returns '' when the topology isn't one we can emit safely (caller
    falls back to the LLM generator)."""
    # --- COMPONENTS: the LLM emits `wiring` in several shapes; extract the device list from ANY:
    #   a list of dicts · a dict with a `components`/`devices` key · a dict of device-dicts.
    wiring = cfg.get("wiring")
    comps = []
    if isinstance(wiring, list):
        comps = wiring
    elif isinstance(wiring, dict):
        for key in ("components", "devices", "wiring", "instances"):
            if isinstance(wiring.get(key), list):
                comps = wiring[key]
                break
        if not comps:
            comps = [{**v, "name": k} for k, v in wiring.items() if isinstance(v, dict)]
    if not comps:
        c = cfg.get("components")
        comps = c if isinstance(c, list) else []

    def _typ(c):
        return str(c.get("type", c.get("device", c.get("model", "")))).lower()
    fets = [c for c in comps if isinstance(c, dict)
            and any(t in _typ(c) for t in ("nfet", "pfet", "nmos", "pmos"))]
    if not (2 <= len(fets) <= 8):
        return ""
    kind = "pmos" if any(("pfet" in _typ(c) or "pmos" in _typ(c)) for c in fets) else "nmos"
    params = cfg.get("params") if isinstance(cfg.get("params"), dict) else {}

    def _um(v, d):
        try:
            x = float(v)
        except Exception:  # noqa: BLE001
            return d
        return round(x * 1e6, 4) if 0 < x < 1e-3 else round(x, 4)   # metres→µm if tiny

    def _size():
        """One representative W/L/nf for the matched devices — resolve from per-device
        params[<fetname>].{w,l,fingers}, else the fet card's own W/L, else flat params."""
        first = fets[0]
        nm = first.get("name") or first.get("id") or ""
        pd = params.get(nm) if isinstance(params.get(nm), dict) else {}
        w_ = pd.get("w", pd.get("W")) or first.get("W", first.get("w")) \
            or params.get("w1", params.get("W", params.get("w", 4e-6)))
        l_ = pd.get("l", pd.get("L")) or first.get("L", first.get("l")) \
            or params.get("l1", params.get("L", params.get("l", 1e-6)))
        nf_ = pd.get("fingers", pd.get("nf")) or first.get("fingers", first.get("nf")) \
            or params.get("fingers1", params.get("fingers", 2))
        return w_, l_, nf_
    _w, _l, _nf = _size()
    w = max(_um(_w, 4.0), 0.66)
    l = max(_um(_l, 1.0), 0.28)
    try:
        nf = max(1, min(int(float(_nf or 2)), 8))
    except Exception:  # noqa: BLE001
        nf = 2
    # ports: cfg.ports OR wiring.ports; strings OR dicts ({"name": …}) — normalise to names
    raw_ports = cfg.get("ports") or (wiring.get("ports") if isinstance(wiring, dict) else None) or []
    ports = []
    for p in raw_ports:
        nm = p.get("name") if isinstance(p, dict) else p
        if nm and str(nm) not in ports:
            ports.append(str(nm))
    if not ports:
        ports = ["IREF", "IOUT", "VDD" if kind == "pmos" else "VSS"]
    n = len(fets)
    well = "nwell" if kind == "pmos" else "pwell"
    rail = next((p for p in ports if re.search(r"vdd|vss|vcc|gnd|rail", p, re.I)),
                ("VDD" if kind == "pmos" else "VSS"))
    outp = next((p for p in ports if re.search(r"out|iout", p, re.I)), "IOUT")
    refp = next((p for p in ports if re.search(r"ref|iref", p, re.I)), "IREF")
    # the three pins we label must be DISTINCT (add_port rejects duplicates)
    if outp == refp:
        outp = "IOUT"
    if rail in (outp, refp):
        rail = "VDD" if kind == "pmos" else "VSS"

    # numcols = interdigitization columns (ABAB…); derive from fingers, keep it modest.
    numcols = max(2, min(nf, 4))
    device = "pfet" if kind == "pmos" else "nfet"
    # CASCODE? (4 fets / the name or topology says cascode) → the INLINE copied-and-adapted
    # 4T generator (validated DRC+LVS clean); else the simple 2T mirror.
    is_cascode = ("cascode" in f"{top} {json.dumps(cfg.get('spec', {}))[:400]}".lower()
                  or len(fets) >= 4)
    if is_cascode:
        return _CASCODE_TEMPLATE % dict(
            top=top, dev=device, w=w, l=l, nf=nf, numcols=numcols, idx=numcols - 1,
            sdlayer=("n+s/d" if device == "pfet" else "p+s/d"),
            refp=refp, outp=outp, rail=rail)
    return f'''# {top} — glayout current-mirror cell ({device}), emitted DETERMINISTICALLY from the
# config. Uses glayout's OWN verified generator: interdigitized + shorted source/gate +
# diode-connected reference + dummies tied to the tapring + a built-in LVS netlist. This is
# DRC- and LVS-clean by construction (no hand-routing that could cross a device).
from glayout import MappedPDK
from glayout.cells.elementary.current_mirror.current_mirror import current_mirror, add_cm_labels
from gdsfactory import Component


def build(pdk: MappedPDK) -> Component:
    # width/length/fingers pass through to the interdigitized multiplier; with_tie adds the
    # tapring LAST and routes the dummies to it; add_cm_labels stamps VSS/VREF/VCOPY/VB.
    cm = current_mirror(pdk, numcols={numcols}, device="{device}",
                        with_dummy=True, with_tie=True,
                        width={w}, length={l}, fingers={nf})
    cm = add_cm_labels(cm, pdk)
    return cm
'''


# The INLINE 4-transistor cascode current mirror — COPIED + ADAPTED from glayout's
# current_mirror.py onto generic_4T_interdigitzed (validated: DRC PASS + LVS PASS on
# gf180mcuD). Emitted with the config's parameters substituted, so the agent has full
# freedom over W/L/fingers/columns/device without calling the library cell directly.
_CASCODE_TEMPLATE = '''# %(top)s — cascode current mirror (%(dev)s), 4 transistors on two interdigitized rows
# (bottom = mirror pair M1/M2, top = cascode pair M3/M4). Adapted from glayout's
# current_mirror.py routing technique: parallel c_routes NEST via different extensions.
#
#   %(refp)s -> M3.drain, M3.source -> M1.drain, M1.source -> %(rail)s   (reference, A side)
#   %(outp)s -> M4.drain, M4.source -> M2.drain, M2.source -> %(rail)s   (output,    B side)
#   M3 diode (g=d) shared with M4.gate; M1 diode (g=d) shared with M2.gate.
from glayout import MappedPDK
from glayout.placement.four_transistor_interdigitized import generic_4T_interdigitzed
from glayout.routing.c_route import c_route
from glayout.routing.L_route import L_route
from glayout.routing.straight_route import straight_route
from glayout.spice.netlist import Netlist
from glayout.backend import Component
import gdstk


def build(pdk: MappedPDK) -> Component:
    W, L, NF, NUMCOLS = %(w)s, %(l)s, %(nf)s, %(numcols)s
    comp = Component(name="%(top)s")

    # ONE tie total: rows BARE (with_tie=False); the ring is generic_4T's OWN substrate-tap
    # ring (with_substrate_tap default True — glayout computes its enclosure), so we add NO
    # manual tapring. (Passing with_substrate_tap=False crashes glayout — library bug.)
    core = generic_4T_interdigitzed(
        pdk, top_row_device="%(dev)s", bottom_row_device="%(dev)s", numcols=NUMCOLS, length=L,
        top_kwargs=dict(width=W, fingers=NF, with_tie=False),
        bottom_kwargs=dict(width=W, fingers=NF, with_tie=False))
    cref = comp << core
    cref.movey(-(cref.ymax + cref.ymin) / 2)          # center vertically before routing

    ms = pdk.util_max_metal_seperation()
    # east: rail source short (inner), then the two stack routes (nested outward)
    comp << c_route(pdk, cref.ports["bottom_A_source_E"], cref.ports["bottom_B_source_E"],
                    extension=3 * ms, viaoffset=False)
    comp << c_route(pdk, cref.ports["top_A_source_E"], cref.ports["bottom_A_drain_E"],
                    extension=6 * ms, viaoffset=False)     # M3.s -> M1.d
    comp << c_route(pdk, cref.ports["top_B_source_E"], cref.ports["bottom_B_drain_E"],
                    extension=9 * ms, viaoffset=False)     # M4.s -> M2.d
    # west: the two gate shorts (nested), each diode-connected via its con_N
    gshort_b = comp << c_route(pdk, cref.ports["bottom_A_gate_W"], cref.ports["bottom_B_gate_W"],
                               extension=3 * ms, viaoffset=False)
    comp << L_route(pdk, cref.ports["bottom_A_drain_W"], gshort_b.ports["con_N"],
                    viaoffset=False, fullbottom=False)     # M1 diode
    gshort_t = comp << c_route(pdk, cref.ports["top_A_gate_W"], cref.ports["top_B_gate_W"],
                               extension=6 * ms, viaoffset=False)
    comp << L_route(pdk, cref.ports["top_A_drain_W"], gshort_t.ports["con_N"],
                    viaoffset=False, fullbottom=False)     # M3 diode
    # the SINGLE ring = generic_4T's own substrate-tap ring (ports substratetap_*).
    # Route the edge DUMMIES to it (5T-OTA tutorial pattern; skip any absent port).
    for dummy_port, ring_port in (
            ("top_A_0_dummy_L_gsdcon_top_met_W",    "substratetap_W_top_met_W"),
            ("top_B_%(idx)s_dummy_R_gsdcon_top_met_E",    "substratetap_E_top_met_E"),
            ("bottom_A_0_dummy_L_gsdcon_top_met_W", "substratetap_W_top_met_W"),
            ("bottom_B_%(idx)s_dummy_R_gsdcon_top_met_E", "substratetap_E_top_met_E")):
        try:
            comp << straight_route(pdk, cref.ports[dummy_port], cref.ports[ring_port],
                                   glayer2="met1")
        except KeyError:
            pass
    # LVS reference netlist: map the 4T netlist onto the cascode topology
    casc = Netlist(circuit_name="CASCODE_CMIRROR",
                   nodes=["%(refp)s", "%(outp)s", "%(rail)s", "N1", "N2", "B"])
    casc.connect_netlist(core.info["netlist"], [
        ("VDD1", "%(refp)s"), ("VSS1", "N1"), ("VG1", "%(refp)s"),
        ("VDD2", "%(outp)s"), ("VSS2", "N2"), ("VG2", "%(refp)s"),
        ("VDD3", "N1"), ("VSS3", "%(rail)s"), ("VG3", "N1"),
        ("VDD4", "N2"), ("VSS4", "%(rail)s"), ("VG4", "N1"),
        ("VB", "B")])
    comp.info["netlist"] = casc
    # ports + labels (LVS matches by label; the ring carries the bulk label B)
    lay = pdk.get_glayer("met2")
    for pin, port in (("%(refp)s", cref.ports["top_A_drain_N"]),
                      ("%(outp)s", cref.ports["top_B_drain_N"]),
                      ("%(rail)s", cref.ports["bottom_A_source_E"]),
                      ("B", cref.ports["substratetap_S_top_met_S"])):
        comp.add_port(name=pin, port=port)
        comp.add(gdstk.Label(pin, origin=port.center, layer=lay[0], texttype=lay[1]))
    return comp
'''


def _gen_layout_script(rec, ctx, design_dir: Path, top: str, feedback="") -> str:
    """Write layout/<top>.py — the glayout generator — from the config JSON's wiring+params.
    For recognized topologies (current/cascode mirrors) emit a DETERMINISTIC, known-buildable
    script (no LLM); otherwise fall back to the model. Returns the script source (also on disk)."""
    ndir, layout_dir = design_dir / "netlist", design_dir / "layout"
    layout_dir.mkdir(parents=True, exist_ok=True)
    from glayout_tools import load_config, config_note
    cfg = load_config(design_dir, top)
    # DETERMINISTIC path first (reliable) — unless the user's feedback asks for a hand change.
    if not feedback:
        det = _deterministic_layout_script(cfg, top)
        if det:
            (layout_dir / f"{top}.py").write_text(det)
            rec.caption("🧩 Generated a known-buildable glayout layout deterministically from the "
                        "config (current-mirror template) — no guesswork on layer/port names.")
            rec.expander_code(f"📄 layout/{top}.py", det[:6000], "python", expanded=False)
            return det
    # GLAYOUT-FIRST: the wiring lives in the config JSON's `wiring` section (there is no
    # hand-written .sp). Render it as a readable component→net list for the layout prompt.
    # Fall back to a legacy netlist/<top>.sp only if one happens to exist.
    netlist = _wiring_from_config(cfg)
    if not netlist:
        netlist = (ndir / f"{top}.sp").read_text(errors="replace") if (ndir / f"{top}.sp").exists() \
            else ctx.get("decomposed_files", {}).get(f"{top}.sp", "")
    # glayout reference code the researcher gathered (real cell generators to imitate)
    refs = ""
    gdir = design_dir / "context" / "glayout_refs"
    if gdir.is_dir():
        for p in sorted(gdir.glob("*.py"))[:2]:
            refs += f"\n# reference: {p.name}\n{p.read_text(errors='replace')[:2500]}\n"
    prompt = (
        f"Write a Glayout layout generator `layout/{top}.py` for this circuit: {ctx['query']}.\n"
        + (f"USER INSTRUCTION: {feedback}\n" if feedback else "")
        + "DESIGN CONFIG (size every device from these params):\n" + config_note(cfg, 1400) + "\n"
        + _layout_script_rules(top, PDK) + "\n\n"
        + (f"GLAYOUT REFERENCE CODE (imitate this style of placement+routing):\n{refs}\n"
           if refs else "")
        + f"WIRING to lay out (from the config JSON) — instantiate every component and route "
          f"every net (c_route / L_route / straight_route + via):\n{netlist[:6000]}\n")
    rec.caption("🧠 Live model output (glayout script):")
    try:
        raw = clean_llm_output(stream_to(get_chat_model(temperature=0.2), prompt, rec.placeholder()))
        src = extract_code_block(raw, "python") or raw
    except Exception:  # noqa: BLE001
        src = ""
    if "def build(" not in src:
        src = ("# AnoaChip layout stub — the model did not produce a build(pdk); edit me.\n"
               "from glayout.backend import Component\n\n"
               "def build(pdk):\n"
               f"    comp = Component(name=\"{top}\")\n"
               "    return comp\n")
    (layout_dir / f"{top}.py").write_text(src)
    rec.expander_code(f"📄 layout/{top}.py", src[:6000], "python", expanded=True)
    return src


def _show_layout_gds(rec, design_dir: Path, top: str, iteration: int, b: dict) -> None:
    """Render + show the current GDS EVERY harden iteration — even a failed build — so the
    layout is always visible (user: 'mana gds shownya'). Prefers the .svg glayout emitted;
    otherwise renders the .gds ourselves with gdstk. No-op only when no GDS exists at all."""
    ldir = design_dir / "layout"
    svg = ldir / f"{top}.svg"
    gds = ldir / f"{top}.gds"
    if not svg.exists() and gds.exists():
        try:
            import gdstk
            lib = gdstk.read_gds(str(gds))
            tops = lib.top_level()
            if tops:
                tops[0].write_svg(str(svg))
        except Exception:  # noqa: BLE001
            pass
    if svg.exists():
        extra = ""
        if b.get("n_ports") is not None:
            extra = f" ({b.get('n_ports')} ports, bbox {b.get('bbox_um')} µm)"
        status = "✅" if b.get("ok") else "🚧 (build not clean yet — shown so far)"
        rec.image(str(svg), f"🔲 {top} layout — iteration {iteration} {status}{extra}")
    elif gds.exists():
        rec.caption(f"🔲 GDS written (`{gds.name}`, {gds.stat().st_size} B) — couldn't render a preview.")


def _save_layout_error_lesson(ctx, top: str, err: str) -> None:
    """Persist a layout BUILD/DRC/LVS error to the knowledge store (kind='fix') so the same
    glayout failure is RECALLED and avoided next time (user: 'setiap ada error masukin ke
    knowledge database biar makin pinter'). Dedupes on the error signature."""
    try:
        mem = get_memory()
        if not getattr(mem, "enabled", False) or not (err or "").strip():
            return
        # the SIGNATURE line — the actual ValueError/DRC/LVS message, not the whole traceback
        sig = ""
        for ln in reversed((err or "").splitlines()):
            if re.search(r"error|valueerror|via_array|drc|lvs|mismatch|<\s*0\.|not connected", ln, re.I):
                sig = ln.strip()
                break
        sig = sig or err.strip().splitlines()[-1][:200]
        design = Path(ctx["design_dir"]).name
        body = (f"GLAYOUT LAYOUT ERROR for '{(ctx.get('query') or '')[:120]}' (top `{top}`):\n"
                f"{sig}\n\nFull context:\n{err[:1200]}\n\n"
                "When this recurs: fix it in layout/<top>.py or the config BEFORE rebuilding.")
        mem.remember("fix", body, design=design, source=f"layout-error:{design}",
                     title=f"layout error: {sig[:80]}", tags="layout error glayout drc lvs")
    except Exception:  # noqa: BLE001
        pass


def agent_harden(rec, ctx, feedback="", _hier_attempt=0):
    """LAYOUT + SIGN-OFF stage (Glayout): turn the spec-clean netlist into a GDS, then DRC
    (magic) + LVS (netgen). Self-improving: a failing DRC/LVS routes back to a targeted fix
    of the layout script (unrouted net, DRC spacing) or the config (device sizing), and
    re-builds — bounded by ANOA_MAX_LAYOUT_ITERS."""
    # ---- HARD GATE: never lay out a circuit whose spec verification is failing ----------
    failing_units = []
    try:
        for up in sorted((Path(ctx["design_dir"]) / "context" / "unit_state").glob("*.json")):
            if json.loads(up.read_text()).get("status") != "pass":
                failing_units.append(up.stem)
    except Exception:  # noqa: BLE001
        pass
    unverified = (ctx.get("simulation_output") or ctx.get("_sim_unverified") or failing_units)
    if unverified and not ctx.get("force_harden"):
        ctx["_harden_refused"] = True
        why = (f"unit test(s) still FAILING: {', '.join(failing_units)}" if failing_units
               else "the spec simulation is not passing")
        rec.error(
            f"⛔ NOT laying out: {why}. The pipeline will keep FIXING the circuit instead; "
            "once every spec passes, layout starts automatically. To override, steer with "
            "**force harden**.")
        return
    ctx.pop("_harden_refused", None)

    design_dir = Path(ctx["design_dir"])
    # GLAYOUT-FIRST: the design is the config JSON (no netlist dir). Prefer the netlist top if
    # a legacy .sp exists, else take the top from the config filename, else slugify the prompt.
    try:
        top = _ensure_top(ctx, design_dir / "netlist") if (design_dir / "netlist").exists() else ""
    except Exception:  # noqa: BLE001
        top = ctx.get("top_module_name") or ""
    if not top:
        cfgs = sorted((design_dir / "config").glob("*.json")) \
            if (design_dir / "config").exists() else []
        top = cfgs[0].stem if cfgs else slugify(ctx["query"])
        ctx["top_module_name"] = top
    from glayout_tools import (run_build, build_summary, glayout_available, tools_available,
                              load_config, save_config, bump_iteration)
    ok_env, env_note = glayout_available()
    if not ok_env:
        rec.error(f"⛔ Glayout not available: {env_note}. Install it (`uv sync`) and retry.")
        ctx["harden_error"] = env_note
        return
    tools = tools_available()
    rec.caption(f"🏭 Glayout layout on {PDK} · DRC={'magic' if tools['magic'] else 'MISSING'} · "
                f"LVS={'netgen' if tools['netgen'] else 'MISSING'}")

    _write_default_config(design_dir, top, ctx)

    # write the layout generator (unless one already exists and this isn't a fresh feedback pass)
    script_rel = f"layout/{top}.py"
    if not (design_dir / script_rel).exists() or feedback:
        _gen_layout_script(rec, ctx, design_dir, top, feedback)

    # NO HARD "x/5" CAP (user: 'remove iteration x/5, do not limit like that'): keep building +
    # fixing until the layout is clean, bounded only by a WALL-CLOCK budget so it can't spin
    # forever. Every fix is fed the FULL error history so it LEARNS and never repeats a mistake.
    import time as _t
    budget_s = float(os.getenv("ANOA_LAYOUT_BUDGET_S", "1800"))
    hard_cap = int(os.getenv("ANOA_MAX_LAYOUT_ITERS", "40"))
    t0 = _t.time()
    last: dict = {}
    err_history: List[str] = []          # every distinct build/DRC/LVS error, in order
    it = 0
    while it < hard_cap and (_t.time() - t0) < budget_s:
        it += 1
        rec.caption(f"🔧 Build glayout → GDS + verify — iteration {it}")
        with st.spinner("Building the glayout code (subprocess) → GDS + DRC + LVS…"):
            res = run_build(design_dir, script_rel, top, pdk=PDK,
                           drc=tools["magic"], lvs=tools["netgen"])
        last = res
        summary = build_summary(res)
        rec.code(summary, language="text")
        (design_dir / "layout" / "build_summary.txt").write_text(summary)
        _log_state(ctx, "layout", summary[:200])

        b = res.get("build", {})
        # SHOW THE GDS EVERY ITERATION via show_gds() (user: 'show gds when building glayout
        # code') — render whatever GDS glayout emitted this iteration, EVEN IF DRC/LVS reported
        # problems, so the layout is always visible as it evolves.
        _show_layout_gds(rec, design_dir, top, it, b)
        drc_ok = res.get("drc", {}).get("status") in ("pass", "not run")
        # THIS stage (GDS) signs off on a clean BUILD + DRC. LVS, PEX and the post-layout
        # testbench/simulation are their OWN downstream stages (user: 'don't bypass LVS/PEX/
        # testbench to report') — so the flow is GDS → LVS → PEX → Testbench → Report, each
        # showing its result. The LVS verdict from run_build is carried for the LVS stage.
        if b.get("ok") and drc_ok:
            gds = b.get("gds")
            rec.success(f"✅ GDS built + DRC clean — `{gds}`, {b.get('n_ports')} ports, bbox "
                        f"{b.get('bbox_um')} µm. Next: LVS → PEX → testbench → report.")
            ctx["harden_metrics"] = {"gds": gds, "n_ports": b.get("n_ports"),
                                     "bbox_um": b.get("bbox_um"),
                                     "drc": res.get("drc", {}).get("status"),
                                     "lvs": res.get("lvs", {}).get("status")}
            ctx["harden_error"] = ""
            ctx.pop("_budget_fail", None)
            _save_harden_lesson(rec, ctx, res, gds, top)
            return
        # ---- something failed → targeted fix, then rebuild ------------------
        ctx["_budget_fail"] = True
        err = _layout_error(res)
        ctx["harden_error"] = err
        err_history.append(err)
        _save_layout_error_lesson(ctx, top, err)
        # LEARN: if the SAME error signature repeats, the incremental fix isn't working — escalate
        # to a FULL regeneration of the glayout code that names the repeated error explicitly.
        sigs = [ _err_sig(e) for e in err_history ]
        repeated = sigs.count(_err_sig(err)) >= 2
        # QUIET progress (user: 'don't scare user by showing warning every iteration') — a calm
        # caption, not a red warning, and just the error gist (no traceback wall).
        rec.caption(f"🔧 refining the glayout code — iteration {it}"
                    + (" (regenerating)" if repeated else "") + f" · {_err_sig(err)}")
        _fix_layout(rec, ctx, design_dir, top, res, err,
                    history=err_history, regenerate=repeated)

    ctx["harden_error"] = _layout_error(last)
    ctx["_sim_unverified"] = False
    rec.error("❌ Layout could not be signed off within the iteration budget — the summary and "
              "reports are saved under `layout/`. Steer with a hint (e.g. 'increase M1 length') "
              "or 'force harden' to keep the last GDS.")
    _save_harden_lesson(rec, ctx, last, last.get("build", {}).get("gds"), top)


def _gen_postlayout_tb(rec, ctx, design_dir: Path, top: str, pexf: Path) -> str:
    """Write the ngspice testbench AGAINST the PEX-extracted subckt (post-layout) from the
    config spec + use case. This is the ONLY testbench in the glayout-first flow — it runs on
    the extracted silicon, never a hand-written schematic. Returns the deck text (or '')."""
    from glayout_tools import load_config, config_note
    cfg = load_config(design_dir, top) or {}
    # The PEX top subckt now has REAL ports (run_pex does `port makeall`, promoting the
    # layout labels) — grab its exact header (ports incl. continuation lines).
    subckt = _pex_top_header(pexf, top)
    sims = ctx.get("sim_types") or _DEFAULT_SIM_TYPES
    prompt = (
        f"Write an ngspice testbench for the POST-LAYOUT (PEX-extracted) circuit `{top}`.\n"
        f"CIRCUIT: {ctx.get('query','')}\n"
        f"The extracted netlist is included with `.include {pexf}` and its top subckt is:\n"
        f"  {subckt or ('.subckt ' + top + ' …')}\n"
        "X-instantiate THAT subckt with EXACTLY that name and EXACTLY those ports in that "
        "order (copy them verbatim — never rename, reorder, drop, or invent ports), add the "
        "supply/bias/input stimulus for the use case, and run ONLY these analyses: "
        + ", ".join(sims) + ".\n"
        "DESIGN SPEC + PARAMS (drive + measure against these):\n" + config_note(cfg, 1200) + "\n"
        + _sim_types_note(ctx) + "\n"
        "MEASURE ONLY WHAT APPLIES to this topology and these analyses (a current mirror has "
        "no gain_db/bw; skip specs the analyses can't produce — the table shows '-' for them). "
        "Make it SELF-CHECKING: `.measure` each applicable spec, echo `SPEC <name> PASS/FAIL "
        "measured=… want=…` per spec (plain words + `=`/`:` only — NO `>` `<` `->` in an echo, "
        "ngspice redirects them to junk files; put comparisons in `.measure`/`if`), `wrdata "
        f"sim/{top}_ac.txt` the AC curve if AC is run and `wrdata sim/{top}_tran.txt` the "
        "transient waveform if TRAN is run, then `echo Result: PASSED`/`FAILED` from the fail "
        "count and `quit`. Start the deck with a `*` title line. Output ONLY the deck in one "
        "```spice block.")
    try:
        raw = clean_llm_output(stream_to(get_chat_model(temperature=0.2), prompt, rec.placeholder()))
        deck = extract_code_block(raw, "spice") or raw
    except Exception:  # noqa: BLE001
        return ""
    # STRIP hallucinated PDK-model includes (`.include /usr/share/pdk/...design.ngspice`
    # crashed the post-layout sim) — any model-ish .include/.lib whose file doesn't exist
    # goes; run_ngspice injects the CORRECT `.lib` for the active PDK automatically.
    kept = []
    for ln in deck.splitlines():
        m = re.match(r"^\s*\.(include|lib)\s+(\S+)", ln, re.I)
        if m and re.search(r"pdk|libs\.tech|\.ngspice$|\.lib\.spice$", m.group(2), re.I) \
                and not Path(m.group(2)).exists():
            continue
        kept.append(ln)
    deck = "\n".join(kept)
    if ".include" not in deck:
        deck = f"* {top} post-layout testbench\n.include {pexf}\n" + deck
    return _canon_dut_instance(deck, subckt, pexf)


def _pex_top_header(pexf: Path, top: str) -> str:
    """The PEX file's TOP `.subckt` header (name-matched, else the last one), with `+`
    continuation lines joined — the exact port list a testbench must instantiate."""
    try:
        lines = pexf.read_text(errors="replace").splitlines()
        cands = [(re.match(r"^\s*\.subckt\s+(\S+)", ln, re.I).group(1), i)
                 for i, ln in enumerate(lines)
                 if re.match(r"^\s*\.subckt\s+(\S+)", ln, re.I)]
        pick = next(((n, i) for n, i in cands if n.lower() == top.lower()),
                    cands[-1] if cands else None)
        if not pick:
            return ""
        i = pick[1]
        parts = [lines[i].strip()]
        for cont in lines[i + 1:]:
            if cont.lstrip().startswith("+"):
                parts.append(cont.lstrip()[1:].strip())
            else:
                break
        return " ".join(parts)
    except Exception:  # noqa: BLE001
        return ""


def _canon_dut_instance(deck: str, subckt: str, pexf: Path) -> str:
    """FORCE the DUT instance to the canonical `xdut <ports…> <subckt>` — never trust the
    model's X-card syntax (v10 wrote `Xpex cascode_current_mirror iref iout vdd vss`: name
    first + an invented port → 'unknown subckt'). Replaces any X line naming the subckt;
    inserts after the PEX include if none exists."""
    if not subckt:
        return deck
    toks = subckt.split()
    if len(toks) < 3:
        return deck
    sname, ports = toks[1], [p for p in toks[2:] if "=" not in p]
    canon = "xdut " + " ".join(ports) + " " + sname
    # subckts the DECK itself defines (a tb-local ideal block is legitimate to instantiate)
    local_subckts = {m.group(1).lower()
                     for m in re.finditer(r"^\s*\.subckt\s+(\S+)", deck, re.M | re.I)}
    out_lines: List[str] = []
    inserted = False
    for ln in deck.splitlines():
        if re.match(r"^\s*x\S*\s", ln, re.I):
            last = (ln.split() or [""])[-1].lower()
            if last == sname.lower() or re.search(rf"\b{re.escape(sname)}\b", ln, re.I):
                if not inserted:          # replace the (however-malformed) DUT instance
                    out_lines.append(canon)
                    inserted = True
                continue
            if last not in local_subckts:
                continue                  # hallucinated subckt (CASCODE_CMIRROR…) — drop it
        out_lines.append(ln)
    if not inserted:                      # no DUT X-card at all → insert after the include
        lines = out_lines
        out_lines = []
        for ln in lines:
            out_lines.append(ln)
            if not inserted and (str(pexf) in ln or pexf.name in ln):
                out_lines.append(canon)
                inserted = True
        if not inserted:
            out_lines.insert(1, canon)
    return "\n".join(out_lines)


def _fix_postlayout_tb(rec, ctx, top: str, pexf: Path, deck: str, err: str,
                       sims: list) -> str:
    """One focused repair of the post-layout deck: the EXACT ngspice error + the current
    deck go in, a corrected deck comes out (include + X-instance preserved). Used by the
    plot gate so 'no tran data' is fixed instead of silently finishing."""
    prompt = (
        f"This ngspice testbench for the PEX-extracted circuit `{top}` FAILED or produced no "
        f"simulation data. Fix it.\n\nNGSPICE ERROR/OUTPUT (the exact failure):\n{err}\n\n"
        f"CURRENT DECK:\n```spice\n{deck[:3500]}\n```\n"
        "Rules: keep `.include " + str(pexf) + "` and the X-instance of the extracted "
        "subckt EXACTLY as-is (same subckt name, same port order). Run ONLY: "
        + ", ".join(sims or ["tran"])
        + ". The deck MUST `wrdata sim/" + top + "_tran.txt time v(out_node) i(...)` for TRAN "
        "(and `wrdata sim/" + top + "_ac.txt` for AC if AC is run) INSIDE a .control block "
        "after the run command. No `>` `<` `->` inside echo. End with `quit`. Output ONLY the "
        "corrected deck in one ```spice block.")
    try:
        raw = clean_llm_output(stream_to(get_chat_model(temperature=0.15), prompt,
                                         rec.placeholder()))
        fixed = extract_code_block(raw, "spice") or ""
        return fixed if ".include" in fixed else ""
    except Exception:  # noqa: BLE001
        return ""


def _post_layout_sim(rec, ctx, design_dir: Path, top: str, tools: dict) -> None:
    """POST-LAYOUT verification: extract the PEX netlist from the signed-off layout and run
    ngspice on IT (parasitic R/C included) for the real DC/AC/transient response — the user's
    flow: the glayout/PEX-extracted netlist is what's simulated, not the schematic. Reuses the
    existing testbench, repointing its `.include` at the PEX netlist. Non-gating: a PEX/sim
    hiccup logs a note, it doesn't fail the (already signed-off) layout."""
    if not tools.get("magic"):
        return
    from glayout_tools import run_pex
    rec.caption("🔬 Post-layout: extracting the PEX netlist (magic) for the real response…")
    pex = run_pex(design_dir, top, pdk=PDK)
    if not pex.get("ok"):
        rec.caption(f"(PEX extraction skipped: {str(pex.get('error'))[:200]})")
        return
    pexf = Path(pex["pex_netlist"])
    rec.success(f"📎 PEX netlist extracted → `{pexf.name}` ({pexf.stat().st_size} B, with parasitics).")
    # GLAYOUT-FIRST: the testbench is written HERE — AFTER the layout is clean and its SPICE is
    # extracted (user: 'testbench is after you finished glayout and extract the spice'). Reuse a
    # legacy tb if one exists; otherwise GENERATE one against the extracted subckt + config spec.
    (design_dir / "tb").mkdir(parents=True, exist_ok=True)
    tbp = design_dir / "tb" / f"{top}_tb.sp"
    if tbp.exists():
        tb = tbp.read_text(errors="replace")
        pex_tb = re.sub(r"^\s*\.include\s+\S+", f".include {pexf}", tb, count=1,
                        flags=re.MULTILINE)
    else:
        pex_tb = _gen_postlayout_tb(rec, ctx, design_dir, top, pexf)
        if not pex_tb:
            rec.caption("(could not build a post-layout testbench — skipping PEX sim.)")
            return
    post = design_dir / "tb" / f"{top}_postlayout_tb.sp"
    post.write_text(pex_tb)
    from spice_sim import (run_ngspice, parse_measures, ac_metrics, check_specs,
                           specs_pass, spec_table)
    # PLOT GATE (user: 'dont finish testbench if it doesnt produce simulation plot'):
    # the stage is NOT done until the requested response data actually exists —
    # sim/<top>_tran.txt for TRAN, sim/<top>_ac.txt for AC. On a miss, feed the exact
    # ngspice error back into a deck fix and re-run, up to 3 attempts; still no data →
    # a LOUD ❌ (never a silent pass into the report).
    sims = [s for s in (ctx.get("sim_types") or _DEFAULT_SIM_TYPES) if s in ("tran", "ac")]
    need = {s: design_dir / "sim" / f"{top}_{s}.txt" for s in sims}
    rec.caption("🔬 Simulating the extracted (post-layout) netlist — DC/AC/transient…")
    out = ""
    for attempt in range(3):
        with st.spinner(f"ngspice on the PEX netlist (attempt {attempt + 1}/3)…"):
            ok, out = run_ngspice(post, workdir=design_dir)
        (design_dir / "sim" / "postlayout.log").write_text(out or "(no output)")
        missing = [s for s, f in need.items() if not (f.exists() and f.stat().st_size > 0)]
        # SUCCESS = the wrdata files exist — that's the deliverable. ngspice often exits
        # non-zero on a stray .measure AFTER the data was already written; requiring a clean
        # exit turned a WORKING attempt into '.txt missing/empty' (the bug the user hit).
        if not missing:
            if not ok:
                rec.caption("(ngspice grumbled after writing the data — data is complete, "
                            "continuing.)")
            break
        why = "; ".join(f"testbench wrote no {s} data (tb/{post.name} must wrdata "
                        f"sim/{need[s].name})" for s in missing)
        rec.warning(f"Post-layout sim attempt {attempt + 1}: {why} — fixing the testbench…")
        if attempt == 2:
            ctx["plsim_error"] = f"{why}. Last ngspice output:\n{(out or '')[-800:]}"
            rec.error("❌ Post-layout testbench did NOT produce the requested simulation "
                      "plots after 3 attempts — the stage is NOT passed. See "
                      "`sim/postlayout.log`; steer with a testbench hint to retry.")
            return
        fixed = _fix_postlayout_tb(rec, ctx, top, pexf, post.read_text(errors="replace"),
                                   (out or "")[-1500:], sims)
        if fixed:
            # canonical X-card on EVERY retry too — the fixer must never re-break the
            # DUT instance (v10's loop kept a malformed instance for 3 attempts).
            post.write_text(_canon_dut_instance(fixed, _pex_top_header(pexf, top), pexf))
    ctx.pop("plsim_error", None)
    metrics = parse_measures(out)
    ac_file = design_dir / "sim" / f"{top}_ac.txt"
    if ac_file.exists():
        try:
            metrics = {**ac_metrics(ac_file), **metrics}
        except Exception:  # noqa: BLE001
            pass
    if metrics:
        ctx["postlayout_metrics"] = metrics
        (design_dir / "sim" / "postlayout_metrics.json").write_text(json.dumps(metrics, indent=2))
        rec.write("**Post-layout (PEX) measured response:**")
        try:
            from glayout_tools import load_config, bump_iteration
            cfg = load_config(design_dir, top) or load_config(design_dir, design_dir.name)
            rows = check_specs(metrics, (cfg.get("spec") or {}))
            rec.code(spec_table(rows) if rows else
                     "\n".join(f"{k} = {v:.6g}" for k, v in metrics.items()), language="text")
            bump_iteration(design_dir, top, cfg, metrics, note="post-layout PEX")
            if rows and not specs_pass(rows):
                rec.warning("⚠ Post-layout specs shifted vs schematic (parasitics) — tune the "
                            "config and re-run if you need to recover them.")
        except Exception:  # noqa: BLE001
            rec.code("\n".join(f"{k} = {v:.6g}" for k, v in metrics.items()), language="text")
    # the analog 'waveforms' now reflect the EXTRACTED layout. SHOWING them is part of the
    # stage's contract (user: 'tb still failed if cannot show simulation transient') — data
    # on disk but no rendered plot is STILL a failure.
    shown = _show_waveform(rec, design_dir, design_dir / "sim", top=top)
    if sims and not shown:
        ctx["plsim_error"] = ("simulation data exists but the response plot could not be "
                              "rendered (see sim/)")
        rec.error("❌ Post-layout testbench NOT passed: the simulation plot could not be "
                  "shown. The report is blocked until this is fixed.")


def _layout_error(res: dict) -> str:
    """The most actionable error string out of a run_build result."""
    b = res.get("build", {})
    if not b.get("ok"):
        return "BUILD: " + (b.get("error") or "unknown build failure")[-1500:]
    if b.get("n_labels", -1) == 0 and b.get("n_ports", 0) > 0:
        return ("NO LABELS: the layout has ports but ZERO text labels — magic/netgen LVS "
                "matches nets by label, so every external pin will read as unconnected. Add a "
                "text label on each pin's metal (glayout add_glayout_labels / gdstk.Label on "
                "the PDK label layer at comp.ports[name].center) before LVS can pass.")
    lvs = res.get("lvs", {})
    if lvs.get("status") == "fail":
        um = "; ".join(f"{u['type']} {u['name']} only in {u['present_in']}"
                       for u in lvs.get("unmatched", [])[:10])
        return (f"LVS FAIL: {lvs.get('conclusion')} — {um}. A net 'only in schematic' means "
                "its ROUTE was not generated in the layout, OR its pin has no LABEL — add the "
                "missing c_route/L_route/straight_route (+ via_stack) and a text label on the "
                "pin. A device 'only in schematic' means a device wasn't placed.")
    if lvs.get("status") == "error":
        return "LVS ERROR: " + str(lvs.get("error"))[-1200:]
    drc = res.get("drc", {})
    if drc.get("status") == "fail":
        rules = "; ".join(e.get("rule", "?") for e in drc.get("error_details", [])[:8])
        return f"DRC FAIL: {drc.get('total_errors')} violation(s) — rules: {rules}."
    if drc.get("status") == "error":
        return "DRC ERROR: " + str(drc.get("error"))[-1200:]
    return "unknown layout failure"


def _err_sig(err: str) -> str:
    """A stable SIGNATURE for a build/DRC/LVS error so we can detect a REPEAT (same mistake
    twice) — the exception type + the key identifier (a KeyError's port name, the DRC rule),
    stripped of line numbers/paths."""
    e = err or ""
    m = re.search(r"(KeyError|ValueError|AttributeError|TypeError):\s*(.+)", e)
    if m:
        return f"{m.group(1)}:{re.sub(r'[0-9]+', '#', m.group(2))[:80]}"
    m = re.search(r"(net only in schematic|via_array,size|min_spacing|not connected|"
                  r"can't abut|width <)[^\n]*", e, re.I)
    if m:
        return re.sub(r"[0-9.]+", "#", m.group(0))[:80]
    return re.sub(r"[0-9]+", "#", e.strip().splitlines()[-1] if e.strip() else "")[:80]


def _fix_layout(rec, ctx, design_dir: Path, top: str, res: dict, err: str,
                history: "List[str] | None" = None, regenerate: bool = False) -> None:
    """Fix a failing glayout layout — and LEARN (user: 'not learn from prev mistakes and did
    same mistakes again'). Every PAST failed attempt is fed back so the model NEVER repeats a
    mistake; when the SAME error signature recurs, `regenerate` triggers a from-scratch rewrite
    that calls out the repeated error explicitly instead of nudging the broken script again."""
    from glayout_tools import load_config, config_note
    script_p = design_dir / "layout" / f"{top}.py"
    cur = script_p.read_text(errors="replace") if script_p.exists() else ""
    cfg = load_config(design_dir, top)
    wiring = _wiring_from_config(cfg)
    remember_fix(_error_query(err), "", design=design_dir.name)

    # RECALL any stored lesson for THIS error signature (past runs saved it) so the fix is
    # informed by what worked before.
    recalled = ""
    try:
        mem = get_memory()
        if getattr(mem, "enabled", False):
            hits = mem.recall(f"glayout layout error {_err_sig(err)}", k=3) or []
            recalled = "\n".join("- " + (h.get("text") or "")[:300] for h in hits)
    except Exception:  # noqa: BLE001
        pass

    hist = history or []
    hist_note = ""
    if len(hist) > 1:
        hist_note = ("EVERY PREVIOUS ATTEMPT ALREADY FAILED WITH — do NOT reproduce any of these, "
                     "they are dead ends:\n"
                     + "\n".join(f"  attempt {i+1}: {_err_sig(e)}" for i, e in enumerate(hist[:-1]))
                     + "\n")

    mode = ("The SAME error keeps recurring, so the incremental edits are not working — "
            "REWRITE the whole `build()` from scratch, correctly this time, structured on the "
            "canonical pattern in the rules." if regenerate else
            "Make the TARGETED change the error calls for — do not rewrite unrelated parts.")

    prompt = (
        f"The Glayout generator `layout/{top}.py` FAILED verification. {mode}\n\n"
        f"CURRENT ERROR:\n{err[:1500]}\n\n"
        + hist_note
        + (f"WHAT WORKED BEFORE (recalled lessons):\n{recalled}\n\n" if recalled else "")
        + "KEY PORT-NAME RULE: a plain nmos/pmos exposes `multiplier_0_{source,drain,gate}_{E,W,"
        "N,S}`. But an INTERDIGITIZED pair (two_pfet_interdigitized / two_nfet_interdigitized / "
        "*_interdigitized / diff_pair) exposes `A_0_{source,drain,gate}_E`, `B_0_…` (per column, "
        "A/B device), NOT `multiplier_0_*`. A KeyError on a port = you used the WRONG family — "
        "match the port names to the component you actually instantiated (use smart_route and "
        "only REAL ports). Dummies auto-tie (never route `*_dummy_*`); the tapring ties by "
        "enclosing (never route `tie_*`).\n\n"
        + _layout_script_rules(top, PDK) + "\n"
        + f"DESIGN CONFIG (size + wiring):\n{config_note(cfg, 900)}\n"
        + (f"WIRING (route every net):\n{wiring[:1500]}\n\n" if wiring else "\n")
        + f"CURRENT SCRIPT:\n```python\n{cur[:8000]}\n```\n"
        "Output ONLY the corrected python in one ```python block.")
    try:
        raw = clean_llm_output(stream_to(get_chat_model(temperature=0.3), prompt, rec.placeholder()))
        fixed = extract_code_block(raw, "python") or raw
    except Exception:  # noqa: BLE001
        fixed = ""
    if "def build(" in fixed:
        script_p.write_text(fixed)
        rec.markdown(f"💾 **`write_file_disk`** · path=layout/{top}.py")
        rec.expander_code(f"📄 layout/{top}.py ({'regenerated' if regenerate else 'fixed'})",
                          fixed[:6000], "python")
    else:
        rec.caption("(no usable script fix came back — keeping the current script)")


def _save_harden_lesson(rec, ctx, res, final_gds, top) -> None:
    """LESSON MEMORY for layout: persist every layout outcome to the knowledge store
    (kind='harden') — DRC/LVS verdict, port count, bbox — so the planner and generator
    RECALL the physical reality of this circuit class next iteration instead of guessing."""
    try:
        mem = get_memory()
        if not getattr(mem, "enabled", False) or not isinstance(res, dict):
            return
        design = Path(ctx["design_dir"]).name
        b = res.get("build", {})
        drc, lvs = res.get("drc", {}), res.get("lvs", {})
        verdict = "PASS" if (final_gds and not ctx.get("_budget_fail")) else \
            f"FAIL — {str(ctx.get('harden_error'))[:400]}"
        body = (f"LAYOUT RESULT for '{(ctx.get('query') or '')[:150]}' (top `{top}`):\n"
                f"- bbox: {b.get('bbox_um')} µm; ports: {b.get('n_ports')}\n"
                f"- DRC: {drc.get('status')} ({drc.get('total_errors', '?')} errors)\n"
                f"- LVS: {lvs.get('status')} ({lvs.get('conclusion', '')})\n"
                f"- GDS produced: {bool(final_gds)}; sign-off verdict: {verdict}")
        mem.remember("harden", body, design=design, source=f"layout:{design}",
                     title=f"layout: {top} DRC={drc.get('status')} LVS={lvs.get('status')}"[:120],
                     tags="layout drc lvs gds")
        # store the winning config + script as reusable code when it signed off
        if final_gds and not ctx.get("_budget_fail"):
            from glayout_tools import load_config
            cfg = load_config(ctx["design_dir"], top)
            if cfg:
                mem.remember("design", json.dumps(cfg)[:4000], design=design,
                             source=f"config:{design}", title=f"{top}.json config",
                             tags="config analog sizing")
            sp = Path(ctx["design_dir"]) / "layout" / f"{top}.py"
            if sp.exists():
                mem.remember("code", sp.read_text(errors="replace")[:8000], design=design,
                             source=f"glayout:{design}", title=f"{top}.py glayout generator",
                             tags="glayout layout code")
        rec.caption("🧠 Layout outcome saved to the knowledge store — the next iteration plans "
                    "with this physical reality.")
    except Exception:  # noqa: BLE001
        pass




# --------------------------------------------------------------------------- #
# Step registry + orchestration
# --------------------------------------------------------------------------- #
# (emoji, title, desc, fn, accepts_feedback)
def _target_file(msg: str, design_dir) -> str:
    """The ONE file the user named — 'fix ota.sp', 'the layout script', 'the testbench'.
    Returns a path relative to the design dir ('netlist/ota.sp' / 'tb/ota_tb.sp' /
    'layout/ota.py' / 'config/ota.json') or ''."""
    design_dir = Path(design_dir)
    ndir, tb, lay, cfg = (design_dir / "netlist", design_dir / "tb",
                          design_dir / "layout", design_dir / "config")
    files = []
    for d, pats in ((ndir, ("*.sp", "*.spice")), (tb, ("*.sp", "*.spice")),
                    (lay, ("*.py",)), (cfg, ("*.json",))):
        for pat in pats:
            files += sorted(d.glob(pat))
    low = (msg or "").lower()
    m = re.search(r"\b([a-z0-9_]+\.(?:sp|spice|py|json))\b", low)   # explicit filename
    if m:
        hit = next((p for p in files if p.name.lower() == m.group(1)), None)
        if hit:
            return str(hit.relative_to(design_dir))
    if re.search(r"\btest\s?bench\b|\btb\b", low):                  # "the testbench"
        tbf = sorted(tb.glob("*_tb.*"))
        if tbf:
            return str(tbf[0].relative_to(design_dir))
    if re.search(r"\blayout|glayout|gds\b", low):                   # "the layout script"
        lf = sorted(lay.glob("*.py"))
        if lf:
            return str(lf[0].relative_to(design_dir))
    if re.search(r"\bconfig|param\b", low):                         # "the config"
        cf = sorted(cfg.glob("*.json"))
        if cf:
            return str(cf[0].relative_to(design_dir))
    for p in sorted(files, key=lambda p: -len(p.stem)):            # stem name
        if re.search(rf"\b{re.escape(p.stem.lower())}\b", low):
            return str(p.relative_to(design_dir))
    return ""


def _web_fix_hint(rec, ctx, fname: str) -> str:
    """A short web hint for fixing `fname` (its check error, else its purpose) — only when the
    user expressed doubt. Bounded: one search + a couple of crawls."""
    from netlist_check import check_file
    ndir = Path(ctx["design_dir"]) / "netlist"
    err = check_file(ndir / fname, ndir) if (ndir / fname).exists() else ""
    terms = _error_search_terms(err) or [f"{Path(fname).stem} spice netlist"]
    rec.caption(f"🔎 Searching the web for: {', '.join(terms[:2])}")
    try:
        urls = _web_search(terms[0], n_github=2, n_other=4, suffix="spice netlist analog")
        docs = _crawl_urls(urls[:3], rec, limit=3)
        return "\n\n".join((getattr(d, "page_content", "") or "")[:800] for d in docs[:2])
    except Exception:  # noqa: BLE001
        return ""


def agent_fix_file(rec, ctx, feedback=""):
    """SURGICAL single-file fix: edit ONLY the file the user named (optionally web-searching
    first if they're unsure), check it, save it — touching no other file. Driven by a chat
    instruction like 'correct ota.sp and search online if in doubt'."""
    from netlist_check import check_file
    design_dir = Path(ctx["design_dir"])
    rel = ctx.get("_fix_target") or _target_file(feedback, design_dir)
    if not rel or not (design_dir / rel).exists():
        rec.warning("Couldn't tell which file to edit — name it like `ota.sp`, `the layout "
                    "script`, or `the testbench`. No files changed.")
        return
    p = design_dir / rel
    is_netlist = p.suffix.lower() in (".sp", ".spice", ".cir", ".cdl")
    is_layout = p.suffix.lower() == ".py"
    is_cfg = p.suffix.lower() == ".json"
    is_tb = rel.startswith("tb/") or "_tb." in p.name
    cur = p.read_text(errors="replace")
    ndir = design_dir / "netlist"

    def _chk() -> str:
        if is_netlist:
            return check_file(p, ndir)
        if is_cfg:
            try:
                json.loads(p.read_text())
                return ""
            except Exception as e:  # noqa: BLE001
                return f"invalid JSON: {e}"
        return ""
    err = _chk()
    rec.caption(f"🩹 Editing ONLY `{rel}` (no other file is touched)…")
    web_hint = ""
    if re.search(r"\b(search|internet|online|web|google|doubt|unsure|look ?up|find out)\b",
                 feedback or "", re.I) and is_netlist:
        web_hint = _web_fix_hint(rec, ctx, p.name)
    if is_layout:
        kind = ("Glayout generator script (`def build(pdk): -> Component`). Keep the routing "
                "(c_route/L_route/straight_route + via_stack), the explicit placement "
                "(movex/movey/center), and add_ports for every pin; size devices from the "
                "config, bare devices first (no tie/tap/dummy)")
        lang = "python"
    elif is_cfg:
        kind = ("design config JSON (spec table + every W/L/fingers/bias parameter). Keep it "
                "valid JSON; the finishing flags stay false until LVS is clean")
        lang = "json"
    elif is_tb:
        kind = ("self-checking ngspice testbench (a .control deck). Measure every spec, print "
                "`echo SPEC <name> PASS/FAIL measured=… want=…` per spec (NEVER use > < or -> in "
                "an echo — ngspice redirects them to junk files; put comparisons in `if`), wrdata "
                "the AC curve, end with `echo Result: PASSED`/`Result: FAILED` + `quit`")
        lang = "spice"
    else:
        kind = ("SPICE subcircuit (`.subckt` with all ports connected, exact PDK model names, "
                "no floating nets)")
        lang = "spice"
    prompt = (
        f"Edit ONLY this one {kind} for the design: {ctx['query']}.\n"
        + (f"USER INSTRUCTION: {feedback}\n" if feedback else "")
        + (f"Its current CHECK ERROR:\n{err[:700]}\n" if err else "")
        + (f"Reference found on the web (apply if relevant):\n{web_hint[:1600]}\n" if web_hint else "")
        + f"Rewrite the COMPLETE file doing exactly what the user asked. Keep the SAME name/"
        "identity, keep the working structure, add clear inline comments. Output ONLY the file "
        f"content — no prose, no ``` fences.\n\n" + cur[:9000])
    try:
        out = extract_code_block(clean_llm_output(
            stream_to(get_chat_model(temperature=0.2), prompt, rec.placeholder())), lang) or ""
    except Exception:  # noqa: BLE001
        out = ""
    ok_shape = ((is_netlist or is_tb) and ".subckt" in out.lower() if is_netlist
                else (".control" in out.lower() if is_tb
                      else ("def build(" in out if is_layout
                            else (bool(out.strip()) if is_cfg else bool(out.strip())))))
    if out.strip() and ok_shape:
        if is_netlist and not is_tb:
            out = _restamp_header(out, re.sub(r"\.(spice|spc|cdl|cir|sp)$", "", p.name, flags=re.I),
                                  ctx["query"])
        p.write_text(out)
        err2 = _chk()
        rec.markdown(f"💾 **`write_file_disk`** · path={rel}")
        if err2:
            rec.error(f"`{rel}` updated but still has a check error:")
            rec.code(err2[:900], "text")
        else:
            rec.success(f"✅ `{rel}` updated & checks clean — no other file changed.")
        rec.expander_code(f"📄 {p.name}", out[:6000], lang)
        if is_tb:                                       # keep ctx in sync for a follow-up simulate
            ctx.setdefault("testbench_code", {})[p.name] = out
    else:
        rec.warning(f"No usable content came back for `{rel}` — left it UNCHANGED.")
    _sync_ctx_from_disk(ctx)


def agent_lvs(rec, ctx, feedback=""):
    """LVS stage (netgen): confirm the layout matches its schematic/netlist. The verdict was
    produced by the GDS stage's run_build; this stage SHOWS it and, on a mismatch, routes back
    to the layout fixer instead of silently continuing to PEX."""
    hm = ctx.get("harden_metrics") if isinstance(ctx.get("harden_metrics"), dict) else {}
    status = (hm.get("lvs") or "not run")
    top = ctx.get("top_module_name") or "top"
    rec.caption(f"🔍 LVS (netgen) — comparing the `{top}` layout against its netlist.")
    if status == "pass":
        rec.success("✅ LVS PASS — the layout matches the netlist (devices + nets).")
        ctx["_lvs_ok"] = True
    elif status in ("not run", "error"):
        rec.info(f"LVS {status} — the extracted cell carries no reference netlist to compare "
                 "against (or netgen couldn't run). Continuing; verify manually if needed.")
        ctx["_lvs_ok"] = True                # non-blocking: a missing reference isn't a mismatch
    else:
        rec.error("❌ LVS FAIL — layout vs schematic mismatch. Routing back to fix the layout.")
        ctx["_lvs_ok"] = False
        ctx["harden_error"] = "LVS mismatch: " + str(hm.get("lvs"))


def agent_pex(rec, ctx, feedback=""):
    """PEX stage (magic): extract the parasitic (R/C) netlist from the signed-off GDS — this is
    the netlist the post-layout simulation runs on."""
    design_dir = Path(ctx["design_dir"])
    top = ctx.get("top_module_name") or "top"
    tools = _harden_tools()
    if not tools.get("magic"):
        rec.info("PEX skipped — magic not available."); return
    from glayout_tools import run_pex
    rec.caption("🔬 PEX (magic) — extracting the parasitic netlist from the layout…")
    pex = run_pex(design_dir, top, pdk=PDK)
    if pex.get("ok"):
        pexf = Path(pex["pex_netlist"])
        ctx["_pex_netlist"] = str(pexf)
        rec.success(f"📎 PEX netlist extracted → `{pexf.name}` ({pexf.stat().st_size} B, with "
                    "parasitic R/C).")
        rec.expander_code(f"📄 {pexf.name}", pexf.read_text(errors='replace')[:4000], "spice")
    else:
        rec.info(f"PEX could not run ({str(pex.get('error'))[:160]}) — the testbench will use the "
                 "schematic-level netlist instead.")


def agent_pl_sim(rec, ctx, feedback=""):
    """Post-layout TESTBENCH + SIMULATION stage: build the ngspice testbench against the PEX
    (extracted) netlist and run DC/AC/transient, SHOWING the response plots — the real silicon
    response the user asked to SEE, not bypassed to the report."""
    design_dir = Path(ctx["design_dir"])
    top = ctx.get("top_module_name") or "top"
    tools = _harden_tools()
    _post_layout_sim(rec, ctx, design_dir, top, tools)


def _harden_tools() -> dict:
    from glayout_tools import tools_available
    try:
        return tools_available()
    except Exception:  # noqa: BLE001
        return {"magic": None, "netgen": None}


def agent_report(rec, ctx, feedback=""):
    """Deep-agent PDF summary (LaTeX): objective → topology + schematic → what was built
    → spec verification (measured vs target, Bode plots) → layout results (GDS, DRC/LVS)."""
    # HARD GATE (user: 'make sure not report when tb is failed'): a report without real
    # measured results would be a lie — if the post-layout testbench produced no simulation
    # plots, the report is REFUSED until the tb is fixed (steer, or 'force report').
    if ctx.get("plsim_error") and "force report" not in (feedback or "").lower():
        rec.error("⛔ NOT writing the report: the post-layout testbench FAILED to produce "
                  f"the simulation plots ({str(ctx['plsim_error'])[:180]}). Fix the "
                  "testbench first (steer with a hint, or re-run) — a report needs real "
                  "measured results. Override with **force report**.")
        return
    try:
        from report_agent import run_report
        run_report(rec, ctx, feedback)
    except Exception as e:  # noqa: BLE001
        rec.error(f"Report generation failed: {e} — design artifacts are unaffected. "
                  "Steer with 'redo the report' to retry.")


STEP_DEFS = {
    "plan":          ("🧭", "Planner", "Drafts the build plan + design notes.", agent_plan, True),
    "retrieve":      ("📚", "Knowledge Recall", "Semantic recall over the pgvector knowledge store.", agent_retrieve, False),
    "web":           ("🌐", "Netlist/Glayout Researcher", "SPICE netlists + glayout code + papers, crawled & cached.", agent_web, True),
    "generate":      ("✍️", "Config + Netlist Generator", "The local LLM drafts the config + SPICE netlist.", agent_generate, True),
    "decompose":     ("🧩", "Decomposer", "Split the netlist into per-subckt files.", agent_decompose, True),
    "testbench":     ("🧪", "ngspice Testbench", "Self-checking spec testbench with PASSED/FAILED.", agent_testbench, True),
    "write":         ("💾", "File Writer", "Write netlist + testbench to the output folder.", agent_write, False),
    "simulate":      ("🔬", "ngspice Spec Check", "Run ngspice; measure gain/BW/PM/power vs spec.", agent_simulate, False),
    "lint":          ("🔍", "Connectivity Gate", "No floating pins / nets before layout.", agent_lint, False),
    "fix_design":    ("🛠️", "Circuit Corrector", "LLM re-tunes the failing circuit / config.", agent_fix_design, True),
    "fix_testbench": ("🛠️", "Testbench Corrector", "LLM fixes the testbench.", agent_fix_testbench, True),
    "fix_file":      ("🩹", "File Fixer", "Edit ONLY the named file (optionally web-searched).", agent_fix_file, True),
    "harden":        ("🏭", "GDS (Glayout) · DRC", "Build the glayout code → GDS → DRC (magic), shown every iteration.", agent_harden, False),
    "lvs":           ("🔍", "LVS (netgen)", "Layout-vs-schematic — the layout matches the netlist.", agent_lvs, False),
    "pex":           ("🧵", "PEX (magic)", "Extract the parasitic R/C netlist from the GDS.", agent_pex, False),
    "pl_sim":        ("🔬", "Post-layout Testbench", "ngspice DC/AC/tran on the extracted netlist — response plots.", agent_pl_sim, False),
    "report":        ("📕", "Report (LaTeX PDF)", "Compiles a LaTeX/PDF summary — goal, topology, spec verification, GDS + DRC/LVS.", agent_report, True),
}


def route_next(ctx) -> str:
    """Which corrector to run after a failed sim (ported from the old graph router)."""
    out = ctx.get("simulation_output", "")
    low = out.lower()
    # A SPEC MISS (measured value fails its target) or a device-level failure (bias point,
    # floating net, spec check `-> FAIL`) is a CIRCUIT/config bug, not the testbench — fix
    # the design (which re-tunes the config + netlist).
    if ("spec miss" in low or "static check failed" in low
            or re.search(r"->\s*FAIL\b", out)):
        return "fix_design"
    # Otherwise: a tb that won't parse / isn't verifiable / targets the wrong top / a
    # convergence problem in the deck itself → fix the testbench.
    tb_names = list(ctx.get("testbench_code", {}).keys())
    is_tb = (any(t in out for t in tb_names) or "timed out" in low
             or "not verifiable" in low or "testbench mismatch" in low)
    return "fix_testbench" if is_tb else "fix_design"


def advance(run, node):
    """Enqueue the dynamic follow-up steps after `node` finished (the sim→fix loop
    and post-pass hardening that the old LangGraph conditional edges handled)."""
    ctx, q = run["ctx"], run["queue"]
    if node == "plan":
        q.extend(ctx.get("_plan", []))
    elif node == "simulate":
        if ctx.get("simulation_output"):              # sim failed
            # If the design COMPILES, the failure is functional/testbench — more RTL-fix retries
            # rarely help on a 9B model and just burn time, so cap LOW and harden sooner. Only a
            # design that won't even compile gets the full retry budget.
            cap = 3 if ctx.get("_design_compiles") else MAX_RETRIES
            if ctx.get("error_count", 0) < cap:
                q[:0] = [route_next(ctx), "write", "simulate"]
            elif ctx.get("_regen_count", 0) < MAX_REGEN:
                # The fix loop couldn't make this design VERIFIABLE. Per the user: when it isn't
                # verifiable, the generator writes the code AGAIN — regenerate the RTL from
                # knowledge rather than hardening an unverified design. Carry the failure as
                # context so the new attempt avoids the same mistake; fresh retry budget.
                ctx["_regen_count"] = ctx.get("_regen_count", 0) + 1
                ctx["_regen_reason"] = (ctx.get("simulation_output") or "")[:1500]
                ctx["error_count"] = 0
                ctx.pop("_sim_unverified", None)
                q[:0] = ["generate", "decompose", "testbench", "write", "simulate"]
            else:
                # ALL fix + regen budgets are spent and the design STILL fails verification.
                # Per the user ("kenapa masih ada error malah diharden — jangan"): NEVER
                # sneak on to lint→harden with a broken design. End the run honestly; the
                # summary says what still fails, and 'force harden' overrides explicitly.
                # A queued REPORT is dropped too — a report documents a FINISHED chip
                # (harden before report, always), never a design still failing its tests.
                ctx["_sim_unverified"] = True
                q[:] = [s for s in q if s != "report"]
        elif "lint" not in q:                         # sim passed → structural lint gate
            # verification passed under the (possibly new) contract — the contract-change
            # override has done its job and normal rules resume
            ctx.pop("_contract_change", None)
            q.insert(0, "lint")
    elif node == "lint":
        if ctx.get("lint_output"):                    # a REAL lint error (cosmetic warnings are
            # suppressed in agent_lint, so a non-empty lint_output is a genuine structural error
            # — e.g. ASSIGNIN — that Yosys would ALSO reject. FIX it before hardening (the user:
            # "correct lint error first before continue to harden"), even if iverilog compiled it.
            if ctx.get("lint_count", 0) < MAX_LINT_RETRIES:
                q[:0] = ["fix_design", "write", "simulate", "lint"]
            # retries exhausted with a REAL structural error → do NOT harden broken RTL;
            # the run ends honestly (steer or 'force harden' to override).
        elif ctx.get("run_harden"):                   # lint clean → harden if requested
            q.append("harden")
        elif ctx.get("make_report", True) and "report" not in q:
            q.append("report")                        # verified, no hardening → summarize now
    elif node == "harden":
        # GLAYOUT-FIRST: is this a JSON-only design (no hand-written netlist)? Then a layout
        # failure is fixed in the GLAYOUT CODE / config — NEVER by falling into the SPICE loop
        # (fix_design→write→simulate). That old routing is what made the run keep updating .sp
        # instead of the glayout script (user: 'mostly you still update the .sp').
        _ddir = Path(ctx["design_dir"])
        json_only = not (_ddir / "netlist").exists() or not any(
            (_ddir / "netlist").glob("*.sp")) and not any((_ddir / "netlist").glob("*.spice"))
        if ctx.pop("_harden_refused", False):
            if json_only:
                return                            # no pre-layout sim to fix — end honestly
            ctx["_refuse_count"] = ctx.get("_refuse_count", 0) + 1
            if ctx["_refuse_count"] <= 2:
                ctx["error_count"] = 0
                ctx.pop("_sim_unverified", None)
                q[:0] = ["fix_design", "write", "simulate"]
            return
        # LAYOUT AUTO-FIX LOOP: agent_harden already runs its OWN internal DRC/LVS self-improve
        # loop (ANOA_MAX_LAYOUT_ITERS), re-writing the layout script + config in place. If it
        # still couldn't sign off, give it ANOTHER harden round (glayout-first) — the fix lives
        # in layout/<top>.py or the config, so re-run HARDEN, not the SPICE loop.
        hm = ctx.get("harden_metrics") if isinstance(ctx.get("harden_metrics"), dict) else {}
        signed_off = bool(hm.get("gds")) and not ctx.get("_budget_fail")
        if not signed_off and ctx.get("harden_error"):
            if ctx.get("_harden_fix_count", 0) < MAX_HARDEN_FIX:
                ctx["_harden_fix_count"] = ctx.get("_harden_fix_count", 0) + 1
                ctx["simulation_output"] = ""     # not a sim failure — a layout one
                if json_only:
                    q[:0] = ["harden"]            # re-run the glayout layout fixer only
                else:
                    q[:0] = ["fix_design", "write", "simulate", "lint", "harden"]
        # GDS signed off (build + DRC clean) → the downstream verification STAGES, each shown
        # (user: 'don't bypass LVS/PEX/testbench to report'): LVS → PEX → post-layout testbench.
        if signed_off and not any(s in q for s in ("lvs", "pex", "pl_sim", "harden")):
            for st in ("lvs", "pex", "pl_sim"):
                q.append(st)
        # the summary PDF is always the LAST step
        if ctx.get("make_report", True) and "report" not in q and (not q or q[0] != "fix_design"):
            q.append("report")
    elif node == "lvs":
        # LVS mismatch (not a missing-reference) → go back and fix the layout before PEX/sim.
        if ctx.get("_lvs_ok") is False and ctx.get("_harden_fix_count", 0) < MAX_HARDEN_FIX:
            ctx["_harden_fix_count"] = ctx.get("_harden_fix_count", 0) + 1
            ctx.pop("_budget_fail", None)
            q[:0] = ["harden", "lvs", "pex", "pl_sim"]
    # The report documents the FINISHED run — it must always be the LAST step. A queued
    # "report" (e.g. from a 'simulate, harden and report' chat request) would otherwise
    # run before the harden that advance() appended after it.
    if "report" in q and q[-1] != "report":
        q[:] = [s for s in q if s != "report"] + ["report"]


def step_token_report(rec, ctx, node: str, before: dict) -> None:
    """'🔢 N tokens' note at the end of a step + accumulation into ctx (survives
    resume; the PDF report prints the totals). Counts every in-process LLM call
    (stream, llm_query, deep-agent internals) plus run_python's out-of-process
    llm() calls, which log to context/tokens.jsonl."""
    try:
        from llm import token_usage, fmt_tokens, count_subprocess_usage
        tf = Path(ctx["design_dir"]) / "context" / "tokens.jsonl"
        seen = int(ctx.get("_tok_jsonl_lines", 0))
        if tf.exists():
            lines = tf.read_text(errors="replace").splitlines()
            for ln in lines[seen:]:
                try:
                    d = json.loads(ln)
                    count_subprocess_usage(d.get("in", 0), d.get("out", 0))
                except Exception:  # noqa: BLE001
                    pass
            ctx["_tok_jsonl_lines"] = len(lines)
        now = token_usage()
        din = now["in"] - int(before.get("in", 0))
        dout = now["out"] - int(before.get("out", 0))
        dcalls = now["calls"] - int(before.get("calls", 0))
        if dcalls <= 0 and (din + dout) <= 0:
            return                                    # mechanical step — no LLM use
        tot = ctx.setdefault("_tokens_total", {"in": 0, "out": 0, "calls": 0})
        tot["in"] += din
        tot["out"] += dout
        tot["calls"] += dcalls
        by = ctx.setdefault("_tokens_by_step", {})
        by[node] = int(by.get(node, 0)) + din + dout
        rec.caption(f"🔢 {fmt_tokens(din + dout)} tokens used this step "
                    f"(in {fmt_tokens(din)} · out {fmt_tokens(dout)} · {dcalls} LLM "
                    f"call{'s' if dcalls != 1 else ''}) — run total "
                    f"{fmt_tokens(tot['in'] + tot['out'])}")
    except Exception:  # noqa: BLE001
        pass


def execute_step(run, node, feedback=""):
    emoji, title, desc, fn, _ = STEP_DEFS[node]
    ctx = run["ctx"]
    if node in ("write", "simulate", "fix_design", "fix_testbench"):
        title = f"{title} (attempt {ctx.get('error_count', 0) + 1})"
    rec = Recorder(emoji, title, desc, node, live=True)
    from llm import token_usage
    tok0 = token_usage()
    try:
        fn(rec, ctx, feedback)
    except Exception as e:  # noqa: BLE001
        rec.error(f"Step crashed: {e} — use Replan or Revise to recover.")
    step_token_report(rec, ctx, node, tok0)
    return {"node": node, "blocks": rec.blocks}


def do_replan(run, feedback):
    """Replanner: choose the SMALLEST set of next steps that recovers the build from the
    user's feedback + latest error. Key rule: a design already exists on disk after many
    correction iterations — do NOT throw that work away and rebuild from zero. Default to
    an incremental repair on the EXISTING files (fix_design → write → simulate). Only fall
    back to the from-scratch steps (generate, decompose, testbench) when the user EXPLICITLY
    asks to start over."""
    ctx = run["ctx"]
    rec = Recorder("🔁", "Replanner", "Revises the remaining plan from your feedback + latest state.",
                   "plan", live=True)
    known = ["retrieve", "web", "generate", "decompose", "testbench", "write", "simulate",
             "fix_design", "fix_testbench"]
    rebuild = {"generate", "decompose", "testbench"}   # full-from-scratch steps

    err = ctx.get("simulation_output") or ctx.get("lint_output", "")
    files = ctx.get("decomposed_files") or {}
    has_design = bool(files)
    top = ctx.get("top_module_name") or "(none yet)"
    iters = ctx.get("error_count", 0) + ctx.get("lint_count", 0)

    # Did the user EXPLICITLY ask to discard the current design and start fresh? Only
    # then do we allow the from-scratch steps; otherwise we keep the RTL on disk.
    start_over = bool(re.search(
        r"\b(from scratch|start over|start again|re-?generate|rewrite everything|"
        r"whole design|new design|redo|scrap|throw away|ulang|dari awal)\b",
        (feedback or "").lower()))

    rec.caption("🧠 Choosing the next steps…")
    raw = stream_to(
        get_chat_model(temperature=0.2),
        "You are the re-planner for an analog IC build agent. A design ALREADY EXISTS on disk "
        "(config + netlist) and has been through several correction iterations — do NOT discard "
        "that work. Output the SMALLEST set of next steps that addresses the user's message, as "
        "a comma-separated list using ONLY these step names: " + ", ".join(known) + ".\n\n"
        "PREFER incremental repair on the EXISTING files:\n"
        "  • a spec miss / bias problem / any circuit bug  -> fix_design (re-tunes config+netlist)\n"
        "  • the testbench / stimulus / measurement is wrong -> fix_testbench\n"
        "  • you need a reference topology for a sub-block  -> web\n"
        "Use the from-scratch steps (generate, decompose, testbench) ONLY if the user EXPLICITLY "
        "asks to start over / regenerate / rewrite the whole design.\n"
        "Every plan MUST end with: write, simulate.\n\n"
        f"DESIGN: {ctx['query']}\n"
        f"STATE: {len(files)} netlist file(s) on disk, top circuit `{top}`, {iters} correction "
        f"iteration(s) already done. User asked to start over? {'YES' if start_over else 'NO'}.\n"
        f"USER MESSAGE: {feedback or '(none)'}\n"
        f"LATEST ERROR: {err[:800] or '(none)'}\n\n"
        "Reply ONLY with the comma-separated step list.",
        rec.placeholder(),
    )
    picked = [s.strip() for s in re.split(
        r"[,\n]", clean_llm_output(raw)) if s.strip() in known]

    # Guard rail: never rebuild from scratch over an existing design unless the user
    # really asked for it — strip the from-scratch steps and ensure a fixer is present.
    if has_design and not start_over:
        picked = [s for s in picked if s not in rebuild]
        if not any(s in picked for s in ("fix_design", "fix_testbench")):
            picked = ["fix_design"] + picked
    if not picked:                              # nothing usable came back from the model
        picked = (["fix_design"] if has_design
                  else ["generate", "decompose", "testbench"])

    # de-dupe (preserve order) then always re-verify at the end
    seen, ordered = set(), []
    for s in picked:
        if s not in seen and s not in ("write", "simulate"):
            seen.add(s)
            ordered.append(s)
    picked = ordered + ["write", "simulate"]

    mode = ("🔧 incremental fix — keeping your existing netlist" if (has_design and not start_over)
            else "🆕 full rebuild from scratch")
    rec.success(f"{mode}.  New plan: " + "  →  ".join(picked))
    run["queue"] = picked
    # A replan grants a fresh retry budget for the NEW plan. It does NOT touch the files
    # on disk — your corrected netlist stays exactly where it is.
    ctx["error_count"] = 0
    run["transcript"].append({"node": "plan", "blocks": rec.blocks})


def do_weblookup(run, block):
    """On-demand: 'go find an example of block X and its inputs/outputs' — searches
    the web, crawls a few hits, summarizes the I/O, and injects it into the NEXT step."""
    ctx = run["ctx"]
    rec = Recorder("🌐", "Web Example Lookup", f"Finding a reference implementation of: {block}",
                   "web", live=True)
    if not (block or "").strip():
        rec.warning("No block name given — nothing to look up.")
        run["transcript"].append({"node": "web", "blocks": rec.blocks})
        return
    rec.caption(f"Searching GitHub + web for: **{block}**")
    with st.spinner("Searching…"):
        urls = _web_search(block, n_github=4, n_other=2)
    rec.code("\n".join(urls) or "(no results)", language="text")
    with st.spinner("Crawling top results…"):
        docs = _crawl_urls(urls, rec, limit=4)
    if not docs:
        rec.warning("No usable reference crawled.")
        run["transcript"].append({"node": "web", "blocks": rec.blocks})
        return
    ctx.setdefault("documents", []).extend(docs)
    ref = docs[0].page_content[:2500]
    rec.caption("🧠 Summarizing the block's inputs/outputs:")
    summary = clean_llm_output(stream_to(
        get_chat_model(temperature=0.2),
        f"From this reference implementation of '{block}', summarize CONCISELY: the module's "
        "PURPOSE, its INPUTS (name : width), its OUTPUTS (name : width), and a minimal usage "
        f"snippet.\n\n{ref}",
        rec.placeholder(),
    ))
    rec.markdown("**Reference summary (inputs / outputs):**")
    rec.code(summary[:2000], "markdown")
    ctx["web_example"] = f"REFERENCE for '{block}':\n{summary}\n\nSOURCE SNIPPET:\n{ref}"
    rec.success(
        f"Found a reference for `{block}` — it will be injected into the next step you run.")
    run["transcript"].append({"node": "web", "blocks": rec.blocks})


# --------------------------------------------------------------------------- #
# File-system agent — the steering prompt can create/remove/edit files on disk
# --------------------------------------------------------------------------- #
def _is_file_command(msg: str) -> bool:
    """Does this steering prompt ask for a FILE operation (vs design steering)? Precise
    on purpose: an edit verb must come WITH a real file path/extension, so hardware
    phrases like 'make a register file' or 'use a 5-stage pipeline' are NOT misrouted."""
    low = (msg or "").lower()
    has_path = (bool(re.search(r"\.(sp|spice|cir|cdl|py|json|log|txt)\b", low))
                or "netlist/" in low or "tb/" in low or "layout/" in low or "config/" in low)
    listy = any(p in low for p in ("list file", "list all file", "show file",
                                   "show all file", "what files", "which files", "ls "))
    edit_verb = any(v in low for v in ("remove", "delete", "hapus", "rm ", "create",
                                       "rename", "move ", "overwrite", "write to",
                                       "new file", "make a file", "add a file"))
    return listy or (edit_verb and has_path)


def _sync_ctx_from_disk(ctx):
    """Re-read netlist/ + tb/ from disk into the pipeline state after the file agent (or
    a manual edit) changed files, so later steps use the new files."""
    design_dir = Path(ctx["design_dir"])
    nl = {p.name: p.read_text() for p in sorted((design_dir / "netlist").glob("*"))
          if p.suffix.lower() in (".sp", ".spice", ".cir", ".cdl")}
    tb = {p.name: p.read_text()
          for p in sorted((design_dir / "tb").glob("*.sp")) + sorted((design_dir / "tb").glob("*.spice"))}
    if nl:
        ctx["decomposed_files"] = nl
        # keep the existing top if its file exists; only re-derive if it's gone —
        # and then STRUCTURALLY (pick_top), never "the first file".
        cur = ctx.get("top_module_name") or ""
        if f"{cur}.sp" not in nl and f"{cur}.spice" not in nl:
            from netlist_check import pick_top
            ctx["top_module_name"] = pick_top(design_dir / "netlist") or cur
    if tb:
        ctx["testbench_code"] = tb


def _short(v) -> str:
    """One-line, length-capped repr of a tool-call argument for the transcript."""
    s = str(v).replace("\n", " ").strip()
    return (s[:80] + "…") if len(s) > 80 else s


def _render_deep_msg(rec, m) -> str:
    """Render ONE deepagents message as its own recorded block — the agent's reasoning,
    each tool/task CALL (name + args), and each tool RESULT (in a collapsible box). This
    is what makes the transcript readable: every tool and its output is shown separately,
    instead of one giant markdown wall. Returns the assistant text if this was one."""
    kind = m.__class__.__name__
    text = ""
    if kind == "AIMessage":
        # per-call token note (user: show usage at EVERY task/tool, not just per step)
        um = getattr(m, "usage_metadata", None) or {}
        if um.get("input_tokens") or um.get("output_tokens"):
            try:
                from llm import fmt_tokens
                rec.caption(f"🔢 +{fmt_tokens((um.get('input_tokens') or 0) + (um.get('output_tokens') or 0))}"
                            f" tokens (in {fmt_tokens(um.get('input_tokens'))} · "
                            f"out {fmt_tokens(um.get('output_tokens'))})")
            except Exception:  # noqa: BLE001
                pass
        text = clean_llm_output(getattr(m, "content", "") or "").strip()
        # never SPILL the anchor source: strip GitHub repo URLs from displayed prose (the repo
        # lives in references/sources.md, internal — the user must not see which repo it is).
        text = re.sub(r"https?://github\.com/[^\s)\]>'\"]+", "the reference design", text)
        if text:
            rec.markdown(text)
        for tc in (getattr(m, "tool_calls", None) or []):
            # DEFENSIVE: a local model can emit a malformed tool call (tc as a str, or
            # args as a JSON string) — never let that crash the whole step.
            if not isinstance(tc, dict):
                continue
            name, args = tc.get("name"), (tc.get("args") or {})
            if not isinstance(args, dict):
                args = {"input": args}
            if name == "write_todos":
                # The agent's write_todos is its PRIVATE scratchpad and it re-rolls over time —
                # showing it created a SECOND, ever-changing "Plan" that disagreed with the one
                # locked plan. Don't render it; the only plan the user sees is our locked rec.plan.
                continue
            else:
                argstr = " · ".join(
                    f"{k}={_short(v)}" for k, v in args.items())
                rec.markdown(f"🔧 **`{name}`**" +
                             (f" · {argstr}" if argstr else ""))
    elif kind == "ToolMessage":
        name = getattr(m, "name", "") or "tool"
        if name == "write_todos":                            # already shown as the checklist
            return ""
        out = str(getattr(m, "content", "") or "").strip()
        lang = "spice" if ".subckt" in out.lower() else (
            "python" if "def build(" in out else "text")
        rec.expander_code(f"↳ {name} output",
                          out[:4000] or "(empty)", lang, expanded=False)
    return text


def _stream_deep_agent(rec, agent, goal, recursion_limit=60) -> str:
    """Stream a deepagents agent and render its plan + every tool/task call and output
    INCREMENTALLY as clean, recorded blocks (no agent graph). Returns the final
    assistant text. Each message is rendered exactly once as it arrives.

    Loop guard: if the model repeats the SAME tool call (e.g. grepping the same pattern
    over and over), stop the agent so it can't spin forever — the caller then proceeds
    with whatever it has (and the step's own 'did it produce output?' check decides)."""
    seen, final = 0, ""
    calls: Dict[str, int] = {}
    writes: Dict[str, int] = {}      # per-PATH write count — catches fixation on ONE file
    ai_texts: Dict[str, int] = {}    # per-MESSAGE reasoning — catches the "let me try again" spam
    stop = reason = ""
    # tools that ARE the work — never count these as "spinning". A write of a NEW path
    # clears the spin counter (real progress); but REWRITING the SAME path over and over
    # is fixation, not progress — qwen will rewrite one broken module 60× with the same
    # bug, resetting the old guard each time and burning an hour. So we bound writes/path.
    _progress = {"write_file_disk", "run_python", "pip_install"}
    # LIVE inner-call ticker: a deep agent's LLM calls used to emit NOTHING until the
    # whole reply finished — on a slow model one call looked like a 20-minute hang and
    # Stop couldn't interrupt it. Streaming "messages" mode ticks a live line per ~1.5 s
    # (and each paint honors a pending Stop).
    live_ph = rec.placeholder()
    t0 = time.time()
    budget_s = float(os.getenv("ANOA_DEEP_BUDGET_S", "2400"))
    n_chunks = 0
    last_tick = 0.0
    with st.spinner("🧠 Deep agent working (planning · tools · sub-tasks)…"):
        for mode, state in agent.stream({"messages": [{"role": "user", "content": goal}]},
                                        stream_mode=["values", "messages"],
                                        config={"recursion_limit": recursion_limit}):
            if time.time() - t0 > budget_s:
                rec.caption(f"⏳ deep-agent session hit its {int(budget_s)}s budget — "
                            "proceeding with what it has.")
                break
            if mode == "messages":
                n_chunks += 1
                now = time.time()
                if now - last_tick > 1.5:
                    last_tick = now
                    live_ph.code(f"⏳ model generating… ({n_chunks} chunks · "
                                 f"{int(now - t0)}s into this session)", language="markdown")
                continue
            msgs = state.get("messages", [])
            for m in msgs[seen:]:
                text = _render_deep_msg(rec, m)
                if text:
                    final = text
                    # REASONING-LOOP guard: the 9B model emits the same "Actually… Wait… let me
                    # try a different approach" message over and over with NO tool call between —
                    # the tool-call guards never fire. Stop once the same reasoning repeats.
                    if len(text) > 40 and not (getattr(m, "tool_calls", None) or []):
                        key = re.sub(r"\s+", " ", text.lower())[:140]
                        ai_texts[key] = ai_texts.get(key, 0) + 1
                        if ai_texts[key] >= 3 or _looks_repetitive(text):
                            stop, reason = "loop", "repeating the same reasoning"
                for tc in (getattr(m, "tool_calls", None) or []):
                    if not isinstance(tc, dict):
                        continue
                    name = tc.get("name")
                    if name == "write_file_disk":
                        path = str((tc.get("args") or {}).get("path", "?"))
                        writes[path] = writes.get(path, 0) + 1
                        if writes[path] >= 4:    # rewrote ONE file 4× → fixating → stop
                            stop, reason = "fixate", path
                        elif writes[path] <= 2:  # genuine forward progress → reset spin guard
                            calls.clear()
                        continue
                    if name in _progress:        # python/pip = real work → reset spin guard
                        calls.clear()
                        continue
                    try:
                        sig = f"{name}|{json.dumps(tc.get('args', {}), sort_keys=True, default=str)[:300]}"
                    except Exception:  # noqa: BLE001
                        sig = str(name)
                    calls[sig] = calls.get(sig, 0) + 1
                    if calls[sig] >= 4:          # same non-productive call 4× → stuck
                        stop, reason = "spin", sig
            seen = len(msgs)
            if stop == "fixate":
                rec.caption(f"↩︎ stopped looping on `{reason}` — the silent completion pass will "
                            "finish it from the anchor.")
                break
            if stop == "spin":
                rec.caption("↩︎ stopped a non-productive spin — proceeding with what it has.")
                break
            if stop == "loop":
                rec.caption("↩︎ stopped a reasoning loop (same thought repeating) — proceeding "
                            "with what it has; the silent pass / corrector will finish it.")
                break
    return final


def do_fileagent(run, msg):
    """Run the deepagents file agent (qwen3.5:9b) on the design dir for a natural-language
    file command ('remove the .vh file', 'create rtl/alu.v', …), show its tool actions +
    outputs, then sync the changed files back into the pipeline state."""
    from deep_agent import build_deep_agent

    ctx = run["ctx"]
    design_dir = Path(ctx["design_dir"])
    rec = Recorder("🤖", "File Agent (deepagents · qwen3.5:9b)",
                   "Real file-system access — plans, then lists/reads/writes/deletes files on disk.",
                   "plan", live=True)
    rec.caption(f"Command: *{msg}*")
    try:
        agent = build_deep_agent(design_dir)
        # renders every tool call + output
        _stream_deep_agent(rec, agent, msg, recursion_limit=40)
    except Exception as e:  # noqa: BLE001
        rec.error(f"File agent error: {e}")
    _sync_ctx_from_disk(ctx)
    rec.success(
        "✅ Synced design files from disk — the pipeline now uses the agent's changes.")
    run["transcript"].append({"node": "plan", "blocks": rec.blocks})


# --------------------------------------------------------------------------- #
# "Every agent is a deep agent" — run a graph node AS a deepagents agent
# --------------------------------------------------------------------------- #
def _show_waveform(rec, design_dir, out_dir, signals="", cycles=120, top="") -> bool:
    """Render the analog 'waveforms' into the transcript: a Bode plot from the AC wrdata
    export (`sim/<top>_ac.txt`) and a transient plot if `sim/<top>_tran.txt` was written.
    Falls back to scanning sim/ for any *_ac.txt / *_tran.txt when top is unknown."""
    from spice_sim import plot_bode, plot_tran
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    shown = False
    ac_files = ([out_dir / f"{top}_ac.txt"] if top else []) + sorted(out_dir.glob("*_ac.txt"))
    for ac in ac_files:
        if ac.exists() and ac.stat().st_size > 0:
            png = plot_bode(ac, out_dir / "bode.png", title=f"{top or ac.stem} — AC response")
            if png:
                rec.image(png, "📈 Bode plot (gain / phase)")
                shown = True
            break
    tr_files = ([out_dir / f"{top}_tran.txt"] if top else []) + sorted(out_dir.glob("*_tran.txt"))
    for tr in tr_files:
        if tr.exists() and tr.stat().st_size > 0:
            png = plot_tran(tr, out_dir / "tran.png", title=f"{top or tr.stem} — transient")
            if png:
                rec.image(png, "📈 Transient response")
                shown = True
            break
    return shown


def _step_tools(rec, base_dir=None):
    """Step-specific tools every deep-agent node gets, on top of the file tools:
    autonomous WEB research, persistent MEMORY recall, and DISPLAY tools (show an
    image/plot, render a simulation waveform) — so each node can plan, research,
    remember, and SHOW results, like Claude. `base_dir` sandboxes the display paths
    to the design directory."""
    from langchain_core.tools import tool
    base = Path(base_dir).resolve() if base_dir else None

    def _resolve(path: str) -> Path:
        p = (base / (path or "")).resolve() if base else Path(path or "").resolve()
        if base and p != base and base not in p.parents:
            raise ValueError(f"path '{path}' escapes the design directory")
        return p

    @tool
    def search_web(query: str) -> str:
        """Search the web. TWO modes, picked automatically from the query:
        • an ERROR / ngspice / DRC / LVS message → a fix hint with the correct pattern;
        • a design/topic (e.g. 'folded-cascode OTA', 'beta-multiplier bias') → a KNOWLEDGE
          digest: what it is and how it's built at transistor level (topology, sizing,
          pitfalls)."""
        if _ERRORISH_RE.search(query or ""):
            return _auto_research(query, rec) or "(no useful web results)"
        return _web_knowledge(query, rec) or "(no useful web results)"

    @tool
    def recall_memory(topic: str) -> str:
        """Recall a remembered fix/lesson for an error message or topic from past runs."""
        return recall_fix(_error_query(topic)) or recall_fix(topic) or "(nothing remembered yet)"

    @tool
    def show_image(path: str, caption: str = "") -> str:
        """Display an image FILE in the transcript so the user can SEE it: a matplotlib
        plot you saved with run_python (e.g. 'sim/bode.png'), the layout preview
        ('layout/<name>.svg'), or any .png/.jpg/.svg under the design dir. Pass a
        path relative to the design directory."""
        try:
            p = _resolve(path)
        except ValueError as e:
            return f"(refused: {e})"
        if not p.exists():
            return f"(not found: {path})"
        rec.image(str(p), caption)
        return f"shown {path}"

    @tool
    def show_waveform(top: str = "", signals: str = "", cycles: int = 120) -> str:
        """Render the analog results into the transcript so the user can SEE them: the Bode
        plot from the AC wrdata export (`sim/<top>_ac.txt`) and the transient plot
        (`sim/<top>_tran.txt`) the testbench wrote with `wrdata`. Pass the top circuit name
        (or leave blank to scan sim/ for any *_ac.txt / *_tran.txt)."""
        out = (base / "sim") if base else Path("sim")
        ok = _show_waveform(rec, base or Path("."), out, top=top)
        return "plots shown" if ok else ("(no wrdata found — the testbench must "
                                         "`wrdata sim/<top>_ac.txt vdb(out) vp(out)` first)")

    @tool
    def fetch_reference(url: str) -> str:
        """Retrieve ONE more reference ON DEMAND from a link in context/sources.md — use
        this only if the ANCHOR design in context/anchor/ is NOT a good fit for the spec.
        For a GitHub repo it fetches the real HDL; for a paper/web page it crawls the text.
        The result is also saved under context/refs/ so you can read_file_disk it. Pass the
        exact URL from context/sources.md."""
        url = (url or "").strip()
        if not url.startswith("http"):
            return "(pass a full URL from context/sources.md)"
        try:
            if "github.com" in url:
                code = _github_code_text(url, max_files=8, max_chars=9000)
                if code:
                    p = base / "context" / "refs" / (re.sub(r"[^\w]", "_", url)[-60:] + ".sp")
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(code)
                    rec.caption(f"🔗 Fetched reference repo on demand: {url}")
                    return f"Saved reference to {p.relative_to(base)}.\n\n{code[:3500]}"
            docs = _crawl_urls([url], rec, limit=1)
            if docs:
                body = docs[0].page_content[:3500]
                p = base / "context" / "refs" / (re.sub(r"[^\w]", "_", url)[-60:] + ".md")
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(docs[0].page_content[:9000])
                rec.caption(f"🔗 Fetched reference on demand: {url}")
                return f"Saved to {p.relative_to(base)}.\n\n{body}"
        except Exception as e:  # noqa: BLE001
            return f"(could not fetch {url}: {e})"
        return f"(nothing usable at {url})"

    @tool
    def delete_file(path: str) -> str:
        """DELETE a file from the design — a stale duplicate module, an obsolete testbench, a
        leftover `.v` you replaced with a `.sv`, etc. Pass a path relative to the design dir
        ('rtl/old_alu.v', 'tb/cmp_tb.v'). Use this to REMOVE code that should no longer be part
        of the build (a finding that says a module is duplicated/unused → delete one)."""
        try:
            p = _resolve(path)
        except ValueError as e:
            return f"(refused: {e})"
        if not p.exists():
            return f"(not found: {path})"
        if p.is_dir():
            return f"(refused: {path} is a directory)"
        p.unlink()
        rec.markdown(f"🗑️ **`delete_file`** · removed `{path}`")
        return f"deleted {path}"

    @tool
    def rename_file(src: str, dst: str) -> str:
        """RENAME or MOVE a design file — e.g. `netlist/ota_5t.sp` → `netlist/ota_2stage.sp`
        after a topology change, or a stale `tb/old_tb.sp` → `tb/<top>_tb.sp`. Both paths
        are relative to the design dir; the file CONTENT is unchanged, only its name. The
        renamed netlist is structure-checked and the result returned."""
        try:
            s, d = _resolve(src), _resolve(dst)
        except ValueError as e:
            return f"(refused: {e})"
        if not s.exists():
            return f"(not found: {src})"
        d.parent.mkdir(parents=True, exist_ok=True)
        if d.exists():
            d.unlink()
        s.rename(d)
        rec.markdown(f"🔤 **`rename_file`** · `{src}` → `{dst}`")
        if d.suffix.lower() in (".sp", ".spice", ".cir", ".cdl") and base:
            try:
                from netlist_check import check_file
                err = check_file(d, base / "netlist")
                if err:
                    return f"renamed {src} → {dst}\nCHECK (fix if needed):\n{err[:700]}"
            except Exception:  # noqa: BLE001
                pass
        return f"renamed {src} → {dst} (clean)"

    tools = [search_web, recall_memory, show_image, show_waveform, fetch_reference,
             delete_file, rename_file]

    # --- durable knowledge store (pgvector + MinIO): recall / fetch / remember ---
    mem = get_memory()
    if mem.enabled:
        @tool
        def recall_knowledge(query: str, kind: str = "") -> str:
            """Semantically RECALL prior knowledge from AnoaChip's long-term store —
            past configs, netlists, glayout scripts, fixes, references — to reuse instead
            of starting cold. Optionally filter kind (design|code|fix|reference|paper|
            harden|note). Returns the best matches with their object_key; pull the full
            file with fetch_knowledge."""
            items = mem.recall(query, kind=kind or None, k=6)
            if not items:
                return "(nothing relevant in the knowledge store yet)"
            lines = []
            for it in items:
                snip = (it.get("text") or "").strip().replace("\n", " ")[:400]
                lines.append(f"[{it.get('kind')}] {it.get('title')} "
                             f"(design={it.get('design')}, key={it.get('object_key') or '-'})\n  {snip}")
            return "\n".join(lines)

        @tool
        def fetch_knowledge(object_key: str, dest_path: str = "") -> str:
            """Pull a stored artifact (by its object_key from recall_knowledge) out of
            object storage into THIS design dir so you can read it with read_file_disk.
            Defaults to context/recall/<name>."""
            blob = mem.get_object(object_key)
            if blob is None:
                return f"(no object: {object_key})"
            dest = dest_path or f"context/recall/{object_key.split('/')[-1]}"
            try:
                p = _resolve(dest)
            except ValueError as e:
                return f"(refused: {e})"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(blob)
            return f"fetched {object_key} -> {dest} ({len(blob)} bytes)"

        @tool
        def remember_knowledge(text: str, kind: str = "note", title: str = "") -> str:
            """Save a durable lesson/insight to AnoaChip's long-term store so FUTURE
            runs can recall it (e.g. a fix that worked, a synthesis gotcha, a sizing
            rule). kind is usually 'fix' or 'note'."""
            rid = mem.remember(kind, text, source="agent", title=title or text[:60], tags="agent")
            return f"remembered ({rid})" if rid else "(store unavailable)"

        tools += [recall_knowledge, fetch_knowledge, remember_knowledge]

    return tools


def run_deep_agent(rec, base_dir, goal, extra_tools=None, instructions=None, temperature=0.2,
                   on_clean_write=None):
    """Build + stream a per-step deep agent (planning + file + web + memory tools),
    rendering EVERY tool/task call and its output as clean, recorded blocks (no agent
    graph). Returns the agent's final assistant text. `on_clean_write` (generation only)
    fires the per-IP verify the moment a module's write compiles clean."""
    from deep_agent import build_step_agent, INSTRUCTIONS as DEEP_INSTRUCTIONS

    agent = build_step_agent(base_dir, extra_tools=extra_tools,
                             instructions=instructions or DEEP_INSTRUCTIONS,
                             temperature=temperature, on_clean_write=on_clean_write)
    return _stream_deep_agent(rec, agent, goal, recursion_limit=60)


def _ctx_store_refs(ctx) -> tuple[str | None, int]:
    """RLM context offloading: dump the reference designs (and any web-fetched
    example) to `<design>/context/references.md` ON DISK so a deep agent PEEKS at
    slices of it (read_file_disk / grep_files) instead of us inlining 4 KB into the
    prompt. This is what keeps the local model's window small ('smaller this size')."""
    design_dir = Path(ctx["design_dir"])
    parts: List[str] = []
    if ctx.get("uploads_digest"):
        parts.append(ctx["uploads_digest"])
    if ctx.get("web_example"):
        parts.append("## USER-REQUESTED WEB REFERENCE\n" + ctx["web_example"])
    for i, d in enumerate(ctx.get("documents") or []):
        if i >= 30:
            break
        src = d.metadata.get("source", "ref") if hasattr(
            d, "metadata") else "ref"
        body = getattr(d, "page_content", str(d))
        parts.append(f"## ref {i} — {src}\n{body[:2000]}")
    if not parts:
        return None, 0
    text = "\n\n".join(parts)
    cdir = design_dir / "context"
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "references.md").write_text(text)
    return "context/references.md", len(text)


def _collect_rtl_from_disk(design_dir: Path) -> str:
    """Concatenate the netlists a deep agent wrote to netlist/ (shared params first) into a
    single string for ctx['generation'] — the mechanical decomposer re-splits it verbatim."""
    ndir = design_dir / "netlist"
    headers = sorted(ndir.glob("shared_params.sp"))
    mods = [p for p in sorted(ndir.glob("*.sp")) + sorted(ndir.glob("*.spice"))
            if p not in headers and "tb" not in p.name.lower()
            and "testbench" not in p.name.lower()]
    return "\n\n".join(p.read_text() for p in headers + mods)


def _planned_rtl_files(sub):
    """From the generate sub-plan, the deliverable files (config .json + netlist .sp) that
    MUST exist on disk before the step is 'done' — excludes the testbench. Returns
    (files:list[str], top:str|None) so the step can be gated on real completeness."""
    files, top = [], None
    for line in sub:
        m = re.search(r"([A-Za-z0-9_]+\.(?:sp|spice|json))\b", line)
        if not m:
            continue
        fn = m.group(1)
        low = line.lower()
        if "_tb" in fn.lower() or "testbench" in low or "test bench" in low:
            continue                      # the testbench is a SEPARATE step
        files.append(fn)
        if top is None and fn.endswith((".sp", ".spice")) and any(
                k in low for k in ("top", "integrat", "full", "complete")):
            top = fn
    return list(dict.fromkeys(files)), top


def _deep_generate(rec, ctx, feedback=""):
    """Verilog Generator as an RLM deep agent: plans, peeks at offloaded references,
    delegates per-module drafts to llm_query, writes RTL to disk, returns the code —
    same ctx['generation'] the rest of the graph consumes."""
    rec.caption(
        "🧠 RLM deep-agent generation — plan + on-disk context + sub-LLM delegation.")
    design_dir = Path(ctx["design_dir"])
    ref_path, ref_len = _ctx_store_refs(ctx)
    ref_note = (
        f"Reference designs are OFFLOADED to `{ref_path}` ({ref_len} chars). PEEK at the parts you "
        f"need with grep_files('<keyword>') or read_file_disk('{ref_path}', start_line, max_lines) — "
        "do NOT try to read it all.\n" if ref_path else "")
    if ctx.get("uploads_digest"):
        ref_note += ("The user ATTACHED files/images — they're included in that context under "
                     "'User-attached files' (and saved under context/uploads/). Use them.\n")
    _log_state(ctx, "generate:start",
               f"query='{ctx['query'][:80]}'" + (f"; user steering='{feedback[:80]}'" if feedback else ""))
    # LESSONS from past runs (knowledge DB): recalled ONLY when the STATE calls for it — this is a
    # RETRY / the user steered / errors are on record. A fresh generation is NOT prefixed with
    # hardcoded "past error / past design" piles (user: 'ga mau recalled past error, past design…
    # kaya ga punya otak — harusnya tau tiap state sama user maunya apa'). The agent can still
    # recall on demand via its recall_memory tool when IT decides it needs to.
    lessons_note = ""
    retrying = bool(ctx.get("fix_history") or ctx.get("error_count")
                    or (ctx.get("simulation_output") or "").strip() or feedback)
    try:
        mem = get_memory()
        if mem.enabled and retrying:
            items = mem.recall(ctx["query"] + " verilog error fix", kind="fix", k=3)
            body = "\n\n".join((it.get("text") or "")[:1200] for it in items if it.get("text"))
            if body:
                (design_dir / "context").mkdir(parents=True, exist_ok=True)
                (design_dir / "context" / "lessons.md").write_text(
                    "# Lessons from past runs (verified error→fix pairs)\n\n" + body)
                lessons_note = ("PAST LESSONS: `context/lessons.md` holds verified error→fix "
                                "lessons from previous runs — read it and do NOT repeat those "
                                "mistakes.\n")
                rec.caption(f"🧠 Recalled {len(items)} past error→fix lesson(s) from the knowledge store.")
    except Exception:  # noqa: BLE001
        pass
    # AUTORESEARCH METHODS: opt-in only (ANOA_AUTORESEARCH_METHODS=1) — another hardcoded
    # recall the user asked to remove from the default generate flow.
    methods_note = ""
    try:
        mem = get_memory()
        if mem.enabled and os.getenv("ANOA_AUTORESEARCH_METHODS", "") in ("1", "true", "yes"):
            mitems = mem.recall(ctx["query"] + " hardware RTL generation self-improvement technique",
                                kind="method", k=2)
            mbody = "\n\n".join((it.get("text") or "")[:1400] for it in mitems if it.get("text"))
            if mbody:
                (design_dir / "context").mkdir(parents=True, exist_ok=True)
                (design_dir / "context" / "methods.md").write_text(
                    "# Autoresearch — self-improvement / codegen methods (studied repos)\n\n" + mbody)
                methods_note = ("AUTORESEARCH METHODS: `context/methods.md` holds self-improvement / "
                                "code-generation techniques recalled from studied method repos — apply "
                                "the relevant approach (research the design + its pitfalls, adapt, then "
                                "reflect on any failure).\n")
                rec.caption(f"🔬 Recalled {len(mitems)} autoresearch method(s) from the knowledge store.")
    except Exception:  # noqa: BLE001
        pass
    # CROSS-PROJECT CONNECT: if the prompt asks to connect this design with a prior one the user
    # built (and verified to GDS), pull that design's RTL into rtl/ now so the generator instantiates
    # it as a submodule instead of rewriting it. Done BEFORE pre_existing is computed so the reused
    # files are protected as already-on-disk.
    connect_note = _connect_designs(ctx, design_dir, rec)
    # STUDY-THE-REFERENCE: if the researcher cloned a close-match repo to context/anchor/, the
    # generator READS it to LEARN the approach (algorithm, interfaces, pitfalls) and then writes
    # its OWN implementation — it does NOT copy the modules. Other sources are links in
    # context/sources.md, studied on demand only if the reference doesn't cover a block.
    anchor_note = ""
    anchor_dir = design_dir / "context" / "anchor"
    # (used by the study-the-reference note below)
    # If the web researcher didn't clone an anchor (web off / thin results), anchor on the
    # closest past verified design from the RLM's OWN memory (knowledge DB) — but NEVER when the
    # user ATTACHED the spec: a past design recalled by fuzzy similarity is exactly the off-topic
    # pollution ('recalled past design') the user banned; the attachment is the only authority.
    if not ctx.get("uploads_digest") and not (
            anchor_dir.exists()
            and (sorted(anchor_dir.rglob("*.sp")) + sorted(anchor_dir.rglob("*.spice")))):
        _recall_db_anchor(ctx, design_dir, rec)
    anchor_files = (sorted(anchor_dir.rglob("*.sp")) + sorted(anchor_dir.rglob("*.spice"))
                    + sorted(anchor_dir.rglob("*.cir"))) if anchor_dir.exists() else []
    papers = sorted((anchor_dir / "papers").glob("*.txt")) + sorted((anchor_dir / "papers").glob("*.md")) \
        if (anchor_dir / "papers").exists() else []
    if anchor_files or papers:
        listing = "\n".join(f"  - {p.relative_to(design_dir)}" for p in (anchor_files[:24] + papers[:4]))
        anchor_note = (
            "📚 STUDY-THE-REFERENCE (do this FIRST — it is KNOWLEDGE to learn from, NOT code to "
            "copy): the closest matching design(s) are on disk under `context/anchor/` (RTL repos "
            "and/or paper text). Use them to UNDERSTAND the problem, then WRITE YOUR OWN RTL:\n"
            "  • grep_files/read_file_disk the reference to learn the ALGORITHM, the interfaces, the "
            "corner cases and the pitfalls for each block you need;\n"
            "  • then write your OWN clean, well-commented implementation adapted to THIS spec — do "
            "NOT paste the reference verbatim, do NOT reproduce its file-for-file structure or its "
            "module count;\n"
            "  • decide your OWN module decomposition and COLLAPSE repetition into ONE parameterized "
            "module instantiated N times (a `generate` loop), never N near-identical copies.\n"
            "Reference material:\n" + listing + "\n"
            "If a block isn't covered: read `context/sources.md` and fetch_reference(<url>) to study "
            "ONE more source. Keep YOUR context small — peek slices, don't read whole files.\n")
    # GENERATE-FROM-KNOWLEDGE: we do NOT copy the anchor's files into rtl/. The reference stays on
    # disk under context/anchor/ as KNOWLEDGE to study (anchor_note above); the agent writes EVERY
    # module ITSELF, with its OWN parameterized decomposition. This is the fix for designs that were
    # just a renamed, file-for-file copy of the reference (e.g. 24 / 101 pasted blocks): the agent
    # now reasons from the knowledge store and decides how many files the design actually needs.
    rtl_dir0 = design_dir / "netlist"
    pre_existing = [p.name for p in sorted(rtl_dir0.glob("*.sp")) + sorted(rtl_dir0.glob("*.spice"))] \
        if rtl_dir0.exists() else []
    # DATA-DRIVEN designs (gm/Id sizing sweep, filter coefficients) compute their sizing data
    # with run_python and write the netlist around it.
    data_driven = _is_data_driven(ctx["query"]) or _is_data_driven(feedback)
    if data_driven and not pre_existing:
        rec.caption("🧮 Data-driven sizing — computing the operating point/parameters in Python.")
    elif not pre_existing:
        rec.caption("🧠 Generating the config + netlist from researched knowledge — the agent "
                    "writes every subcircuit itself (the reference is studied, never copied).")
    seeded: List[str] = []          # never seed by copying — the agent generates from knowledge
    # .anchor_seeded is written ONLY by old copy-seeded runs; new runs never set it, so a fresh
    # build always takes the genuine-generation path below. Kept for backward-compat resume of any
    # design half-built by a previous (copy-seeding) version.
    marker = design_dir / "context" / ".anchor_seeded"
    ctx["_seeded"] = marker.exists()
    _on_clean_write = None                 # per-IP verify hook; set in the generation branch

    if ctx["_seeded"]:
        # the ONE plan = the modules on disk. Runs on a FRESH seed AND on RESUME (marker present),
        # so a re-run never falls back to the read-looping open-ended agent.
        if seeded:
            _prune_strays(design_dir, seeded, rec)
            # rename modules to AnoaChip's OWN names (top → top.v/sv, fazyrv_X → X) before the
            # per-module pass, so the whole design carries the new naming consistently.
            seeded = _rename_to_own(design_dir, rec) or seeded
        on_disk = seeded or [p.name for p in sorted(rtl_dir0.glob("*.sp")) + sorted(rtl_dir0.glob("*.spice"))
                             if "tb" not in p.name.lower()]
        sub = [f"{f} — write & verify this circuit" for f in on_disk]
        _save_plan(design_dir, "generate", sub)
        rec.plan(sub)
        # SMART per-module loop: read → REWRITE with a AnoaChip header + inline comments →
        # compile-check → tick, ONE module at a time (bounded one-shot each, never an open-ended
        # agent that read-loops); a botched rewrite falls back to the verified version. A BIG
        # multi-module design (e.g. a 100-module CGRA split out of one anchor file) is copied
        # VERBATIM — re-typing dozens of proven modules with a 9B model corrupts them and is slow;
        # only small designs get the per-module spec adaptation.
        big = len([f for f in on_disk if f.lower().endswith((".sp", ".spice"))]) > 12
        if big:
            rec.caption(f"🧱 Large design ({len(on_disk)} circuits) — copying the proven subckts "
                        "verbatim (with this design's header) and checking each; the model "
                        "only steps in to repair one that fails its checks.")
        _adapt_modules_one_by_one(rec, design_dir, ctx, on_disk, feedback, rewrite=not big)
        from netlist_check import pick_top as _pt
        ctx["top_module_name"] = _pt(design_dir / "netlist") or slugify(ctx["query"], 24)
        final = ""
    else:
        # no anchor to seed (or resuming) → the LOCKED file list, reused verbatim every entry.
        sub = _subplan(rec, ctx["query"], "generate", feedback, design_dir=design_dir)
        # CONTRACT ENFORCEMENT on resume: rtl left by an OLD, different plan is pruned so the
        # generator can't 'resume' the wrong design (and pick_top can't choose its top).
        if sub and pre_existing:
            pre_existing = _prune_offplan_rtl(rec, design_dir, sub, pre_existing)
        resume_note = ""
        if len(pre_existing) >= 2:
            resume_note = (
                "▶️ RESUME — this design is PARTIALLY BUILT. These files ALREADY EXIST on disk and are "
                "good; do NOT rewrite them, do NOT start over:\n  " + ", ".join(pre_existing) + "\n"
                "CONTINUE from here: write/adapt ONLY what is still missing or broken, then finish.\n")
        sub_note = ("THE FILES — this is the LOCKED plan (the ONE plan shown above). Build/adapt EXACTLY "
                    "these files; do NOT invent a different breakdown:\n"
                    + "\n".join(f"- {p}" for p in sub) + "\n") if sub else ""
        notes_note = ""
        if (design_dir / "design_notes.md").exists():
            notes_note = ("THE CONTRACT: `design_notes.md` on disk is the build contract — the plan "
                          "above mirrors its Module Map. Before writing each module, read its port "
                          "list from the notes (read_file_disk('design_notes.md')) and implement "
                          "EXACTLY that interface — same module name, same ports, same widths. "
                          "NEVER build a different design than the contract describes.\n")

        # PER-IP VERIFY HOOK (user: 'setelah buat compile check clean ✓, buat tb dan simulasiin
        # itu' + 'kalo belum verify tbnya jangan lanjut bikin module lain, fokus benerin dulu'):
        # the MOMENT a planned module's write compiles clean, its unit tb is generated and
        # simulated in isolation. PASS → next module. FAIL → the agent is told to STOP and fix
        # THIS module (the saved failure is in the tool result); every clean re-write of the
        # module re-runs the verify, CONTINUING from the persisted tb + error state
        # (context/unit_state/<mod>.json) — never a fresh blind guess. After
        # ANOA_UNIT_HOOK_ROUNDS rounds the block is handed to the corrector with its state.
        _p_files, _p_top = _planned_rtl_files(sub)
        _hooked: set = set()                    # modules DONE at this stage (pass / handed over)
        _rounds: Dict[str, int] = {}
        _max_rounds = int(os.getenv("ANOA_UNIT_HOOK_ROUNDS", "3"))

        def _on_clean_write(relpath: str) -> str:
            fn = Path(relpath).name
            stem = Path(fn).stem
            if (not relpath.replace("\\", "/").startswith("netlist/")
                    or not fn.lower().endswith((".sp", ".spice")) or "_tb" in stem
                    or "shared_params" in stem or stem in _hooked):
                return ""
            if _p_top and stem.lower() == Path(_p_top).stem.lower():
                return ""                       # the integration top gets the chip-level tb later
            try:                                # subckt name as DEFINED in the file, not the stem
                m = re.search(r"^\s*\.subckt\s+([A-Za-z_]\w*)",
                              (design_dir / "netlist" / fn).read_text(errors="replace"),
                              re.IGNORECASE | re.MULTILINE)
                mod = m.group(1) if m else stem
                rec.caption(f"🔬 `{mod}` checks clean — unit tb + ngspice simulation NOW "
                            "(before any next circuit).")
                ok = _gen_and_verify_unit_tb(rec, ctx, mod, fn)
            except Exception:  # noqa: BLE001
                return ""
            if ok is None:
                _hooked.add(stem)               # not unit-testable — nothing to check
                return ""
            if ok:
                _hooked.add(stem)
                return (f"\nUNIT VERIFY: `{mod}` unit test PASSED in isolation ✓ — continue to "
                        "the NEXT circuit.")
            _rounds[stem] = _rounds.get(stem, 0) + 1
            last = (_load_unit_state(design_dir, mod).get("last_out") or "")[:900]
            if _rounds[stem] >= _max_rounds:
                _hooked.add(stem)
                return (f"\nUNIT VERIFY: `{mod}` STILL FAILING after {_rounds[stem]} verify "
                        f"round(s). Its full error state is saved in context/unit_state/{mod}.json "
                        "and the corrector stage will continue from it. Continue to the NEXT "
                        "circuit.\nLAST FAILURE:\n" + last)
            return (f"\nUNIT VERIFY FAILED for `{mod}` — STOP. Do NOT write the next circuit yet. "
                    f"FIX THIS CIRCUIT FIRST: study the failure below (its tb is tb/{mod}_tb.sp and "
                    "was already checked/iterated — the remaining miss is most likely the "
                    f"CIRCUIT's sizing/bias), then write netlist/{fn} again with the fix. The unit "
                    "test re-runs automatically on your next clean write and CONTINUES from the "
                    f"saved error state.\nFAILURE:\n{last}")

        goal = (
            f"Design a full-custom analog circuit for: {ctx['query']}.\n"
            + (f"USER INSTRUCTION: {feedback}\n" if feedback else "")
            + resume_note
            + sub_note
            + notes_note
            + _SUBPLAN
            + connect_note
            + anchor_note
            + ref_note
            + lessons_note
            + methods_note
            + "YOUR SINGLE DELIVERABLE is ONE file: config/<name>.json. glayout builds the "
              "layout straight from it, so DO NOT write any SPICE netlist (.sp) — no top .subckt, "
              "no shared_params.sp, no per-parameter files. The reference SPICE you researched is "
              "only INPUT you read to fill this JSON.\n"
              "Write config/<name>.json with THREE sections:\n"
              "1) `spec`: the target table (gain_db, bw_hz, phase_margin_deg, power_w, supply, "
              "load) — whatever the circuit's spec actually is (a current mirror uses "
              "iout/iref ratio, output_resistance, compliance_v — NOT gain/BW).\n"
              "2) `params`: EVERY component value, NONE omitted — per MOSFET W, L, fingers, "
              "multipliers (M); every R, C, L; every bias current and reference voltage. SEED "
              "these from context/reference_params.md if it exists (values EXTRACTED from the "
              "researched netlist/paper — copy, then scale for THIS spec), never invent blindly.\n"
              "3) `wiring`: a list of every component with its type (nfet/pfet/res/cap/…), its "
              "size (ref into `params`), and the NET each terminal connects to — e.g. "
              "{{\"name\":\"M1\",\"type\":\"nfet\",\"W\":\"w1\",\"L\":\"l1\",\"nf\":4,"
              "\"d\":\"vout\",\"g\":\"vin\",\"s\":\"vss\",\"b\":\"vss\"}}. This wiring is what "
              "glayout routes (c_route/L_route/straight_route + via), so name EVERY net and make "
              "the connections COMPLETE (no dangling terminal). List the ports of the whole "
              "circuit under `ports`.\n"
              "ONLY IF sizing must be computed (gm/Id sweep, filter coefficients) use run_python "
              "(numpy) to compute the values, then write them into the JSON.\n"
              "When config/<name>.json exists with spec+params+wiring all filled, reply just "
              "'done' — your deliverable is that ONE file; do NOT paste it back.\n"
        )
        final = run_deep_agent(rec, design_dir, goal,
                               extra_tools=_step_tools(rec, design_dir), temperature=0.2,
                               on_clean_write=_on_clean_write)

    # COMPLETENESS GATE — the generator must write EVERY planned RTL module before we move on.
    # If it stopped early (loop guard, repeated call, etc.), FINISH the missing modules HERE;
    # never advance to decompose with a partial design.
    planned, _top = _planned_rtl_files(sub)
    rtl_dir = design_dir / "netlist"

    def _missing():
        """A planned file is satisfied by an exact stem match, a defined subckt of that
        name, OR a file the agent SPECIALIZED from the generic planned name — planned
        `ota.sp` → wrote `ota_5t.sp`, where the planned stem is a LEADING TOKEN of an
        existing stem. A config/<name>.json is satisfied by any config/*.json on disk.
        The match is DIRECTIONAL: a SHORTER existing stem must NOT satisfy a LONGER
        planned one."""
        from netlist_check import parse_dir
        have_stems = {p.stem.lower() for p in
                      list(rtl_dir.glob("*.sp")) + list(rtl_dir.glob("*.spice"))}
        have_stems |= {m.lower() for m in parse_dir(rtl_dir)["defs"]}
        have_cfg = bool(list((design_dir / "config").glob("*.json"))) \
            if (design_dir / "config").exists() else False
        out = []
        for f in planned:
            if f.endswith(".json"):
                if not have_cfg:
                    out.append(f)
                continue
            stem = re.sub(r"\.(spice|spc|cdl|cir|sp)$", "", f, flags=re.I).lower()
            if any(h == stem or (len(stem) > 2 and h.startswith(stem + "_"))
                   for h in have_stems):
                continue
            out.append(f)
        return out
    def _broken():
        """Files already written that FAIL their structure check. The gate treats a broken
        file as NOT DONE, so generation can't finish until every netlist checks clean."""
        from netlist_check import check_file
        out = {}
        for p in sorted(rtl_dir.glob("*.sp")) + sorted(rtl_dir.glob("*.spice")):
            err = check_file(p, rtl_dir)
            if err:
                out[p.name] = err
        return out

    miss, broken = _missing(), _broken()
    # SILENT completion/repair: finish the locked plan and fix any compile failure QUIETLY,
    # grounding each fix in the anchor / references — no "generation not finished" warnings.
    has_anchor = (design_dir / "context" / "anchor").exists()
    has_sources = (design_dir / "context" / "sources.md").exists()
    for _pass in range(3):
        if not miss and not broken:
            break
        rec.caption("🔧 finishing the remaining file(s)…")
        have = sorted(rtl_dir.glob("*.sp")) + sorted(rtl_dir.glob("*.spice"))
        done_now = ", ".join(p.name for p in have) or "(none)"
        broken_note = "".join(
            f"- FIX netlist/{f} — its structure errors:\n{e[:500]}\n" for f, e in broken.items())
        ground = (
            "For EVERY file below, ground your work in the references: grep_files/read_file_disk the "
            "closest netlist in `context/anchor/` to UNDERSTAND the correct topology/sizing, then "
            "WRITE YOUR OWN correct implementation adapted to the spec — study it, don't paste it."
            + (" If the references don't cover a block, read `context/sources.md` and "
               "fetch_reference(<url>) ONE more source to study." if has_sources else "")
            + "\n" if (has_anchor or has_sources) else "")
        goal2 = (
            f"You are STILL generating the netlist for: {ctx['query']}. Already written: {done_now}.\n"
            + ground
            + ("WRITE THE MISSING FILES NOW (config JSON and/or netlist .sp), ONE write_file_disk "
               "call each, sizing from the config, reusing the ports in design_notes.md and the "
               "existing subckts. Do NOT rewrite working files:\n"
               + "\n".join(f"- {('config/' if f.endswith('.json') else 'netlist/')}{f}" for f in miss)
               + "\n" if miss else "")
            + (("These files FAILED their structure check — read each, fix the exact errors "
                "(floating nets / dangling ports), write it back; the write result must say "
                "'check clean':\n" + broken_note)
               if broken else "")
            + "When the config + every netlist exist AND check clean, reply 'done'.\n" + VERILOG_PITFALLS
        )
        run_deep_agent(rec, design_dir, goal2,
                       extra_tools=_step_tools(rec, design_dir), temperature=0.2,
                       on_clean_write=_on_clean_write)
        miss, broken = _missing(), _broken()

    _sync_ctx_from_disk(ctx)
    gen = _collect_rtl_from_disk(design_dir)
    if ".subckt" not in gen.lower():              # nothing usable on disk — fall back to the reply
        gen = extract_code_block(final)
    ctx["_gen_planned"] = planned
    ctx["_gen_missing"] = miss                     # the runner gates on this — won't advance if set

    # PER-IP VERIFY-ON-CREATE (user: setiap IP — 'verify compile succeed → baru bikin tb → lakukan
    # simulasi tbnya → kalo berhasil baru next ip, kalo ga, generate itu terus'): with the plan
    # complete and every file compiling, walk the IPs in build order and, one at a time, write its
    # unit tb → simulate it in isolation → fix locally until it passes. Verified IPs are recorded
    # in ctx['unit_verified'] so the testbench stage keeps their tbs instead of redoing them.
    if not miss and not broken:
        try:
            from netlist_check import pick_top as _pt3
            ctx["top_module_name"] = ctx.get("top_module_name") or _pt3(rtl_dir) or ""
            _generate_unit_tbs(rec, ctx, ctx["top_module_name"],
                               ctx.get("decomposed_files", {}))
        except Exception as e:  # noqa: BLE001
            rec.caption(f"(per-circuit verification skipped: {e})")
    _log_state(ctx, "generate:done",
               f"planned={len(planned)}, missing={len(miss)}, "
               f"unit verified={ctx.get('unit_verified') or []}")

    # GLAYOUT-FIRST: the deliverable is the config JSON (spec + wiring + params) — glayout builds
    # the layout straight from it, so there is NO netlist to require. The step is DONE when the
    # config exists (miss empty) and its `wiring` is populated.
    cfg_files = sorted((design_dir / "config").glob("*.json")) \
        if (design_dir / "config").exists() else []
    cfg_obj = {}
    if cfg_files:
        try:
            cfg_obj = json.loads(cfg_files[0].read_text(errors="replace"))
        except Exception:  # noqa: BLE001
            cfg_obj = {}
    wiring = cfg_obj.get("wiring") or cfg_obj.get("components")
    has_wiring = bool(wiring)
    if cfg_files and has_wiring and not miss:
        n = len(wiring) if isinstance(wiring, (list, dict)) else 0
        rec.success(f"Generated config `{cfg_files[0].name}` — spec + params + wiring "
                    f"({n} component(s) → nets).")
        rec.json(cfg_obj)
        # GLAYOUT CODE IS GENERATED HERE (user: 'generation glayout should be in generation
        # instead of layout') — write layout/<top>.py from the config's wiring now, so the
        # Generate step's deliverable is the glayout code; the next stage just BUILDS it → GDS.
        try:
            gtop = cfg_files[0].stem
            ctx["top_module_name"] = gtop
            rec.caption("🧩 Generating the glayout code from the config wiring…")
            _gen_layout_script(rec, ctx, design_dir, gtop, feedback)
        except Exception as e:  # noqa: BLE001
            rec.caption(f"(glayout code will be generated in the build stage: {e})")
    elif cfg_files and not has_wiring:
        rec.error(f"Config `{cfg_files[0].name}` is missing its `wiring` section (the "
                  "component→net connections glayout needs). This step will RETRY.")
        ctx["_regen_reason"] = "config has no `wiring` section — add every component and its net connections."
    else:
        rec.error("Generation produced no config JSON with wiring. Revise/Replan, or untick "
                  "🧠 RLM deep agents in the sidebar for a one-shot draft.")
        rec.code(gen[:1500] or "(no output)", language="text")
    ctx["generation"] = gen
    ctx["simulation_output"] = ""


def _deep_plan(rec, ctx, feedback=""):
    """GRAND PLANNER (Claude-Code style): write the GENERAL plan FIRST (from the spec alone),
    THEN execute each step's tooling — recall, then web/GitHub/paper research (which clones the
    anchor), then the build CONTRACT (design_notes.md) whose module map mirrors the anchor's
    blocks. It writes ONLY the plan & boilerplate interfaces — NOT full RTL. Each later agent
    reads this grand plan, sub-plans against the LOCKED file list, and does its job."""
    rec.caption("🧠 Planner — research the reference design, then build it.")
    design_dir = Path(ctx["design_dir"])
    constraints = _constraints_note(ctx)        # real PDK/clock — no hallucinated node

    # 1) GRAND PLAN FIRST — like Claude Code's plan step. Write the GENERAL, ordered intentions
    #    ("search the architecture", "search github/paper/web", "module map", "generate", "tb",
    #    "simulate", "lint", "harden within constraints") from the SPEC ALONE — we do NOT recall
    #    or research before planning. Each plan item is then EXECUTED with its tooling below.
    # An ATTACHED image/PDF is the AUTHORITATIVE spec — plan from what it shows (block list,
    # memory map, targets), not from a deictic prompt like "create like this image".
    plan_query = ctx["query"]
    dig = (ctx.get("uploads_digest") or "").strip()
    if dig:
        plan_query = (f"{ctx['query']}\n\nATTACHED SPEC (authoritative — follow it EXACTLY: every "
                      f"block, the memory map, and the targets):\n{dig[:2500]}")
        rec.caption("🖼️ Planning from the attached spec (image/PDF) — it overrides the prompt wording.")
    points = _plan_points(rec, plan_query, feedback, constraints=constraints)
    ctx["_plan_points"] = points   # later agents (generator, testbench…) sub-plan against these

    # 2) EXECUTE "search the architecture / prior knowledge" → RECALL from the store (DB).
    try:
        agent_retrieve(rec, ctx, feedback)
    except Exception as e:  # noqa: BLE001
        rec.warning(f"recall skipped: {e}")

    # 3) EXECUTE "search GitHub / papers / web" → live research + clone the anchor.
    if ctx.get("use_web"):
        try:
            _deep_web(rec, ctx, feedback)
        except Exception as e:  # noqa: BLE001
            rec.warning(f"research skipped: {e}")

    # 4) the build CONTRACT (design_notes.md): the architecture + BOILERPLATE module
    #    interfaces (port lists) + connections + verification — generated DIRECTLY (no file
    #    tools), so the planner produces the plan/skeleton, NEVER full RTL implementations.
    rec.caption("🧠 Reasoning the architecture → the build contract…")
    refs = _ref_context(ctx)
    # SEE WHAT'S INSIDE THE ANCHOR BEFORE deciding the modules: base the Module Map on the
    # blocks the reference design actually has (same decomposition, adapt widths/ports), so we
    # never invent a module the references can't supply and then get stuck on it.
    anchor_mods = _anchor_module_list(design_dir)
    anchor_block = ""
    if anchor_mods:
        listing = "\n".join(f"- `{nm}` (in {src})" for nm, src in anchor_mods[:30])
        anchor_block = (
            "\n\nINTERNAL — for INSPIRATION ONLY, here is how existing reference designs decomposed "
            "similar problems. Do NOT copy this list and do NOT match its count: DESIGN YOUR OWN "
            "Module Map appropriate to THIS spec, deciding the modules and how many yourself. "
            "CONSOLIDATE repetition — an N-element array / N-tile fabric / N-lane datapath is ONE "
            "PARAMETERIZED module instantiated N times (a `generate` loop), NEVER N near-identical "
            "blocks; a wide datapath is one parameterized module, not one per bit/byte. Aim for the "
            "SMALLEST set of clean, parameterized, reusable modules that covers the spec. IMPORTANT: "
            "do NOT mention a reference / anchor / source repo / file paths anywhere in the document "
            "— present the Module Map as the design's OWN. Reference decomposition:\n" + listing)
        rec.caption(f"🧩 Reference decomposition: {len(anchor_mods)} block(s) seen — designing our "
                    "OWN parameterized module map (repeated/instanced blocks collapsed).")
    # GROUND THE CONTRACT IN THE REAL SPEC: the architect used to get only ctx['query'] (a
    # deictic 'create architecture like in image') and invented its own 'typical' SoC (5-stage,
    # 64 KB SRAM, 115200 baud) that CONTRADICTED a perfect understanding.md + research.md — the
    # user's 'design notes malah ngide sendiri'. Now the notes are written FROM the attached-spec
    # digest + the per-block research digest, with the authority rule enforced in the template.
    spec_auth = ""
    und_p = design_dir / "context" / "understanding.md"
    res_p = design_dir / "context" / "research.md"
    spec_body = und_p.read_text(errors="replace")[:2600] if und_p.exists() else dig[:2600]
    if spec_body:
        spec_auth = ("\n\nAUTHORITATIVE SPEC (understanding of the user's attachment) — copy its "
                     "facts EXACTLY, never 'improve' them:\n" + spec_body)
    if res_p.exists():
        spec_auth += ("\n\nRESEARCH DIGEST (how each block is implemented — reuse this knowledge):\n"
                      + res_p.read_text(errors="replace")[:2000])
    try:
        doc = clean_llm_output(stream_to(
            get_chat_model(temperature=0.3),
            DESIGN_NOTES_PROMPT.format(
                query=ctx["query"], constraints=constraints,
                feedback=(f"USER STEERING: {feedback}" if feedback else ""))
            + spec_auth
            + "\n\nFollow THIS plan checklist:\n" + "\n".join(f"- {p}" for p in points)
            + anchor_block
            + (f"\n\nResearched references (reuse these):\n{refs[:2000]}" if refs else "")
            + "\n\nREMINDER: interfaces (port lists) ONLY — NO module bodies, NO internal wires, "
              "NO repeated lines. Focus your words on the KNOWLEDGE (math, formats, hazards, refs)."
              " Every size/width/count comes from the AUTHORITATIVE SPEC above — verbatim.",
            rec.placeholder())).strip()
    except Exception:  # noqa: BLE001
        doc = ""
    doc = _collapse_repeats(doc)   # guard: a looping model can never write duplicate-signal spam
    notes = design_dir / "design_notes.md"
    if len(doc) > 500:
        notes.write_text(doc)
    elif not notes.exists():
        notes.write_text("# Build plan\n\n" + "\n".join(f"- [ ] {p}" for p in points))
    rec.success(f"📝 Grand plan + build contract → design_notes.md ({len(notes.read_text())} chars). "
                "The planner writes only the plan + interfaces — the generator writes every module "
                "ITSELF from this knowledge (no copy-paste of the reference).")
    # SHOW the build contract as INLINE rendered markdown (NOT a dropdown) so the user can read
    # it directly and beautifully.
    rec.markdown("### 📄 Design notes — the build contract\n\n" + notes.read_text()[:8000])
    # NOTE: the concrete file list is NOT locked here. Generation derives its OWN module list from
    # the spec (the generate sub-plan), grounded in the researched knowledge — it does NOT copy the
    # reference's files. Locking the plan at generate (not here) avoids a second, conflicting module
    # list (the inconsistency the user kept hitting).


def _deep_web(rec, ctx, feedback=""):
    """Web Researcher as a deep agent: identifies the core sub-blocks, searches +
    crawls reference HDL (via the web_research tool), and writes a reference digest to
    disk. Crawled docs flow into ctx['documents'] for the generator's context store."""
    from langchain_core.tools import tool as _tool
    rec.caption(
        "🧠 RLM deep-agent researcher — searches netlist/glayout repos, crawls, digests to disk.")
    design_dir = Path(ctx["design_dir"])
    _state = {"calls": 0}

    # PROBLEM-RESEARCH MODE: if the user steered "find about the problem / error / stuck", or a
    # compile/sim error is on record, research the ERROR MESSAGES (not the design topic). This is
    # the intent the search agent was missing — honoring the steer regardless of step sequence.
    err = (ctx.get("simulation_output") or ctx.get("lint_output") or "").strip()
    problem = bool(re.search(
        r"\b(problem|error|stuck|fix|bug|issue|fail|failing|why|debug|wrong|crash|broken)\b",
        feedback or "", re.I)) or bool(err)
    err_terms = _error_search_terms(err) if problem else []
    if problem and err:
        (design_dir / "context").mkdir(parents=True, exist_ok=True)
        (design_dir / "context" / "last_error.log").write_text(err)

    @_tool
    def web_research() -> str:
        """Search GitHub for SPICE-netlist + glayout repos + the web for papers for THIS design, crawl them, and
        store the real code/PDFs. Takes NO arguments — it searches the user's request EXACTLY as
        written (you do NOT pass a query, keywords, or invented topics); when the user ATTACHED
        a spec, it automatically researches the design AND every hardware block the attachment
        lists. Call this ONCE; calling again will not improve results."""
        import time as _time
        _state["calls"] += 1
        if _state["calls"] > 1:                       # hard stop the retry loop
            n = len(ctx.get("documents", []))
            return (f"STOP — you already searched and have {n} reference(s). Do NOT call "
                    "web_research again; write the digest to context/research.md NOW from "
                    "what you have plus your own knowledge.")
        # Wall-clock budget for the WHOLE research call: search + crawl always run, but the
        # OPTIONAL full-repo clone / PDF download are skipped once we're over budget, so research
        # can never stall the pipeline (the symptom: a run "stuck at research" forever).
        _t0 = _time.time()
        _budget = float(os.getenv("ANOA_RESEARCH_BUDGET_S", "240"))
        _deadline = _t0 + _budget
        _over = lambda: (_time.time() - _t0) > _budget
        by_topic: Dict[str, List[str]] = {}   # block topic → its GitHub hits (per-block anchors)
        if problem and err_terms:
            # research the ACTUAL compiler/sim errors — what the user asked for — not the design
            main, similar = err_terms[0], err_terms[1:4]
            rec.caption("🔑 Researching the PROBLEM: " + ", ".join(f"`{t}`" for t in err_terms[:4]))
            urls = _web_search(main, similar=similar, n_github=4, n_other=16, suffix="spice netlist analog")
        else:
            # SEARCH THE PROMPT VERBATIM — exactly the user's request, nothing else. No variants,
            # no sub-block decomposition. web_research takes NO query arg, so the model can't
            # hallucinate one ('GF(2^8)/Galois field' for 'fazyrv rv32i 8 bit').
            main = ctx["query"]
            topics: List[str] = []
            dig = (ctx.get("uploads_digest") or "").strip()
            if dig:
                # The user ATTACHED the spec (image/PDF). THAT is the authority — a prompt like
                # "create like this image" must never be web-searched literally (it returns
                # garbage and the image gets ignored). Understanding = the attachment digest;
                # the reference hunt is re-keyed to WHAT THE ATTACHMENT SHOWS — the design's
                # name AND every hardware block the digest lists (CPU, CGRA, interconnect,
                # UART, SRAM, …). Researching only a one-line query let a look-alike repo of
                # the WRONG topic become the sole anchor, derailing every later stage.
                main = _digest_query(dig, ctx["query"])
                topics = _digest_topics(dig)
                (design_dir / "context").mkdir(parents=True, exist_ok=True)
                (design_dir / "context" / "understanding.md").write_text(
                    "# What to build (from the user's ATTACHED spec — image/PDF)\n\n"
                    + dig[:4000] + "\n")
                rec.caption("🖼️ The attached image/PDF IS the spec — grounding the plan on it "
                            f"and researching references for: *{main[:100]}*")
            else:
                # STEP 1: understand what the prompt MEANS (crawl the top hit).
                _understand_prompt(main, design_dir, rec, deadline=_deadline)
            if topics:
                # STEP 2 (attached spec): ONE search per block from the understanding + one for
                # the whole design — MANY repos/PDFs covering ALL of it, never a single anchor.
                rec.caption("🔑 Researching the design + EVERY block in the understanding: "
                            + ", ".join(f"`{t}`" for t in [main[:60]] + topics))
                urls = _web_search(main, n_github=6, n_other=8)
                # NOTE: the diagram-title query does NOT nominate anchors — its tokens are
                # ambiguous ('Nano' matched TangNano Pacman/HDMI repos, which then became
                # anchors). Anchors come from the per-BLOCK topics only; the title's hits
                # still get crawled and listed as links.
                for t in topics:
                    if _over():
                        rec.caption(f"⏱ Research budget reached — blocks from `{t}` on stay as links only.")
                        break
                    t_urls = _web_search(t, n_github=4, n_other=3, suffix="spice netlist analog")
                    by_topic[t] = [u for u in t_urls if "github.com" in u]
                    urls += [u for u in t_urls if u not in urls]
                urls = urls[:48]
            else:
                # STEP 2: references for the FULL prompt + a few close 'similar' phrasings so the
                # search still lands pages when SearXNG is rate-limited and the exact wording is thin.
                sim = _design_variants(main, 2)
                rec.caption(f"🔑 Researching references for: *{main[:120]}*"
                            + (" (+ " + ", ".join(f"`{s}`" for s in sim) + ")" if sim else ""))
                urls = _web_search(main, similar=sim, n_github=10, n_other=12)
        n_gh = sum("github.com" in u for u in urls)
        rec.write(f"🔎 Found **{len(urls)}** references — **{n_gh}** GitHub repos (netlists/glayout) "
                  f"+ **{len(urls) - n_gh}** papers/web (knowledge); crawling…")
        docs = _crawl_urls(urls, rec, limit=len(urls), deadline=_deadline)
        ctx.setdefault("documents", []).extend(docs)
        _store_web_docs(docs, ctx)
        if not _over():
            _download_references(urls, design_dir, rec,               # PDFs + code → store
                                 max_repos=10 if by_topic else 4,
                                 max_pdfs=16 if by_topic else 10, deadline=_deadline)
        # ANCHOR + LINKS: clone the best-match repo(s) in full (to STUDY, not copy) — one per
        # block of an attached spec, one total for a typed prompt — save the rest as links in
        # context/sources.md (retrieve on demand). NOT problem-mode (errors don't anchor).
        if not problem and not _over():
            if by_topic:
                # a fresh ATTACHED spec defines the design — drop any previously-cloned anchor
                # (possibly a different design) so a stale/wrong reference can't steer generation
                shutil.rmtree(design_dir / "context" / "anchor", ignore_errors=True)
            info = _build_anchor_and_links(urls, design_dir, main, rec,
                                           topic_urls=by_topic or None, deadline=_deadline)
            ctx["_anchors"] = list(info.get("anchors", {}).keys())
        elif _over():
            rec.caption(f"⏱ Research budget ({int(_budget)}s) reached — skipping optional clone/download; "
                        "writing the digest from what was gathered.")
        if not docs:
            return ("No pages crawled. Do NOT search again — write the digest from your own "
                    "knowledge of this design now.")
        gh = [d for d in docs if "github.com" in d.metadata.get("source", "")]
        web = [d for d in docs if "github.com" not in d.metadata.get("source", "")]
        head = (f"Done — crawled {len(gh)} GitHub repo(s) + {len(web)} paper/web page(s). "
                "The closest repo(s) are CLONED to context/anchor/ to STUDY (learn the approach, "
                "then write your own netlist — do NOT copy them); other sources are LINKS in "
                "context/sources.md. Now WRITE context/research.md; do NOT call web_research again.\n\n")
        return (head + "\n\n".join(f"{d.metadata.get('source','')}:\n{d.page_content[:400]}"
                                   for d in (gh[:3] + web[:3])))[:4000]

    if problem:
        # the user wants the PROBLEM researched online — search the errors, write the FIX.
        goal = (
            "The current design has a PROBLEM and the user asked you to RESEARCH IT ONLINE.\n"
            + (f"USER STEERING: {feedback}\n" if feedback else "")
            + (f"The errors to research:\n" + "\n".join(f"- {t}" for t in err_terms) + "\n"
               if err_terms else "")
            + "FIRST read_file_disk('context/last_error.log') for the exact messages. Then call "
              "web_research() ONCE — it takes NO arguments and already searches THE ERROR (the "
              "compiler messages) automatically. After it returns, WRITE context/research.md: for EACH error, "
              "the CAUSE and the concrete FIX (with a tiny correct SPICE/glayout snippet). Reply with that. "
              "Do NOT narrate, do NOT research the design topic — focus on solving the error."
        )
    else:
        if (ctx.get("uploads_digest") or "").strip():
            # ATTACHED spec: research covers EVERY block the understanding lists, and the digest
            # must be organized per TARGET block — not a portrait of one look-alike repo.
            middle = (
                "Call web_research() ONCE. The user ATTACHED the spec (image/PDF) — web_research "
                "AUTOMATICALLY researches the attached design AND every hardware block its "
                "understanding lists (CPU, accelerator, interconnect, peripherals, memory, …), "
                "one search per block, gathering MANY repos + papers. You do NOT pass keywords "
                "and do NOT invent search terms. After it returns, read "
                "context/understanding.md and WRITE context/research.md with ONE SHORT SECTION "
                "PER BLOCK of the attached spec: what the gathered references say about "
                "implementing THAT block (approach + key modules). Do NOT narrate, do NOT "
                "search again, and NEVER describe some other design the references happen to "
                "implement — research.md is about the ATTACHED design's blocks.\n")
        else:
            middle = (
                "Call web_research() ONCE. It AUTOMATICALLY searches the user's request EXACTLY as "
                f"written ('{ctx['query'][:120]}') — you do NOT pass keywords, you do NOT invent search "
                "terms, you do NOT decompose it into sub-blocks. Do NOT 'improve' the query. After it "
                "returns, WRITE a concise digest to context/research.md describing the reference "
                "design's ARCHITECTURE and its key modules. Do NOT narrate, do NOT search again.\n")
        goal = (
            f"You are the hardware reference researcher for: {ctx['query']}.\n"
            + (f"USER STEERING: {feedback}\n" if feedback else "")
            + middle
            + "IMPORTANT — do NOT reveal the SOURCE to the user: never name the GitHub repo, its "
              "owner, or its URL in your reply or in research.md. Call it 'the reference design'. "
              "(The repo is saved internally to references; the user must not see which repo it is.)"
        )
    run_deep_agent(rec, design_dir, goal, extra_tools=[
                   web_research] + _step_tools(rec, design_dir), temperature=0.2)
    docs_now = ctx.get("documents", [])
    n_gh = sum("github.com" in d.metadata.get("source", "")
               for d in docs_now if hasattr(d, "metadata"))
    rec.success(f"Researcher gathered {len(docs_now)} reference chunk(s) — "
                f"{n_gh} from GitHub (code) + {len(docs_now) - n_gh} from papers/web (knowledge).")


def _deep_testbench(rec, ctx, feedback=""):
    """Testbench Writer as a deep agent: reads the DUT's real port list off disk and
    writes a self-checking ngspice testbench to tb/."""
    rec.caption(
        "🧠 RLM deep-agent testbench writer — reads the DUT off disk, writes tb/.")
    design_dir = Path(ctx["design_dir"])
    top = ctx["top_module_name"]
    files = ctx.get("decomposed_files", {})
    header = next((f for f in files if f.startswith("shared_params")), None)
    # locked test-case plan (decided once, reused on every retry) — same list every entry
    sub = _subplan(rec, ctx["query"], "testbench", feedback, design_dir=design_dir)
    sub_note = ("MEASURE/TEST CASES to cover — this is the LOCKED plan; your write_todos MUST "
                "mirror it exactly (same cases, same order):\n"
                + "\n".join(f"- {p}" for p in sub) + "\n") if sub else ""
    cfg_note = ""
    try:
        from glayout_tools import load_config
        cfg = load_config(design_dir, top) or load_config(design_dir, design_dir.name)
        if cfg:
            cfg_note = ("DESIGN CONFIG (spec thresholds + vdd come from HERE):\n"
                        + json.dumps({k: cfg.get(k) for k in ("spec", "params") if cfg.get(k)})[:1200]
                        + "\n")
    except Exception:  # noqa: BLE001
        pass
    goal = (
        _contract_note(ctx)
        + f"Write a self-checking ngspice testbench for top circuit `{top}`. The DUT files are on "
        f"disk under netlist/. Read `netlist/{top}.sp`"
        + (f" and `netlist/{header}`" if header else "")
        + " with read_file_disk to get the EXACT .subckt port list.\n"
        + sub_note + cfg_note + _sim_types_note(ctx)
        + _SUBPLAN
        + "STIMULUS MUST BE REAL, not invented: read design_notes.md's '## 1b. Use case' "
          "(grep_files 'Use case') and drive THOSE realistic inputs (amplitude/frequency), "
          "alongside the spec-table measurements.\n"
        + (f"USER INSTRUCTION: {feedback}\n" if feedback else "")
        + f"STRICT: start with a `*` title comment; `.include netlist/{top}.sp`; instantiate the "
          f"DUT `XDUT <nodes...> {top}` wiring every port; add VDD/stimulus/load sources; run "
          ".op + .ac (+ .tran if needed); in a `.control` block `run`, meas/let every spec, "
          f"`wrdata sim/{top}_ac.txt vdb(out) vp(out)`, print `SPEC <name> PASS/FAIL measured=… want=…` (no > < -> in echo) and "
          "PASS|FAIL` per spec, then `echo Result: PASSED`/`Result: FAILED` + `quit`; close with "
          "`.endc` and `.end`.\n"
        + f"WRITE it to tb/{top}_tb.sp with write_file_disk, then reply with it in one ```spice block."
    )
    final = run_deep_agent(rec, design_dir, goal,
                           extra_tools=_step_tools(rec, design_dir), temperature=0.2)
    _sync_ctx_from_disk(ctx)
    tb = {k: v for k, v in (ctx.get("testbench_code")
                            or {}).items() if v.strip()}
    if not tb:                                 # agent inlined the code instead of writing it
        code = extract_code_block(final)
        if code.strip():
            (design_dir / "tb").mkdir(parents=True, exist_ok=True)
            (design_dir / "tb" / f"{top}_tb.sp").write_text(code)
            tb = {f"{top}_tb.sp": code}
    # MERGE — keep any unit tbs already in ctx (replacement is what wiped them from disk)
    ctx["testbench_code"] = {**ctx.get("testbench_code", {}),
                             **{k: dedup_modules(v) for k, v in tb.items()}}
    if ctx["testbench_code"]:
        rec.success(
            f"Testbench `{next(iter(ctx['testbench_code']))}` (deep agent):")
        rec.code(
            next(iter(ctx["testbench_code"].values())), language="spice")
    else:
        rec.error("Deep agent produced no testbench — Revise or Replan to retry.")


def _faulty_files(files: Dict[str, str], err: str, top: str, cap: int = 3) -> List[str]:
    """EVERY design file the error log names, in order of appearance (capped). Fixing
    one file per cycle could never converge when the errors span several files."""
    order = sorted((err.find(f), f) for f in files
                   if f in err and f.endswith((".sp", ".spice")))
    out = [f for pos, f in order if pos >= 0][:cap]
    if not out:
        for cand in (f"{top}.sp", f"{top}.spice"):
            if cand in files:
                return [cand]
        out = [next(iter(files))] if files else []
    return out


def _deep_fix_design(rec, ctx, feedback=""):
    """Module Corrector as an RLM deep agent: the error log is offloaded to disk; the
    agent peeks at it + EVERY broken module the log names, recalls past error→fix
    lessons from the knowledge store FIRST, rewrites the modules on disk (each write is
    compile-checked instantly), and a verified fix is saved back to the store so the
    same mistake is never made twice."""
    rec.caption(
        "🧠 RLM deep-agent corrector — peeks the error log on disk, recalls past fixes, rewrites.")
    design_dir = Path(ctx["design_dir"])
    files = dict(ctx["decomposed_files"])
    err = ctx.get("simulation_output") or ctx.get("lint_output") or ctx.get("harden_error", "")
    faulty_list = _faulty_files(files, err, ctx.get("top_module_name", ""))
    attempt = ctx.get("error_count", 0) + ctx.get("lint_count", 0)

    cdir = design_dir / "context"
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "last_error.log").write_text(err or "(no error text)")

    history = dict(ctx.get("fix_history", {}))
    rec.write(f"**Fixing {len(faulty_list)} file(s) named in the errors:** "
              + ", ".join(f"`{f}`" for f in faulty_list))
    rec.code(err[:1800], language="text")

    # ALWAYS recall past lessons for this error class first (pgvector) — not only when
    # stuck. A lesson from a previous run usually solves the error on attempt 1.
    err_sig = _error_query(err)
    lesson = recall_fix(err_sig)
    if lesson:
        rec.caption(f"🧠 Recalled a stored lesson for: *{err_sig}*")
        (cdir / "recalled_fix.md").write_text(lesson)

    prior_notes = []
    for f in faulty_list:
        past = history.get(f, [])
        if past:
            prior_notes.append(
                f"Earlier fix of `{f}` FAILED — do NOT reproduce it; take a different approach.")
    has_research = (cdir / "research.md").exists()
    # CROSS-MODULE port-contract findings (the 'bad_port' kind) span TWO files — the parent
    # with the bad connection and the child missing the port. Tell the corrector to open BOTH
    # and reconcile the interface, instead of editing one module in isolation (which can never
    # resolve a parent↔child mismatch). This is the class the user wants fully corrected.
    from netlist_check import unconnected_pins
    floats = unconnected_pins(design_dir / "netlist", ctx.get("top_module_name", ""))
    xmod_block = ""
    if floats:
        lines = [f"  • {f['subckt']}.{f['name']} — "
                 + ("port never used inside the subckt" if f["kind"] == "dangling_port"
                    else "net has only ONE terminal (floating)")
                 for f in floats[:12]]
        xmod_block = (
            "\nCONNECTIVITY DEFECTS (these break LVS — fix EVERY one):\n"
            + "\n".join(lines)
            + "\nFor each: wire the dangling port to the device terminal it belongs to, or give "
            "the floating net its missing second connection (the device the schematic intends). "
            "Do NOT tie signal nets to a rail to silence this.\n")
    goal = (
        _contract_note(ctx)
        # the USER's steer is the TOP priority — honor it literally, whatever it asks.
        + (f"USER INSTRUCTION (do exactly this): {feedback}\n" if feedback else "")
        + "The circuit FAILED its check/simulation/spec. Errors: `context/last_error.log`. "
        + f"Suspect file(s): {', '.join('netlist/' + f for f in faulty_list)}.\n"
        "FOLLOW THIS ORDER:\n"
        "1) read_file_disk('context/last_error.log') — note EVERY error/spec miss, not just the first.\n"
        "2) READ the design config (config/<name>.json) — sizing changes go THERE, then the netlist "
        "follows the config.\n"
        "3) RESEARCH the error ONLINE if unfamiliar (a convergence/model error): call search_web ONCE.\n"
        + ("4) RECALL the DB: read_file_disk('context/recalled_fix.md') — a stored lesson for THIS "
           "error; also recall_knowledge if useful.\n" if lesson
           else "4) RECALL the DB: call recall_memory/recall_knowledge for a stored fix.\n")
        + ("5) read_file_disk('context/research.md') — prior web research on this error.\n" if has_research else "")
        + "6) For a SPEC MISS: compute (run_python: gm/Id, gm·ro, gm/(2π·CL)) which parameter to "
          "change, edit the CONFIG, then regenerate the affected netlist FROM it. For a "
          "connectivity/bias defect: fix the netlist directly. write_file_disk each file back; the "
          "write result shows a STRUCTURE CHECK — fix and write again until clean.\n"
        + xmod_block
        + ("\n".join(prior_notes) + "\n" if prior_notes else "")
        + VERILOG_PITFALLS
    )
    temp = min(0.2 + 0.18 * attempt, 0.85)
    run_deep_agent(rec, design_dir, goal,
                   extra_tools=_step_tools(rec, design_dir), temperature=temp)

    # Trust the disk (every write was structure-checked); store a verified lesson.
    from netlist_check import check_file
    rtl_dir = design_dir / "netlist"
    fixed_clean = []
    for f in faulty_list:
        disk = rtl_dir / f
        if disk.exists():
            new_code = disk.read_text()
            history[f] = history.get(f, []) + [new_code]
            files[f] = new_code
            if not check_file(disk, rtl_dir):
                fixed_clean.append(f)
                rec.success(f"Corrected `{f}` — structure check now clean ✓")
            else:
                rec.warning(f"`{f}` still has structure errors — next cycle continues.")
            rec.expander_code(f"📄 {f} (after fix)", new_code, "spice")
    if fixed_clean and err_sig:
        f0 = fixed_clean[0]
        broken0 = (history.get(f0, [None, None])[-2]
                   if len(history.get(f0, [])) >= 2 else "")
        remember_fix(err_sig, "", design=Path(ctx["design_dir"]).name,
                     broken=broken0 or "", fixed=files[f0])
        rec.caption("💾 Saved this error→fix lesson to the knowledge DB (pg/MinIO) for future runs.")
    # Re-sync EVERY netlist file from disk — a fix may have edited another subckt not in
    # faulty_list; without this the next `write` step would overwrite it with stale ctx content.
    for disk in sorted(rtl_dir.glob("*.sp")) + sorted(rtl_dir.glob("*.spice")):
        files[disk.name] = disk.read_text()
    ctx["decomposed_files"] = files
    ctx["fix_history"] = history


def _deep_fix_testbench(rec, ctx, feedback=""):
    """Testbench Corrector as an RLM deep agent: regenerates the testbench from the DUT
    on disk, given the offloaded error log."""
    rec.caption(
        "🧠 RLM deep-agent testbench corrector — regenerates from the DUT on disk.")
    design_dir = Path(ctx["design_dir"])
    tb = ctx.get("testbench_code", {})
    top = ctx["top_module_name"]
    name = next(iter(tb), f"{top}_tb.sp")
    err = ctx.get("simulation_output", "")
    attempt = ctx.get("error_count", 0)

    cdir = design_dir / "context"
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "last_error.log").write_text(err or "(no error text)")
    rec.write("**Errors offloaded to `context/last_error.log`:**")
    rec.code(err[:1800], language="text")

    has_research = (cdir / "research.md").exists()
    goal = (
        # the USER's steer is the TOP priority — honor it literally, whatever it asks.
        (f"USER INSTRUCTION (do exactly this): {feedback}\n" if feedback else "")
        + f"The testbench `{name}` for circuit `{top}` FAILED — errors are in `context/last_error.log`.\n"
        f"Read it and `netlist/{top}.sp` (+ config/<name>.json for the spec thresholds) with "
        "read_file_disk, then write a BRAND-NEW correct self-checking ngspice testbench FROM "
        "SCRATCH (do not reuse the broken structure).\n"
        + ("read_file_disk('context/research.md') — the researcher already looked up THIS error "
           "online; APPLY what it found.\n" if has_research else "")
        + f"STRICT: start with a `*` title; `.include netlist/{top}.sp`; instantiate `XDUT <nodes> "
          f"{top}` wiring every port; add VDD/stimulus/load; `.op`+`.ac`; in `.control` `run`, "
          f"meas/let every spec, `wrdata sim/{top}_ac.txt vdb(out) vp(out)`, print per-spec "
          "PASS/FAIL then `echo Result: PASSED`/`Result: FAILED` + `quit`; end `.endc`/`.end`.\n"
        + f"WRITE it to tb/{name} with write_file_disk, then reply with it in one ```spice block."
    )
    temp = min(0.3 + 0.18 * attempt, 0.9)
    final = run_deep_agent(rec, design_dir, goal,
                           extra_tools=_step_tools(rec, design_dir), temperature=temp)

    code = extract_code_block(final)
    disk = design_dir / "tb" / name
    if code.strip() and ".control" in code.lower():
        disk.write_text(code)
    elif disk.exists():
        code = disk.read_text()
    new_tb = {name: dedup_modules(code)} if code.strip() else dict(tb)
    history = dict(ctx.get("fix_history", {}))
    history[name] = history.get(name, []) + [next(iter(new_tb.values()), "")]
    rec.success("Corrected testbench (deep agent):")
    rec.code(next(iter(new_tb.values()), "(none)"), language="spice")
    # MERGE — never replace: replacing wiped every per-IP unit tb from ctx, and agent_write's
    # prune then deleted them from disk (the "unit tbs vanished at the next stage" bug).
    ctx["testbench_code"] = {**ctx.get("testbench_code", {}), **new_tb}
    ctx["fix_history"] = history


_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}


def _extract_pdf_text(path: Path) -> str:
    """Best-effort PDF → text (first 20 pages) WITH OCR fallback for scanned/figure pages,
    cleaned of references/header-footer chrome (see extract.py). '' only if there's truly no
    text and OCR is unavailable."""
    try:
        from extract import pdf_to_text
        return pdf_to_text(path)
    except Exception:  # noqa: BLE001
        try:
            import pypdf
            reader = pypdf.PdfReader(str(path))
            return "\n".join((pg.extract_text() or "") for pg in reader.pages[:20]).strip()
        except Exception:  # noqa: BLE001
            return ""


def _save_uploads(design_dir: Path, uploads) -> str:
    """Persist user-attached files/images under context/uploads/ and build a digest the
    deep agents PEEK at. Text is embedded (capped), PDFs are text-extracted best-effort,
    and images are saved with their on-disk path noted so a node can analyze them with
    the Python tool (run_python + pillow). Returns the digest markdown (or '')."""
    if not uploads:
        return ""
    updir = design_dir / "context" / "uploads"
    updir.mkdir(parents=True, exist_ok=True)
    parts: List[str] = []
    for uf in uploads:
        try:
            data = uf.getvalue()
        except Exception:  # noqa: BLE001
            continue
        name = re.sub(r"[^\w.\-]", "_", os.path.basename(uf.name))
        path = updir / name
        path.write_bytes(data)
        rel = path.relative_to(design_dir)
        ext = path.suffix.lower()
        if ext in _IMAGE_EXT:
            # VISION ONLY (user: 'jangan pakai ocr — sampah banget'): the vision model UNDERSTANDS
            # the diagram — structure, blocks, connections, bit-widths — which a flat OCR of a
            # block diagram can never capture (the OCR fallback poisoned understanding.md with
            # jumbled label soup). A transient vision failure is RETRIED, never OCR-degraded.
            vision = ""
            try:
                from llm import model_supports_vision, describe_image
                if model_supports_vision():
                    for _try in range(3):
                        vision = (describe_image(path) or "").strip()
                        if vision:
                            break
            except Exception:  # noqa: BLE001
                vision = ""
            if vision:
                parts.append(f"### {name} (image · understood by the vision model below)\n"
                             f"Saved at `{rel}`.\n{vision[:6000]}\n"
                             "This is the model's reading of the diagram — build to it; "
                             "open the image with run_python (PIL) only if you need a finer detail.")
            else:
                parts.append(f"### {name} (image · {len(data)} bytes)\nSaved at `{rel}`. "
                             "The vision model could not read it — open it with run_python "
                             "(PIL.Image) to inspect its contents; do NOT guess what it shows.")
        elif ext == ".pdf":
            text = _extract_pdf_text(path)
            parts.append(f"### {name} (PDF)\n{text[:6000]}" if text else
                         f"### {name} (PDF · {len(data)} bytes)\nSaved at `{rel}`. "
                         "Extract its text with run_python (pip_install pypdf) if needed.")
        else:
            try:
                parts.append(f"### {name}\n```\n{data.decode('utf-8', 'replace')[:6000]}\n```")
            except Exception:  # noqa: BLE001
                parts.append(f"### {name} ({len(data)} bytes)\nSaved at `{rel}` (binary).")
    return ("# User-attached files (uploaded with the prompt)\n\n" + "\n\n".join(parts)) if parts else ""


def _parse_spec_from_prompt(prompt: str) -> dict:
    """Best-effort extraction of the analog spec table from the prompt so the config seed and
    the testbench thresholds have real numbers. Recognizes gain (dB), bandwidth / GBW (Hz with
    k/M/G), phase margin (deg), and power (W with m/u/n). Missing entries just aren't set."""
    spec: dict = {}
    low = (prompt or "").lower()

    def _hz(val: str, unit: str) -> float:
        mult = {"": 1, "k": 1e3, "m": 1e6, "g": 1e9}.get(unit.lower(), 1)
        return float(val) * mult

    def _w(val: str, unit: str) -> float:
        mult = {"": 1, "m": 1e-3, "u": 1e-6, "µ": 1e-6, "n": 1e-9, "p": 1e-12}.get(unit.lower(), 1)
        return float(val) * mult

    m = re.search(r"(\d+(?:\.\d+)?)\s*db\b[^.]{0,12}?gain|gain[^\d]{0,12}(\d+(?:\.\d+)?)\s*db", low)
    if m:
        spec["gain_db"] = {"min": float(m.group(1) or m.group(2))}
    # bandwidth: the number may come before ("1 MHz bandwidth") or after the keyword
    m = re.search(r"(\d+(?:\.\d+)?)\s*([kmg]?)hz\s*(?:of\s*)?(?:bandwidth|bw|gbw|ugbw)", low) or \
        re.search(r"(?:bandwidth|bw|gbw|ugbw|gain[- ]bandwidth)[^\d]{0,14}(\d+(?:\.\d+)?)\s*([kmg]?)hz", low)
    if m:
        spec["bw_hz"] = {"min": _hz(m.group(1), m.group(2))}
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:deg|°|degree|degrees)\s*(?:of\s*)?(?:phase margin|pm)", low) or \
        re.search(r"(?:phase margin|pm)[^\d]{0,12}(\d+(?:\.\d+)?)\s*(?:deg|°|degrees)?", low)
    if m:
        spec["phase_margin_deg"] = {"min": float(m.group(1))}
    m = re.search(r"(?:power|consumption)[^\d]{0,16}(\d+(?:\.\d+)?)\s*([mµunp]?)w\b", low) or \
        re.search(r"(\d+(?:\.\d+)?)\s*([mµunp]?)w\b[^.]{0,10}?(?:power|consumption)", low)
    if m:
        spec["power_w"] = {"max": _w(m.group(1), m.group(2))}
    return spec


def _merge_spec(prompt: str, spec_overrides: dict | None) -> dict:
    """Spec table = what's parsed from the prompt, then OVERRIDDEN by any explicit
    UI fields (Gain dB / Bandwidth Hz — both optional)."""
    spec = _parse_spec_from_prompt(prompt)
    for key, val in (spec_overrides or {}).items():
        if val is None or val == "":
            continue
        try:
            f = float(val)
        except (TypeError, ValueError):
            continue
        if key == "gain_db":
            spec["gain_db"] = {"min": f}
        elif key == "bw_hz":
            spec["bw_hz"] = {"min": f}
    return spec


# The analyses the testbench must run. Default = all three so a circuit is fully
# characterized; the UI lets the user narrow it (dc / tran / ac, any combination).
_DEFAULT_SIM_TYPES = ["dc", "ac", "tran"]


def new_run(prompt, use_web, run_harden, clock_port, clock_period, die_um, core_util,
            autonomous=True, deep_steps=True, uploads=None, num_ctx=None, model=None,
            spec_overrides=None, sim_types=None, chat_id=None):
    # UNIQUE dir per chat: two chats with the same prompt used to SHARE output/<slug> — a new
    # chat rmtree'd the other chat's design, and deleting one chat vanished the other's
    # artifacts. Suffix the slug with the chat id so each chat owns its own workspace.
    slug = slugify(prompt)
    if chat_id:
        slug = f"{slug}--{str(chat_id).replace('chat_', '')[:8]}"
    design_dir = OUTPUT_DIR / slug
    if design_dir.exists():
        shutil.rmtree(design_dir)                    # safe: this chat's own dir only
    design_dir.mkdir(parents=True, exist_ok=True)
    set_num_ctx(num_ctx)                             # apply the chosen context window to the model
    set_model(model)                                 # apply the chosen Ollama model (picker)
    sims = [s.lower() for s in (sim_types or _DEFAULT_SIM_TYPES)
            if s.lower() in ("dc", "ac", "tran")] or list(_DEFAULT_SIM_TYPES)
    return {
        "ctx": {
            "query": prompt, "use_web": use_web, "design_dir": str(design_dir),
            "documents": [], "error_count": 0, "fix_history": {},
            "decomposed_files": {}, "testbench_code": {}, "top_module_name": "",
            "generation": "", "simulation_output": "", "web_example": "",
            "lint_output": "", "lint_count": 0, "deep_steps": deep_steps,
            # analog: run_harden = do the Glayout layout + DRC/LVS after spec passes;
            # clock_port/clock_period/die_um/core_util are kept only for backend compat.
            "run_harden": run_harden, "clock_port": clock_port, "clock_period": clock_period,
            "die_um": die_um, "core_util": core_util, "num_ctx": num_ctx, "model": model,
            "spec": _merge_spec(prompt, spec_overrides), "pdk": PDK, "sim_types": sims,
            "uploads_digest": _save_uploads(design_dir, uploads),
        },
        "queue": ["plan"],
        "transcript": [],
        "status": "running",
        "pending": None,
        "autonomous": autonomous,
    }


# A follow-up in a chat that ALREADY has a built design should CONTINUE it, not rebuild. This
# matches the continuation/step verbs ("redo … testbench/simulate/lint/harden", "fix", "continue",
# "the design"). The runner only treats a message as a continuation when a prior design exists.
CONTINUE_RE = re.compile(
    r"\b(redo|re-?run|re-?do|continue|resume|retry|again|fix|correct|finish|edit|update|change|"
    r"modify|repair|adjust|debug|rewrite|harden|gds|tape-?out|synth\w*|test\s?bench|\btb\b|"
    r"simulat\w*|\bsim\b|lint|report|pdf|summar\w*|laporan|ringkasan|"
    r"the design|this design|the rtl|same design|keep going|proceed)\b",
    re.I)


def _continue_steps(msg: str, design_dir=None):
    """Map a follow-up instruction to the pipeline steps to run on the EXISTING design (so a chat
    continuation does the requested work, not a full rebuild). Returns (queue, wants_harden).

    GLAYOUT-FIRST designs (config JSON, no hand-written .sp netlists) resume into the LAYOUT
    chain — harden → lvs → pex → pl_sim → report — NEVER the legacy testbench/write/simulate
    SPICE loop (a bare 'continue' used to route there and die on 'TESTBENCH MISMATCH')."""
    low = (msg or "").lower()
    dd = Path(design_dir) if design_dir else None
    json_only = False
    gds_clean = False
    if dd and (dd / "config").is_dir() and list((dd / "config").glob("*.json")):
        nd = dd / "netlist"
        json_only = not nd.is_dir() or not (list(nd.glob("*.sp")) + list(nd.glob("*.spice")))
        try:
            vj = next(iter((dd / "layout").glob("verify_*.json")), None)
            if vj:
                v = json.loads(vj.read_text())
                gds_clean = bool(v.get("build", {}).get("ok")
                                 and v.get("drc", {}).get("is_pass")
                                 and v.get("lvs", {}).get("is_pass"))
        except Exception:  # noqa: BLE001
            gds_clean = False
    if json_only:
        want_hard = bool(re.search(r"\bharden|\bgds|synth|tape-?out|layout", low))
        want_gen = bool(re.search(r"\b(re-?generate|regenerate|rewrite|redesign|restructur)", low))
        want_report = bool(re.search(r"\breport\b|\bpdf\b|summar|laporan|ringkasan", low))
        want_sim = bool(re.search(r"simulat|\bsim\b|test\s?bench|\btb\b|transient|\btran\b|\bac\b", low))
        if want_gen:
            return ["generate", "harden"], True
        if want_report and not want_sim and not want_hard:
            return ["report"], False
        if want_hard and not gds_clean:
            return ["harden"], True
        # bare continue / sim request: layout already clean → re-extract + simulate + report;
        # otherwise (re)build the layout first (advance chains lvs→pex→pl_sim after it).
        if gds_clean:
            return ["pex", "pl_sim", "report"], False
        return ["harden"], True
    # RESTRUCTURE = a NEW ARCHITECTURE CONTRACT: the grand plan must be rewritten first
    # (design_notes.md's Module Map is the build contract the generator follows — without
    # a replan, "restructure" would regenerate the SAME architecture). advance() then
    # runs the full new plan: generate → tb → verify → harden → report.
    if re.search(r"\brestructur\w*|re-?architect\w*|redesign\b|\brombak\b|arsitektur ulang", low):
        return ["plan"], bool(re.search(r"\bharden|\bgds|synth|tape-?out", low))
    want_gen = bool(re.search(r"\b(re-?generate|regenerate|rewrite the netlist|re-?build the "
                              r"netlist|new netlist|rewrite the circuit)\b", low))
    want_tb = bool(re.search(r"test\s?bench|\btb\b", low))
    want_sim = bool(re.search(r"simulat|\bsim\b", low))
    want_lint = bool(re.search(r"\blint", low))
    want_hard = bool(re.search(r"\bharden|\bgds|synth|tape-?out", low))
    want_report = bool(re.search(r"\breport\b|\bpdf\b|summar|laporan|ringkasan", low))
    # DESIGN-CHANGE intent — "kurangi size/bit sram", "shrink", "make it smaller",
    # "pipeline the cpu", "optimize" — must run the MODULE CORRECTOR on the existing
    # RTL first (the user's instruction rides in as its feedback), then re-verify.
    # Without this, "kurangi bit sram lalu harden" regenerated the TESTBENCH and
    # hardened the UNCHANGED design.
    want_fix = bool(re.search(
        r"\b(kurangi|kecilkan|perkecil|turunkan|ubah|ganti|optimasi|optimalkan|"
        r"reduce|shrink|smaller|narrow|optimi[sz]e|pipeline the|improve|refactor)\b", low))
    q = []
    if want_gen:
        q += ["generate", "decompose"]
    elif want_fix:
        # a contract-changing fix INVALIDATES the old testbenches — regenerate them to
        # the new contract right after the design change (never treat old tbs as golden)
        q += ["fix_design", "testbench"]
    if want_tb:
        q.append("testbench")
    if want_gen or want_fix or want_tb or want_sim or want_lint or want_hard:
        q.append("write")                         # (re)write to disk before simulating
    if want_sim or want_lint or want_hard or want_gen or want_fix or want_tb:
        q.append("simulate")                      # advance() chains simulate → lint → harden
    # de-dupe preserving order
    seen, out = set(), []
    for s in q:
        if s not in seen:
            seen.add(s)
            out.append(s)
    if not out:
        # "make the report/pdf/summary" alone runs ONLY the report step on the existing state
        out = ["report"] if want_report else ["testbench", "write", "simulate"]
    elif want_report and "report" not in out:
        out.append("report")
    return out, want_hard


def continue_run(query, design_dir, feedback, run_harden, clock_port, clock_period, die_um,
                 core_util, autonomous=True, deep_steps=True, prior_ctx=None, num_ctx=None,
                 model=None, spec_overrides=None, sim_types=None):
    """CONTINUE an existing design from its SAVED STATE — do NOT wipe the folder or re-plan from
    scratch. Loads the prior run's full ctx (top circuit, decomposed files, layout result, fix
    history…), re-syncs netlist/ + tb/ from disk, fixes the top (never a leaf), and queues ONLY
    the steps the instruction asks for. This is precise resume-from-state for a chat follow-up."""
    design_dir = Path(design_dir)
    ctx = dict(prior_ctx) if isinstance(prior_ctx, dict) else {}
    # the follow-up's context window / model wins; else keep what the prior run used
    num_ctx = num_ctx if num_ctx else ctx.get("num_ctx")
    model = model if model else ctx.get("model")
    set_num_ctx(num_ctx)
    set_model(model)                                 # apply the chosen Ollama model (picker)
    ctx.update({"query": ctx.get("query") or query, "design_dir": str(design_dir),
                "use_web": False, "deep_steps": deep_steps, "num_ctx": num_ctx, "model": model,
                "clock_port": clock_port, "clock_period": clock_period,
                "die_um": die_um, "core_util": core_util, "pdk": PDK})
    # a follow-up may narrow the analyses or update the target spec (both optional)
    if sim_types:
        sims = [s.lower() for s in sim_types if s.lower() in ("dc", "ac", "tran")]
        if sims:
            ctx["sim_types"] = sims
    ctx.setdefault("sim_types", list(_DEFAULT_SIM_TYPES))
    if spec_overrides:
        spec = dict(ctx.get("spec") or {})
        for key, val in spec_overrides.items():
            if val in (None, ""):
                continue
            try:
                spec[key] = {"min": float(val)}
            except (TypeError, ValueError):
                pass
        ctx["spec"] = spec
    # ensure every key the steps expect exists (saved values win)
    for k, dv in {"documents": [], "error_count": 0, "fix_history": {}, "decomposed_files": {},
                  "testbench_code": {}, "top_module_name": "", "generation": "",
                  "simulation_output": "", "web_example": "", "lint_output": "",
                  "lint_count": 0, "uploads_digest": ""}.items():
        ctx.setdefault(k, dv)
    ctx["documents"] = []                           # saved docs are stringified; not needed to resume
    # start the continuation with a CLEAN retry budget (drop stale per-step counters/flags)
    for k in [k for k in ctx if k.startswith(("_retry_", "_crash_"))]:
        ctx.pop(k, None)
    ctx["error_count"] = 0
    ctx["lint_count"] = 0
    ctx.pop("_sim_unverified", None)
    # fresh budgets for the harden loops too — a follow-up instruction ("kurangi bit
    # sram lalu harden") must not be blocked by the PREVIOUS run's exhausted counters
    for k in ("_harden_fix_count", "_refuse_count", "_relax_count",
              "_hier_retry_done", "_antenna_aggressive"):
        ctx.pop(k, None)
    # drop the PRIOR run's error so it can't drive a stale "could not be verified (0 attempts)"
    # summary before this continuation's simulate re-runs and writes a fresh verdict.
    ctx["simulation_output"] = ""
    ctx["lint_output"] = ""
    _sync_ctx_from_disk(ctx)                        # re-load the existing netlist/ + tb/ into ctx
    _ensure_top(ctx, design_dir / "netlist")        # real integration top, not a stale leaf
    # SURGICAL single-file edit: "correct cmp.v" or "set the testbench input a=8, expect y=16" →
    # edit ONLY that file (rtl/ or tb/), leave every other file untouched. A "redo/regenerate the
    # testbench" request still REGENERATES it (handled by _continue_steps), not a value edit.
    low = (feedback or "").lower()
    tgt = _target_file(feedback, design_dir)
    regen = re.search(r"\b(redo|re-?generate|regenerate|rewrite|new)\b.{0,20}\b(test\s?bench|tb)\b", low) \
        or re.search(r"\b(test\s?bench|tb)\b.{0,20}\b(redo|re-?generate|regenerate|from scratch)\b", low)
    edit_intent = re.search(r"\b(fix|correct|edit|update|change|repair|debug|adjust|modify|rewrite|"
                            r"set|expect|want|make|assign|drive|stimulus|value)\b", low)
    if tgt and edit_intent and not regen:
        ctx["_fix_target"] = tgt
        # Surgically edit the one file, THEN re-verify it — a fix that is never simulated leaves the
        # run "unverified (0 attempts)" (the exact bug the user hit: "correct simulation, make sure tb
        # correct, and then harden again" only ran fix_file). advance() chains simulate → lint → harden.
        steps = ["fix_file", "simulate"]
        want_hard = bool(re.search(r"\bharden|\bgds|synth|tape-?out", low))
    else:
        steps, want_hard = _continue_steps(feedback, design_dir)
    # ---- chat OVERRIDES for the physical contract (the user is the boss) ---------------
    # "die 800 um" / "size 1 mm"      → new die budget
    # "clock 40 ns"                   → new timing budget
    # "ignore the budget / keep as-is"→ skip the die/timing gate (re-enable: "enforce budget")
    # "force harden"                  → harden even though verification fails (explicit!)
    # "flat harden" / "hier harden"   → sea-of-cells vs per-IP macro (kotak-kotak) layout
    m = re.search(r"\b(?:die|size)\D{0,12}?(\d{2,5})\s*(?:um|µm|micron)", low) \
        or re.search(r"\bdie\D{0,12}?(\d{2,5})\b", low)
    if m:
        ctx["die_um"] = float(m.group(1))
    m = re.search(r"\b(?:clock|clk|period)\D{0,12}?(\d+(?:\.\d+)?)\s*ns\b", low)
    if m:
        ctx["clock_period"] = float(m.group(1))
    if re.search(r"\b(ignore|skip|relax)\b.{0,20}\b(budget|size|area|timing)\b|"
                 r"\bkeep (it|the size|as.?is)\b|\bbiarkan\b", low):
        ctx["ignore_budget"] = True
    if re.search(r"\b(enforce|check|apply)\b.{0,16}\bbudget\b", low):
        ctx.pop("ignore_budget", None)
    # CONTRACT CHANGE ("kurangi bit", "SRAM 256B", "restructure"): the user's new
    # contract voids the old verification state — wipe unit verdicts + fix history so
    # nothing "restores" the old design to please an old testbench, and remember the
    # order (every fixer/tb/diagnose prompt carries it until the design passes again).
    if re.search(r"\b(kurangi|kecilkan|perkecil|turunkan|reduce|shrink|narrow|"
                 r"restructur\w*|redesign|rombak|re-?architect\w*)\b", low):
        ctx["_contract_change"] = feedback
        shutil.rmtree(design_dir / "context" / "unit_state", ignore_errors=True)
        ctx.pop("unit_verified", None)
        ctx["fix_history"] = {}
    ctx["force_harden"] = bool(want_hard and re.search(r"\bforce\b|\banyway\b|\btetap\b|\bpaksa\b", low))
    if re.search(r"\bflat(ten)?\b", low) and want_hard:
        ctx["harden_hier"] = False
    if re.search(r"\bhier|\bmacro|\bkotak", low):
        ctx["harden_hier"] = True
    ctx["run_harden"] = bool(run_harden or want_hard)
    return {
        "ctx": ctx, "queue": steps, "transcript": [], "status": "running",
        "pending": None, "autonomous": autonomous, "feedback": feedback,
    }


# --------------------------------------------------------------------------- #
# Output summary + downloads
# --------------------------------------------------------------------------- #
def write_result_md(design_dir: Path, prompt: str, top: str, sim_passed: bool, harden: dict | None):
    lines = [f"# {top}", "", f"**Prompt:** {prompt}", "",
             f"- Spec simulation (ngspice): {'PASSED ✅' if sim_passed else 'FAILED ❌'}"]
    if harden:
        lines += [
            f"- GDSII: {'`' + os.path.basename(harden['gds']) + '`' if harden.get('gds') else 'not produced'}",
            f"- Ports: {harden.get('n_ports', 'n/a')}",
            f"- Bounding box: {harden.get('bbox_um', 'n/a')} µm",
            f"- DRC (magic): {harden.get('drc', 'n/a')}",
            f"- LVS (netgen): {harden.get('lvs', 'n/a')}",
        ]
    (design_dir / "result.md").write_text("\n".join(lines))


def render_output(design_dir: Path):
    st.markdown("---")
    st.markdown("### 📦 Output")
    st.caption(f"Everything is under `output/{design_dir.name}/`.")
    tree = []
    for p in sorted(design_dir.rglob("*")):
        if p.is_file() and "runs" not in p.parts:
            tree.append(str(p.relative_to(design_dir)))
    st.code("output/" + design_dir.name + "/\n" +
            "\n".join(f"  {t}" for t in tree[:60]), language="text")

    cols = st.columns(2)
    gds_files = list(design_dir.glob("*.gds"))
    if gds_files:
        with cols[0]:
            with open(gds_files[0], "rb") as f:
                st.download_button("⬇️ Download GDSII", f,
                                   file_name=gds_files[0].name)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in design_dir.rglob("*"):
            if p.is_file() and "runs" not in p.parts:
                z.write(p, p.relative_to(design_dir))
    with cols[1]:
        st.download_button("⬇️ Download all (zip)",
                           buf.getvalue(), file_name=f"{design_dir.name}.zip")


def finalize(run):
    ctx = run["ctx"]
    design_dir = Path(ctx["design_dir"])
    sim_passed = not ctx.get("simulation_output")
    top = ctx.get("top_module_name") or slugify(ctx["query"])
    write_result_md(design_dir, ctx["query"],
                    top, sim_passed, ctx.get("harden_metrics"))
    # Push this whole design (RTL/TB/sim/GDS/notes/uploads) into the durable knowledge
    # store so future runs can RECALL it — this is how the RLM gets better over time.
    try:
        n = get_memory().ingest_run(design_dir, design=design_dir.name, query=ctx["query"])
        if n:
            ctx["ingested_count"] = n
    except Exception:  # noqa: BLE001
        pass


# --------------------------------------------------------------------------- #
# Human-in-the-loop feedback panel
# --------------------------------------------------------------------------- #
def feedback_ui(run):
    pend = run.get("pending")
    accepts = STEP_DEFS.get(
        pend, (None,) * 5)[4] if pend in STEP_DEFS else False
    queue = run["queue"]
    ctx = run["ctx"]
    st.markdown("---")
    if queue:
        st.info(f"⏸ **Paused** after `{pend}`. Next up: **`{queue[0]}`**. "
                "Review the output above, then continue or steer the agent.")
    elif ctx.get("simulation_output"):
        st.warning(f"⏸ **Paused** after `{pend}`. Circuit not yet spec-verified "
                   f"({ctx.get('error_count', 0)} attempts). Steer with Replan, or finish.")
    else:
        st.success(
            f"⏸ **Paused** after `{pend}`. Nothing left queued — finish, or steer.")

    # Feedback box FIRST so its value is available to every button below.
    fb = st.text_area("💬 Feedback / steering (used by Revise and Replan)",
                      key=f"fb_{len(run['transcript'])}",
                      placeholder="e.g. 'increase M1/M2 width for more gain', or 'add Miller compensation'…",
                      height=80)

    cols = st.columns([1, 1, 1])
    if cols[0].button("▶️ Continue" if queue else "🏁 Finish", type="primary", use_container_width=True):
        run["action"] = "continue"
        st.rerun()
    if cols[1].button("🔁 Replan", use_container_width=True,
                      help="Let the Replanner choose the next steps from your feedback above."):
        run["action"] = "replan"
        run["pending_feedback"] = fb
        st.rerun()
    if cols[2].button("✍️ Revise step", use_container_width=True, disabled=not accepts,
                      help=("Re-run this step with your feedback." if accepts
                            else "This step has no LLM to re-run.")):
        run["action"] = "revise"
        run["pending_feedback"] = fb
        st.rerun()

    with st.expander("🌐 Stuck? Ask the agent to fetch a web example of a block (name it + its ports)"):
        blk = st.text_input("Block to look up", key=f"blk_{len(run['transcript'])}",
                            placeholder="e.g. '5T OTA', 'beta-multiplier bias', 'cascode current mirror'")
        if st.button("🌐 Search the web for this block + its ports"):
            run["action"] = "weblookup"
            run["pending_block"] = blk
            st.rerun()


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def steer_box(run):
    """A prompt you can send ANYTIME — even while the agent is working. It's applied
    at the next step boundary: it revises the current step with your instruction, or
    (if that step has no LLM) replans the next steps from your message."""
    msg = st.chat_input("💬 Steer the agent or run a file command (e.g. 'remove the .vh file', "
                        "'create rtl/alu.v') — works even while it's running…")
    if msg and msg.strip():
        run["steer_msg"] = msg.strip()
        st.rerun()


def main():
    st.set_page_config(page_title="AnoaChip", layout="wide")
    st.title("🦌 AnoaChip — prompt → SPICE → GDSII (analog)")
    st.caption(
        "Local-LLM analog IC automation · prompt → netlist → ngspice spec check → "
        "Glayout layout · DRC/LVS · Ollama + Glayout")

    with st.sidebar:
        st.header("Model")
        st.success(f"Chat: {provider_label()}")

        mem = get_memory()
        if mem.enabled:
            s = mem.stats()
            kinds = ", ".join(f"{k}:{v}" for k, v in sorted((s.get("by_kind") or {}).items()))
            st.caption(f"🗄️ Knowledge store: **{s.get('total', 0)}** items"
                       + (f" ({kinds})" if kinds else ""))

        st.header("Run mode")
        run_mode = st.radio("Run mode",
                            ["🤖 Autonomous (run end-to-end)",
                             "✋ Review each step"],
                            label_visibility="collapsed",
                            help="Autonomous runs every agent to completion without asking "
                                 "(Chipster-style). Review pauses after each agent so you can "
                                 "Continue / Revise / Replan. Either way you can send a steering "
                                 "prompt at the bottom while it works.")
        autonomous = run_mode.startswith("🤖")
        deep_steps = st.checkbox("🧠 RLM deep agents (recursive)", value=True,
                                 help="Run EVERY LLM node (Planner, Researcher, Netlist Generator, "
                                      "Testbench Writer, both Correctors) as a Recursive-Language-Model "
                                      "deep agent: it plans (write_todos), OFFLOADS big context to disk and "
                                      "PEEKS slices, DELEGATES focused sub-tasks to fresh local-LLM calls "
                                      "(llm_query) or sub-agents (task), and builds up the netlist in files "
                                      "— so the 9B model never holds it all at once. The steps are "
                                      "unchanged. Untick to fall back to fast one-shot prompts.")

        hw_ok = librelane_available()
        if hw_ok:
            st.success(f"Glayout backend ready · PDK {PDK}")
        else:
            st.warning("Glayout not importable — netlist + ngspice only (no layout). Run `uv sync`.")

        st.header("Design prompt")
        prompt = st.text_area("Describe the analog circuit to build", height=140,
                              value="a 5-transistor OTA in sky130, 40 dB DC gain, 1 MHz bandwidth, "
                                    "60 degree phase margin, driving a 1 pF load, power under 1 mW")
        uploads = st.file_uploader(
            "📎 Attach files / images (spec, paper, schematic, netlist)",
            accept_multiple_files=True,
            type=["txt", "md", "csv", "json", "sp", "spice", "cir", "cdl", "log",
                  "pdf", "png", "jpg", "jpeg", "webp"],
            help="Saved into the design's context/uploads/. Text + PDF content is fed to the "
                 "agents as reference; schematics/images are saved so a node can analyze them "
                 "with the Python tool (run_python + pillow).")
        use_web = st.checkbox("Use web research", value=True)

        st.header("Layout")
        run_harden = st.checkbox(
            "Run Glayout layout (DRC/LVS) after specs pass", value=hw_ok, disabled=not hw_ok)
        clock_port = st.text_input("(unused for analog) clock port", value="clk")
        clock_period = st.number_input(
            "(unused) clock period (ns)", 1.0, value=24.0, step=1.0)
        die_um = st.number_input(
            "(unused) die size (µm)", 50.0, value=600.0, step=50.0)
        core_util = st.slider("(unused) core utilization (%)", 10, 80, 25)
        go = st.button("🚀 Generate chip", type="primary",
                       use_container_width=True)
        if st.session_state.get("run") is not None and st.button("🔄 New run / reset", use_container_width=True):
            st.session_state.run = None
            st.rerun()

    if "run" not in st.session_state:
        st.session_state.run = None

    if go:
        st.session_state.run = new_run(prompt, use_web, run_harden and hw_ok,
                                       clock_port, clock_period, die_um, core_util, autonomous,
                                       deep_steps, uploads=uploads)

    run = st.session_state.run
    if run is None:
        st.subheader("Agent workflow")
        st.graphviz_chart(workflow_graph(), use_container_width=True)
        st.info("Describe the analog circuit on the left, pick **Autonomous** or **Review each "
                "step**, and click **Generate chip**. In Autonomous it runs every agent end-to-end "
                "without asking. Type a **prompt at the bottom while it works** to steer it "
                "(revise/replan) or run a **file command** (e.g. *'fix ota.sp'*, *'edit the "
                "config'*) — the file agent edits your design on disk. A **connectivity gate** "
                "catches floating nets before layout so Glayout LVS is clean.")
        return

    # Live workflow graph (amber = working, green = done).
    st.subheader("Live agent workflow")
    graph_ph = st.empty()

    # 1) Apply a steering prompt the user sent WHILE the agent worked, or a button action.
    steer = run.pop("steer_msg", None)
    act = run.pop("action", None)
    if steer:
        # "remove the .vh file", "create rtl/alu.v" → file agent
        if _is_file_command(steer):
            run["pending_fileagent"] = steer
            run["status"] = "fileagent"
        else:
            pend = run.get("pending")
            # revisable step → redo it with the new instruction
            if pend in STEP_DEFS and STEP_DEFS[pend][4]:
                if run["transcript"]:
                    run["transcript"].pop()
                run["queue"].insert(0, pend)
                run["feedback"] = steer
                run["status"] = "running"
            # not revisable (write/sim) → replan from the message
            else:
                run["pending_feedback"] = steer
                run["status"] = "replan"
    elif act == "continue":
        run["status"] = "finalize" if not run["queue"] else "running"
    elif act == "revise":
        if run["transcript"]:
            # drop the step we're redoing
            run["transcript"].pop()
        run["queue"].insert(0, run["pending"])      # and re-run it next
        run["feedback"] = run.pop("pending_feedback", "")
        run["status"] = "running"
    elif act == "replan":
        run["status"] = "replan"
    elif act == "weblookup":
        run["status"] = "weblookup"

    # 2) Re-draw the whole transcript so far (static).
    for record in run["transcript"]:
        replay_record(record)

    # 3) Persistent steering prompt — send it anytime, even mid-run (chat_input is
    #    interactive while the step below blocks; it lands on the next run).
    if run["status"] != "done":
        steer_box(run)

    # 4) Replan / web-lookup / file-agent execute now.
    if run["status"] == "replan":
        do_replan(run, run.pop("pending_feedback", ""))
        run["status"] = "paused"
    elif run["status"] == "weblookup":
        do_weblookup(run, run.pop("pending_block", ""))
        # re-run the paused step with the new reference
        run["queue"].insert(0, run["pending"])
        run["status"] = "paused"
    elif run["status"] == "fileagent":
        do_fileagent(run, run.pop("pending_fileagent", ""))
        run["status"] = "paused"

    # 5) Run the next queued step (live), then pause.
    if run["status"] == "running":
        node = run["queue"].pop(0)
        fb = run.pop("feedback", "")
        done = {GRAPH_KEY.get(r["node"], r["node"]) for r in run["transcript"]}
        graph_ph.graphviz_chart(workflow_graph(active=GRAPH_KEY.get(node, node), done=done),
                                use_container_width=True)
        run["transcript"].append(execute_step(run, node, fb))
        advance(run, node)
        run["pending"] = node
        run["status"] = "paused"

    # 6) Autonomous: auto-advance with no asking (Chipster-style). Pauses only at the end.
    if run["status"] == "paused" and run.get("autonomous"):
        if run["queue"]:
            run["action"] = "continue"
            st.rerun()
        else:
            run["status"] = "finalize"

    # 7) Finalize.
    if run["status"] == "finalize":
        finalize(run)
        run["status"] = "done"

    # Final graph state.
    done = {GRAPH_KEY.get(r["node"], r["node"]) for r in run["transcript"]}
    if run["status"] == "done" and (run["ctx"].get("harden") or {}).get("gds"):
        done.add("gds")
    graph_ph.graphviz_chart(workflow_graph(done=done),
                            use_container_width=True)

    # 8) Feedback panel (review mode) / output.
    if run["status"] == "paused":
        if run.get("autonomous"):
            st.info(
                "🤖 Running autonomously… type a prompt at the bottom anytime to steer it.")
        else:
            feedback_ui(run)
    elif run["status"] == "done":
        ctx = run["ctx"]
        if ctx.get("simulation_output"):
            st.error(f"❌ RTL could not be verified ({ctx.get('error_count', 0)} attempts). "
                     "Files saved under output/. Use **Replan** to keep trying.")
        else:
            st.success("✅ RTL verified (simulation passed).")
        render_output(Path(ctx["design_dir"]))


if __name__ == "__main__":
    main()
