"""Headless run engine.

Drives AnoaChip's existing pipeline loop (`new_run` → `execute_step`/`advance` →
`finalize` from src/anoa_chip/app.py) in a background thread, with the streamlit shim
installed so nothing draws to a UI. As each `Recorder` block is produced it is:
  • pushed to a per-run event bus (the SSE stream the web UI reads), and
  • persisted to Postgres (`run.transcript`), so a reload re-hydrates the conversation.
After every step the design's artifacts are ingested into the knowledge store, so the
RLM's memory updates LIVE during a run, not only at the end.
"""
from __future__ import annotations

import re
import subprocess
import sys
import threading
from pathlib import Path

from . import db, headless_st

# --- import the existing pipeline headlessly (once) -------------------------
_REPO = Path(__file__).resolve().parents[2]
_PIPELINE = None


def _pipeline():
    global _PIPELINE
    if _PIPELINE is None:
        headless_st.install()
        src = str(_REPO / "src" / "anoa_chip")
        if src not in sys.path:
            sys.path.insert(0, src)
        import app as pipeline  # noqa: E402  (the streamlit app, now headless)
        _emit_patch(pipeline)
        _patch_subprocess()
        _PIPELINE = pipeline
    return _PIPELINE


# Track every subprocess (iverilog / verilator / LibreLane / crawler) per run so Stop
# can KILL it immediately instead of waiting for it to finish.
_PROCS: dict[str, set] = {}


def _patch_subprocess() -> None:
    if getattr(subprocess.Popen, "_anoa_tracked", False):
        return
    orig_init = subprocess.Popen.__init__

    def _init(self, *a, **k):
        orig_init(self, *a, **k)
        rid = getattr(_local, "run_id", None)
        if rid:
            _PROCS.setdefault(rid, set()).add(self)
    _init._anoa_tracked = True
    subprocess.Popen.__init__ = _init


class RunPaused(Exception):
    """Raised mid-step to abort a long-running step promptly when pause is requested."""


# Per-thread "current event sink" so the patched Recorder can stream blocks live.
_local = threading.local()


def _emit_patch(pipeline) -> None:
    """Wrap Recorder._add so every block it records is also streamed to the active run,
    and Recorder._live so in-place slot updates stream as `block_live` events (the ticking
    LibreLane stage panel / LLM token stream). Guarded so it can never double-wrap."""
    if not getattr(pipeline.Recorder._add, "_anoa_wrapped", False):
        orig = pipeline.Recorder._add

        def _add(self, kind, payload):
            orig(self, kind, payload)
            sink = getattr(_local, "sink", None)
            if sink is None:
                return
            safe = _safe(payload)
            # rewrite image blocks to a design-relative path the /file endpoint can serve
            if kind == "image" and safe and isinstance(safe[0], str):
                dd = getattr(_local, "design_dir", None)
                if dd:
                    import os
                    try:
                        safe[0] = os.path.relpath(safe[0], dd)
                    except Exception:  # noqa: BLE001
                        pass
            sink({"type": "block", "node": getattr(self, "node", ""),
                  "kind": kind, "payload": safe})
            # responsive pause: if a pause was requested, abort THIS step now (right after
            # emitting the current block) instead of finishing a multi-minute deep-agent step
            cancel = getattr(_local, "cancel", None)
            if cancel is not None and cancel():
                raise RunPaused()
        _add._anoa_wrapped = True
        pipeline.Recorder._add = _add

    if not getattr(pipeline.Recorder._live, "_anoa_wrapped", False):
        orig_live = pipeline.Recorder._live

        def _live(self, slot, kind, payload):
            orig_live(self, slot, kind, payload)
            sink = getattr(_local, "sink", None)
            if sink is None:
                return
            sink({"type": "block_live", "node": getattr(self, "node", ""),
                  "slot": slot, "kind": kind, "payload": _safe(payload)})
            # a live tick is the ONLY emission during a long subprocess (LibreLane) —
            # honor Stop here so pause aborts promptly. A STEER must NOT abort: it would
            # throw away hours of a running harden; it applies at the next step instead.
            rid = getattr(_local, "run_id", "") or ""
            pause = _PAUSE.get(rid)
            if pause is not None and pause.is_set():
                raise RunPaused()
        _live._anoa_wrapped = True
        pipeline.Recorder._live = _live


