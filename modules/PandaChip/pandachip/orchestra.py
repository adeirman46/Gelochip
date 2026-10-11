"""PandaChip deep-agent orchestrator.

A LangChain/LangGraph deep agent (deepagents) drives the analog design
flow instead of the flat tool loop in agent.py. What that buys, and why
it matters here:

- write_todos: the plan lives in persisted state, not in the model's
  head, so "finish one block before starting the next" survives context
  pressure instead of evaporating twenty steps in.
- subagents: each IP block is designed and verified in its OWN context
  window by a fresh block-designer, so the mixer's debugging does not rot
  the context that the charge pump is being designed in. The orchestrator
  only ever sees each block's verdict.

Every EDA action still goes through OpenADA (pandachip.eda_tools.Workspace),
so the evidence contract and the phase ledger are identical to agent.py.

Usage:
    .venv/bin/python -m pandachip.orchestra --task-file task.md \
        --workdir designs/run1 --model gemini-3.1-pro-preview
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path

# Vertex drops JSON-schema keys it does not support and logs a warning for
# every one, on every tool, on every call. It is harmless and it drowns the
# run log, which is the user's only window into what the agent is doing.
logging.getLogger("langchain_google_vertexai.functions_utils").setLevel(
    logging.ERROR)
logging.getLogger("langchain_google_genai._function_utils").setLevel(
    logging.ERROR)

from langchain_core.tools import tool

from . import research
from .agent import GUIDE, verification_gaps
from .eda_tools import Workspace

DEFAULT_MODEL = "glm-5.2:cloud"

# Cross-run memory: distilled lessons from every finished run. Loaded into
# every agent's prompt so run N+1 starts knowing what run N had to learn
# the hard way (body-bias tricks, convergence fixes, sizing that worked).
LESSONS_PATH = Path(__file__).parent / "prompts" / "lessons.md"


def load_lessons() -> str:
    try:
        text = LESSONS_PATH.read_text().strip()
    except FileNotFoundError:
        return ""
    return f"\n\n# LESSONS FROM PREVIOUS RUNS (hard-won - apply them)\n{text}" \
        if text else ""


def distill_lessons(model, outcome: dict, run_name: str) -> None:
    """After a run: ask the run's own model for up to 3 NEW general
    lessons and append them to the shared lessons file."""
    summary = str(outcome.get("summary", ""))[:4000]
    if not summary:
        return
    known = ""
    try:
        known = LESSONS_PATH.read_text()[-4000:]
    except FileNotFoundError:
        pass
    try:
        from langchain_core.messages import HumanMessage
        r = model.invoke([HumanMessage(content=(
            "From this analog-design run outcome, write up to 3 NEW, GENERAL "
            "lessons for future runs on this platform (GF180MCU + xschem + "
            "ngspice): device/sizing recipes that worked, convergence or "
            "tool fixes, topology insights. One line each, imperative, "
            "specific. Do NOT repeat anything in KNOWN LESSONS. If nothing "
            "new was learned, reply exactly NONE.\n\n"
            f"KNOWN LESSONS:\n{known}\n\nRUN OUTCOME:\n{summary}"))])
        text = r.content if isinstance(r.content, str) else ""
        lines = [l.strip("-* \t") for l in text.splitlines()
                 if l.strip() and "NONE" not in l.upper()][:3]
        if lines:
            from datetime import date
            with LESSONS_PATH.open("a") as f:
                for l in lines:
                    f.write(f"- [{date.today().isoformat()} {run_name}] {l}\n")
            print(f"[lessons] banked {len(lines)} new lesson(s)", flush=True)
    except Exception as exc:
        print(f"[lessons] distillation skipped: {exc}", flush=True)


# ---------------------------------------------------------------- model


def build_model(name: str):
    """A LangChain chat model for either backend, matching agent.py's rule:
    gemini-* goes to Vertex AI on ADC, everything else to local Ollama."""
    if name.startswith("gemini"):
        from langchain_google_vertexai import ChatVertexAI
        from . import gemini
        return ChatVertexAI(
            model_name=name,
            project=gemini.project(),
            location=os.getenv("GOOGLE_CLOUD_LOCATION", "global"),
            temperature=0.3,
            max_output_tokens=int(os.getenv("PANDACHIP_GEMINI_MAX_TOKENS", "16384")),
        )
    from langchain_ollama import ChatOllama
    # Cloud-hosted Ollama models keep a large window (server-side KV cache);
    # local ones stay small so this never gets OOM-killed on a small box.
    num_ctx = int(os.getenv("PANDACHIP_NUM_CTX", "32768")) if "cloud" in name \
        else int(os.getenv("PANDACHIP_NUM_CTX_LOCAL", "16384"))
    return ChatOllama(
        model=name,
        base_url=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
        temperature=0.3,
        num_ctx=num_ctx,
        num_predict=int(os.getenv("PANDACHIP_NUM_PREDICT", "8192")),
        reasoning=False,
    )


# ---------------------------------------------------------------- tools


def _safe(fn):
    """A crashing tool is a message to the model, never a dead run.

    Without this, one bad argument (a path the workspace rejects, a
    malformed vector list) propagates out of the graph and throws away
    every minute of design work already done.
    """
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            return json.dumps({"ok": False,
                               "error": f"{type(exc).__name__}: {exc}",
                               "instruction": "Fix the arguments and retry; "
                                              "do not repeat the same call."})
    return wrapper


def build_tools(ws: Workspace, researched: set[str]) -> list:
    """The OpenADA-backed toolset, as LangChain tools over one workspace."""

    @tool
    @_safe
    def write_file(path: str, content: str) -> str:
        """Create or overwrite a text file in the design workspace.

        Promoting a NEW block schematic to the workspace root is refused
        while an earlier block still has no passing testbench. Experiment
        freely under exp/ instead.
        """
        return json.dumps(ws.write_file(path, content))

    @tool
    @_safe
    def read_file(path: str) -> str:
        """Read a text file from the design workspace."""
        return json.dumps(ws.read_file(path))

    @tool
    @_safe
    def netlist_schematic(schematic: str) -> str:
        """Netlist an xschem .sch through OpenADA. Returns status,
        diagnostics and the netlist text. Rejects schematics whose format
        or drawing quality would make them unreadable."""
        return json.dumps(ws.netlist_schematic(schematic))

    @tool
    @_safe
    def simulate_netlist(netlist: str) -> str:
        """Run a SPICE deck in ngspice through OpenADA. Returns status,
        log tail and the rawfile path."""
        return json.dumps(ws.simulate_netlist(netlist))

    @tool
    @_safe
    def analyze_raw(raw_path: str, vectors: list[str]) -> str:
        """Waveform evidence from a rawfile: min/max/Vpp/mean and dominant
        FFT peaks (or AC gain/-3dB corners) for the named vectors.

        Also embeds the waveforms into the schematics, so every .sch opens
        in xschem SHOWING its own simulation.
        """
        result = ws.analyze_raw(raw_path, vectors)
        if not result.get("error"):
            try:
                still_blank = ws.embed_missing_graphs()
                if still_blank:
                    result["schematics_without_waveforms"] = still_blank
            except Exception as exc:
                result["embed_warning"] = str(exc)
        return json.dumps(result)

    @tool
    @_safe
    def plot_xy(name: str, title: str, x_label: str, y_label: str,
                series: list[dict]) -> str:
        """Draw a sweep chart PNG (VOUT vs input power, VOUT vs frequency).
        series: [{"name": str, "points": [[x, y], ...]}]. Saved as
        waves_<name>.png so it appears with the simulation evidence."""
        return json.dumps(ws.plot_xy(name, title, x_label, y_label, series))

    @tool
    @_safe
    def search_web(query: str) -> str:
        """Research a design question online (topologies, sizing equations,
        typical values, tool errors). A query you already ran is refused."""
        norm = " ".join(sorted(query.lower().replace('"', " ").split()))
        if norm in researched:
            return json.dumps({"ok": False, "error": "duplicate research",
                               "instruction": "You already ran this search. "
                               "Stop researching and start designing."})
        researched.add(norm)
        result = research.search_web(ws.root, query)
        if not result.get("error"):
            ws.mark_phase("spec_ingestion", "researched the architecture")
        return json.dumps(result)

    @tool
    @_safe
    def fetch_reference(url: str) -> str:
        """Fetch one web page (paper, app note, repo file) into
        context/refs/ and return an extract."""
        if url in researched:
            return json.dumps({"ok": False, "error": "already fetched"})
        researched.add(url)
        result = research.fetch_reference(ws.root, url)
        if not result.get("error"):
            ws.mark_phase("spec_ingestion", "researched the architecture")
        return json.dumps(result)

    @tool
    @_safe
    def set_phase(phase: str) -> str:
        """Announce entering a workflow phase: spec_ingestion, plan,
        sch_gen, tb_gen or sim. Announcing does NOT complete a phase --
        evidence does. Entering tb_gen/sim is refused while the toplevel
        and its blocks do not exist."""
        return json.dumps(ws.set_phase(phase))

    @tool
    @_safe
    def workflow_status() -> str:
        """What still stands between this run and a credible finish:
        unfinished phases, unverified blocks, a missing toplevel, and
        charts the task asked for but nobody drew. Check this before
        claiming anything is done."""
        return json.dumps({
            "phases": {k: v.get("status") for k, v in ws.reconcile_phases().items()},
            "blocks_drawn": ws.finished_blocks(),
            "blocks_unverified": ws.unverified_blocks(),
            "experiment_versions": ws.experiment_counts(),
            "integration_gaps": ws.integration_gaps(),
            "planning_gaps": ws.planning_gaps(),
            "remaining": ws.workflow_gaps(),
        })

    return [write_file, read_file, netlist_schematic, simulate_netlist,
            analyze_raw, plot_xy, search_web, fetch_reference, set_phase,
            workflow_status]


# ------------------------------------------------------------ subagents

RESEARCHER = """You gather JUST ENOUGH reference material to start designing.

