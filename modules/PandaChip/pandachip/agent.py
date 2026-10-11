"""PandaChip analog design agent.

An LLM — Ollama-hosted (default: glm-5.2:cloud) or Google Gemini via
Vertex AI ADC (model names starting with "gemini") — designs analog
circuits by writing xschem schematics and driving OpenADA (xschem
netlist -> ngspice simulation, executed in the pandachip-eda
IIC-OSIC-TOOLS container) until the waveform evidence supports the
requested behaviour.

Usage:
    .venv/bin/python -m pandachip.agent --task-file task.md --workdir designs/run1
"""

from __future__ import annotations

import argparse
import fcntl
import os
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from . import research
from .eda_tools import Workspace

OLLAMA_URL = "http://localhost:11434/api/chat"
DEFAULT_MODEL = "glm-5.2:cloud"
GUIDE = (Path(__file__).parent / "prompts" / "xschem_gf180_guide.md").read_text()

SYSTEM_PROMPT = f"""You are PandaChip, an expert analog IC design agent.
You design circuits as xschem schematics on the GF180MCU-D open PDK and
verify them with ngspice transient simulation through the OpenADA contract.
You are rigorous: a design is done only when simulation evidence
(waveform statistics and FFT peaks) demonstrates the required behaviour.
All file paths are relative to your workspace. Keep schematics tidy:
consistent grid spacing, clear net names, sensible placement.

Workflow phases: announce each with the set_phase tool as you enter it:
spec_ingestion (understand the spec, then RESEARCH BEFORE PLANNING:
search_web the architecture, typical topologies/values and reference
netlists, fetch_reference the best hit - the plan must cite what it is
based on), plan (write plan.md with write_file
covering the COMPLETE circuit: every block/IP with topology, connectivity
and sizing, the top-level integration, and - for EVERY block - an
expected-values table: each input and output node with its expected
waveform shape, frequency, amplitude/Vpp and DC level, plus the overall
pass criteria. Numbers, not adjectives; never plan just the first block),
sch_gen (write the schematic until it netlists clean), tb_gen (stimuli,
analyses, control block), sim (simulate, analyze, verify). When finishing,
call done with spec_met=true ONLY if the evidence proves the spec;
otherwise spec_met=false with an honest statement of what remains.

set_phase is an ANNOUNCEMENT, not a completion. A phase only counts as
complete when its artifact exists, and the tool layer checks this itself:
spec_ingestion needs a search_web/fetch_reference or a read of task.md,
plan needs BOTH plan.md and test_method.md, sch_gen needs every block AND
the toplevel drawn and netlisted, tb_gen needs a deck with real stimulus
AND a .tran/.ac/.dc analysis that RAN, sim needs analyze_raw to resolve
real vectors. NEVER skip a phase or announce one you are not entering.

NEVER SKIP AHEAD. FINISH ONE THING BEFORE STARTING THE NEXT:

1. Research ONCE. Do not re-run a search you already ran - the answer
   will not change, and repeats are refused.
2. Write plan.md AND test_method.md before drawing anything.
   test_method.md states, for EVERY block and the toplevel: the deck that
   drives it, the stimulus, the nodes measured, and the NUMERIC pass/fail
   criterion for each input and output. It is the contract you verify
   against - write it before you can be tempted to move the goalposts.
3. Then build ONE BLOCK AT A TIME, in signal-chain order. For each block:
     a. experiment under exp/ with numbered versions (exp/matching_v1.sch,
        _v2, _v3 ...) - try, simulate, measure, iterate;
     b. when a version meets its test_method.md criteria, PROMOTE it to
        the root as <block>.sch + <block>.sym;
     c. run its own <block>_verify.spice deck and analyze_raw its nodes.
   Only when that block PASSES do you start the next one. Promoting a new
   block while an earlier one is still unverified is REFUSED.
4. Only after EVERY block has passed its own testbench, draw the toplevel
   that wires the whole chain, netlist it, and simulate the system.
   Entering tb_gen or sim before the toplevel and all its blocks exist is
   REFUSED - you cannot test a system that has not been built.
5. Then the sweeps and charts the task asks for, one simulation per point.

A pile of blocks is not a design. A design that was never integrated at
the top is not finished, whatever the individual blocks measured.

Any design with more than one functional block MUST be hierarchical:
one .sch + .sym per block, each block verified against its expected
values BEFORE the next is drawn, then ONE top-level testbench. Flat
schematics are only for single-block circuits.

WORK VISIBLY WITH VERSIONED FILES: once you have netlisted or simulated a
schematic, do NOT overwrite it to make a change - save the revision as a
NEW numbered version (lna_v1.sch, lna_v2.sch, mixer_v1.sch, ...) and its
own verify deck. This leaves a visible trail of what you tried, like the
LNA demo (lna_v3 -> lna_v4 -> lna_v5). When a version passes, PROMOTE it:
copy it to the final block name (lna.sch + lna.sym) that the top level
instantiates. Never build a separate per-block testbench schematic
(no tb_<block>.sch) - use a <block>_verify.spice deck instead.

spec_met=true means the FULL requested system was built and verified.
If the task asks for a multi-block chain and you only completed a subset,
that is spec_met=false, whatever the subset's own results show. Never
narrow the task scope on your own.

The harness AUTO-REJECTS done(spec_met=true) unless, in this session:
a simulation completed successfully, analyze_raw covered the key node of
every stage (input, each intermediate, output - at least 3 vectors), every
schematic is properly drawn (real pin-to-pin wires, no stacked symbols),
and waveform plots could be generated from the rawfiles. Design the
testbench so EVERY block's function is visible in the waveforms.

OpenADA contract rules (from the official openada skill):
- Execution status and engineering status are separate questions:
  execution 'completed' only means the native tool ran; engineering 'pass'
  means the operation's fixed assertion passed.
- A successful simulation establishes valid analysis evidence; it does not
  by itself establish that the circuit meets its specification — that is
  what your waveform/FFT analysis must show.
- Treat PDK trees as read-only; never restate model-file content from
  memory. Do not claim evidence you did not obtain from a tool result.
- If a tool reports a diagnostic, read it and fix the actual cause; do not
  retry the identical request.
- You can research online: search_web for topology/sizing knowledge or a
  stubborn tool error, fetch_reference for one specific page. Cite what
  you used in plan.md. Do not substitute research for simulation evidence.
- Experiment freely under exp/ in the workspace: candidate versions
  (exp/block_v1.sch, _v2...), sweep decks, and ideal-element golden-model
  decks to compare the real implementation against. Promote the winner to
  the workspace root; only root schematics face the quality gates.

{GUIDE}
"""