def _run_step(pipeline, run_obj, node, feedback):
    """Run one step. RunPaused can mean STOP (pause) or STEER (override this step now);
    a crash halts. Returns (record, paused, crashed, steered)."""
    emoji, title, desc, fn, _ = pipeline.STEP_DEFS[node]
    ctx = run_obj["ctx"]
    if node in ("write", "simulate", "fix_design", "fix_testbench"):
        title = f"{title} (attempt {ctx.get('error_count', 0) + 1})"
    rec = pipeline.Recorder(emoji, title, desc, node, live=True)
    rid = getattr(_local, "run_id", "")
    paused = crashed = steered = False
    try:
        from llm import token_usage
        tok0 = token_usage()
    except Exception:  # noqa: BLE001
        tok0 = {}
    try:
        fn(rec, ctx, feedback)
    except RunPaused:
        _local.cancel = None              # stop re-raising while we record the note
        steer_ev, pause_ev = _STEER_EV.get(rid), _PAUSE.get(rid)
        if steer_ev is not None and steer_ev.is_set() and not (pause_ev and pause_ev.is_set()):
            steered = True
            rec.caption("💬 Applying your steer — re-running this step with it…")
        else:
            paused = True
            rec.caption("⏸ Paused mid-step — this step will re-run when you say continue.")
    except Exception as e:  # noqa: BLE001
        crashed = True
        rec.error(f"Step crashed: {e}\nSay **continue** to retry this step (it does NOT skip "
                  "ahead), or **replan**.")
    try:
        pipeline.step_token_report(rec, ctx, node, tok0)   # 🔢 tokens used this step
    except Exception:  # noqa: BLE001
        pass
    return {"node": node, "blocks": rec.blocks}, paused, crashed, steered


def _safe(payload):
    """Make a Recorder block JSON-serializable (tuples → lists, drop unknowns)."""
    import json
    out = []
    for v in (payload if isinstance(payload, (list, tuple)) else [payload]):
        try:
            json.dumps(v)
            out.append(v)
        except (TypeError, ValueError):
            out.append(str(v)[:4000])
    return out


# --- design versioning (git) -------------------------------------------------
# Every step that changes files becomes a VERSION (v1..vN) — the Artifacts panel shows
# GitHub-style history with per-file +green/−red diffs for the RTL, testbenches, notes
# and report sources. Heavy build outputs are ignored; the history stays about the code.
_GITIGNORE = """# AnoaChip design versioning — the DESIGN (rtl/tb/notes/report sources) only,
# never build outputs: those are huge, binary, or regenerated every run.
chip/
macros/
sim/
work/
versions/
context/uploads/
context/anchor/
context/refs/
*.gds
*.vcd
*.vvp
*.png
*.svg
*.pdf
*.nl.v
*.pnl.v
report/*.aux
report/*.log
report/*.toc
report/*.out
__pycache__/
"""


def _commit_design(design_dir, label: str) -> None:
    d = Path(design_dir)
    if not d.is_dir():
        return
    try:
        if not (d / ".git").exists():
            subprocess.run(["git", "init", "-q"], cwd=d, timeout=20, check=True,
                           capture_output=True)
            (d / ".gitignore").write_text(_GITIGNORE)
            subprocess.run(["git", "config", "user.email", "agent@anoachip.local"],
                           cwd=d, timeout=10, capture_output=True)
            subprocess.run(["git", "config", "user.name", "AnoaChip"],
                           cwd=d, timeout=10, capture_output=True)
        subprocess.run(["git", "add", "-A"], cwd=d, timeout=30, capture_output=True)
        staged = subprocess.run(["git", "diff", "--cached", "--quiet"],
                                cwd=d, timeout=30, capture_output=True)
        if staged.returncode != 0:                     # something actually changed
            subprocess.run(["git", "commit", "-q", "-m", label[:120]],
                           cwd=d, timeout=30, capture_output=True)
            _snapshot_version(d, label)
    except Exception:  # noqa: BLE001
        pass


def _snapshot_version(d: Path, label: str) -> None:
    """PHYSICAL version folders too (user: 'folder v1, ..., optimized version, dst'):
    versions/v003_fix_design/ holding rtl/ + tb/ + design_notes.md as they were at that
    version. Read-only history for humans; the agent's file tools skip versions/ so an
    old copy can never be 'restored' to defeat a contract change."""
    import re as _re
    import shutil as _shutil
    vdir = d / "versions"
    vdir.mkdir(exist_ok=True)
    n = len([p for p in vdir.iterdir() if p.is_dir()]) + 1
    slug = _re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:40] or "step"
    snap = vdir / f"v{n:03d}_{slug}"
    snap.mkdir(exist_ok=True)
    for sub in ("rtl", "tb"):
        if (d / sub).is_dir():
            _shutil.copytree(d / sub, snap / sub, dirs_exist_ok=True)
    for f in ("design_notes.md",):
        if (d / f).exists():
            _shutil.copy(d / f, snap / f)
    (snap / "VERSION.txt").write_text(
        f"v{n} — {label}\nRead-only snapshot. The live design is ../../rtl and ../../tb; "
        "diffs are in the Artifacts ▸ Versions panel.\n")