Fetch the sources you are given, and run AT MOST 3 additional searches.
Research is a starting point, not the deliverable -- the circuit is. Stop
as soon as you have starting values to simulate; the simulator settles
every remaining question far better than more reading would.

Report back CONCRETE NUMBERS: device W/L, component values, bias points,
expected voltages, with the source of each. Never invent a number -- say
"not stated" instead. Do not run any simulation."""

BLOCK_DESIGNER = """You design and verify EXACTLY ONE analog block, end to end.

You are given one block: its role in the chain, its interface, and the
numeric pass criteria from /<block>_plan.md - that file is your
contract. You do not touch any other
block, and you do not build the toplevel.

FILE LAYOUT: the workspace IS the filesystem root. Read your block's
"/<block>_plan.md" (your contract - NEVER rewrite it or any other plan;
append a "## Measured results" section to your own at most),
write candidates to "exp/<block>_v1.sch", promote to "<block>.sch". There
is NO "/workspace" directory -- never prefix a path with it.

YOU ARE AN EXPERIMENTALIST. Do not try to be right first time -- BUILD
MANY VERSIONS AND MEASURE THEM. A block that passed on v1 usually means
the testbench is too weak, not that the design is brilliant. Expect to
draw FIVE OR MORE candidates before one earns promotion, and keep going
past the first pass to find a version that EXCEEDS the target with margin.

