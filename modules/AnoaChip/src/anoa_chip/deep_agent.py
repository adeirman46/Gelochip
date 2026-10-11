"""
AnoaChip Deep Agents — every LLM node is a Recursive-Language-Model-style
(RLM) deep agent, driven ENTIRELY by the local Ollama model (qwen3.5:9b).

The MIT "Recursive Language Models" idea (arXiv:2512.24601) applied here:
treat the big stuff (reference netlists, glayout examples, error logs, DRC/LVS
reports) as an *environment on disk* — NOT as one giant prompt. The root agent
keeps its own window SMALL: it PEEKS at slices (`read_file_disk` with line
ranges, `grep_files`) and DELEGATES focused sub-tasks to fresh sub-LLM calls
(`llm_query`) or full sub-agents (the built-in `task` tool). It builds the
answer up in files, then returns it. This is why a 9B local model can handle
full analog designs: it never has to hold everything at once.

The model is ALWAYS get_chat_model() (Ollama). deepagents' Anthropic default
(get_default_model) is never used because we pass `model=` explicitly.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List

from langchain_core.tools import tool
from deepagents import create_deep_agent

from llm import get_chat_model

PITFALLS = (
    "SPICE + Glayout classic mistakes to avoid: "
    "(1) ngspice EATS the first line of a deck as its title — always start netlist "
    "files with a `*` comment line; (2) every `.subckt` needs its `.ends` and its "
    "ports MUST all be connected inside the body — a port or net that appears only "
    "once is floating and guarantees an LVS mismatch; (3) `straight_route` only works "
    "when the two ports are inline and parallel — if the geometry needs a C or L "
    "shape, straight_route silently generates NOTHING and LVS fails: use `c_route` / "
    "`L_route` (or `smart_route`, which picks correctly), and `via_stack` whenever the "
    "two ports are on different metal layers; (4) NEVER instantiate `nmos(pdk)` / "
    "`pmos(pdk)` with default sizing — always pass width/length/fingers/multipliers "
    "from the config file, and generate the BARE device first: `with_tie=False, "
    "with_substrate_tap=False, with_dummy=False` — substrate ties, guard rings and "
    "dummies are FINISHING steps added only after routing is complete and LVS is "
    "clean; (5) placement must be explicit — `movex`/`movey`/`center` every reference "
    "(align with `evaluate_bbox`, `align_comp_to_port`), never leave two devices "
    "overlapping; (6) EVERY layout Component MUST expose PORTS and LABELS: `add_ports`/"
    "`add_port` for every pin (VDD, VSS, IN±, OUT, IBIAS) AND a matching TEXT LABEL "
    "placed on the pin's metal (glayout's `add_glayout_labels`/`labelled_ports`, or a "
    "gdstk/gdsfactory `Label` on the PDK label layer at the port center) — magic/netgen "
    "LVS matches nets by these labels, so an unlabelled port is an unconnected pin to "
    "LVS even if it is routed."
)

# RLM-style operating contract shared by every deep-agent node. Each pipeline
# node ALSO gets a specific goal (the user message); this is the standing
# behaviour: keep context small, peek, delegate, build up in files, verify.
INSTRUCTIONS = f"""You are an AnoaChip ANALOG IC engineer agent operating as a
Recursive Language Model (RLM): you keep your OWN context small and treat large
inputs as an environment on disk.