TOOLS = [
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Create or overwrite a text file in the workspace.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"}},
            "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read a text file from the workspace.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "netlist_schematic",
        "description": "Generate a SPICE netlist from an xschem .sch file via OpenADA. Returns status, diagnostics and the netlist text.",
        "parameters": {"type": "object", "properties": {
            "schematic": {"type": "string"}},
            "required": ["schematic"]}}},
    {"type": "function", "function": {
        "name": "simulate_netlist",
        "description": "Run the SPICE netlist in ngspice via OpenADA. Returns status, log tail, and the rawfile path.",
        "parameters": {"type": "object", "properties": {
            "netlist": {"type": "string"}},
            "required": ["netlist"]}}},
    {"type": "function", "function": {
        "name": "analyze_raw",
        "description": "Waveform evidence from a simulation rawfile: min/max/Vpp/mean and dominant FFT peaks for the named vectors (node names or v(node)).",
        "parameters": {"type": "object", "properties": {
            "raw_path": {"type": "string"},
            "vectors": {"type": "array", "items": {"type": "string"}}},
            "required": ["raw_path", "vectors"]}}},
    {"type": "function", "function": {
        "name": "plot_xy",
        "description": "Draw an XY chart PNG from data points (sweep results: VOUT vs input power in dBm, VOUT vs frequency, ...). Saved as waves_<name>.png so it shows with the simulation evidence.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"},
            "title": {"type": "string"},
            "x_label": {"type": "string"},
            "y_label": {"type": "string"},
            "series": {"type": "array", "items": {"type": "object", "properties": {
                "name": {"type": "string"},
                "points": {"type": "array", "items": {"type": "array", "items": {"type": "number"}}}},
                "required": ["points"]}}},
            "required": ["name", "title", "x_label", "y_label", "series"]}}},
    {"type": "function", "function": {
        "name": "search_web",
        "description": "Research a design question online (topology choices, sizing equations, typical component values, ngspice/xschem error fixes, PDK facts). Returns a digest with sources, also saved to context/refs/. Use during spec_ingestion/plan and whenever a tool diagnostic stumps you.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "fetch_reference",
        "description": "Fetch one specific web page (paper, app note, repo file) as text into context/refs/ and return an extract.",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string"}},
            "required": ["url"]}}},
    {"type": "function", "function": {
        "name": "set_phase",
        "description": "Announce entering a workflow phase. Call at the start of each: spec_ingestion, plan, sch_gen, tb_gen, sim.",
        "parameters": {"type": "object", "properties": {
            "phase": {"type": "string", "enum": ["spec_ingestion", "plan", "sch_gen", "tb_gen", "sim"]}},
            "required": ["phase"]}}},
    {"type": "function", "function": {
        "name": "done",
        "description": "Finish the task. Call only when simulation evidence demonstrates the required behaviour.",
        "parameters": {"type": "object", "properties": {
            "summary": {"type": "string"},
            "evidence": {"type": "string"},
            "spec_met": {"type": "boolean", "description": "true ONLY if the simulation evidence demonstrates the requested spec"}},
            "required": ["summary", "spec_met"]}}},
]