BUILD REAL SILICON, NOT A BLOCK DIAGRAM. Every ACTIVE block must be drawn
at device level with real PDK transistors (nfet_03v3 / pfet_03v3), each
with explicit W and L. A cross-coupled differential rectifier is FOUR
transistors minimum; a 3-stage Dickson pump is at least six devices plus
its pump capacitors; a bias network needs real device-based biasing.
Ideal sources, behavioural expressions or an empty L/C shell standing in
for an active circuit are REFUSED - only a genuinely passive block
(matching network, balun, filter) may be L/C only. Aim for the density of
a real design: tens of devices across the chain, not four symbols.

EVERY SCHEMATIC MUST SHOW ITS OWN WAVEFORMS. Two shapes achieve that:

  - EXPERIMENTS (exp/<block>_v1.sch, _v2, ... _vN): SELF-CONTAINED. The
    candidate circuit AND its stimulus sources live in the one schematic,
    so it simulates directly and its waveforms embed into that same file.
    One file per version - v1, v2, v3 ... never overwrite an earlier one.

  - PROMOTED IP (<block>.sch + <block>.sym): a pure block with PORTS and
    no stimulus - it cannot show waveforms on its own, because whatever
    drives it lives outside. So for EVERY promoted IP you MUST also draw
    tb_<block>.sch: a testbench schematic that instantiates <block>.sym,
    drives it with real stimulus, and carries the waveforms. An IP with
    no tb_<ip>.sch does not count as verified.