# --- event bus --------------------------------------------------------------
class RunBus:
    """Append-only event log with REPLAY. Every event a run emits is kept, so a (re)connecting
    viewer replays the FULL backlog from index 0 and then continues live. This is what makes a
    reload (or switching chats and back) mid-run RESTORE the whole transcript instead of showing
    an empty stream — the old consume-once Queue dropped every event already read."""
    def __init__(self):
        self.log: list[dict] = []
        self._lock = threading.Lock()
        self.done = False

    def push(self, event: dict):
        with self._lock:
            self.log.append(event)

    def finish(self, status: str):
        self.done = True
        self.push({"type": "end", "status": status})

    def since(self, idx: int):
        """Events from `idx` onward + the new cursor — the replay primitive the stream uses.
        `block_live` updates for the same (node, slot) are COALESCED to the newest within
        the batch: a reconnecting viewer replays each ticking panel once, not the thousands
        of intermediate paints a multi-hour LibreLane run produced."""
        with self._lock:
            batch = self.log[idx:]
            cursor = len(self.log)
        if len(batch) > 1:
            last: dict = {}
            for i, ev in enumerate(batch):
                if ev.get("type") == "block_live":
                    last[(ev.get("node"), ev.get("slot"))] = i
            if last:
                batch = [ev for i, ev in enumerate(batch)
                         if ev.get("type") != "block_live"
                         or last[(ev.get("node"), ev.get("slot"))] == i]
        return batch, cursor


_BUSES: dict[str, RunBus] = {}
_PAUSE: dict[str, "threading.Event"] = {}
_STEER: dict[str, list] = {}        # steering messages sent WHILE a run is working
_STEER_EV: dict[str, "threading.Event"] = {}   # "interrupt the current step and apply now"
_CUR_NODE: dict[str, str] = {}      # the step currently running (for the echo block)
# steps that actually consume feedback (so steering isn't eaten by a mechanical step)
_LLM_STEPS = {"plan", "web", "generate", "testbench", "fix_design", "fix_testbench", "report"}


# a steer mentioning these wants FRESH research → re-run the web step, don't just continue
_RESEARCH_RE = re.compile(
    r"\b(web|github|git ?hub|paper|papers|research|reference|references|find|search|"
    r"look ?up|online|internet|source|sources|context|repo|repos|datasheet)\b", re.I)


def _apply_steer(run_obj: dict) -> str | None:
    """Consume queued steers for this run and route them:
      • research intent ('find web/github/paper…') → re-queue the WEB step so it fetches
        FRESH context, then comes back to the rest of the plan;
      • otherwise → set the steer as feedback for the (re-run) current/next step.
    Returns a note for the transcript, or None if nothing was queued."""
    rid = getattr(_local, "run_id", "")
    steers = _STEER.pop(rid, None)
    if not steers:
        return None
    text = " · ".join(steers)
    run_obj["feedback"] = ((run_obj.get("feedback") or "") + " " + text).strip()
    q = run_obj["queue"]
    if _RESEARCH_RE.search(text):
        if not q or q[0] != "web":
            q.insert(0, "web")          # GO BACK to the researcher with the steer
        return f"🌐 Re-researching web/GitHub/papers with your steer: {text}"
    return f"💬 Steering applied: {text}"


def _unproductive(node: str, ctx: dict) -> str:
    """Reason a step produced nothing (so we RETRY it instead of skipping ahead). Empty
    string = the step produced its expected artifact. web/retrieve are research, so they
    never gate the build."""
    if node == "generate":
        # GLAYOUT-FIRST: the deliverable is the config JSON (spec + wiring + params) — glayout
        # builds the layout from it, so there is NO netlist/RTL to require. Productive == a
        # config JSON exists on disk with a populated `wiring` (component→net) section.
        dd = ctx.get("design_dir")
        cfgs = sorted(Path(dd, "config").glob("*.json")) \
            if dd and Path(dd, "config").is_dir() else []
        if not cfgs:
            return "produced no config JSON"
        try:
            import json as _json
            obj = _json.loads(cfgs[0].read_text(errors="replace"))
        except Exception:  # noqa: BLE001
            return "config JSON is not valid"
        if not (obj.get("wiring") or obj.get("components")):
            return "config has no wiring (component→net connections)"
        return ""
    if node == "decompose":
        return "" if (ctx.get("decomposed_files") or {}) else "produced no modules"
    if node == "testbench":
        tb = ctx.get("testbench_code") or {}
        return "" if any((v or "").strip() for v in tb.values()) else "produced no testbench"
    return ""


def get_bus(run_id: str) -> RunBus | None:
    return _BUSES.get(run_id)


def request_steer(run_id: str, message: str) -> bool:
    """Steer a LIVE run. The message is (1) ECHOED into the transcript immediately so the
    user sees their intent right away, and (2) used to INTERRUPT the current step and
    re-run it with the steering applied (override the current state), falling back to the
    next step if the current one can't be interrupted. Returns True if the run is live."""
    message = (message or "").strip()
    if not message or run_id not in _PAUSE:
        return False
    _STEER.setdefault(run_id, []).append(message)
    bus = _BUSES.get(run_id)
    if bus:                                   # show the user's message instantly
        bus.push({"type": "block", "node": _CUR_NODE.get(run_id, "generate"),
                  "kind": "info", "payload": [f"💬 You: {message}"]})
    ev = _STEER_EV.get(run_id)
    if ev:                                    # interrupt the current step to apply now
        ev.set()
    return True