def chat(model: str, messages: list[dict], think: bool | None = None,
         use_tools: bool = True, num_ctx: int | None = None) -> dict:
    if model.startswith("gemini"):
        from . import gemini
        return gemini.chat(model, messages,
                           tools=TOOLS if use_tools else None)
    body = json.dumps({
        "model": model,
        "messages": messages,
        **({"tools": TOOLS} if use_tools else {}),
        "stream": False,
        # Hardware-safe context sizing (GarudaChip rule): cloud models keep a
        # large window (KV cache is server-side); local models default lower
        # so the runner and this agent never get OOM-killed on small boxes.
        "options": {"temperature": 0.3,
            "num_ctx": num_ctx or (
                int(os.getenv("PANDACHIP_NUM_CTX", "32768"))
                if "cloud" in model else
                int(os.getenv("PANDACHIP_NUM_CTX_LOCAL", "16384"))),
            "num_predict": int(os.getenv("PANDACHIP_NUM_PREDICT", "8192"))},
        **({"think": think} if think is not None else {}),
    }).encode()
    has_images = any(m.get("images") for m in messages)
    last_error: Exception | None = None
    delay = 0.0
    for attempt in range(6):
        if delay:
            time.sleep(delay)
        delay = 10.0 * (attempt + 1)
        req = urllib.request.Request(
            OLLAMA_URL, data=body, headers={"Content-Type": "application/json"})
        try:
            print(f"  [chat] waiting for {model}"
                  f"{' (with images)' if has_images else ''}...", flush=True)
            with open("/tmp/pandachip-ollama.lock", "w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                with urllib.request.urlopen(req, timeout=300) as resp:
                    return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                # Rate limit: back off patiently (30s, 60s, 120s, 240s, 300s)
                delay = min(300.0, 30.0 * (2 ** attempt))
                last_error = exc
                print(f"  [chat retry {attempt + 1}] 429 rate-limited; "
                      f"waiting {int(delay)}s", flush=True)
                continue
            if has_images or (400 <= exc.code < 500):
                # Client errors are permanent (e.g. a text-only model
                # rejecting images) — fail fast so fallbacks kick in now.
                raise RuntimeError(
                    f"Ollama rejected the request: {exc.code} {exc.reason}"
                ) from exc
            last_error = exc
            print(f"  [chat retry {attempt + 1}] {exc}", flush=True)
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            print(f"  [chat retry {attempt + 1}] {exc}", flush=True)
    raise RuntimeError(f"Ollama chat failed after retries: {last_error}")


def _researched(ws: Workspace, result: dict, seen: set, key: str) -> dict:
    """Research is the observable evidence that the spec was ingested.

    Research is also where a model can spin forever: re-issuing near-identical
    queries burns the step budget (and rate limits) without learning anything.
    A repeat is refused and redirected to the actual design work.
    """
    norm = " ".join(sorted(key.lower().replace('"', " ").split()))
    if norm in seen:
        return {"ok": False, "error": "duplicate research request",
                "instruction": "You already ran this search - the answer will "
                               "not change. Stop researching and design: "
                               "write plan.md and test_method.md, then draw "
                               "the blocks and the toplevel."}
    seen.add(norm)
    if isinstance(result, dict) and not result.get("error"):
        ws.mark_phase("spec_ingestion", "researched the architecture")
    return result


def verification_gaps(ws: Workspace, progress: dict) -> list[str]:
    """Why done(spec_met=true) is not yet credible. Empty when it is."""
    # Workflow first: unwalked phases, IPs with no evidence of their own,
    # and sweep charts the task asked for but nobody drew.
    gaps: list[str] = ws.workflow_gaps()
    if not progress["sim_ok"]:
        gaps.append("no successful simulation ran in this session - "
                    "simulate and verify before claiming the spec is met")
    if len(progress["vectors"]) < 3:
        gaps.append(f"analyze_raw covered only {len(progress['vectors'])} "
                    "vector(s) - verify the key node of EVERY stage "
                    "(input, each intermediate, output)")
    gaps += ws.wiring_report()
    if not gaps:
        try:
            subprocess.run([sys.executable, "-m", "pandachip.autoplot",
                            str(ws.root)], capture_output=True, timeout=180)
        except Exception:
            pass
        if not list(ws.root.glob("waves_*.png")):
            gaps.append("no waveform plots (waves_*.png) could be generated "
                        "from the rawfiles - rerun the simulation so the "
                        "evidence can be shown")
        # every schematic must open in xschem SHOWING its waveforms
        gaps += ws.embed_missing_graphs()
    return gaps


def run(task: str, workdir: str, model: str = DEFAULT_MODEL,
        max_steps: int = 40, resume: bool = False) -> dict:
    ws = Workspace(workdir)
    researched: set[str] = set()  # queries already run; repeats are refused
    handlers = {
        "write_file": lambda a: ws.write_file(a["path"], a["content"]),
        "read_file": lambda a: ws.read_file(a["path"]),
        "netlist_schematic": lambda a: ws.netlist_schematic(a["schematic"]),
        "simulate_netlist": lambda a: ws.simulate_netlist(a["netlist"]),
        "analyze_raw": lambda a: ws.analyze_raw(a["raw_path"], a["vectors"]),
        "set_phase": lambda a: ws.set_phase(a["phase"]),
        "search_web": lambda a: _researched(
            ws, research.search_web(ws.root, a["query"]), researched, a["query"]),
        "fetch_reference": lambda a: _researched(
            ws, research.fetch_reference(ws.root, a["url"]), researched, a["url"]),
        "plot_xy": lambda a: ws.plot_xy(a["name"], a["title"], a["x_label"],
                                        a["y_label"], a["series"]),
    }
    preflight = ws.preflight()
    print(f"[preflight] {preflight.get('summary')}", flush=True)

    # Uploaded reference files: images ride along to the model (multimodal
    # Ollama models); PDF/text content is inlined into the task, bounded.
    images: list[str] = []
    extracted: list[str] = []
    uploads = sorted((ws.root / "uploads").glob("*")) if (ws.root / "uploads").is_dir() else []
    for up in uploads:
        suffix = up.suffix.lower()
        if suffix in (".png", ".jpg", ".jpeg", ".webp"):
            import base64
            images.append(base64.b64encode(up.read_bytes()).decode())
        elif suffix == ".pdf":
            import subprocess
            try:
                txt = subprocess.run(["pdftotext", str(up), "-"],
                                     capture_output=True, text=True,
                                     timeout=60).stdout
                extracted.append(f"[Content of {up.name}]:\n{txt[:6000]}")
            except Exception:
                extracted.append(f"[{up.name}: text extraction failed]")
        elif suffix in (".txt", ".md", ".csv", ".cir", ".spice", ".sch"):
            extracted.append(f"[Content of {up.name}]:\n"
                             f"{up.read_text(errors='replace')[:6000]}")
    if uploads:
        print(f"[uploads] {len(images)} image(s), {len(extracted)} text/pdf", flush=True)
    if images:
        # Vision pre-pass WITHOUT tools: some Ollama runners (e.g. qwen3.5)
        # crash with 500 when images and tools share one request. Extract
        # the diagram's engineering content first, then design from text.
        try:
            vr = chat(model, [{"role": "user", "content":
                "Extract every engineering detail from this circuit "
                "diagram: block topology, component types and their "
                "connections, target specs, values, frequencies, "
                "impedances. Be exhaustive and structured.",
                "images": images}], use_tools=False,
                num_ctx=int(os.getenv("PANDACHIP_VISION_NUM_CTX", "8192")))
            desc = vr.get("message", {}).get("content", "")
            if desc.strip():
                extracted.append("[Image analysis by the model]:\n" + desc[:6000])
                images = []
                print("[vision] diagram analyzed in a dedicated pre-pass",
                      flush=True)
        except Exception as exc:
            print(f"[vision] pre-pass failed ({exc}); attaching raw images",
                  flush=True)

    user_content = (
        f"{task}\n\nOpenADA scoped preflight "
        f"(assertion spice-analysis-evidence-valid): "
        f"{json.dumps({k: preflight.get(k) for k in ('engineering', 'summary')})}")
    if extracted:
        user_content += "\n\n" + "\n\n".join(extracted)
    first_msg: dict = {"role": "user", "content": user_content}
    if images:
        first_msg["images"] = images
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        first_msg,
    ]
    if resume and (ws.root / "transcript.json").exists():
        try:
            prior = json.loads((ws.root / "transcript.json").read_text())
            # Unwind the whole capitulation tail: dangling assistant
            # tool-calls, stale wrap-up orders ("call done NOW"), previous
            # RESUMED markers, and empty assistant turns. Leaving any of
            # them teaches the resumed model to instantly call done again.
            def _stale(m: dict) -> bool:
                if m.get("role") == "assistant":
                    return bool(m.get("tool_calls")) or not m.get("content")
                if m.get("role") == "user":
                    c = str(m.get("content", ""))
                    return c.startswith("Step budget exhausted") or \
                        c.startswith("The run was interrupted")
                return False
            while prior and _stale(prior[-1]):
                prior.pop()
            if len(prior) >= 2:
                prior[0] = {"role": "system", "content": SYSTEM_PROMPT}
                prior.append({"role": "user", "content":
                    "The run was interrupted and has now been RESUMED with "
                    "a fresh step budget. The workspace and all your files "
                    "are unchanged - do NOT start over, and do NOT call "
                    "done yet: the quality gate requires evidence produced "
                    "in THIS session. Diagnose the last diagnostics, fix "
                    "the actual cause, re-run simulate_netlist and "
                    "analyze_raw on every stage node, and only then call "
                    "done with what the fresh evidence shows."})
                messages = prior
                print(f"[resume] continuing from transcript "
                      f"({len(prior)} messages)", flush=True)
        except Exception as exc:
            print(f"[resume] transcript unusable ({exc}); starting fresh",
                  flush=True)
    transcript_path = ws.root / "transcript.json"
    outcome: dict = {"status": "max_steps_reached", "steps": 0}
    nudges = 0
    progress: dict = {"sim_ok": False, "vectors": set()}
    done_rejections = 0

    for step in range(1, max_steps + 1):
        try:
            reply = chat(model, messages)
        except RuntimeError:
            # A non-multimodal model can reject image attachments outright:
            # drop the images once and describe the situation instead.
            if any(m.get("images") for m in messages):
                print("[images] model rejected images; retrying text-only",
                      flush=True)
                for m in messages:
                    if m.get("images"):
                        del m["images"]
                        m["content"] += ("\n\n[Note: attached images could "
                                         "not be delivered to this model; "
                                         "proceed from the text description.]")
                reply = chat(model, messages)
            else:
                raise
        msg = reply.get("message", {})
        messages.append(msg)
        calls = msg.get("tool_calls") or []
        if step == 1:
            for m in messages:
                if m.get("images"):
                    del m["images"]
                    m["content"] += ("\n\n[Reference image was shown in "
                                     "the first turn; rely on your plan.]")
        if msg.get("content"):
            print(f"[{step}] assistant: {msg['content'][:400]}", flush=True)
        if not calls:
            # Thinking-only or empty turns happen with reasoning models:
            # nudge instead of treating them as a final answer.
            if not msg.get("content") and nudges < 4:
                nudges += 1
                print(f"[{step}] (empty turn; nudge {nudges})", flush=True)
                messages.append({
                    "role": "user",
                    "content": "Continue now: carry out your plan by calling "
                               "tools. When the evidence is verified, call "
                               "done."})
                continue
            outcome = {"status": "stopped_without_done", "steps": step,
                       "last_text": msg.get("content", ""),
                       "spec_met": False,
                       "summary": ("The model returned repeated empty turns. "
                                   "Likely causes: the model does not support "
                                   "tool calling, or its context is too small "
                                   "for the design guide. Try a stronger / "
                                   "tool-capable model from the dropdown.")}
            break

        finished = False
        for call in calls:
            fn = call.get("function", {})
            name = fn.get("name")
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            print(f"[{step}] tool: {name}({json.dumps(args)[:200]})", flush=True)
            if name == "done":
                gaps = (verification_gaps(ws, progress)
                        if args.get("spec_met") else [])
                if gaps and done_rejections < 3:
                    done_rejections += 1
                    print(f"[{step}] done REJECTED: {gaps}", flush=True)
                    messages.append({"role": "tool", "name": "done",
                                     "content": json.dumps({
                        "ok": False, "done_rejected": gaps,
                        "instruction": "spec_met=true is not credible yet. "
                            "Fix every issue listed, re-verify with "
                            "simulation evidence, then call done again."})})
                    continue
                if gaps:  # rejection budget exhausted: record honestly
                    args["spec_met"] = False
                    args["summary"] = (args.get("summary", "") +
                                       " [quality gate failed: " +
                                       "; ".join(gaps) + "]")
                outcome = {"status": "done", "steps": step,
                           "summary": args.get("summary", ""),
                           "evidence": args.get("evidence", ""),
                           "spec_met": bool(args.get("spec_met"))}
                finished = True
                break
            handler = handlers.get(name)
            if handler is None:
                result = {"ok": False, "error": f"unknown tool {name}"}
            else:
                try:
                    result = handler(args)
                except Exception as exc:  # surface tool crashes to the model
                    result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            if name == "simulate_netlist" and isinstance(result, dict) \
                    and result.get("execution") == "completed":
                progress["sim_ok"] = True
            timed_out = isinstance(result, dict) and \
                result.get("execution") == "timed_out"
            if timed_out:
                messages.append({"role": "user", "content":
                    "That simulation TIMED OUT (killed at ~540 s). The "
                    "analysis is too long - almost always a transient at a "
                    "high frequency. Do NOT resubmit the same deck. For an "
                    "RF block verify GAIN with .ac (seconds), or shorten the "
                    "transient to a few tens of periods (tstop=30/f, "
                    "timestep=1/(200*f)); e.g. at 2.4 GHz use '.tran 2p "
                    "12n'. Match the timestep to the frequency."})
            failed = isinstance(result, dict) and (
                result.get("error") or result.get("execution") == "rejected"
                or result.get("execution") == "timed_out"
                or any(d.get("severity") == "error"
                       for d in result.get("diagnostics") or []))
            progress["fails"] = progress.get("fails", 0) + 1 if failed else 0
            if progress["fails"] == 2:
                messages.append({"role": "user", "content":
                    "Two failures in a row. STOP retrying variations. "
                    "search_web the exact error text plus the circuit "
                    "context, and fetch_reference a known-good example; "
                    "then apply what you learned. If a sim keeps timing out, "
                    "the operating point is likely not converging - fix the "
                    "bias or add convergence options, do not resubmit."})
            if progress["fails"] >= 4:
                progress["fails"] = 0
                messages.append({"role": "user", "content":
                    "This block is blocking the whole run. STOP working on "
                    "it now. If the task has other blocks (mixer, LO, PA, "
                    "...), BUILD THOSE NEXT so the full system exists; note "
                    "this block's open issue in plan.md and come back to it "
                    "at the end. Do not keep looping on one block."})
            if name == "analyze_raw" and isinstance(result, dict) \
                    and not result.get("error"):
                progress["vectors"].update(map(str, args.get("vectors") or []))
                try:  # waveforms appear in the schematics as soon as possible
                    ws.embed_missing_graphs()
                except Exception:
                    pass
            print(f"[{step}]   -> {json.dumps(result)[:300]}", flush=True)
            messages.append({"role": "tool", "name": name,
                             "content": json.dumps(result)})
        # Compact history: keep full detail only for the last few tool
        # results; older ones shrink to a summary so context stays bounded.
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        for m in tool_msgs[:-4]:
            if len(m.get("content", "")) > 400:
                m["content"] = m["content"][:300] + " ...[trimmed]"
        transcript_path.write_text(json.dumps(messages, indent=1))
        if finished:
            break

    if outcome.get("status") == "max_steps_reached":
        outcome["steps"] = max_steps
        # One final wrap-up turn: if the evidence is already in, record it.
        messages.append({
            "role": "user",
            "content": "Step budget exhausted. Call the done tool NOW. If "
                       "your existing simulation evidence demonstrates the "
                       "spec, summarize it; otherwise state honestly what "
                       "was verified and what remains."})
        try:
            reply = chat(model, messages)
            for call in reply.get("message", {}).get("tool_calls") or []:
                fn = call.get("function", {})
                if fn.get("name") == "done":
                    args = fn.get("arguments") or {}
                    if isinstance(args, str):
                        args = json.loads(args)
                    if args.get("spec_met"):
                        gaps = verification_gaps(ws, progress)
                        if gaps:
                            args["spec_met"] = False
                            args["summary"] = (args.get("summary", "") +
                                               " [quality gate failed: " +
                                               "; ".join(gaps) + "]")
                    outcome = {"status": "done", "steps": max_steps,
                               "summary": args.get("summary", ""),
                               "evidence": args.get("evidence", ""),
                               "spec_met": bool(args.get("spec_met"))}
                    messages.append(reply["message"])
                    break
        except Exception as exc:
            print(f"[wrap-up] failed: {exc}", flush=True)

    transcript_path.write_text(json.dumps(messages, indent=1))
    # The outcome carries the workflow verdict, so the UI never has to
    # infer "completed" from a claim the agent made about itself.
    gaps = ws.workflow_gaps()
    outcome["phases_incomplete"] = gaps
    if gaps and outcome.get("spec_met"):
        outcome["spec_met"] = False
        outcome["summary"] = (outcome.get("summary", "") +
                              " [workflow incomplete: " + "; ".join(gaps) + "]")
    (ws.root / "outcome.json").write_text(json.dumps(outcome, indent=2))
    return outcome


def run_safe(task: str, workdir: str, model: str = DEFAULT_MODEL,
             max_steps: int = 40, resume: bool = False) -> dict:
    """run() but a fatal error is recorded as an outcome, not just a crash."""
    try:
        return run(task, workdir, model, max_steps, resume)
    except Exception as exc:
        outcome = {"status": "error", "steps": 0,
                   "summary": f"Run aborted by an infrastructure error: {exc}",
                   "spec_met": False}
        (Path(workdir) / "outcome.json").write_text(json.dumps(outcome, indent=2))
        print(f"[fatal] {exc}", flush=True)
        return outcome


def main() -> None:
    ap = argparse.ArgumentParser(description="PandaChip analog design agent")
    ap.add_argument("--task", help="task text")
    ap.add_argument("--task-file", help="file containing the task text")
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--max-steps", type=int, default=40)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()
    task = args.task or Path(args.task_file).read_text()
    t0 = time.time()
    outcome = run_safe(task, args.workdir, args.model, args.max_steps, args.resume)
    outcome["wall_seconds"] = round(time.time() - t0, 1)
    print(json.dumps(outcome, indent=2))


if __name__ == "__main__":
    main()