Your loop, on GF180MCU with the xschem/ngspice rules in your guide:
1. Draw a self-contained candidate under exp/ as <block>_v1.sch, stimulus
   included. Real pin-to-pin wires, sensible placement -- netlist_schematic
   rejects unreadable drawings.
2. netlist_schematic it, simulate_netlist it, and analyze_raw the nodes
   named in your /<block>_plan.md so the waveforms embed in that version.
3. Compare against the numeric criteria, then ITERATE: exp/<block>_v2.sch,
   _v3, _v4, _v5 ... Change ONE thing per version and measure what it did,
   so you learn the sensitivity instead of guessing:
     - sweep the device W/L that dominates the block's gain or drop
     - try the alternative topology the references mention
     - move the bias point and see which direction helps
   Keep a running table of version -> measured numbers in your report.
   Never overwrite a version you already simulated: each one is evidence.
4. Promote the BEST version, not the first adequate one. THREE simulated
   versions is the MINIMUM, never a limit: while candidates keep IMPROVING,
   keep building - v4, v5, v6 - diagnosing and changing something real each
   time. Do not settle for a near miss while progress is still happening.

   BUT DO NOT DEADLOCK THE RUN ON ONE BLOCK. If you reach SIX simulated
   versions and the last three have not improved on the best, stop
   iterating: promote the best version you have, write its measured
   shortfall into known_issues.md (block, criterion, best number reached,
   what limits it, what you would try next), report the shortfall plainly,
   and let the orchestrator move on. A whole chain with one honestly
   documented weak block is worth far more than one perfect block and no
   system. You can revisit it after the chain exists. Write <block>.sch and <block>.sym at the workspace
   root, then draw tb_<block>.sch -- a testbench SCHEMATIC instantiating
   <block>.sym with real stimulus -- netlist and simulate THAT, and
   analyze_raw its nodes. Do NOT use a bare <block>_verify.spice deck:
   the IP owes a visible testbench schematic carrying its waveforms.

Report back: the table of every version you tried with its measured
numbers, which one won and WHY, the margin over spec, and the promoted
filenames. If you could not meet the spec, say so plainly with the best
numbers you reached and what limited them -- never claim a pass you did
not measure. Do NOT call a block done on a simulation you did not run."""

INTEGRATOR = """You build and verify the TOPLEVEL only.

Every block has already been designed, promoted and individually verified.
Instantiate them in one top schematic that wires the complete signal chain
in order, netlist it, build the top testbench deck, simulate it, and
analyze_raw the key node of EVERY stage: the input, each inter-block node,
and the output.

Do not redesign a block. If a block misbehaves in the system, report which
one and the measured evidence -- the orchestrator decides whether to send
it back. Report the per-stage measured numbers against plan.md."""

SWEEPER = """You produce the swept-result charts.

The toplevel is built and verified. Run ONE REAL SIMULATION PER POINT --
never extrapolate, estimate, or reuse a point. For each point: edit the
source amplitude or frequency in a deck under exp/, simulate_netlist it,
analyze_raw the output node, and record the number.

Then draw each curve with plot_xy. Report the table of points you actually
simulated, and state the dBm-to-amplitude convention you used.

If the task asks for efficiency (PCE), measure it - never estimate it. For
each input-power point: PCE(%) = 100 * (Vout_dc^2 / Rload) / P_available,
where Vout_dc is the steady-state mean from analyze_raw, Rload is the
load resistor in the deck, and P_available = Vamp^2 / (8 * Rsrc) for a
source of amplitude Vamp behind Rsrc (50 ohm). Draw it with
plot_xy(name="pce_vs_power", ...) and report the peak PCE and where it
occurs. A power converter without a measured efficiency is unfinished."""


REVIEWER = """You are an independent design reviewer. You verify claims -
you never design, never edit files, never fix anything.

Given a block (or the toplevel) and its plan file: read the plan's numeric
criteria, then re-derive every number YOURSELF with analyze_raw on the
block's testbench rawfile (tb_<block>.raw). Do not trust the designer's
report - trust the rawfile.