def request_pause(run_id: str) -> bool:
    """Stop a run fast: KILL any live subprocess it spawned (iverilog/verilator/LibreLane/
    crawler) and set the pause flag so the loop stops at the next checkpoint. State is
    saved, so 'continue' resumes. Returns True if the run was live."""
    for p in list(_PROCS.get(run_id, ())):
        try:
            if p.poll() is None:
                p.kill()
        except Exception:  # noqa: BLE001
            pass
    ev = _PAUSE.get(run_id)
    if ev is not None:
        ev.set()
        return True
    return False


# --- a tiny uploaded-file wrapper new_run()/_save_uploads understand --------
class _Upload:
    def __init__(self, name: str, data: bytes):
        self.name = name
        self._d = data

    def getvalue(self) -> bytes:
        return self._d


# --- public entry -----------------------------------------------------------
def looks_like_followup(prompt: str) -> bool:
    """Does the deterministic continuation regex already recognize this message?"""
    return bool(_pipeline().CONTINUE_RE.search(prompt or ""))


def start_run(*, chat_id: str, message_id: str, prompt: str,
              files: list[dict] | None = None, opts: dict | None = None,
              force_continue: bool = False) -> dict:
    """Create a run row + bus, launch the pipeline thread, return the run record.
    `force_continue=True` (from the intent classifier) treats the message as a follow-up
    on the existing design even when no continuation keyword matches."""
    pipeline = _pipeline()
    db.clear_control_messages(chat_id)   # the user acted → drop any stale '⏸ Paused' bubble
    opts = opts or {}
    uploads = [_Upload(f["name"], f["data"]) for f in (files or []) if f.get("data")]

    # CONTINUE an existing design instead of rebuilding: if THIS chat already produced a design
    # (rtl/ has files) and the message reads like a continuation ("redo the testbench/harden",
    # "fix", "continue", "the design"), reuse that folder + run only the asked steps — so a
    # follow-up doesn't wipe to an empty dir named after the message and re-plan from scratch.
    prior = None
    try:
        from pathlib import Path
        if (force_continue or pipeline.CONTINUE_RE.search(prompt or "")) and not uploads:
            # the most RECENT run whose design actually has RTL on disk (skip empty re-plans)
            for r in db.designs_for_chat(chat_id):
                dd = r.get("design_dir")
                if not dd:
                    continue
                rtl = Path(dd) / "rtl"
                if rtl.is_dir() and (any(rtl.glob("*.v")) or any(rtl.glob("*.sv"))):
                    prior = r
                    break
    except Exception:
        prior = None

    spec_overrides = {"gain_db": opts.get("gain_db"), "bw_hz": opts.get("bw_hz")}
    sim_types = opts.get("sim_types")
    if prior:
        run_obj = pipeline.continue_run(
            prior.get("query") or prompt, prior["design_dir"], prompt,
            opts.get("run_harden", False), opts.get("clock_port", "clk"),
            float(opts.get("clock_period", 24.0)), float(opts.get("die_um", 600.0)),
            int(opts.get("core_util", 25)),
            autonomous=True, deep_steps=opts.get("deep_steps", True),
            prior_ctx=prior.get("ctx") if isinstance(prior.get("ctx"), dict) else None,
            num_ctx=opts.get("num_ctx"), model=opts.get("model"),
            spec_overrides=spec_overrides, sim_types=sim_types)
    else:
        run_obj = pipeline.new_run(
            prompt,
            opts.get("use_web", True),
            opts.get("run_harden", False),
            opts.get("clock_port", "clk"),
            float(opts.get("clock_period", 24.0)),
            float(opts.get("die_um", 600.0)),
            int(opts.get("core_util", 25)),
            autonomous=True,
            deep_steps=opts.get("deep_steps", True),
            uploads=uploads,
            num_ctx=opts.get("num_ctx"),
            model=opts.get("model"),
            spec_overrides=spec_overrides,
            sim_types=sim_types,
            chat_id=chat_id,
        )
    design_dir = run_obj["ctx"]["design_dir"]
    rec = db.create_run(chat_id, message_id, prompt, design_dir)
    bus = RunBus()
    _BUSES[rec["id"]] = bus
    _PAUSE[rec["id"]] = threading.Event()
    _STEER_EV[rec["id"]] = threading.Event()

    t = threading.Thread(target=_execute, args=(rec["id"], run_obj, bus), daemon=True)
    t.start()
    return rec