You manage REAL files for one analog design with your file tools — `list_files`,
`read_file_disk` (reads a SLICE: pass start_line/max_lines), `write_file_disk`,
`delete_file_disk`, and `grep_files` (regex-probe across files). The layout of a
design directory:
  config/<name>.json   — the DESIGN CONFIG: spec block + EVERY parameter
                         (W/L/fingers/multipliers per device, bias, vdd, cap,
                         placement offsets, routing choices, finishing flags)
  netlist/<name>.sp    — SPICE netlist (.subckt with ports)
  tb/<name>_tb.sp      — ngspice testbench (.measure + wrdata exports)
  sim/                 — simulation logs, wrdata data, bode/tran plots
  layout/<name>.py     — glayout generator script: `def build(pdk): -> Component`
  layout/*.gds|.svg|verify_*.json — layout + DRC/LVS verdicts
  context/             — offloaded references (crawled netlists, glayout examples)

How to work (RLM loop):
0. STATE FIRST. If `context/state.md` exists, read it before anything else — it is the
   RUN JOURNAL: what has been built, which specs pass/fail, and what the user
   asked/steered. Never redo what it records as done, never contradict the user.
1. CONFIG FIRST — IT IS THE COMPLETE PARAMETER RECORD. Before writing any netlist
   or layout code, write `config/<name>.json` with the target spec (gain_db, bw_hz,
   phase_margin_deg, power_w, …) AND a `params` block that lists EVERY component
   value in the design — no exceptions: per MOSFET its W, L, fingers, multipliers
   (M); every resistor R (Ω), capacitor C (F), inductor L (H); every bias current
   and reference voltage; the supply. Name each entry after the device it sizes
   (e.g. "M1_M2": {{"w":..,"l":..,"fingers":..,"m":..}}, "Rbias": 50e3, "Cc": 1.2e-12,
   "Ibias": 20e-6). SEED these from context/reference_params.md when it exists — the
   W/L/M, R, C, L, bias EXTRACTED from the closest researched netlist/paper — and scale
   for this spec, instead of inventing. This is the SINGLE SOURCE OF TRUTH: the netlist reads its device
   sizes from here, the layout sizes from here, and TUNING happens ONLY here — when a
   spec fails, MUTATE these values (W/L/fingers, R, C, bias, compensation) and
   regenerate; never hand-patch a generated netlist/layout. Every simulation records
   the config + measured performance to config/<name>_history.jsonl, so any past
   parameter set and the performance it produced can be recalled and tuned from.
2. PEEK, don't swallow. For anything big (reference netlists, glayout example code,
   ngspice logs, DRC/LVS reports), `grep_files` for the relevant lines or
   `read_file_disk` a slice — never assume you must read a whole file to act.
3. DELEGATE focused sub-tasks. Use `llm_query(prompt)` to summarize/extract/classify
   a slice, or to draft ONE small piece (a bias branch, one testbench section) —
   give it a self-contained prompt with just the slice it needs. Use the `task`
   tool for a heavier sub-job. Do NOT over-delegate: batch related work.
4. RECURSE IN CODE when the work is repetitive over many pieces: inside `run_python`
   a function `llm(prompt)` is available — write a SHORT script that LOOPS over the
   pieces, calls `llm(...)` once per piece, and writes the results to a context/
   file you then read. Example:
   `notes = [llm('Ports+topology of this SPICE netlist, tersely: ' + p.read_text()[:4000])
   for p in sorted(Path('context/anchor').rglob('*.sp'))[:8]]`
5. BUILD UP in files. Write netlists to `netlist/`, testbenches to `tb/`, layout
   scripts to `layout/` with `write_file_disk` instead of holding it in your reply.
6. LAYOUT CODE IS PYTHON (glayout): the deliverable layout/<name>.py defines
   `build(pdk) -> Component`. Inside it:
     • import from glayout: `from glayout import MappedPDK, sky130, gf180`,
       primitives `from glayout.primitives.fet import nmos, pmos`,
       `from glayout.primitives.mimcap import mimcap`,
       `from glayout.primitives.guardring import tapring`,
       routing `from glayout.routing.smart_route import smart_route`,
       `from glayout.routing.c_route import c_route`,
       `from glayout.routing.L_route import L_route`,
       `from glayout.routing.straight_route import straight_route`,
       `from glayout.primitives.via_gen import via_stack`,
       placement utils `from glayout.util.comp_utils import evaluate_bbox, movex,
       movey, center, align_comp_to_port`, `from glayout.util.port_utils import
       rename_ports_by_orientation`.
     • size every device FROM THE CONFIG (json.load the config file at the top),
       bare first: with_tie=False, with_substrate_tap=False, with_dummy=False.
     • place refs with `comp << device`, then movex/movey/center — explicit,
       non-overlapping placement.
     • route EVERY connection: smart_route(pdk, ref.ports["..."], ref2.ports["..."])
       or the explicit c_route/L_route/straight_route + via_stack. After routing,
       every net in the netlist must exist in the layout — an unrouted connection
       shows up as "net only in schematic" in LVS.
     • expose the circuit's ports AND LABELS: comp.add_ports(...)/add_port for every
       pin (VDD, VSS, inputs, outputs, bias), then place a TEXT LABEL on each pin's
       metal (glayout add_glayout_labels / a gdstk/gdsfactory Label on the PDK label
       layer at the port center) — LVS matches nets by these labels, so an unlabelled
       port reads as an unconnected pin. Attach the reference netlist
       (comp.info['netlist']) the way the glayout cells in the knowledge base do.
     • FINISHING LAST: only once LVS is clean on the bare circuit, enable ties /
       substrate taps / dummies / guard ring (tapring) per the config's
       `finishing` block, re-route what changed, and re-verify.
7. Use `write_todos` to plan multi-step work and track progress.
8. `run_python` is ALSO a data tool: compute bias points, gm/Id sizing, LUTs for
   testbench stimuli with numpy — and it's fine for reading an attached PDF/image
   (pypdf/pillow). Keep prints SMALL.
9. VERIFY before finishing — re-read what you wrote and check it against the rules.
- {PITFALLS}
- Before editing a file, read it first. After writing, confirm the file path.
"""


# Per-file last check error during a write (path -> (error, broken_content)), so when a
# file goes broken→clean we can persist the error→fix lesson. Module-level so it survives
# across write_file_disk calls within a generation step.
_LAST_WRITE_ERR: dict = {}


def _save_gen_fix_lesson(err: str, broken: str, fixed: str, design: str) -> None:
    """Persist a fix made DURING generation to the knowledge DB (kind='fix'), with a stable
    id by error signature so it dedupes. This is what makes EVERY problem solved while
    working in chat get saved — not just corrector-stage fixes."""
    try:
        import re as _re
        import hashlib
        from memory_store import get_memory
        mem = get_memory()
        if not getattr(mem, "enabled", False):
            return
        # concise signature = the first real error message line
        sigline = next((ln for ln in (err or "").splitlines()
                        if "error" in ln.lower() or "floating" in ln.lower()
                        or "mismatch" in ln.lower()), err[:80])
        sig = _re.sub(r"^.*?:\s*\d+:?\s*", "", sigline).strip()[:120] or "netlist error"
        body = (f"ERROR SIGNATURE: {sig}\n\nSYMPTOM:\n{err[:600]}\n\n"
                f"BROKEN (do NOT write this):\n```\n{broken[:1200]}\n```\n\n"
                f"CORRECT FIX:\n```\n{fixed[:1600]}\n```\n")
        rid = "fix_" + hashlib.sha1(sig.lower().encode()).hexdigest()[:16]
        mem.remember("fix", body, design=design, source="auto-fix:generation",
                     title=("fix: " + sig)[:120], tags="fix lesson generation",
                     object_key=rid, meta={"error_sig": sig})
    except Exception:  # noqa: BLE001
        pass


_NETLIST_EXT = (".sp", ".spice", ".cir", ".cdl", ".spc")
_GREP_EXT = (".sp", ".spice", ".cir", ".cdl", ".spc", ".py", ".md", ".log",
             ".txt", ".json", ".rpt", ".v")


def _check_layout_py(p: Path) -> str:
    """Syntax-check a glayout generator script + structural must-haves."""
    try:
        src = p.read_text()
        compile(src, str(p), "exec")
    except SyntaxError as e:
        return f"python syntax error: line {e.lineno}: {e.msg}"
    src = p.read_text()
    notes = []
    if "def build(" not in src:
        notes.append("script must define `def build(pdk):` returning the Component")
    if not re.search(r"(smart_route|c_route|L_route|straight_route)", src):
        notes.append("no routing calls found — every connection must be routed "
                     "with smart_route / c_route / L_route / straight_route")
    if not re.search(r"add_ports?\(", src):
        notes.append("no add_port/add_ports found — the circuit must expose its "
                     "ports (VDD, VSS, in/out/bias)")
    if not re.search(r"(add_glayout_labels|labelled_ports|gdstk\.Label|add_label|Label\()", src):
        notes.append("no LABELS found — every external port must get a text label on its "
                     "pin metal (add_glayout_labels / gdstk.Label on the PDK label layer); "
                     "LVS matches nets by label, so an unlabelled pin fails LVS")
    if re.search(r"(nmos|pmos)\(\s*pdk\s*\)", src):
        notes.append("bare nmos(pdk)/pmos(pdk) call with DEFAULT sizing found — "
                     "size from the config file (width/length/fingers/multipliers)")
    return "; ".join(notes)


def make_fs_tools(base_dir: str | Path, on_clean_write=None) -> List:
    """Real on-disk file tools, sandboxed to `base_dir` (the design directory).
    Reads are SLICED (RLM 'peek') and there is a regex `grep_files` so an agent can
    probe a large context without loading it whole — the key to keeping the local
    model's window small. `on_clean_write(relpath) -> str` (optional) fires the moment a
    netlist or layout script passes its write-time check — the generation step hooks
    per-circuit verify there (write netlist → clean ✓ → sim/build → next); whatever it
    returns is appended to the tool result so the agent sees the verdict."""
    base = Path(base_dir).resolve()

    def _resolve(path: str) -> Path:
        p = (base / (path or "")).resolve()
        if p != base and base not in p.parents:
            raise ValueError(f"path '{path}' escapes the design directory")
        return p

    @tool
    def list_files(subdir: str = "") -> str:
        """List files under the design directory. Optionally pass a subdir like
        'netlist', 'tb', 'layout', 'config' or 'context'."""
        d = _resolve(subdir)
        if not d.exists():
            return f"(no such path: {subdir or '.'})"
        if d.is_file():
            return str(d.relative_to(base))
        files = [str(p.relative_to(base)) for p in sorted(d.rglob("*"))
                 if p.is_file() and "_drc_out" not in str(p) and "_lvs_out" not in str(p)]
        return "\n".join(files) or "(empty)"

    @tool
    def read_file_disk(path: str, start_line: int = 1, max_lines: int = 250) -> str:
        """Read a SLICE of a text file under the design dir, e.g. 'netlist/ota.sp'.
        Returns a header (total lines/chars) then lines [start_line, start_line+max_lines).
        PEEK at big files in slices instead of reading them whole — keeps context small."""
        p = _resolve(path)
        if not p.exists() or not p.is_file():
            return f"(not found: {path})"
        text = p.read_text()
        lines = text.splitlines()
        n = len(lines)
        start = max(1, int(start_line))
        end = min(n, start - 1 + max(1, int(max_lines)))
        body = "\n".join(lines[start - 1:end]) if n else ""
        more = "" if end >= n else f"\n… ({n - end} more lines — read from line {end + 1} to continue)"
        return (f"# {path} — {n} lines, {len(text)} chars; showing {start}-{end}\n{body}{more}")[:20000]

    @tool
    def grep_files(pattern: str, subdir: str = "") -> str:
        """Regex-search the design files (optionally within a subdir like 'netlist',
        'layout' or 'context'). Returns up to 60 matching 'path:line: text' rows.
        Use this to PROBE a large context (reference netlists, glayout examples,
        sim logs, DRC/LVS reports) instead of reading whole files."""
        try:
            rx = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            return f"(bad regex: {e})"
        d = _resolve(subdir)
        roots = [d] if d.exists() else []
        hits: List[str] = []
        for root in roots:
            paths = [root] if root.is_file() else sorted(
                p for p in root.rglob("*")
                if p.is_file() and "_drc_out" not in str(p)
                and "_lvs_out" not in str(p) and p.suffix in _GREP_EXT)
            for p in paths:
                try:
                    for i, line in enumerate(p.read_text().splitlines(), 1):
                        if rx.search(line):
                            hits.append(f"{p.relative_to(base)}:{i}: {line.strip()[:160]}")
                            if len(hits) >= 60:
                                return "\n".join(hits) + "\n… (truncated at 60 matches)"
                except Exception:  # noqa: BLE001
                    continue
        return "\n".join(hits) or f"(no matches for /{pattern}/)"

    @tool
    def write_file_disk(path: str, content: str) -> str:
        """Create or OVERWRITE a file under the design dir, e.g. 'netlist/ota.sp' or
        'layout/ota.py'. SPICE netlists are AUTO-REPAIRED (title line, fences, .ends)
        and STRUCTURALLY CHECKED on write (floating nets, dangling ports, missing
        nodes); glayout layout scripts are syntax- and rule-checked (build(pdk),
        routing calls, add_ports, no default-sized fets). If the result says
        PROBLEMS, fix the file and write it again before moving on."""
        p = _resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        fixnote = ""
        is_netlist = p.suffix.lower() in _NETLIST_EXT
        if is_netlist:
            try:
                from netlist_check import autofix_text
                content, notes = autofix_text(content)
                if notes:
                    fixnote = " · auto-repaired: " + "; ".join(notes)
            except Exception:  # noqa: BLE001
                pass
        p.write_text(content)
        note = f"wrote {path} ({len(content)} bytes){fixnote}"
        # Instant feedback loop: a structural error surfaces in THIS tool result,
        # so the agent fixes the file now — not later at sim/LVS time.
        err = ""
        try:
            if is_netlist:
                from netlist_check import check_netlist_text
                err = check_netlist_text(content, filename=p.name)
            elif p.suffix == ".py" and "layout" in path.replace("\\", "/"):
                err = _check_layout_py(p)
            elif p.suffix == ".json":
                import json as _json
                try:
                    _json.loads(content)
                except Exception as je:  # noqa: BLE001
                    err = f"invalid JSON: {je}"
        except Exception:  # noqa: BLE001
            err = ""
        if err:
            _LAST_WRITE_ERR[str(p)] = (err, content)   # remember for the fix-lesson
            return (f"{note}\nPROBLEMS — fix this file and write it again "
                    f"NOW (do not move to the next file):\n{err}")
        # broken→clean during GENERATION = a real fix → save the lesson to the
        # knowledge DB (pg/MinIO) so the same mistake isn't repeated next run.
        prev = _LAST_WRITE_ERR.pop(str(p), None)
        if prev:
            _save_gen_fix_lesson(prev[0], prev[1], content, base.name)
        extra = ""
        is_tb = "tb/" in path.replace("\\", "/") or "_tb." in p.name
        if on_clean_write and not is_tb and (is_netlist or p.suffix == ".py"):
            try:                     # per-circuit verify hook (sim/build NOW)
                extra = on_clean_write(path) or ""
            except Exception:  # noqa: BLE001
                extra = ""
        return f"{note} — check clean ✓{extra}"

    @tool
    def delete_file_disk(path: str) -> str:
        """Delete a file under the design dir, e.g. 'context/stale_notes.md'."""
        p = _resolve(path)
        if p.exists() and p.is_file():
            p.unlink()
            return f"deleted {path}"
        return f"(not found: {path})"

    @tool
    def rename_file_disk(src: str, dst: str) -> str:
        """Rename/move a file under the design dir, e.g. rename 'netlist/ota_5t.sp' to
        'netlist/ota_2stage.sp' after a topology change, or 'tb/old_tb.sp' to
        'tb/<top>_tb.sp'. Use this (not delete+write) when a file's identity changes so
        history stays clean. Remember to update every .include and X-instantiation that
        referenced the old name."""
        sp, dp = _resolve(src), _resolve(dst)
        if not sp.exists() or not sp.is_file():
            return f"(not found: {src})"
        dp.parent.mkdir(parents=True, exist_ok=True)
        sp.rename(dp)
        return f"renamed {src} → {dst}"

    return [list_files, read_file_disk, grep_files, write_file_disk, delete_file_disk,
            rename_file_disk]


def make_rlm_tools(temperature: float = 0.2, model=None) -> List:
    """The RLM recursion primitive: `llm_query`, a single fresh local-LLM call the
    root agent uses to DELEGATE a focused sub-task (summarize/extract/classify a
    slice, or draft one small piece) so its own context stays small. Pairs with the
    built-in `task` tool (heavier sub-agent delegation) that deepagents always adds."""

    @tool
    def llm_query(prompt: str) -> str:
        """Delegate a focused sub-task to a fresh local LLM call and return its answer.
        Give a SELF-CONTAINED prompt (include the exact slice of context to process):
        e.g. 'Summarize the ports+topology of this SPICE subckt: <netlist>' or 'Write
        the bias branch devices for ...'. Use this to keep YOUR own context small.
        Batch related work into one call — do not call it per line."""
        m = model or get_chat_model(temperature=temperature)
        try:
            out = m.invoke(prompt)
            text = getattr(out, "content", None)
            if not text:
                text = str(out)
        except Exception as e:  # noqa: BLE001
            return f"(llm_query failed: {e})"
        return text[:6000]

    return [llm_query]


def make_python_tools(base_dir: str | Path, timeout: int = 0) -> List:
    """A real Python sandbox for the agent: `run_python` (execute a snippet, capture
    output) and `pip_install` (fetch libraries on demand). This lets a node COMPUTE
    before writing circuit files — bias-point / gm/Id sizing sweeps with numpy,
    testbench stimulus tables, parsing an attached PDF/image — and drop the results
    next to the netlist. The snippet also gets `llm(prompt)` — a fresh local-LLM call
    usable FROM CODE, the RLM recursion primitive (langchain 'RLMs in deep agents'):
    orchestration code loops over pieces of context and fans sub-queries out
    deterministically. Scripts run with the current interpreter (glayout importable),
    cwd = the design dir, with a timeout so a runaway can't hang the app."""
    base = Path(base_dir).resolve()
    timeout = timeout or int(os.getenv("ANOA_PY_TIMEOUT_S", "600"))

    # `llm()` available INSIDE the snippet: a direct Ollama /api/chat call (no imports from
    # this package needed in the subprocess). Model = the run's active pick, passed via env.
    _LLM_HELPER = (
        "def llm(prompt, temperature=0.2):\n"
        "    \"\"\"One fresh local-LLM call — the RLM recursion primitive, callable from code.\n"
        "    Loop over chunks/files and call this per piece; collect the results.\"\"\"\n"
        "    import json as _j, os as _o, urllib.request as _u\n"
        "    _b = _o.environ.get('OLLAMA_BASE_URL', 'http://localhost:11434').rstrip('/')\n"
        "    _m = _o.environ.get('ANOA_LLM_MODEL') or _o.environ.get('OLLAMA_MODEL', 'qwen3.5:9b')\n"
        "    _body = {'model': _m, 'messages': [{'role': 'user', 'content': str(prompt)[:24000]}],\n"
        "             'stream': False, 'think': False, 'options': {'temperature': temperature}}\n"
        "    _rq = _u.Request(_b + '/api/chat', _j.dumps(_body).encode(),\n"
        "                     {'Content-Type': 'application/json'})\n"
        "    _r = _j.loads(_u.urlopen(_rq, timeout=600).read())\n"
        "    try:  # token accounting — the pipeline folds this into the step's 🔢 note\n"
        "        with open('context/tokens.jsonl', 'a') as _f:\n"
        "            _f.write(_j.dumps({'in': _r.get('prompt_eval_count', 0),\n"
        "                               'out': _r.get('eval_count', 0)}) + chr(10))\n"
        "    except Exception:\n"
        "        pass\n"
        "    return _r['message']['content']\n"
    )

    @tool
    def run_python(code: str) -> str:
        """Run a Python snippet in the design directory and return its stdout/stderr.
        Use it to COMPUTE circuit data before writing files: gm/Id sizing sweeps,
        bias-point math, stimulus tables with numpy — or to sanity-import a
        layout/<name>.py (glayout IS importable here). A function `llm(prompt) -> str`
        is predefined in the snippet: use it to RECURSE over big context — loop over
        files/chunks, call llm() per piece, collect and write the results to a
        context/ file (deterministic coverage via a code loop). Also good for reading
        an attached PDF/image (pip_install pypdf / pillow first). The working dir is
        the design dir, so relative paths like 'netlist/...' resolve there.
        matplotlib is forced to the headless 'Agg' backend — savefig to a file,
        never show(). Keep prints SMALL: you only get back the last ~6000 chars."""
        work = base / "work"
        work.mkdir(parents=True, exist_ok=True)
        script = work / "_snippet.py"
        # Force a headless matplotlib backend IF it's installed — never crash the
        # snippet just because matplotlib is absent. Then the RLM llm() primitive.
        header = ("try:\n    import matplotlib; matplotlib.use('Agg')\n"
                  "except Exception:\n    pass\n") + _LLM_HELPER
        script.write_text(header + (code or ""))
        env = dict(os.environ)
        env.setdefault("PDK_ROOT", str(Path.home() / "pdks"))
        try:
            from llm import current_model
            env["ANOA_LLM_MODEL"] = current_model()   # snippet's llm() uses the active model
        except Exception:  # noqa: BLE001
            pass
        try:
            proc = subprocess.run([sys.executable, str(script)], cwd=str(base), env=env,
                                  capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return f"(timed out after {timeout}s — do less work per call or split it up)"
        except Exception as e:  # noqa: BLE001
            return f"(could not run python: {e})"
        out = proc.stdout + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
        tag = "OK" if proc.returncode == 0 else f"EXIT {proc.returncode}"
        return f"[{tag}]\n{out.strip()[-6000:] or '(no output)'}"

    @tool
    def pip_install(packages: str) -> str:
        """Install Python packages so `run_python` can import them. Pass names
        space- or comma-separated, e.g. 'numpy', 'scipy', 'pypdf pillow'. Call this
        BEFORE run_python when an import is missing."""
        pkgs = [p for p in re.split(r"[,\s]+", (packages or "").strip()) if p]
        if not pkgs:
            return "(no packages given)"
        attempts = []
        if shutil.which("uv"):                       # this project is uv-managed
            attempts.append(
                ["uv", "pip", "install", "--python", sys.executable, *pkgs])
        attempts.append([sys.executable, "-m", "pip", "install", *pkgs])
        last = ""
        for cmd in attempts:
            try:
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=600)
                if proc.returncode == 0:
                    return f"installed: {', '.join(pkgs)}"
                last = (proc.stdout + proc.stderr)[-1500:]
            except Exception as e:  # noqa: BLE001
                last = str(e)
        return f"(pip install failed for {', '.join(pkgs)}: {last})"

    return [run_python, pip_install]


def build_deep_agent(base_dir: str | Path, model=None, temperature: float = 0.2):
    """A deepagents agent with planning + REAL file tools + the RLM `llm_query`
    delegation primitive, driven by Ollama qwen3.5:9b. Used by the file agent."""
    return create_deep_agent(
        tools=make_fs_tools(base_dir) + make_rlm_tools(temperature),
        instructions=INSTRUCTIONS,
        model=model or get_chat_model(temperature=temperature),
        # keep the planning tool; use OUR real-disk file tools instead of the
        # built-in virtual-filesystem ones (write_file/read_file/ls/edit_file).
        builtin_tools=["write_todos"],
    )


def build_step_agent(base_dir: str | Path, extra_tools=None, instructions: str | None = None,
                     temperature: float = 0.2, model=None, on_clean_write=None,
                     subagents=None):
    """A deep agent for ONE pipeline step ("every agent is a deep agent"). Every node
    gets: planning (`write_todos`), real file tools (slice-read + grep), the RLM
    `llm_query` delegation primitive, the built-in `task` sub-agent tool, PLUS whatever
    step-specific tools (web research, memory, simulate, layout build, …) the caller
    passes. All driven by the local Ollama model. The fixed graph still orchestrates
    the steps; this upgrades a single node's brain into an RLM. `on_clean_write` is
    threaded into write_file_disk (per-circuit verify hook — see make_fs_tools).
    `subagents` (deepagents SubAgent dicts) adds NAMED specialist sub-agents callable
    via the `task` tool — e.g. the report step's `diagram` figure-maker."""
    tools = (list(make_fs_tools(base_dir, on_clean_write=on_clean_write))
             + list(make_rlm_tools(temperature))
             + list(make_python_tools(base_dir))
             + list(extra_tools or []))
    return create_deep_agent(
        tools=tools,
        instructions=instructions or INSTRUCTIONS,
        model=model or get_chat_model(temperature=temperature),
        subagents=list(subagents or []),
        builtin_tools=["write_todos"],
    )