Reply with a verdict table: criterion | expected | measured (by you) |
PASS/FAIL, followed by a one-line overall verdict. Flag any claim the
designer made that the rawfile does not support, any node the plan names
that was never measured, and any suspicious sign (an output suspiciously
exactly at target, a DC level riding on a rail, ripple bigger than the
mean). Be blunt; a false PASS costs a whole downstream stage."""


def build_subagents(model, lessons: str = "") -> list[dict]:
    return [
        {"name": "researcher", "description":
            "Researches topologies, sizing and reference papers. Returns "
            "concrete numbers with sources. Runs no simulations.",
         "system_prompt": RESEARCHER, "model": model},
        {"name": "block-designer", "description":
            "Designs and verifies ONE analog block end to end: iterates "
            "exp/ versions until it meets its numeric criteria, then "
            "promotes it. Dispatch one per block, one at a time.",
         "system_prompt": BLOCK_DESIGNER + "\n\n" + GUIDE + lessons, "model": model},
        {"name": "integrator", "description":
            "Builds the toplevel from already-verified blocks and verifies "
            "the whole chain. Use only after every block has passed.",
         "system_prompt": INTEGRATOR + "\n\n" + GUIDE + lessons, "model": model},
        {"name": "sweeper", "description":
            "Runs sweep points as real simulations and draws the charts "
            "with plot_xy. Use after the toplevel is verified.",
         "system_prompt": SWEEPER + "\n\n" + GUIDE + lessons, "model": model},
        {"name": "design-reviewer", "description":
            "Independently re-verifies a promoted block or the toplevel "
            "against its plan by re-measuring the tb rawfile. Read-only; "
            "returns a criterion-by-criterion PASS/FAIL table.",
         "system_prompt": REVIEWER, "model": model},
    ]


ORCHESTRATOR = """You are PandaChip, orchestrating an analog IC design on the
GF180MCU-D open PDK. Every EDA action runs through OpenADA (xschem netlist,
ngspice simulation) and a design is done ONLY when simulation evidence
demonstrates the required behaviour.

You do not draw circuits yourself. You plan, dispatch subagents, and check
their evidence. Use write_todos to hold the plan, and work the list in
order -- NEVER start an item before the previous one is finished.

FILE LAYOUT: the design workspace IS the filesystem root. plan.md is at
"/plan.md" (or just "plan.md"), experiments at "exp/<block>_v1.sch",
promoted blocks at "<block>.sch". There is NO "/workspace" directory --
never prefix a path with it.

THE ORDER IS NOT NEGOTIABLE:

1. spec_ingestion -- set_phase, then dispatch `researcher` ONCE for the
   architecture and any reference papers in the task. One dispatch, then
   move on: enough references to start, not a literature review. The
   circuits are the deliverable.
2. plan -- ONE FILE PER DELIVERABLE, all written BEFORE any schematic:
     - toplevel_plan.md: the complete signal chain in order, how the
       blocks connect, the top-level integration, its numeric pass
       criteria, and the sweeps/charts the task demands.
     - <block>_plan.md for EVERY block in the chain (match_plan.md,
       rectifier_plan.md, ...; sub-tops get <subtop>_plan.md): the
       interface (ports), topology, device sizing, an expected-values
       table (each input and output node: shape, frequency, amplitude/
       Vpp, DC level), AND the test method - the exact stimulus, the
       nodes measured, and the NUMERIC pass/fail criterion for each.
       The plan IS the test spec; there is no separate test_method.md.
   Numbers, not adjectives; plan the COMPLETE chain, never just the
   first block. Put one todo per block, in signal-chain order.
3. sch_gen -- dispatch `block-designer` for ONE block at a time, in
   signal-chain order. Tell it to EXPERIMENT: many exp/ versions, measured
   against its <block>_plan.md, promoting the best rather than the first that
   scrapes a pass. When it reports back, CHECK with workflow_status that
   the block is really verified, and read its version table -- if it
   promoted a v1 that only just met spec, send it back to find margin.
   Then dispatch `design-reviewer` on the block: it re-measures the tb
   rawfile itself and returns a criterion-by-criterion verdict. Accept
   the block ONLY on the reviewer's PASS - a designer's own claim of
   success is not acceptance. Only then mark that todo complete and
   dispatch the next block.

   THE WHOLE CHAIN COMES FIRST. Your job is a working SYSTEM, not one
   immaculate block. If a block-designer reports it could not meet a
   criterion after six versions, accept its best with the shortfall
   recorded in known_issues.md and MOVE ON to the next block. Never let
   one block consume the run: a complete chain with two documented weak
   blocks can be measured, debugged and improved, while four perfect
   blocks and no toplevel is worth nothing. Come back and re-dispatch the
   weak blocks only AFTER the toplevel simulates end to end.