def _execute(run_id: str, run_obj: dict, bus: RunBus) -> None:
    pipeline = _pipeline()
    _local.sink = bus.push
    _local.run_id = run_id           # so spawned subprocesses are tracked for Stop
    ctx = run_obj["ctx"]
    design_dir = ctx["design_dir"]
    _local.design_dir = design_dir
    pause_ev = _PAUSE.get(run_id)
    steer_ev = _STEER_EV.get(run_id)
    # lets the streamed Recorder abort the current step on a pause OR a steer (override now)
    _local.cancel = lambda: (pause_ev is not None and pause_ev.is_set()) or \
                            (steer_ev is not None and steer_ev.is_set())
    design = Path(design_dir).name
    status = "done"
    paused = False
    crashed = False
    try:
        from memory_store import get_memory
        mem = get_memory()
        # uploaded files → knowledge store immediately (live)
        _ingest_uploads(mem, Path(design_dir), design)
        # on a resume that re-runs the interrupted step, drop its partial card in the UI
        if run_obj.pop("_trim", False):
            bus.push({"type": "trim"})

        guard = 0
        while run_obj["queue"] and guard < 200:
            guard += 1
            # route a steer queued BETWEEN steps before choosing the next step (research
            # intent re-queues 'web'; otherwise it becomes feedback for the next step)
            if _STEER.get(run_id):
                note = _apply_steer(run_obj)
                if steer_ev:
                    steer_ev.clear()
                if note:
                    bus.push({"type": "block", "node": run_obj["queue"][0] if run_obj["queue"]
                              else "web", "kind": "info", "payload": [note]})
            node = run_obj["queue"].pop(0)
            _CUR_NODE[run_id] = node
            bus.push({"type": "step", "node": node})
            # _run_step: RunPaused → pause(stop) OR steer(override now); crash → halt
            record, step_paused, step_crashed, step_steered = _run_step(
                pipeline, run_obj, node, run_obj.pop("feedback", ""))
            run_obj["transcript"].append(record)
            if step_steered:
                # the user steered DURING this step → re-run it (or re-research) with the
                # steer applied NOW, never just continuing to the next step.
                if steer_ev:
                    steer_ev.clear()
                run_obj["queue"].insert(0, node)          # come back to this step…
                note = _apply_steer(run_obj)              # …after 'web' if research intent
                if note:
                    bus.push({"type": "block", "node": node, "kind": "info", "payload": [note]})
                db.update_run(run_id, status="running", ctx=ctx,
                              transcript=_records(run_obj["transcript"]),
                              queue=run_obj["queue"], pending=node)
                continue
            if step_crashed:
                # crashes are often a transient local-model glitch → AUTO-RETRY (bounded),
                # never skip ahead; only halt after it keeps failing.
                ck = f"_crash_{node}"
                ctx[ck] = ctx.get(ck, 0) + 1
                run_obj["queue"].insert(0, node)
                if ctx[ck] < 3:
                    bus.push({"type": "block", "node": node, "kind": "warning",
                              "payload": [f"↻ {node} crashed (transient) — auto-retrying "
                                          f"(attempt {ctx[ck] + 1}); not skipping ahead."]})
                    db.update_run(run_id, status="running", ctx=ctx,
                                  transcript=_records(run_obj["transcript"]),
                                  queue=run_obj["queue"], pending=node)
                    continue
                paused = True
                crashed = True
                db.update_run(run_id, status="paused", ctx=ctx,
                              transcript=_records(run_obj["transcript"]),
                              queue=run_obj["queue"], pending=node)
                break
            if step_paused:
                # user pressed Stop → halt; state saved, `continue` resumes this step.
                paused = True
                run_obj["queue"].insert(0, node)
                db.update_run(run_id, status="paused", ctx=ctx,
                              transcript=_records(run_obj["transcript"]),
                              queue=run_obj["queue"], pending=node)
                break
            # NEVER SKIP a step that produced nothing. Retry that same step (bounded),
            # then HALT — do NOT fall through to the next step with empty/garbage state.
            why = _unproductive(node, ctx)
            if why:
                key = f"_retry_{node}"
                ctx[key] = ctx.get(key, 0) + 1
                run_obj["queue"].insert(0, node)          # re-run THIS step, never skip
                if ctx[key] < 3:
                    bus.push({"type": "block", "node": node, "kind": "warning",
                              "payload": [f"↻ {node}: {why} — retrying (attempt {ctx[key] + 1}); "
                                          "NOT skipping to the next step."]})
                    db.update_run(run_id, status="running", ctx=ctx,
                                  transcript=_records(run_obj["transcript"]),
                                  queue=run_obj["queue"], pending=node)
                    continue
                paused = True
                crashed = True
                bus.push({"type": "block", "node": node, "kind": "error",
                          "payload": [f"{node}: {why} after 3 tries — refine the prompt or steer, "
                                      "then **continue**. (Did NOT skip ahead.)"]})
                db.update_run(run_id, status="paused", ctx=ctx,
                              transcript=_records(run_obj["transcript"]),
                              queue=run_obj["queue"], pending=node)
                break
            pipeline.advance(run_obj, node)
            run_obj["pending"] = node
            # persist FULL resumable state after each step
            db.update_run(run_id, status="running", ctx=ctx,
                          transcript=_records(run_obj["transcript"]),
                          queue=run_obj["queue"], pending=node)
            # VERSION the design like git history (v1..vN) — the Artifacts panel
            # shows what each step added (+) and removed (−) in rtl/, tb/, notes.
            att = ctx.get("error_count", 0)
            _commit_design(design_dir, node + (f" (attempt {att + 1})"
                                               if node in ("write", "fix_design",
                                                           "fix_testbench") else ""))
            # add to the knowledge store only at meaningful events (insight / research /
            # problem→fix), not a blind per-step file dump
            _ingest_event(mem, bus, run_obj, node, Path(design_dir), design)
            # also honor a pause that arrived during a non-streaming (subprocess) step
            if pause_ev is not None and pause_ev.is_set():
                paused = True
                break
        if not paused:
            pipeline.finalize(run_obj)
            _ingest_final(mem, bus, run_obj, Path(design_dir), design)   # keep verified designs
    except Exception as exc:  # noqa: BLE001
        status = "error"
        bus.push({"type": "block", "node": "error", "kind": "error",
                  "payload": [f"Run crashed: {exc}"]})
    finally:
        _local.sink = None
        _local.cancel = None
        status = "paused" if paused else status
        run_obj["status"] = status
        db.update_run(run_id, status=status, ctx=ctx,
                      transcript=_records(run_obj["transcript"]),
                      queue=run_obj["queue"], pending=run_obj.get("pending"))
        chat_id = db.get_run(run_id)["chat_id"]
        if crashed:
            db.add_message(chat_id, "assistant",
                           "⚠️ A step crashed (e.g. a timeout). Say **continue** to retry that "
                           "same step — it will NOT skip ahead — or **replan**.")
        elif paused:
            db.add_message(chat_id, "assistant",
                           "⏸ Paused. Say **continue** to resume from here.")
        else:
            db.add_message(chat_id, "assistant", _summary(run_obj))
        bus.finish(status)
        _PAUSE.pop(run_id, None)
        _PROCS.pop(run_id, None)
        _STEER.pop(run_id, None)
        _STEER_EV.pop(run_id, None)
        _CUR_NODE.pop(run_id, None)
        _local.run_id = None


