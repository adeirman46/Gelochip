"""Tool implementations the PandaChip agent exposes to the LLM.

Every EDA action goes through the OpenADA CLI; the EDA binaries themselves
run inside the pandachip-eda IIC-OSIC-TOOLS container via toolbin/ wrappers.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
from pathlib import Path

from .rawread import read_raw

ROOT = Path(__file__).resolve().parents[1]
TOOLBIN = ROOT / "toolbin"
OPENADA = ROOT / ".venv" / "bin" / "openada"

MAX_TEXT = 6000

# The workflow timeline. A phase is only ever "reached" because the tool
# layer SAW the work happen - the model announcing it is just a hint.
PHASES = ("spec_ingestion", "plan", "sch_gen", "tb_gen", "sim")


def _env() -> dict:
    env = dict(os.environ)
    env["PATH"] = f"{TOOLBIN}:{env.get('PATH', '')}"
    return env



_SI = {"t":1e12,"g":1e9,"meg":1e6,"x":1e6,"k":1e3,"m":1e-3,"u":1e-6,
       "n":1e-9,"p":1e-12,"f":1e-15}
def _si(tok: str):
    """Parse a SPICE number with an optional SI suffix -> float, or None."""
    import re as _r
    m=_r.match(r"^([-+]?[0-9.]+(?:[eE][-+]?[0-9]+)?)([a-zA-Z]*)$", tok.strip())
    if not m: return None
    val=float(m.group(1)); suf=m.group(2).lower()
    if suf.startswith("meg"): return val*1e6
    return val*_SI.get(suf[:1] if suf else "", 1.0) if suf else val

class Workspace:
    """A run directory; all agent file paths are resolved inside it."""

    def __init__(self, path: str | Path):
        self.root = Path(path).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.tmp = self.root / ".tmp"
        self.tmp.mkdir(exist_ok=True)
        # consecutive not-passing simulations per deck, to refuse the
        # "re-run the same deck and hope" loop
        self._sim_tries: dict[str, int] = {}

    def _reset_tries(self, stem: str) -> None:
        """A file changed: the decks it feeds deserve fresh attempts."""
        base = stem.removesuffix("_ctrl")
        for key in list(self._sim_tries):
            k = Path(key).stem.removesuffix("_ctrl")
            if k == base or k.startswith(base) or base.startswith(k):
                del self._sim_tries[key]

    def resolve(self, rel: str) -> Path:
        # The workspace IS the filesystem root as far as the agent is
        # concerned, and deep-agent harnesses address files that way
        # ("/plan.md"). Anchor such paths at the workspace instead of
        # treating them as an escape attempt.
        rel = str(rel).lstrip("/") or "."
        p = (self.root / rel).resolve()
        if not str(p).startswith(str(self.root)):
            raise ValueError(f"path escapes workspace: {rel}")
        return p

    # ---- tools -----------------------------------------------------------

    def write_file(self, path: str, content: str) -> dict:
        p = self.resolve(path)
        # The plan documents are the FULL-CHAIN contract. A block-designer
        # replacing them with its own block-only view is how a complete
        # plan degrades into "bias_match block plan" - so a rewrite that
        # shrinks an existing contract is refused; revisions must extend.
        if (p.name.endswith("_plan.md") or
                p.name in ("plan.md", "test_method.md")) and p.exists():
            old = p.stat().st_size
            if old >= 600 and len(content) < 0.6 * old:
                return {"ok": False, "error": "plan narrowing refused",
                        "instruction":
                            f"{p.name} already holds a contract "
                            f"({old} bytes); your write ({len(content)} "
                            "bytes) would replace it with a narrower one. "
                            "READ the existing file and APPEND or extend "
                            "it instead of rewriting it."}
        # ONE BLOCK AT A TIME. Promoting a new block to the workspace root
        # while an earlier block still has no passing testbench is exactly
        # the skipping that produces a pile of unverified schematics. The
        # exp/ tree stays wide open - that is where versions are tried.
        if p.suffix == ".sch" and p.parent == self.root and not p.exists() \
                and not self._is_apparatus(p.stem):
            # Promotion is EARNED BY EXPERIMENT. A block promoted straight
            # from v1 was never compared against anything, so there is no
            # basis for calling it the best - only the first that ran.
            tried = sorted((self.root / "exp").glob(f"{p.stem}_v*.sch"))
            simulated = [v for v in tried
                         if (v.with_suffix(".raw").exists()
                             or any((self.root / "exp").glob(f"{v.stem}*.raw"))
                             or (self.root / f"{v.stem}.raw").exists())]
            top_syms_pre = self._instantiated_blocks(content)
            is_top_pre = bool({s for s in top_syms_pre
                               if (self.root / f"{s}.sym").exists()})
            if not is_top_pre and len(simulated) < 3:
                return {"ok": False, "error": "not enough experiments",
                        "versions_simulated": [v.name for v in simulated],
                        "instruction":
                            f"Do not promote {p.stem} yet. You have "
                            f"{len(simulated)} simulated version(s) under "
                            f"exp/. Build and SIMULATE at least 3 distinct "
                            f"candidates (exp/{p.stem}_v1.sch, _v2, _v3 ...), "
                            "changing one thing at a time and measuring each "
                            "against test_method.md, then promote the one "
                            "with the best margin - not the first that ran."}
            pending = [b for b in self.unverified_blocks() if b != p.stem]
            top_syms = self._instantiated_blocks(content)
            is_top = bool({s for s in top_syms
                           if (self.root / f"{s}.sym").exists()})
            if pending:
                return {"ok": False, "error": "previous block not verified",
                        "unverified": pending,
                        "instruction":
                            f"Finish {pending[0]} first: iterate it under "
                            f"exp/ ({pending[0]}_v1.sch, _v2...), run its "
                            f"{pending[0]}_verify.spice deck, analyze_raw its "
                            f"nodes against test_method.md, and only when it "
                            f"PASSES promote it and start "
                            f"{'the toplevel' if is_top else p.stem}. "
                            "Never leave a block behind unverified."}
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        # Planning is complete only with BOTH the design plan and the test
        # method that says how each block's I/O will be proven correct.
        if (p.name.endswith("_plan.md") or
                p.name in ("plan.md", "test_method.md")) \
                and len(content) >= 400 \
                and any(c.isdigit() for c in content):
            self.mark_phase("spec_ingestion", "spec was read to write plans")
            if not self.planning_gaps():
                self.mark_phase("plan", "toplevel + per-block plans written")
        self._reset_tries(p.stem)  # the file changed: decks get fresh tries
        return {"ok": True, "path": str(p.relative_to(self.root)), "bytes": len(content)}

    def read_file(self, path: str) -> dict:
        p = self.resolve(path)
        if not p.exists():
            return {"ok": False, "error": f"no such file: {path}"}
        text = p.read_text(errors="replace")
        if p.name == "task.md":
            self.mark_phase("spec_ingestion", "task.md was read")
        clipped = len(text) > MAX_TEXT
        return {"ok": True, "path": path, "content": text[:MAX_TEXT], "clipped": clipped}

    def _openada(self, args: list[str]) -> dict:
        env = _env()
        env["TMPDIR"] = str(self.tmp)
        # xschem binds a fixed TCP port (2022) on startup, so two netlist
        # calls at once - two runs, or a run plus the open GUI - make one
        # of them die with exit code 10. The agent reads that as "my
        # schematic is broken" and redraws a perfectly good circuit, which
        # is how a block burns ten versions going nowhere. Serialize every
        # EDA invocation across all processes on this machine.
        import fcntl as _fcntl
        with open("/tmp/pandachip-eda.lock", "w") as lock:
            _fcntl.flock(lock, _fcntl.LOCK_EX)
            proc = subprocess.run(
                [str(OPENADA), *args],
                capture_output=True, text=True, env=env, cwd=self.root,
                timeout=600,
            )
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError:
            return {
                "execution": {"status": "failed"},
                "engineering": {"status": "unknown",
                                "summary": f"openada produced no JSON (exit {proc.returncode})"},
                "diagnostics": [{"severity": "error",
                                 "message": (proc.stderr or proc.stdout)[-1500:]}],
            }

    @staticmethod
    def _compact(result: dict, extra: dict | None = None) -> dict:
        out = {
            "execution": result.get("execution", {}).get("status"),
            "engineering": result.get("engineering", {}).get("status"),
            "summary": result.get("engineering", {}).get("summary"),
            "diagnostics": [
                {"severity": d.get("severity"), "code": d.get("code"),
                 "message": str(d.get("message"))[:800]}
                for d in result.get("diagnostics", [])[:8]
            ],
            "artifacts": [a.get("path") for a in result.get("artifacts", [])],
        }
        if extra:
            out.update(extra)
        return out

    # ---- phase ledger ----------------------------------------------------
    # A phase is 'running' because the model said so, but only ever 'done'
    # because this tool layer WITNESSED the artifact that defines it. The
    # model cannot mark its own homework.

    def _phases_path(self) -> Path:
        return self.root / "phases.json"

    def load_phases(self) -> dict:
        """The ledger as {phase: {status, ...}}; migrates the old log.

        Status is always DERIVED from banked evidence on the way out, so a
        stale file can never report a phase as pending while the work that
        precedes it is already done.
        """
        blank = {ph: {"status": "pending"} for ph in PHASES}
        path = self._phases_path()
        if not path.exists():
            return blank
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            return blank
        if isinstance(data, dict):
            for ph in PHASES:
                data.setdefault(ph, {"status": "pending"})
                # Ledgers written before status was derived carry only
                # "done"; treat that as the banked evidence it stood for.
                if data[ph].get("status") == "done":
                    data[ph]["evidence"] = True
            return self._resync(data)
        if isinstance(data, list):  # legacy append-only announcements
            for entry in data:
                ph = entry.get("phase")
                if ph in blank:
                    blank[ph] = {"status": "running", "at": entry.get("at")}
        return blank

    def resync_phases(self) -> dict:
        """Re-derive and PERSIST the ledger (the web UI reads the file)."""
        ledger = self._resync(self.load_phases())
        self._save_phases(ledger)
        return ledger

    def _save_phases(self, ledger: dict) -> None:
        self._phases_path().write_text(json.dumps(ledger, indent=1))

    @staticmethod
    def _now() -> str:
        import time as _time
        return _time.strftime("%H:%M:%S")

    def set_phase(self, phase: str) -> dict:
        """The model announcing which phase it is working in.

        This marks the phase 'running' only. It never marks it 'done' -
        that takes evidence (see mark_phase). Re-announcing a phase that
        already earned its evidence does not demote it. Entering 'sim'
        is refused outright while the system to simulate does not exist.
        """
        if phase not in PHASES:
            return {"ok": False, "error": f"phase must be one of {PHASES}"}
        # Credit whatever is already on disk before judging the request:
        # files written through another toolset are still evidence, and
        # refusing a phase whose predecessor is visibly complete is a lie.
        ledger = self.reconcile_phases()
        # STRICT SEQUENCE. A phase cannot be entered while any earlier one
        # is still missing its evidence - that is what let a run show PLAN
        # and SCH GEN both in progress with neither actually finished.
        behind = [p for p in PHASES[:PHASES.index(phase)]
                  if ledger[p].get("status") != "done"]
        if behind:
            return {"ok": False, "phase": phase,
                    "error": f"cannot enter '{phase}': earlier phase(s) "
                             f"{behind} have not produced their evidence",
                    "finish_first": behind,
                    "unmet": (self.planning_gaps() if "plan" in behind
                              else self.integration_gaps())[:6],
                    "instruction": f"Complete {behind[0]} first. The phases "
                                   "run in order and none may be skipped."}
        if phase in ("tb_gen", "sim"):
            blocking = self.integration_gaps()
            if blocking:
                return {"ok": False, "phase": phase,
                        "error": f"cannot enter '{phase}': the integrated "
                                 "design does not exist yet",
                        "fix_first": blocking[:6],
                        "instruction": "Finish sch_gen: draw and netlist "
                                       "EVERY block, then the toplevel that "
                                       "wires the whole chain, before "
                                       "building testbenches or simulating."}
        # Exactly ONE phase is announced at a time, and _resync decides
        # what that means for the displayed status.
        for other in PHASES:
            ledger[other].pop("announced", None)
        ledger[phase]["announced"] = True
        ledger[phase].setdefault("at", self._now())
        self._resync(ledger)
        self._save_phases(ledger)
        pending = [p for p in PHASES if ledger[p].get("status") != "done"]
        return {"ok": True, "phase": phase, "status": ledger[phase]["status"],
                "note": "Announced only. This phase counts as complete when "
                        "its evidence exists.",
                "phases_without_evidence": pending}

    def mark_phase(self, phase: str, note: str) -> None:
        """Record that a phase's defining artifact was witnessed.

        This banks EVIDENCE; it does not by itself paint the phase done.
        Status is derived in _resync so a later phase can never show
        complete while an earlier one is still outstanding.
        """
        if phase not in PHASES:
            return
        ledger = self.load_phases()
        if ledger[phase].get("evidence"):
            return
        ledger[phase]["evidence"] = True
        ledger[phase]["at"] = self._now()
        ledger[phase]["note"] = note
        self._save_phases(self._resync(ledger))

    @staticmethod
    def _resync(ledger: dict) -> dict:
        """Derive every phase's status from banked evidence, in order.

        A phase is done only when it AND every phase before it has
        evidence: evidence for a later phase is held, not shown, until the
        earlier ones catch up. At most one phase is ever 'running'.
        """
        blocked = False
        for ph in PHASES:
            entry = ledger[ph]
            if entry.get("evidence") and not blocked:
                entry["status"] = "done"
                continue
            # The FIRST phase still missing evidence is the one being
            # worked on - whether or not the model announced it. Subagents
            # do the real work and never call set_phase, so an
            # announcement is a poor proxy for what is actually happening.
            entry["status"] = "pending" if blocked else "running"
            blocked = True
        return ledger

    def reconcile_phases(self) -> dict:
        """Credit phases whose artifact is sitting in the workspace.

        The live hooks record evidence as it happens, but a ledger can also
        be missing it: runs from before the ledger existed, a resumed run,
        a deleted phases.json. Reading the workspace recovers the truth.
        Promotion is from artifacts on disk. It also REVOKES credit whose
        artifact turns out not to exist: sch_gen/tb_gen/sim all rest on an
        integrated toplevel, so if there is no top the design is not built,
        whatever the ledger was told earlier.
        """
        if self.integration_gaps():
            ledger = self.load_phases()
            revoked = False
            for ph in ("sch_gen", "tb_gen", "sim"):
                if ledger[ph].get("evidence"):
                    ledger[ph] = {"status": "pending"}
                    revoked = True
            if revoked:
                self._save_phases(self._resync(ledger))
        if any((self.root / "context" / "refs").glob("*")):
            self.mark_phase("spec_ingestion", "research saved in context/refs")
        if self._substantial("plan.md", 800) or \
                self._substantial("toplevel_plan.md", 600) or self.block_plans():
            self.mark_phase("spec_ingestion", "spec was read to write plans")
            if not self.planning_gaps():
                self.mark_phase("plan", "plan contract present on disk")
        # Reconstructing history, not re-judging it: drawing quality is
        # enforced live in netlist_schematic, where the agent can still act
        # on it. But an integrated toplevel is structural, not stylistic -
        # without one there is no design, however many blocks were drawn.
        if any(s.with_suffix(".spice").exists()
               for s in self.root.glob("*.sch")) and not self.integration_gaps():
            top = self.toplevel()
            self.mark_phase("sch_gen",
                            f"toplevel {top.name} and its blocks are netlisted"
                            if top else "schematics netlisted")
        for deck in sorted(self.root.glob("*.spice")) + \
                sorted((self.root / "exp").glob("*.spice")):
            low = [ln.lstrip().lower() for ln in
                   deck.read_text(errors="replace").splitlines()]
            stimulus = any(ln.startswith(("v", "i")) and
                           ("sin(" in ln or "pulse(" in ln or "pwl(" in ln)
                           for ln in low)
            analysed = any(ln.split()[0] in (".tran", ".ac", ".dc")
                           for ln in low if ln.split())
            stem = deck.stem[:-5] if deck.stem.endswith("_ctrl") else deck.stem
            if stimulus and analysed and (
                    (self.root / f"{stem}.raw").exists() or
                    any(self.root.glob(f"{stem}_*.raw")) or
                    (self.root / "exp" / f"{stem}.raw").exists()):
                self.mark_phase("tb_gen", f"{deck.name} ran with stimulus")
                break
        if (any(self.root.glob("*.raw")) or
                any((self.root / "exp").glob("*.raw"))) and \
                any(self.root.glob("waves_*.png")) and \
                not self.block_verification_gaps() and \
                not self.requested_chart_gaps():
            self.mark_phase("sim", "every schematic has waveform evidence")
        ledger = self.load_phases()
        self._save_phases(ledger)  # persist in ledger form (migrates legacy)
        return ledger

    def block_verification_gaps(self) -> list[str]:
        """Every IP block, sub-top and the toplevel must be verifiable.

        Every root-level schematic - block with a .sym, or a top that
        instantiates local blocks - needs its own simulation evidence in
        the workspace: a rawfile and/or waveform plot named after it
        (<block>_verify.raw, waves_<block>*.png, ...). A block that was
        never simulated on its own is not a verified IP, whatever the
        top-level waveforms show.
        """
        gaps: list[str] = []
        for sch in sorted(self.root.glob("*.sch")):
            stem = sch.stem
            # A testbench schematic IS the verification apparatus - it does
            # not need a testbench of its own. Only IPs, sub-tops and the
            # toplevel owe evidence.
            if self._is_apparatus(stem):
                continue
            if not (self.root / f"{stem}_plan.md").exists() and \
                    not self._substantial("plan.md", 800):
                gaps.append(
                    f"{stem}.sch has no {stem}_plan.md - every block owes "
                    f"a plan carrying its expected values and its test "
                    f"(stimulus, nodes, numeric pass/fail)")
            if not (self.root / f"tb_{stem}.sch").exists():
                gaps.append(
                    f"{sch.name} has no testbench schematic - draw "
                    f"tb_{stem}.sch that instantiates {stem}.sym, drives it "
                    f"with real stimulus, and shows its waveforms. Every IP "
                    f"used through a symbol needs its own tb_<ip>.sch")
            elif not self.block_verified(stem):
                gaps.append(
                    f"tb_{stem}.sch was never simulated - netlist and run "
                    f"it, then analyze its rawfile so {stem} owns measured "
                    f"waveform evidence")
        # Every schematic must OPEN IN XSCHEM SHOWING its waveforms.
        try:
            for name in self.embed_missing_graphs():
                gaps.append(
                    f"{name} does not display its waveforms - simulate the "
                    f"deck that drives it and analyze_raw its nodes so the "
                    f"graph panes embed into the schematic")
        except Exception:
            pass
        return gaps

    def requested_chart_gaps(self) -> list[str]:
        """Charts the task explicitly requested but nobody drew.

        If the task asks for swept results ('VOUT vs input power', 'dBm
        vs Vo', a frequency sweep...), completion requires at least one
        plot_xy chart - a waves_*.png with no matching rawfile - because
        sweep numbers quoted without a chart are not reviewable evidence.
        """
        task = self.root / "task.md"
        if not task.exists():
            return []
        import re as _re
        text = task.read_text(errors="replace").lower()
        # plot_xy charts are the waves_*.png with no matching rawfile.
        charts = [p.stem[len("waves_"):] for p in self.root.glob("waves_*.png")
                  if not (self.root / f"{p.stem[len('waves_'):]}.raw").exists()
                  and not (self.root / "exp" /
                           f"{p.stem[len('waves_'):]}.raw").exists()]
        gaps: list[str] = []
        if _re.search(r"\bvs\.?\b|sweep|dbm", text) and not charts:
            gaps.append(
                "the task explicitly asks for swept result charts (e.g. "
                "VOUT vs input power in dBm, VOUT vs frequency): run the "
                "sweep simulations and draw each curve with plot_xy - "
                "quoting sweep numbers in text is not evidence")
        # PCE is required exactly when the task asks for efficiency -
        # it is a power-converter metric, not a universal one.
        if _re.search(r"\bpce\b|efficien", text) and \
                not any("pce" in c or "effic" in c for c in charts):
            gaps.append(
                "power conversion efficiency was never measured: for each "
                "input power point compute PCE = (Vout_dc^2 / Rload) / "
                "P_available from the sweep rawfiles and draw it with "
                'plot_xy(name="pce_vs_power", ...) - every design must '
                "report its measured efficiency")
        return gaps

    def phase_gaps(self) -> list[str]:
        """Which workflow phases never produced their defining artifact."""
        ledger = self.reconcile_phases()
        why = {
            "spec_ingestion": "no spec reading or research happened",
            "plan": "no substantive plan contract was written "
                    "(toplevel_plan.md + <block>_plan.md per block)",
            "sch_gen": "no root-level schematic ever netlisted clean",
            "tb_gen": "no testbench deck with a real analysis card ran",
            "sim": "no simulation was analysed for waveform evidence",
        }
        return [f"phase '{ph}' never completed: {why[ph]}"
                for ph in PHASES if ledger[ph].get("status") != "done"]

    def workflow_gaps(self) -> list[str]:
        """Everything still standing between this run and a credible done:
        unfinished phases, a missing/incomplete toplevel, unverified IPs,
        and requested-but-missing charts."""
        return (self.phase_gaps() + self.planning_gaps()
                + self.integration_gaps() + self.device_level_gaps()
                + self.block_verification_gaps()
                + self.requested_chart_gaps())

    def preflight(self) -> dict:
        """Scoped OpenADA preflight, as prescribed by the openada skill:
        one project root, one intended engineering assertion."""
        result = self._openada([
            "doctor", "--project-root", str(self.root),
            "--assertion", "spice-analysis-evidence-valid"])
        (self.root / "preflight.json").write_text(json.dumps(result, indent=2))
        return self._compact(result)

    @staticmethod
    def _lint_sch(text: str) -> list[str]:
        """Line-numbered checks for the mistakes xschem silently drops."""
        import re as _re
        errs = []
        depth = 0
        for i, ln in enumerate(text.splitlines(), 1):
            s = ln.strip()
            if not s:
                continue
            if depth > 0:
                # inside a multi-line {...} attribute block: free text is fine
                depth += ln.count("{") - ln.count("}")
                continue
            if s.startswith(";") or s.startswith("#") or s.startswith("//"):
                errs.append(f"line {i}: ';'-style comments are NOT valid in "
                            f".sch files - delete them (use T records for "
                            f"annotations): {s[:60]}")
                continue
            if s.startswith("C "):
                if not _re.match(r"^C \{[^}]+\} +-?\d+ +-?\d+ +[0-3] +[01] +\{", s):
                    if "," in s.split("}")[1][:40] if "}" in s else False:
                        errs.append(f"line {i}: coordinates must be SPACE-separated integers, never commas: {s[:80]}")
                    else:
                        errs.append(f"line {i}: component record must be 'C {{sym}} x y rot flip {{attrs}}': {s[:80]}")
            elif s.startswith("N "):
                if not _re.match(r"^N +-?\d+ +-?\d+ +-?\d+ +-?\d+", s):
                    errs.append(f"line {i}: wire record needs 4 integer coords 'N x1 y1 x2 y2 {{lab=NET}}': {s[:80]}")
                elif not _re.match(r"^N +-?\d+ +-?\d+ +-?\d+ +-?\d+ *(\{.*)?$", s):
                    errs.append(f"line {i}: wire label must be in braces "
                                f"'{{lab=NET}}' - a bare word here corrupts "
                                f"the xschem parser and following components "
                                f"disappear: {s[:80]}")
            elif s.startswith("{"):
                errs.append(f"line {i}: stray '{{...}}' block is invalid; use a T record for text: {s[:60]}")
            elif s[0] not in "vGKVSENCBTPLA*":
                errs.append(f"line {i}: unknown record type '{s[:20]}'")
            depth += ln.count("{") - ln.count("}")
        return errs

    # Symbols that name/annotate rather than implement the circuit: they do
    # not count as components when judging whether the drawing is wired.
    _ANNOT_SYMS = ("lab_pin", "gnd", "vdd", "code", "title", "launcher",
                   "opin", "ipin", "iopin", "arrow", "spice_probe")

    @classmethod
    def _sch_quality(cls, text: str) -> list[str]:
        """Human-readability checks: real wires and non-overlapping placement.

        A schematic that connects everything through lab_pin labels alone
        netlists fine but is unreadable; require pin-to-pin N wire records
        in proportion to the component count, and no stacked symbols.
        """
        import re as _re
        comps = 0
        wires = 0
        seen_xy: dict[tuple[int, int], str] = {}
        problems: list[str] = []
        for ln in text.splitlines():
            s = ln.strip()
            if s.startswith("N "):
                wires += 1
                continue
            m = _re.match(r"^C \{([^}]+)\} +(-?\d+) +(-?\d+) ", s)
            if not m:
                continue
            sym, x, y = m.group(1), int(m.group(2)), int(m.group(3))
            if any(a in sym for a in cls._ANNOT_SYMS):
                continue
            comps += 1
            key = (x, y)
            if key in seen_xy:
                problems.append(
                    f"components {seen_xy[key]} and {sym} are stacked at the "
                    f"same coordinate ({x},{y}) - spread the placement out")
            else:
                seen_xy[key] = sym.rsplit('/', 1)[-1]
        if comps >= 3 and wires < comps:
            problems.insert(0,
                f"only {wires} wire (N) records for {comps} components - "
                "connectivity must be DRAWN with real pin-to-pin wires "
                "(labels name nets, they do not replace wires). Route every "
                "local connection with N segments, signal flow left to "
                "right, stages on aligned rows.")
        return problems

    def netlist_schematic(self, schematic: str) -> dict:
        sch = self.resolve(schematic)
        if not sch.exists():
            return {"ok": False, "error": f"no such schematic: {schematic}"}
        sch_text = sch.read_text(errors="replace")
        lint = self._lint_sch(sch_text)
        if lint:
            return {"execution": "rejected", "engineering": "unknown",
                    "summary": "Schematic fails xschem format checks - fix these exact lines before netlisting (xschem silently drops invalid records, so the drawing would be missing parts).",
                    "diagnostics": [{"severity": "error", "code": "sch.lint",
                                     "message": e} for e in lint[:10]]}
        quality = self._sch_quality(sch_text)
        if quality:
            return {"execution": "rejected", "engineering": "unknown",
                    "summary": "Schematic is netlistable but not acceptable: a human engineer must be able to read it. Fix the wiring/placement below, then netlist again.",
                    "diagnostics": [{"severity": "error", "code": "sch.quality",
                                     "message": p} for p in quality[:10]]}
        out = sch.with_suffix(".spice")
        result = self._openada(["netlist", str(sch), "-o", str(out)])
        extra: dict = {"netlist_path": str(out.relative_to(self.root))}
        if out.exists():
            text = out.read_text(errors="replace")
            extra["netlist_text"] = text[:MAX_TEXT]
            self._reset_tries(out.stem)  # regenerated deck: fresh tries
        compact = self._compact(result, extra)
        # sch_gen is NOT earned by one block netlisting: the design is the
        # whole chain. It completes only when a toplevel exists and every
        # block it instantiates is drawn and netlisted.
        if compact.get("engineering") == "pass" and sch.parent == self.root:
            if not self.integration_gaps():
                self.mark_phase("sch_gen",
                                "toplevel and every block it instantiates "
                                "are drawn and netlisted")
        return compact

    APPARATUS = ("_tb", "tb_", "_test", "_view", "_verify")

    @classmethod
    def _is_apparatus(cls, stem: str) -> bool:
        return any(tag in stem.lower() for tag in cls.APPARATUS)

    def block_verified(self, stem: str) -> bool:
        """Has this block passed a testbench SCHEMATIC of its own?

        An IP that other schematics instantiate through its symbol cannot
        show waveforms itself - it has no stimulus. Its evidence lives in
        tb_<block>.sch: a real testbench schematic that drives it and
        carries the waveforms.
        """
        tb = self.root / f"tb_{stem}.sch"
        if not tb.exists():
            return False
        return (any(self.root.glob(f"tb_{stem}*.raw"))
                or any(self.root.glob(f"waves_tb_{stem}*.png")))

    def finished_blocks(self) -> list[str]:
        """Promoted root blocks: a .sch with a .sym, excluding apparatus."""
        return sorted(p.stem for p in self.root.glob("*.sch")
                      if (self.root / f"{p.stem}.sym").exists()
                      and not self._is_apparatus(p.stem))

    def unverified_blocks(self) -> list[str]:
        return [b for b in self.finished_blocks() if not self.block_verified(b)]

    # Blocks that are legitimately passive: an L/C match or balun has no
    # business containing transistors. Everything else in an active chain
    # (rectifier, charge pump, bias, amplifier) must be built from real
    # PDK devices, not ideal elements standing in for silicon.
    PASSIVE_OK = ("match", "balun", "filter", "tank", "network", "ind", "cap")

    def experiment_counts(self) -> dict:
        """How many candidate versions exist per block under exp/.

        Surfaced to the agent so it can tell 'still improving' from
        'spinning on one block while the rest of the chain waits'.
        """
        import re as _re
        counts: dict = {}
        for sch in (self.root / "exp").glob("*_v*.sch"):
            m = _re.match(r"^(.*)_v\d+$", sch.stem)
            if m:
                counts[m.group(1)] = counts.get(m.group(1), 0) + 1
        return counts

    def device_counts(self, stem: str) -> dict:
        """PDK devices instantiated by a schematic, by kind."""
        import re as _re
        sch = self.root / f"{stem}.sch"
        if not sch.exists():
            return {}
        counts: dict = {}
        for m in _re.finditer(r"^C \{([^}]+)\}", sch.read_text(errors="replace"),
                              _re.MULTILINE):
            sym = m.group(1).strip()
            base = sym.split("/")[-1].removesuffix(".sym")
            if base.startswith(("nfet", "pfet", "npn", "pnp", "diode",
                                "nmos", "pmos")):
                counts[base] = counts.get(base, 0) + 1
        return counts

    def device_level_gaps(self) -> list[str]:
        """Active blocks that were faked with ideal elements."""
        gaps = []
        for stem in self.finished_blocks():
            if any(tag in stem.lower() for tag in self.PASSIVE_OK):
                continue
            if not self.device_counts(stem):
                gaps.append(
                    f"{stem}.sch contains no PDK transistors - an active "
                    f"block (rectifier, charge pump, bias, amplifier) must "
                    f"be built from real nfet_03v3/pfet_03v3 devices, not "
                    f"ideal sources or behavioural stand-ins. Redesign it "
                    f"at device level.")
        return gaps

    def _substantial(self, name: str, min_bytes: int) -> bool:
        p = self.root / name
        return p.exists() and p.stat().st_size >= min_bytes

    def block_plans(self) -> list[str]:
        """The per-block plan files (everything but the toplevel's)."""
        return sorted(p.name for p in self.root.glob("*_plan.md")
                      if p.name != "toplevel_plan.md")

    def planning_gaps(self) -> list[str]:
        """Planning is ONE FILE PER DELIVERABLE, each carrying its own test.

        toplevel_plan.md holds the chain and the integration criteria;
        every block gets <block>_plan.md with its expected values AND the
        stimulus/nodes/pass-criteria that verify it. The plan IS the test
        spec. (The legacy plan.md + test_method.md pair still counts, so
        old runs are not demoted retroactively.)
        """
        if self._substantial("plan.md", 800) and \
                self._substantial("test_method.md", 800):
            return []  # legacy contract, still honoured
        gaps = []
        if not self._substantial("toplevel_plan.md", 600):
            gaps.append(
                "toplevel_plan.md is missing or too thin - write the "
                "complete signal chain in order, the block connections, "
                "the top-level integration and its numeric pass criteria, "
                "and the sweeps/charts the task demands")
        if not self.block_plans():
            gaps.append(
                "no per-block plans exist - write <block>_plan.md for "
                "EVERY block (match_plan.md, rectifier_plan.md, ...), each "
                "with the interface, topology, sizing, an expected-values "
                "table, AND the test method: stimulus, nodes measured, and "
                "a numeric pass/fail criterion per node")
        return gaps

    def toplevel(self) -> Path | None:
        """The root schematic that integrates the chain.

        A TESTBENCH is not a toplevel: tb_rectifier.sch instantiates
        rectifier.sym, but it exists to exercise one block, not to wire the
        system together. Counting it as integration is what let a run go
        green with no toplevel at all - so apparatus is excluded, and the
        real top must instantiate at least TWO distinct blocks.
        """
        best: tuple[int, Path] | None = None
        for sch in sorted(self.root.glob("*.sch")):
            if self._is_apparatus(sch.stem):
                continue
            text = sch.read_text(errors="replace")
            blocks = {m for m in self._instantiated_blocks(text)
                      if (self.root / f"{m}.sym").exists()}
            if len(blocks) >= 2 and (best is None or len(blocks) > best[0]):
                best = (len(blocks), sch)
        return best[1] if best else None

    @staticmethod
    def _instantiated_blocks(text: str) -> set[str]:
        """Local block symbols a schematic instantiates (C {foo.sym} ...)."""
        import re as _re
        names = set()
        for m in _re.finditer(r"^C \{([^}]+)\}", text, _re.MULTILINE):
            sym = m.group(1).strip()
            if "/" in sym:          # devices/vsource.sym etc: PDK/stock part
                continue
            if sym.endswith(".sym"):
                names.add(sym[:-4])
        return names

    def integration_gaps(self) -> list[str]:
        """Why the design is not yet a complete, integrated system.

        A chain of blocks with no toplevel is not a design. This is the
        gate that stops the agent 'finishing' sch_gen after drawing the
        first block, and stops it simulating a system that does not exist.
        """
        gaps: list[str] = []
        top = self.toplevel()
        if top is None:
            drawn = sorted(p.stem for p in self.root.glob("*.sch"))
            return ["no TOPLEVEL schematic exists: no root .sch instantiates "
                    "the local block symbols. Draw the top that wires the "
                    "whole chain together" +
                    (f" (blocks drawn so far: {', '.join(drawn)})" if drawn
                     else "") + ". A set of blocks is not a design."]
        for block in sorted(self._instantiated_blocks(
                top.read_text(errors="replace"))):
            if not (self.root / f"{block}.sch").exists():
                gaps.append(f"{top.name} instantiates {block}.sym but "
                            f"{block}.sch does not exist - draw the block")
            elif not (self.root / f"{block}.spice").exists():
                gaps.append(f"{block}.sch was never netlisted - netlist it "
                            f"so the toplevel can be built from real blocks")
        if not (self.root / f"{top.stem}.spice").exists():
            gaps.append(f"the toplevel {top.name} was never netlisted")
        return gaps

    def wiring_report(self) -> list[str]:
        """Quality problems across every schematic in the workspace root."""
        problems: list[str] = []
        for sch in sorted(self.root.glob("*.sch")):
            for p in self._sch_quality(sch.read_text(errors="replace")):
                problems.append(f"{sch.name}: {p}")
        return problems

    def plot_xy(self, name: str, title: str, x_label: str, y_label: str,
                series: list[dict]) -> dict:
        """Draw an XY chart (sweep results etc.) to waves_<name>.png.

        series: [{"name": str, "points": [[x, y], ...]}, ...]
        """
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        safe = "".join(c for c in name if c.isalnum() or c in "_-") or "chart"
        fig, ax = plt.subplots(figsize=(8, 4.5))
        for s in series:
            pts = sorted((float(x), float(y)) for x, y in s.get("points", []))
            if not pts:
                continue
            ax.plot([p[0] for p in pts], [p[1] for p in pts],
                    marker="o", label=str(s.get("name", "")))
        ax.set_title(title)
        ax.set_xlabel(x_label)
        ax.set_ylabel(y_label)
        ax.grid(True, alpha=0.3)
        if len(series) > 1 or any(s.get("name") for s in series):
            ax.legend()
        out = self.root / f"waves_{safe}.png"
        fig.tight_layout()
        fig.savefig(out, dpi=110)
        plt.close(fig)
        return {"ok": True, "path": str(out.relative_to(self.root))}

    def embed_missing_graphs(self) -> list[str]:
        """Embed autoloading waveform panes into schematics that lack them.

        Every .sch must SHOW its simulation: nets labeled in the schematic
        are matched against the rawfiles (block ports resolve through the
        x1.net hierarchy names too) and pandachip.embed_graphs appends
        autoload panes. Returns the schematics that still have none.
        """
        import re as _re
        import subprocess as _sp
        import sys as _sys
        from .rawread import read_raw
        problems: list[str] = []
        raws = [r for r in list(self.root.glob("*.raw")) +
                list((self.root / "sim").glob("*.raw")) if r.stat().st_size]
        if not raws:
            return ["no rawfiles exist to embed waveform panes from - "
                    "run a simulation first"]
        schs = sorted(self.root.glob("*.sch"))
        for sch in schs:
            text = sch.read_text(errors="replace")
            if "flags=graph" in text:
                continue
            labs = []
            for lab in _re.findall(r"lab=([A-Za-z0-9_.]+)", text):
                if lab not in ("0",) and lab not in labs:
                    labs.append(lab)
            # rawfiles whose name matches this schematic first, newest next
            ordered = sorted(raws, key=lambda r: (
                0 if r.stem.startswith(sch.stem) else 1,
                -r.stat().st_mtime))
            embedded = False
            for raw in ordered:
                try:
                    vecs = read_raw(raw)["vectors"].keys()
                except Exception:
                    continue
                names = {}
                for k in vecs:
                    inner = k[2:-1] if k.lower().startswith("v(") else k
                    names.setdefault(inner.lower(), inner)
                nodes = []
                for lab in labs:
                    hit = names.get(lab.lower()) or next(
                        (v for n, v in names.items()
                         if n.endswith("." + lab.lower())), None)
                    if hit and hit not in nodes:
                        nodes.append(hit)
                if not nodes:
                    continue
                groups = [" ".join(nodes[i:i + 2])
                          for i in range(0, min(len(nodes), 6), 2)]
                _sp.run([_sys.executable, "-m", "pandachip.embed_graphs",
                         str(sch), str(raw), *groups],
                        capture_output=True, timeout=120)
                if "flags=graph" in sch.read_text(errors="replace"):
                    embedded = True
                    break
            if not embedded:
                problems.append(
                    f"{sch.name}: no waveform panes could be embedded - none "
                    "of its labeled nets appear in any rawfile; label the "
                    "probe nets and rerun the simulation")
        return problems

    def simulate_netlist(self, netlist: str) -> dict:
        deck = self.resolve(netlist)
        if not deck.exists():
            return {"ok": False, "error": f"no such netlist: {netlist}"}
        # Refuse the hope-loop: the SAME deck, unchanged, that already
        # failed twice will fail a third time. The next attempt must be a
        # new exp/ version (or an actual edit), not a resubmission.
        if self._sim_tries.get(str(deck), 0) >= 2:
            return {"execution": "rejected", "engineering": "unknown",
                    "summary": f"{deck.name} already failed to produce "
                               "trustworthy evidence twice, unchanged.",
                    "diagnostics": [{"severity": "error",
                                     "code": "deck.unchanged_retry",
                                     "message": "Do not resubmit this deck. "
                                     "Diagnose the last log, then draw the "
                                     "next exp/ version with ONE concrete "
                                     "change (or edit this deck/schematic) "
                                     "and simulate that instead."}]}
        outdir = self.root / "sim"
        outdir.mkdir(exist_ok=True)

        text = deck.read_text(errors="replace")
        lines_lower = [ln.lstrip().lower() for ln in text.splitlines()]
        if any(ln.startswith(".option") and "savecurrents" in ln
               for ln in lines_lower) and \
                any(ln.startswith("x") for ln in lines_lower):
            return {"execution": "rejected", "engineering": "unknown",
                    "summary": "Deck rejected before simulation: .option "
                               "savecurrents with subcircuit devices makes "
                               "ngspice emit dims=0 current vectors that "
                               "invalidate the rawfile as OpenADA evidence.",
                    "diagnostics": [{"severity": "error",
                                     "code": "deck.savecurrents",
                                     "message": "Remove '.option savecurrents' "
                                     "from the CONTROL block (use i(vsource) "
                                     "for branch currents) and re-netlist."}]}
        # Guard against a transient whose point count is so large it will
        # spin ngspice past the timeout (the classic GHz-transient trap).
        import re as _re2
        for ln in lines_lower:
            m = _re2.match(r"\.tran\s+(\S+)\s+(\S+)", ln)
            if not m:
                continue
            step, stop = _si(m.group(1)), _si(m.group(2))
            if step and stop and stop / step > 2_000_000:
                return {"execution": "rejected", "engineering": "unknown",
                        "summary": "Deck rejected before simulation: the "
                        f".tran implies ~{int(stop/step):,} points, which "
                        "would run for many minutes and time out. This is the "
                        "GHz-transient trap.",
                        "diagnostics": [{"severity": "error",
                                         "code": "deck.tran_too_long",
                                         "message": "Shorten the transient to "
                                         "a few tens of periods (tstop=30/f, "
                                         "timestep=1/(200*f)) or verify gain "
                                         "with .ac instead."}]}
        has_include = any(
            ln.startswith((".include", ".inc ", ".lib")) for ln in lines_lower)
        analyses = [kind for kind, card in (("tran", ".tran"), ("ac", ".ac"),
                                            ("dc", ".dc"), ("op", ".op"))
                    if any(ln.split()[0] == card if ln.split() else False
                           for ln in lines_lower)]

        if has_include:
            # PDK model .lib/.include decks require OpenADA's ngspice control
            # mode with declared deck-owned rawfiles (docs/CURRENT_DRIVERS.md).
            raw_names = ({kind: f"{deck.stem}_{kind}.raw" for kind in analyses}
                         if len(analyses) > 1 else
                         {(analyses[0] if analyses else "tran"): f"{deck.stem}.raw"})
            run_deck = deck
            if ".control" not in text.lower():
                lines = text.splitlines()
                end_idx = next((i for i, ln in enumerate(lines)
                                if ln.strip().lower() == ".end"), len(lines))
                block = [".control", "set filetype=binary", "run"]
                if len(raw_names) > 1:
                    for kind, name in raw_names.items():
                        block += [f"setplot {kind}1", f"write {name}"]
                else:
                    block += [f"write {next(iter(raw_names.values()))}"]
                block += [".endc"]
                lines[end_idx:end_idx] = block
                run_deck = deck.with_name(f"{deck.stem}_ctrl{deck.suffix}")
                run_deck.write_text("\n".join(lines) + "\n")
            args = ["simulate", str(run_deck),
                    "--execution-mode", "control",
                    "--workdir", str(self.root),
                    "--timeout", os.getenv("PANDACHIP_SIM_TIMEOUT", "180"),
                    "--output-dir", str(outdir)]
            for name in raw_names.values():
                # OpenADA requires deck-owned outputs to be fresh: remove
                # leftovers from previous simulations of the same deck.
                (self.root / name).unlink(missing_ok=True)
                args += ["--expect-output", f"raw={name}"]
        else:
            raw_names = {"tran": f"{deck.stem}.raw"}
            args = ["simulate", str(deck), "--timeout", os.getenv("PANDACHIP_SIM_TIMEOUT", "180"),
                    "--output-dir", str(outdir)]

        result = self._openada(args)
        extra: dict = {}
        for a in result.get("artifacts", []):
            path = a.get("path", "")
            if path.endswith(".raw"):
                extra["raw_path"] = str(Path(path).relative_to(self.root))
            elif path.endswith(".log"):
                tail = Path(path).read_text(errors="replace")[-2000:]
                extra["log_tail"] = tail
        produced = {kind: name for kind, name in raw_names.items()
                    if (self.root / name).exists()}
        if produced:
            extra["raw_paths"] = produced
            extra.setdefault("raw_path", next(iter(produced.values())))
        compact = self._compact(result, extra)
        # Track the hope-loop counter: not-passing runs of an unchanged
        # deck accumulate; a pass (or an edit elsewhere) clears it.
        if compact.get("engineering") == "pass":
            self._sim_tries.pop(str(deck), None)
        else:
            self._sim_tries[str(deck)] = self._sim_tries.get(str(deck), 0) + 1
        # tb_gen is earned by a ROOT-level deck that actually carries
        # stimulus and a real analysis card and then ran - not by
        # announcing "tb_gen", and not by an exp/ scratch experiment:
        # the delivered testbench must be inspectable in the workspace root.
        if compact.get("execution") == "completed" and produced \
                and deck.parent == self.root:
            stimulus = any(ln.startswith(("v", "i")) and
                           ("sin(" in ln or "pulse(" in ln or "pwl(" in ln or
                            "dc " in ln or "ac " in ln)
                           for ln in lines_lower)
            if stimulus and [k for k in analyses if k != "op"]:
                self.mark_phase("tb_gen",
                                f"{deck.name} ran with stimulus + "
                                f"{'/'.join(analyses)} analysis")
        return compact

    def analyze_raw(self, raw_path: str, vectors: list[str]) -> dict:
        p = self.resolve(raw_path)
        if not p.exists():
            return {"ok": False, "error": f"no such rawfile: {raw_path}"}
        raw = read_raw(p)
        have = raw["vectors"]
        scale_name = raw["meta"]["variables"][0]
        t = have[scale_name]
        report: dict = {
            "ok": True,
            "points": raw["meta"]["n_points"],
            "scale": scale_name,
            "t_start": t[0], "t_stop": t[-1],
            "available_vectors": raw["meta"]["variables"],
            "vectors": {},
        }
        for name in vectors:
            key = next((k for k in have
                        if k.lower() == name.lower()
                        or k.lower() == f"v({name.lower()})"), None)
            if key is None:
                report["vectors"][name] = {"error": "vector not found"}
                continue
            y = have[key]
            n = len(y)
            mean = sum(y) / n
            stats = {
                "min": min(y), "max": max(y), "mean": mean,
                "vpp": max(y) - min(y),
            }
            if scale_name.lower() == "frequency":
                stats.update(_ac_report(t, y))
            else:
                stats["fft_peaks"] = _fft_peaks(t, y)
            report["vectors"][name] = stats
        # sim is earned when real vectors were actually resolved and read
        # out of a rawfile - not when a vector lookup silently missed.
        if any("error" not in v for v in report["vectors"].values()):
            self.mark_phase("sim", f"waveform evidence read from {p.name}")
        return report


def _ac_report(freqs: list[float], mag: list[float]) -> dict:
    """AC sweep evidence: gain in dB, peak, and -3 dB corners."""
    db = [20 * math.log10(m) if m > 0 else -300.0 for m in mag]
    peak_idx = max(range(len(db)), key=db.__getitem__)
    peak_db = db[peak_idx]
    f_lo = f_hi = None
    for i in range(peak_idx, -1, -1):
        if db[i] <= peak_db - 3:
            f_lo = freqs[i]
            break
    for i in range(peak_idx, len(db)):
        if db[i] <= peak_db - 3:
            f_hi = freqs[i]
            break
    samples = []
    for target in (1e5, 1e6, 1e7, 5e7, 1e8, 2e8, 5e8, 1e9):
        if freqs[0] <= target <= freqs[-1]:
            idx = min(range(len(freqs)), key=lambda i: abs(freqs[i] - target))
            samples.append({"freq_hz": freqs[idx], "gain_db": round(db[idx], 2)})
    return {
        "analysis": "ac",
        "gain_db_peak": round(peak_db, 2),
        "freq_at_peak_hz": freqs[peak_idx],
        "f_minus3db_low_hz": f_lo,
        "f_minus3db_high_hz": f_hi,
        "gain_db_samples": samples,
    }


def _fft_peaks(t: list[float], y: list[float], top: int = 6) -> list[dict]:
    """Top spectral peaks of a (possibly non-uniform) transient vector."""
    try:
        import numpy as np
    except ImportError:
        return [{"error": "numpy unavailable"}]
    t_arr = np.asarray(t)
    y_arr = np.asarray(y)
    # resample to a uniform grid (ngspice tran points are not equidistant)
    n = 1 << max(10, int(math.ceil(math.log2(len(y_arr)))))
    tu = np.linspace(t_arr[0], t_arr[-1], n)
    yu = np.interp(tu, t_arr, y_arr)
    yu = yu - yu.mean()
    win = np.hanning(n)
    spec = np.abs(np.fft.rfft(yu * win)) * 2.0 / win.sum()
    freqs = np.fft.rfftfreq(n, (tu[-1] - tu[0]) / (n - 1))
    order = np.argsort(spec)[::-1]
    peaks: list[dict] = []
    used: list[float] = []
    df = freqs[1] if len(freqs) > 1 else 0.0
    for idx in order:
        f = float(freqs[idx])
        if f <= 0:
            continue
        if any(abs(f - u) < 4 * df for u in used):
            continue
        peaks.append({"freq_hz": f, "amplitude": float(spec[idx])})
        used.append(f)
        if len(peaks) >= top:
            break
    return peaks