4. Integration -- once workflow_status shows NO unverified blocks,
   dispatch `integrator` to build and verify the toplevel.
5. tb_gen / sim -- the top testbench and full-chain simulation. Note that
   set_phase refuses tb_gen and sim while the toplevel does not exist.
6. Charts -- dispatch `sweeper` for the swept results the task asks for;
   when the task names efficiency/PCE, that includes a measured
   pce_vs_power curve computed from the sweep rawfiles.

Before you finish, call workflow_status. If anything remains -- an
unverified block, a missing toplevel, a chart never drawn -- it is NOT
done: keep working. Report honestly at the end: what was verified, with
the measured numbers, and what remains. Never claim evidence you did not
obtain from a tool result, and never narrow the task's scope on your own.

{guide}
"""


def run(task: str, workdir: str, model_name: str = DEFAULT_MODEL,
        recursion_limit: int = 400, resume: bool = False) -> dict:
    ws = Workspace(workdir)
    researched: set[str] = set()
    # ONE model instance, shared by the orchestrator and every subagent,
    # so the model chosen in the web UI is the model that does all of the
    # work - no subagent silently falls back to a different default.
    model = build_model(model_name)
    tools = build_tools(ws, researched)
    lessons = load_lessons()
    if lessons:
        print(f"[lessons] {lessons.count(chr(10))} line(s) of prior "
              "experience loaded", flush=True)
    subagents = build_subagents(model, lessons)
    print(f"[model] {model_name} ({type(model).__name__}) drives the "
          f"orchestrator and all {len(subagents)} subagents: "
          f"{', '.join(s['name'] for s in subagents)}", flush=True)

    from deepagents import create_deep_agent
    from deepagents.backends import FilesystemBackend
    # deepagents ships its own filesystem tools. Left at their default they
    # root at the process CWD and quietly write the design into a stray
    # 'workspace/' folder, where none of the gates can see it. Root them at
    # the run directory in virtual mode so "/plan.md" IS the run's plan.md,
    # and both toolsets act on exactly the same files.
    # Checkpointing is what makes a cloud-LLM run survivable: one 502 from
    # ollama.com/Vertex mid-stream must cost a retry, not the entire run.
    try:
        from langgraph.checkpoint.memory import InMemorySaver
    except ImportError:  # older langgraph name
        from langgraph.checkpoint.memory import MemorySaver as InMemorySaver
    agent = create_deep_agent(
        model=model,
        tools=tools,
        system_prompt=ORCHESTRATOR.format(guide=GUIDE) + lessons,
        subagents=subagents,
        backend=FilesystemBackend(root_dir=ws.root, virtual_mode=True),
        checkpointer=InMemorySaver(),
    )

    preflight = ws.preflight()
    print(f"[preflight] {preflight.get('summary')}", flush=True)

    # Uploaded reference files: the web UI saves them under uploads/ and
    # agent.py fed them to the model - this orchestrator never did, so an
    # attached architecture diagram was silently ignored. Images go through
    # a vision pre-pass (extract the engineering content once, then design
    # from text - subagents never carry raw images); PDF/text is inlined.
    uploads = sorted((ws.root / "uploads").glob("*")) \
        if (ws.root / "uploads").is_dir() else []
    extracted: list[str] = []
    image_blocks: list[dict] = []
    for up in uploads:
        suffix = up.suffix.lower()
        if suffix in (".png", ".jpg", ".jpeg", ".webp"):
            import base64
            mime = {"png": "image/png", "webp": "image/webp"}.get(
                suffix[1:], "image/jpeg")
            image_blocks.append({"type": "image_url", "image_url": {
                "url": f"data:{mime};base64,"
                       + base64.b64encode(up.read_bytes()).decode()}})
        elif suffix == ".pdf":
            import subprocess as _sp
            try:
                txt = _sp.run(["pdftotext", str(up), "-"],
                              capture_output=True, text=True,
                              timeout=60).stdout
                extracted.append(f"[Content of {up.name}]:\n{txt[:6000]}")
            except Exception:
                extracted.append(f"[{up.name}: text extraction failed]")
        elif suffix in (".txt", ".md", ".csv", ".cir", ".spice", ".sch"):
            extracted.append(f"[Content of {up.name}]:\n"
                             f"{up.read_text(errors='replace')[:6000]}")
    if uploads:
        print(f"[uploads] {len(image_blocks)} image(s), "
              f"{len(extracted)} text/pdf", flush=True)
    if image_blocks:
        try:
            from langchain_core.messages import HumanMessage
            vr = model.invoke([HumanMessage(content=[
                {"type": "text", "text":
                 "Extract every engineering detail from this circuit "
                 "diagram: block topology, component types and their "
                 "connections, target specs, values, frequencies, "
                 "impedances. Be exhaustive and structured."},
                *image_blocks])])
            desc = vr.content if isinstance(vr.content, str) else " ".join(
                b.get("text", "") for b in vr.content if isinstance(b, dict))
            if desc.strip():
                extracted.append("[Architecture diagram analysis]:\n"
                                 + desc[:6000])
                print("[vision] reference diagram analyzed", flush=True)
        except Exception as exc:
            print(f"[vision] pre-pass failed ({exc}); continuing from text",
                  flush=True)

    prompt = (f"{task}\n\nOpenADA scoped preflight: "
              f"{json.dumps({k: preflight.get(k) for k in ('engineering', 'summary')})}")
    if extracted:
        prompt += "\n\n" + "\n\n".join(extracted)
    if resume:
        # The workspace survived; only the agent's memory did not. Tell it
        # exactly what is already banked so it continues instead of
        # redesigning blocks that already passed.
        prompt += (
            "\n\nThis run was INTERRUPTED and has been RESUMED. The workspace "
            "is intact - do NOT start over and do NOT redo work that is "
            "already banked. Current state:\n"
            f"{json.dumps({'phases': {k: v.get('status') for k, v in ws.load_phases().items()}, 'blocks_drawn': ws.finished_blocks(), 'blocks_unverified': ws.unverified_blocks(), 'remaining': ws.workflow_gaps()[:10]}, indent=1)}\n"
            "Rebuild your todo list from what REMAINS, read "
            "the plan files (toplevel_plan.md, <block>_plan.md) for the contract "
            "you are working to, and carry "
            "on from the first unfinished item.")

    outcome: dict = {"status": "max_steps_reached", "steps": 0}
    # stream_mode="values" re-emits the WHOLE message list every chunk, so
    # messages are numbered from a monotonic counter and de-duplicated by
    # id. One line per tool CALL (an AI turn can carry several), so the
    # runbook reads as a clean 1,2,3... sequence with no repeats or holes.
    step = 0
    seen: set[str] = set()
    final_text = ""

    def flatten(content) -> str:
        if isinstance(content, list):  # provider content blocks
            return " ".join(b.get("text", "") for b in content
                            if isinstance(b, dict))
        return str(content or "")

    # The last subagent dispatched, so nested steps can be attributed even
    # though LangGraph namespaces them by node id rather than by name.
    current_sub = {"name": ""}

    def who(namespace) -> str:
        """Which agent a message came from: '' for the orchestrator, else
        the subagent's name, so the log shows who is actually working."""
        if not namespace:
            return ""
        for part in reversed(namespace):
            name = str(part).split(":")[0]
            if name not in ("tools", "agent", "model", "__start__", "task"):
                return name
        # Nested but unnamed: it is the subagent currently running.
        return current_sub["name"] or "subagent"

    def _emit(namespace, chunk) -> None:
        """Print one stream chunk as numbered, agent-attributed log lines."""
        nonlocal step, final_text
        agent_name = who(namespace)
        tag = f" <{agent_name}>" if agent_name else ""
        for msg in chunk.get("messages") or []:
            key = getattr(msg, "id", None) or f"{id(msg)}"
            if key in seen:
                continue
            seen.add(key)
            kind = getattr(msg, "type", "")
            text = flatten(getattr(msg, "content", ""))
            calls = getattr(msg, "tool_calls", None) or []
            if kind == "ai" and text.strip():
                step += 1
                if not agent_name:
                    final_text = text
                print(f"[{step}]{tag} assistant: {text[:400]}", flush=True)
            for call in calls:
                step += 1
                args = json.dumps(call.get("args", {}))
                if call["name"] == "task":
                    current_sub["name"] = str(
                        call.get("args", {}).get("subagent_type", "subagent"))
                print(f"[{step}]{tag} tool: {call['name']}({args[:400]})",
                      flush=True)
            if kind == "tool" and text.strip():
                print(f"[{step}]{tag}   -> {text[:300]}", flush=True)
                # deepagents ships its own filesystem tools, so files can
                # appear without any of our hooks firing. Re-derive the
                # ledger from what is actually on disk after every tool
                # result, or the timeline reports work that plainly
                # happened as still missing.
                ws.reconcile_phases()

    def transient(exc: Exception) -> bool:
        """Errors worth resuming through: network flakes and rate limits
        from the cloud LLM, never logic errors in our own code."""
        text = f"{type(exc).__name__}: {exc}".lower()
        return any(s in text for s in (
            "timed out", "timeout", "connection", "reset", "refused",
            "502", "503", "504", "429", "unavailable", "overloaded",
            "rate limit", "resource exhausted", "responseerror",
            "server error", "eof"))

    config = {"recursion_limit": recursion_limit,
              "configurable": {"thread_id": "pandachip"}}
    payload: dict | None = {"messages": [{"role": "user", "content": prompt}]}
    retries = 0
    try:
        # subgraphs=True surfaces the SUBAGENTS' own tool calls. Without it
        # a block-designer's twenty-minute design loop shows up as a single
        # opaque "task(...)" line and the user cannot see what is happening.
        # On a transient LLM failure the stream is resumed from the last
        # checkpoint (payload=None continues the same thread) - the flat
        # agent.py retried Ollama six times, and this loop owes the same
        # patience or a single 502 throws away an hour of design work.
        while True:
            try:
                for namespace, chunk in agent.stream(
                        payload, config,
                        stream_mode="values", subgraphs=True):
                    _emit(namespace, chunk)
                break
            except Exception as exc:
                retries += 1
                if retries > 6 or not transient(exc):
                    raise
                delay = min(300, 15 * 2 ** (retries - 1))
                print(f"[retry {retries}/6] {type(exc).__name__}: "
                      f"{str(exc)[:200]} - resuming from checkpoint in "
                      f"{delay}s", flush=True)
                time.sleep(delay)
                payload = None  # continue the checkpointed thread
        outcome = {"status": "done", "steps": step, "summary": final_text[:4000]}
    except Exception as exc:
        outcome = {"status": "error", "steps": step,
                   "summary": f"Orchestrator aborted: {type(exc).__name__}: {exc}"}
        print(f"[fatal] {exc}", flush=True)

    # The verdict is the workspace's, not the model's.
    gaps = verification_gaps(ws, {"sim_ok": True, "vectors": set(range(3))})
    outcome["phases_incomplete"] = gaps
    outcome["spec_met"] = not gaps
    if gaps:
        outcome["summary"] = (outcome.get("summary", "") +
                              " [workflow incomplete: " + "; ".join(gaps[:8]) + "]")
    else:
        outcome.setdefault("evidence", "every block verified, toplevel "
                           "simulated, requested charts drawn")
    (ws.root / "outcome.json").write_text(json.dumps(outcome, indent=2))
    # Bank what this run learned so the next one starts smarter.
    distill_lessons(model, outcome, ws.root.name)
    return outcome


def main() -> None:
    ap = argparse.ArgumentParser(description="PandaChip deep-agent orchestrator")
    ap.add_argument("--task", help="task text")
    ap.add_argument("--task-file", help="file containing the task text")
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--recursion-limit", type=int, default=400)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()
    task = args.task or Path(args.task_file).read_text()
    t0 = time.time()
    outcome = run(task, args.workdir, args.model, args.recursion_limit,
                  args.resume)
    outcome["wall_seconds"] = round(time.time() - t0, 1)
    print(json.dumps(outcome, indent=2))


if __name__ == "__main__":
    main()