def _records(transcript) -> list:
    """Normalize a transcript to JSON-safe records. Handles both live records (blocks
    are (kind, payload) tuples) and re-hydrated records (blocks are {kind,payload} dicts),
    so resuming a run from the DB and appending new steps works seamlessly."""
    out = []
    for r in transcript:
        norm = []
        for b in r.get("blocks", []):
            if isinstance(b, dict):
                norm.append({"kind": b.get("kind"), "payload": _safe(b.get("payload", []))})
            else:
                k, p = b
                norm.append({"kind": k, "payload": _safe(p)})
        out.append({"node": r.get("node"), "blocks": norm})
    return out


# words that mean "pick up where you left off"
_CONTINUE = ("continue", "please continue", "keep going", "resume", "carry on",
             "lanjut", "lanjutkan", "teruskan", "gas", "next")


def is_continue(prompt: str) -> bool:
    p = (prompt or "").strip().lower()
    return any(p == w or p.startswith(w) for w in _CONTINUE)


def classify_intent(prompt: str) -> str:
    """UNDERSTAND the user's intent with the model — not string matching (user: 'daripada
    fuzzy mending kamu mengerti maksud user'). Called only when the deterministic routes
    don't match, in a chat that already has a design. Returns:
      'continue'  — resume where it left off (any phrasing/typo/language)
      'followup'  — an instruction about the EXISTING design (fix/shrink/harden/report/…)
      'new'       — a genuinely new, different piece of hardware to build from scratch
    """
    try:
        from llm import get_chat_model
        out = get_chat_model(temperature=0.0).invoke(
            "You route messages for a chip-design agent. This chat ALREADY HAS a built "
            "design (RTL + testbenches on disk).\n"
            f"USER MESSAGE: «{(prompt or '')[:400]}»\n\n"
            "What does the user want? Answer with EXACTLY one word:\n"
            "continue — resume/keep going (any language, typos included)\n"
            "followup — do something to the EXISTING design (fix, change, shrink, "
            "resize, harden, simulate, report, a question about it)\n"
            "new — build a DIFFERENT new piece of hardware from scratch\n")
        text = (getattr(out, "content", "") or "").strip().lower()
        if "continue" in text:
            return "continue"
        if "new" in text:
            return "new"
        return "followup"
    except Exception:  # noqa: BLE001
        return "followup"      # safest default: never wipe into a fresh build on a guess


def has_design(chat_id: str) -> bool:
    """True when some run in this chat left real RTL on disk — the precondition for any
    'continue' to make sense (used to refuse a bogus fresh build on the literal word)."""
    try:
        for r in db.designs_for_chat(chat_id):
            dd = r.get("design_dir")
            if dd and (Path(dd) / "rtl").is_dir() and (
                    any((Path(dd) / "rtl").glob("*.v")) or any((Path(dd) / "rtl").glob("*.sv"))):
                return True
    except Exception:  # noqa: BLE001
        pass
    return False


def resume_run(*, chat_id: str, message_id: str) -> dict | None:
    """Rebuild the latest run for a chat from its SAVED state (ctx + queue + transcript +
    files on disk) and continue the pipeline from where it stopped. Returns the run rec,
    or None if there's nothing resumable."""
    pipeline = _pipeline()
    db.clear_control_messages(chat_id)   # the user acted → drop any stale '⏸ Paused' bubble
    prev = db.latest_run_for_chat(chat_id)
    if not prev:
        return None
    ctx = prev.get("ctx") or {}
    queue = prev.get("queue") or []
    design_dir = prev.get("design_dir") or ctx.get("design_dir")
    if not design_dir or not Path(design_dir).exists():
        return None
    ctx["design_dir"] = design_dir
    # re-apply the model + context window the run was started with, so resuming after a server
    # restart (which clears the process-global overrides) uses the SAME Ollama model, not the default.
    try:
        from llm import set_model, set_num_ctx
        set_model(ctx.get("model"))
        set_num_ctx(ctx.get("num_ctx"))
    except Exception:  # noqa: BLE001
        pass
    # GLAYOUT-FIRST designs (config JSON, no hand-written .sp) NEVER resume into the legacy
    # SPICE loop: scrub testbench/write/simulate/lint stages from the saved queue and reset
    # a top name poisoned by an LVS artifact (the saved 'CASCODE_CMIRROR' bug — user:
    # 'rename it, correct workflow'). Verification happens post-layout (pex → pl_sim).
    dd = Path(design_dir)
    cfgs = sorted((dd / "config").glob("*.json")) if (dd / "config").is_dir() else []
    nd = dd / "netlist"
    json_only = bool(cfgs) and (not nd.is_dir()
                                or not (list(nd.glob("*.sp")) + list(nd.glob("*.spice"))))
    if json_only:
        ctx["top_module_name"] = cfgs[0].stem            # the config IS the design's name
        ctx.pop("simulation_output", None)
        legacy = {"testbench", "write", "simulate", "lint", "decompose",
                  "fix_testbench", "fix_design", "correct"}
        queue = [s for s in queue if s not in legacy]
        if not queue:
            gds_ok = False
            try:
                import json as _json
                vj = next(iter((dd / "layout").glob("verify_*.json")), None)
                if vj:
                    v = _json.loads(vj.read_text())
                    gds_ok = bool(v.get("build", {}).get("ok")
                                  and v.get("drc", {}).get("is_pass")
                                  and v.get("lvs", {}).get("is_pass"))
            except Exception:  # noqa: BLE001
                pass
            queue = ["pex", "pl_sim", "report"] if gds_ok else ["harden"]
    # if the run had already drained its queue, decide a sensible continuation
    if not queue:
        if ctx.get("simulation_output"):
            queue = ["fix_design", "write", "simulate"]   # still broken → keep fixing
        elif ctx.get("run_harden") and not (ctx.get("harden") or {}).get("gds"):
            # RE-VERIFY first — never jump straight to harden on a resume: simulate
            # re-runs the unit + integration testbenches, and advance() only chains
            # lint → harden when they PASS (the "jangan harden kalau masih error" rule).
            queue = ["simulate"]
        else:
            return None                                    # nothing left to do

    transcript = prev.get("transcript") or []
    # If we're re-running the step that was interrupted (its partial card is the last one),
    # drop that partial card and tell the UI to remove it — so continue shows ONE clean card
    # for the step, not the aborted one + the redo.
    trim = bool(transcript and queue and transcript[-1].get("node") == queue[0])
    if trim:
        transcript = transcript[:-1]

    run_obj = {"ctx": ctx, "queue": list(queue), "transcript": transcript,
               "status": "running", "pending": prev.get("pending"), "autonomous": True,
               "_trim": trim}
    # re-read the RTL/TB the previous run wrote, so the pipeline uses the real disk state
    try:
        pipeline._sync_ctx_from_disk(ctx)
    except Exception:  # noqa: BLE001
        pass

    rec = db.create_run(chat_id, message_id, ctx.get("query", "continue"), design_dir)
    bus = RunBus()
    _BUSES[rec["id"]] = bus
    _PAUSE[rec["id"]] = threading.Event()
    _STEER_EV[rec["id"]] = threading.Event()
    threading.Thread(target=_execute, args=(rec["id"], run_obj, bus), daemon=True).start()
    return rec


def _summary(run_obj) -> str:
    ctx = run_obj["ctx"]
    top = ctx.get("top_module_name") or "design"
    report = (" 📕 Report: `" + Path(ctx["report_pdf"]).name + "` (see the report card / "
              "Artifacts).") if ctx.get("report_pdf") else ""
    if ctx.get("simulation_output") or ctx.get("_sim_unverified"):
        return (f"⚠️ `{top}` — verification is NOT passing after the retry budget "
                f"({ctx.get('error_count', 0)} fix attempts). Per your rule, it was NOT "
                "hardened. Steer with a hint about the failing block, or say **force harden** "
                f"to override.{report}")
    # ANALOG flow stores the layout result in harden_metrics (gds/drc/lvs); the legacy
    # digital dict was ctx['harden'] — read both so the final banner never lies about a
    # GDS that exists (user hit '⚠ did NOT produce a GDS' under a DRC+LVS-clean layout).
    harden = ctx.get("harden") if isinstance(ctx.get("harden"), dict) else {}
    hm = ctx.get("harden_metrics") if isinstance(ctx.get("harden_metrics"), dict) else {}
    gds = hm.get("gds") or harden.get("gds")
    sim_note = "design verified"
    if gds:
        drc, lvs = hm.get("drc"), hm.get("lvs")
        checks = f" (DRC {drc} · LVS {lvs})" if drc or lvs else ""
        if ctx.get("plsim_error"):
            return (f"⚠️ `{top}` — GDSII generated{checks}, BUT the post-layout testbench "
                    f"produced no simulation plots: {str(ctx['plsim_error'])[:160]} — "
                    f"steer with a testbench hint to retry.{report}")
        return f"✅ `{top}` — {sim_note}; GDSII generated{checks}.{report}"
    # Layout was REQUESTED but produced no GDS — don't show a green ✅: it doesn't exist.
    if ctx.get("run_harden") or harden or ctx.get("harden_error"):
        why = (ctx.get("harden_error") or "")[:160]
        return (f"⚠️ `{top}` — {sim_note}, but the layout did NOT produce a GDS"
                + (f" — {why}" if why else " — see the layout step") + f".{report}")
    return f"✅ `{top}` — {sim_note}. (Layout was not requested.){report}"


# --- live knowledge ingest (only newly-written files) -----------------------
def _ingest_uploads(mem, design_dir: Path, design: str) -> None:
    if not getattr(mem, "enabled", False):
        return
    for p in (design_dir / "context" / "uploads").glob("*"):
        if p.is_file():
            try:
                mem.ingest_file(p, design=design, source=f"upload:{design}")
            except Exception:  # noqa: BLE001
                pass


def _emit_knowledge(bus, mem) -> None:
    """Tell the UI the knowledge store changed (so the badge updates on real events,
    not on a blind timer)."""
    try:
        bus.push({"type": "knowledge", "total": (mem.stats() or {}).get("total", 0)})
    except Exception:  # noqa: BLE001
        pass


def _ingest_event(mem, bus, run_obj, node: str, design_dir: Path, design: str) -> None:
    """Add to the knowledge store at MEANINGFUL moments only:
      • plan      → the architecture note (a design insight)
      • web       → the research digest (papers/code/github already stored by the pipeline)
      • simulate  → if it now PASSES after a prior error, remember the PROBLEM→FIX lesson
                    so the same mistake isn't repeated; track the error otherwise
      • lint      → track the structural error for the eventual fix lesson
    """
    if not getattr(mem, "enabled", False):
        return
    ctx = run_obj["ctx"]
    added = 0
    if node == "plan":
        f = design_dir / "design_notes.md"
        if f.exists() and mem.ingest_file(f, design=design, source=f"insight:{design}"):
            added += 1
    elif node == "web":
        f = design_dir / "context" / "research.md"
        if f.exists() and mem.ingest_file(f, design=design, source=f"research:{design}"):
            added += 1
    elif node == "lint":
        if ctx.get("lint_output"):
            run_obj["_last_error"] = ctx["lint_output"][:1500]
    elif node == "simulate":
        if ctx.get("simulation_output"):                 # still failing → remember the error
            run_obj["_last_error"] = ctx["simulation_output"][:1500]
        elif run_obj.get("_last_error"):                 # PASS after a problem → store the fix
            mem.remember(
                "fix",
                f"PROBLEM:\n{run_obj['_last_error']}\n\nRESOLVED in design '{design}' — the "
                f"corrected, simulation-passing RTL is stored as code for '{design}'.",
                design=design, source=f"fix:{design}",
                title=f"fix: {run_obj['_last_error'][:90]}", tags="fix")
            run_obj["_last_error"] = ""
            added += 1
    if added:
        _emit_knowledge(bus, mem)


def _ingest_final(mem, bus, run_obj, design_dir: Path, design: str) -> None:
    """On a VERIFIED finish, store the working design (RTL = reusable code knowledge +
    a one-line 'design' summary). Only when simulation passed — we keep good designs,
    not broken ones."""
    if not getattr(mem, "enabled", False):
        return
    ctx = run_obj["ctx"]
    if ctx.get("simulation_output"):
        return
    added = 0
    rtl = list((design_dir / "rtl").glob("*.v")) + list((design_dir / "rtl").glob("*.vh"))
    for p in rtl:
        if mem.ingest_file(p, design=design, source=f"verified:{design}"):
            added += 1
    mem.remember(
        "design",
        f"VERIFIED design: {ctx.get('query', '')}\nTop module: {ctx.get('top_module_name')}\n"
        f"Modules: " + ", ".join(p.name for p in rtl),
        design=design, source=f"verified:{design}",
        title=(ctx.get("query") or design)[:120], tags="design verified")
    if added:
        _emit_knowledge(bus, mem)
