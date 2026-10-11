"""SPICE netlist checking & auto-repair for AnoaChip (the analog counterpart of
GarudaChip's verilog_check).

Two layers, both cheap and offline:

1. `autofix_text` — mechanical cleanup of LLM output: strip markdown fences,
   normalize continuation lines, guarantee a title/comment first line (ngspice
   silently EATS the first line as the deck title — a classic footgun that makes
   the first .subckt disappear), balance .subckt/.ends, drop stray .end inside
   library files.

2. `check_netlist_text` / `check_file` — structural lint that catches the LVS
   killers BEFORE layout is ever attempted:
     • .subckt/.ends imbalance, duplicate subckt names
     • device cards with too few nodes (M needs D G S B, R/C/L/V/I need 2, ...)
     • subckt ports never used inside the body (dangling port ⇒ LVS mismatch)
     • nets referenced exactly ONCE inside a subckt (floating net ⇒ something
       is NOT connected — the #1 cause of "straight_route didn't generate")
     • X-instances that reference an unknown subckt
   Returns "" when clean, else a compact human/LLM-readable error report.

3. `ngspice_parse_check` — optional deeper check: wrap the file in a tiny deck
   (.include + .control quit) and let ngspice's parser chew it, with the PDK
   model library included when PDK_ROOT is set, so `sky130_fd_pr__*` /
   `gf180mcu_fd_pr__*` models resolve. Reports only Error-lines.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import List, Tuple

# Minimum node counts per SPICE element letter (element name itself excluded).
# value/model tokens come after the nodes; we only check the floor.
_MIN_NODES = {
    "m": 4,   # Mosfet: D G S B
    "q": 3,   # BJT: C B E
    "d": 2, "r": 2, "c": 2, "l": 2, "v": 2, "i": 2, "b": 2,
    "x": 1,   # subckt instance: >=1 node + subckt name
    "e": 4, "g": 4, "f": 2, "h": 2,
}

# Known PDK primitive prefixes — an X-instance calling these is fine even though
# the subckt is not defined in the user's file (it comes from the PDK library).
_PDK_PREFIXES = ("sky130_fd_pr__", "sky130_fd_sc", "gf180mcu_fd_pr__",
                 "gf180mcu_fd_sc", "sky130_", "gf180mcu_")

_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_+-]*\s*$")


# --------------------------------------------------------------------------- #
#  autofix
# --------------------------------------------------------------------------- #
def autofix_text(text: str) -> Tuple[str, List[str]]:
    """Mechanically repair common LLM netlist tics. Returns (fixed, notes)."""
    notes: List[str] = []
    lines = (text or "").replace("\r\n", "\n").split("\n")

    # 1) strip markdown fences
    if any(_FENCE_RE.match(ln) for ln in lines):
        lines = [ln for ln in lines if not _FENCE_RE.match(ln)]
        notes.append("stripped markdown fences")

    # 2) drop leading blank lines
    while lines and not lines[0].strip():
        lines.pop(0)

    # 3) ngspice treats line 1 as the TITLE — if the file starts with a live
    #    statement (.subckt, device card, .include), prepend a comment title.
    if lines:
        first = lines[0].strip()
        if first and not first.startswith("*") and not first.startswith("//"):
            lines.insert(0, "* AnoaChip netlist")
            notes.append("prepended title comment (ngspice eats line 1)")

    # 4) '//' comments -> '*' comments (SPICE uses * and $)
    fixed = []
    for ln in lines:
        if ln.lstrip().startswith("//"):
            ln = ln.replace("//", "*", 1)
            if "// -> *" not in notes:
                notes.append("// -> * comments")
        fixed.append(ln)
    lines = fixed

    # 5) balance .subckt/.ends
    opens = sum(1 for ln in lines if ln.strip().lower().startswith(".subckt"))
    closes = sum(1 for ln in lines if ln.strip().lower().startswith(".ends"))
    if opens > closes:
        lines += [".ends"] * (opens - closes)
        notes.append(f"appended {opens - closes} missing .ends")

    return "\n".join(lines), notes


# --------------------------------------------------------------------------- #
#  structural parse + lint
# --------------------------------------------------------------------------- #
def _logical_lines(text: str) -> List[Tuple[int, str]]:
    """Join '+' continuation lines; return (first_lineno, joined) per statement."""
    out: List[Tuple[int, str]] = []
    for i, raw in enumerate(text.split("\n"), 1):
        s = raw.strip()
        if not s or s.startswith("*") or s.startswith("$"):
            continue
        if s.startswith("+") and out:
            no, prev = out[-1]
            out[-1] = (no, prev + " " + s[1:].strip())
        else:
            out.append((i, s))
    return out


def parse_netlist(text: str) -> dict:
    """Parse into {subckts: {name: {ports, lines, nets, xcalls}}, toplevel: [...]}"""
    subckts: dict = {}
    toplevel: List[Tuple[int, str]] = []
    cur = None
    for no, s in _logical_lines(text):
        low = s.lower()
        if low.startswith(".subckt"):
            toks = s.split()
            name = toks[1] if len(toks) > 1 else f"_anon_{no}"
            # params (k=v) are not ports
            ports = [t for t in toks[2:] if "=" not in t]
            cur = {"name": name, "ports": ports, "lines": [], "lineno": no}
            subckts[name.lower()] = cur
        elif low.startswith(".ends"):
            cur = None
        elif cur is not None:
            cur["lines"].append((no, s))
        else:
            toplevel.append((no, s))
    return {"subckts": subckts, "toplevel": toplevel}


def _device_nodes(stmt: str) -> Tuple[str, List[str]]:
    """Return (element_letter, node_list_best_effort) for one device card."""
    toks = stmt.split()
    if not toks:
        return "", []
    el = toks[0][0].lower()
    rest = [t for t in toks[1:] if "=" not in t]
    if el == "x":
        # last token without '=' is the subckt name, everything before = nodes
        return el, rest[:-1] if rest else []
    n = _MIN_NODES.get(el)
    if n is None:
        return el, []
    # nodes are the first n tokens; models/values follow
    return el, rest[:n]


def check_netlist_text(text: str, filename: str = "netlist") -> str:
    """Structural lint. Returns '' when clean, else a compact error report."""
    errs: List[str] = []
    parsed = parse_netlist(text)
    subckts = parsed["subckts"]

    if not subckts and not parsed["toplevel"]:
        return f"{filename}: empty netlist (no .subckt and no devices)"

    seen_names: set = set()
    for key, sc in subckts.items():
        name, ports = sc["name"], sc["ports"]
        if key in seen_names:
            errs.append(f"duplicate .subckt '{name}'")
        seen_names.add(key)
        if not ports:
            errs.append(f".subckt {name}: has NO ports — every circuit must "
                        f"expose its ports (VDD VSS in/out/bias)")

        # collect net usage inside the body
        net_count: dict = {}
        dev_names: set = set()
        for no, s in sc["lines"]:
            if s.lower().startswith("."):
                continue
            el, nodes = _device_nodes(s)
            dev = s.split()[0].lower()
            if dev in dev_names:
                errs.append(f".subckt {name} line {no}: duplicate device name '{s.split()[0]}'")
            dev_names.add(dev)
            if el in _MIN_NODES:
                toks_wo_params = [t for t in s.split()[1:] if "=" not in t]
                need = _MIN_NODES[el] + (1 if el == "x" else 0)  # x: nodes + subname
                if len(toks_wo_params) < need + (0 if el == "x" else 1) - (1 if el != "x" else 0):
                    pass  # element-specific below
                if el == "m" and len(toks_wo_params) < 5:
                    errs.append(f".subckt {name} line {no}: MOSFET needs D G S B + model: '{s[:80]}'")
                if el in "rclvidb" and len(toks_wo_params) < 2:
                    errs.append(f".subckt {name} line {no}: 2-terminal element missing nodes: '{s[:80]}'")
            for nd in nodes:
                net_count[nd.lower()] = net_count.get(nd.lower(), 0) + 1
            if el == "x":
                rest = [t for t in s.split()[1:] if "=" not in t]
                if rest:
                    sub = rest[-1].lower()
                    if sub not in subckts and not sub.startswith(_PDK_PREFIXES):
                        errs.append(f".subckt {name} line {no}: X-instance calls "
                                    f"UNDEFINED subckt '{rest[-1]}'")

        # dangling ports (port never used inside body) — a guaranteed LVS fail
        for p in ports:
            if p.lower() not in net_count:
                errs.append(f".subckt {name}: port '{p}' is NEVER CONNECTED inside "
                            f"the body — route it or drop it")
        # floating internal nets (used exactly once, not a port, not 0/gnd/vdd rails)
        rails = {"0", "gnd", "vss", "vdd", "vcc", "vssa", "vdda", "vssd", "vddd"}
        plow = {p.lower() for p in ports}
        for nd, cnt in net_count.items():
            if cnt == 1 and nd not in plow and nd not in rails:
                errs.append(f".subckt {name}: net '{nd}' appears only ONCE — floating/"
                            f"unconnected node (check your routing)")

    if errs:
        head = f"{filename}: {len(errs)} netlist problem(s):"
        return "\n".join([head] + [f"  - {e}" for e in errs[:25]])
    return ""


# --------------------------------------------------------------------------- #
#  file-level checks (used by the write_file hook, like verilog check_file was)
# --------------------------------------------------------------------------- #
def check_file(path: str | Path, netlist_dir: str | Path | None = None) -> str:
    """Lint one netlist file. Returns '' when clean."""
    p = Path(path)
    try:
        text = p.read_text()
    except Exception as e:  # noqa: BLE001
        return f"cannot read {p}: {e}"
    return check_netlist_text(text, filename=p.name)


def _pdk_lib_line() -> str:
    """The .lib include for the active PDK's ngspice models, if locatable."""
    pdk_root = os.getenv("PDK_ROOT", str(Path.home() / "pdks"))
    pdk = os.getenv("PDK", "gf180mcuD").lower()
    if pdk.startswith("sky130"):
        lib = Path(pdk_root) / "sky130A" / "libs.tech" / "ngspice" / "sky130.lib.spice"
        if lib.exists():
            return f".lib {lib} tt"
    if pdk.startswith("gf180"):
        lib = Path(pdk_root) / "gf180mcuD" / "libs.tech" / "ngspice" / "sm141064.ngspice"
        if lib.exists():
            return f".lib {lib} typical"
    return ""


NETLIST_SUFFIXES = (".sp", ".spice", ".cir", ".cdl", ".spc")


def tb_quality_report(src: str) -> Tuple[List[str], List[str]]:
    """Is this ngspice testbench actually able to VERIFY anything? Returns
    (hard_problems, soft_notes). A hard problem means the tb cannot produce a
    trustworthy PASS/FAIL and must be rewritten before it is even run:
      • no .control block / no `run` command      → nothing executes
      • no analysis (.op/.ac/.tran/.dc or control op/ac/tran/dc)
      • no measurement (meas/.measure/wrdata)     → nothing observed
      • no `Result: PASSED`/`Result: FAILED` echo → no machine-readable verdict
      • no DUT: neither an .include of a netlist file nor an X-instance
    """
    hard: List[str] = []
    soft: List[str] = []
    low = (src or "").lower()
    if ".control" not in low:
        hard.append("no .control block — add `.control` … `run` … checks … `.endc`")
    elif not re.search(r"^\s*run\b", src, re.IGNORECASE | re.MULTILINE):
        hard.append("no `run` inside .control — the analyses never execute")
    if not re.search(r"^\s*\.?(op|ac|tran|dc)\b", src, re.IGNORECASE | re.MULTILINE):
        hard.append("no analysis card (.op/.ac/.tran/.dc) — nothing is simulated")
    if not re.search(r"\b(meas|\.measure|wrdata)\b", low):
        hard.append("no measurement (meas/.measure/wrdata) — nothing is observed")
    if "result:" not in low:
        hard.append("no `echo Result: PASSED`/`Result: FAILED` verdict — the runner "
                    "cannot judge the run; compare each measured value to its spec with "
                    "control-block if/else and echo the verdict")
    if not re.search(r"^\s*\.include\b", src, re.IGNORECASE | re.MULTILINE):
        hard.append("no .include of the DUT netlist (e.g. `.include netlist/<name>.sp`)")
    if not re.search(r"^\s*x\w+", src, re.IGNORECASE | re.MULTILINE):
        hard.append("no X-instance of the DUT subckt — the circuit under test is "
                    "never instantiated")
    if not re.search(r"^\s*v\w+", src, re.IGNORECASE | re.MULTILINE):
        soft.append("no V-source found — check supplies/stimulus")
    if "measured=" not in low and "want=" not in low and "expected" not in low:
        soft.append("checks don't print measured/target values — per spec echo "
                    "`SPEC <name> PASS/FAIL measured=$&<vec> want=<target>` (never use > < or "
                    "-> in an echo; they redirect to junk files — put comparisons in `if`)")
    # a leftover of the redirection bug: an echo with > / < / -> writes junk files
    if re.search(r"^\s*echo\b[^\n]*(->|[<>])", src, re.IGNORECASE | re.MULTILINE):
        hard.append("an `echo` line contains `>` `<` or `->` — ngspice treats these as FILE "
                    "REDIRECTION and writes junk files. Remove them: put every comparison in an "
                    "`if (...)` condition and keep echo to plain words + `=`/`:`")
    return hard, soft


# element-letter → human device type (for the extracted-parameter dump)
_ELEM_TYPE = {
    "m": "mosfet", "q": "bjt", "j": "jfet", "z": "mesfet",
    "r": "resistor", "c": "capacitor", "l": "inductor",
    "d": "diode", "v": "vsource", "i": "isource",
    "e": "vcvs", "g": "vccs", "f": "cccs", "h": "ccvs",
    "k": "coupling", "x": "subckt_inst", "b": "behavioral", "s": "switch",
}


def extract_params_from_netlist(text: str) -> dict:
    """Pull the COMPLETE parameter set out of a reference SPICE netlist so the config can be
    SEEDED from a real similar design (the user's rule: research a similar netlist/paper, then
    extract ITS parameter values instead of inventing them — ALL of them, not just W/L/M).

    For EVERY element it captures: the element type, its model/subckt, every trailing scalar
    value (R/C/L/source magnitude), AND every `key=value` on the card (w, l, m, nf, ad, as,
    pd, ps, nrd, nrs, geo, temp, ic, …). It also captures `.param`, `.model` overrides,
    `.option`, `.temp` and `.ic`. Values are kept verbatim (SI suffixes like '4u', '1.2p')."""
    out: dict = {"elements": {}, "params": {}, "models": {}, "options": {}, "globals": {}}

    def _kv(stmt: str) -> dict:
        return {m.group(1).lower(): m.group(2)
                for m in re.finditer(r"\b([a-zA-Z]\w*)\s*=\s*"
                                     r"(\{[^}]*\}|'[^']*'|[-+0-9.eE]+[a-zA-Z%]*|\S+)", stmt)}

    for _no, s in _logical_lines(text or ""):
        low = s.lower()
        toks = s.split()
        if not toks:
            continue
        if low.startswith(".param"):
            out["params"].update(_kv(s))
            continue
        if low.startswith(".model"):
            if len(toks) >= 3:
                out["models"][toks[1]] = {"type": toks[2], **_kv(s)}
            continue
        if low.startswith(".option"):
            out["options"].update(_kv(s) or {t: True for t in toks[1:]})
            continue
        if low.startswith((".temp", ".ic", ".nodeset")):
            out["globals"][toks[0].lstrip(".")] = " ".join(toks[1:])
            continue
        if s[0] == ".":
            continue
        el = s[0].lower()
        etype = _ELEM_TYPE.get(el)
        if not etype:
            continue
        kv = _kv(s)
        # trailing scalar value(s) with no '=' after the nodes (R/C/L/source magnitude, model name)
        rest = [t for t in toks[1:] if "=" not in t]
        model = next((t for t in rest if re.search(
            r"[a-zA-Z].*(?:fet|mos|nch|pch|npn|pnp|diode|res|cap|ind)", t, re.I)), "")
        scalars = [t for t in rest if re.match(r"^[-+0-9.]", t) or re.match(r"^(dc|ac|sin|pulse|pwl|exp)", t, re.I)]
        entry = {"type": etype}
        if model:
            entry["model"] = model
        if scalars:
            entry["value"] = " ".join(scalars[-4:]) if etype in ("vsource", "isource") else scalars[-1]
        if kv:
            entry["params"] = kv                   # EVERY key=value on the card
        out["elements"][toks[0]] = entry
    return {k: v for k, v in out.items() if v}


def extract_params_summary(text: str) -> str:
    """Compact LLM-readable dump of ALL extracted reference parameters — written to
    context/reference_params.md so the generator copies the starting values."""
    p = extract_params_from_netlist(text)
    if not p:
        return ""
    lines: List[str] = []
    for name, d in (p.get("elements") or {}).items():
        bits = [f"type={d['type']}"]
        if d.get("model"):
            bits.append(f"model={d['model']}")
        if d.get("value"):
            bits.append(f"value={d['value']}")
        for k, v in (d.get("params") or {}).items():
            bits.append(f"{k}={v}")
        lines.append(f"- {name}: " + ", ".join(bits))
    if p.get("params"):
        lines.append("- .param: " + ", ".join(f"{k}={v}" for k, v in p["params"].items()))
    for mname, md in (p.get("models") or {}).items():
        lines.append(f"- .model {mname} ({md.get('type','')}): "
                     + ", ".join(f"{k}={v}" for k, v in md.items() if k != "type"))
    for k, v in (p.get("globals") or {}).items():
        lines.append(f"- .{k}: {v}")
    if p.get("options"):
        lines.append("- .option: " + ", ".join(f"{k}={v}" for k, v in p["options"].items()))
    return "\n".join(lines)


def parse_dir(netlist_dir: str | Path) -> dict:
    """Parse every netlist file in a directory.

    Returns {"defs": {subckt: {"file": name, "ports": [...]}},
             "insts": {subckt: [called_subckt, ...]}} — the analog analogue of
    the old verilog parse_rtl, used for top-picking and stray pruning."""
    d = Path(netlist_dir)
    defs: dict = {}
    insts: dict = {}
    if not d.exists():
        return {"defs": defs, "insts": insts}
    for p in sorted(d.iterdir()):
        if not p.is_file() or p.suffix.lower() not in NETLIST_SUFFIXES:
            continue
        try:
            parsed = parse_netlist(p.read_text(errors="replace"))
        except Exception:  # noqa: BLE001
            continue
        for key, sc in parsed["subckts"].items():
            defs[sc["name"]] = {"file": p.name, "ports": sc["ports"]}
            called: List[str] = []
            for _no, s in sc["lines"]:
                if s[:1].lower() == "x":
                    rest = [t for t in s.split()[1:] if "=" not in t]
                    if rest:
                        called.append(rest[-1])
            insts[sc["name"]] = called
    return {"defs": defs, "insts": insts}


def unconnected_pins(netlist_dir: str | Path, top: str) -> List[dict]:
    """Every FLOATING connection in the design, machine-readable — the analog version of
    the digital 'no disconnected pins' gate (user rule: every port must be connected and
    every net routed, otherwise LVS fails). Two classes:
      (a) dangling_port    — a .subckt port never used inside its body;
      (b) floating_net     — an internal net used exactly once (one terminal = unconnected).
    Checks the top circuit AND every subckt it reaches. Returns
    [{kind, subckt, name}] so the corrector can wire each one to a real net."""
    d = Path(netlist_dir)
    out: List[dict] = []
    if not d.exists():
        return out
    info = parse_dir(d)
    # subckts in the top's cone (or all, when top unknown)
    scope = set(info["defs"])
    if top and top in info["defs"]:
        scope, stack = set(), [top]
        while stack:
            m = stack.pop()
            if m in scope:
                continue
            scope.add(m)
            stack += [c for c in info["insts"].get(m, []) if c in info["defs"]]
    rails = {"0", "gnd", "vss", "vdd", "vcc", "vssa", "vdda", "vssd", "vddd"}
    for p in sorted(d.iterdir()):
        if not p.is_file() or p.suffix.lower() not in NETLIST_SUFFIXES:
            continue
        try:
            parsed = parse_netlist(p.read_text(errors="replace"))
        except Exception:  # noqa: BLE001
            continue
        for _key, sc in parsed["subckts"].items():
            if sc["name"] not in scope:
                continue
            net_count: dict = {}
            for _no, s in sc["lines"]:
                if s.lower().startswith("."):
                    continue
                _el, nodes = _device_nodes(s)
                for nd in nodes:
                    net_count[nd.lower()] = net_count.get(nd.lower(), 0) + 1
            plow = {q.lower() for q in sc["ports"]}
            for q in sc["ports"]:
                if q.lower() not in net_count:
                    out.append({"kind": "dangling_port", "subckt": sc["name"], "name": q})
            for nd, cnt in net_count.items():
                if cnt == 1 and nd not in plow and nd not in rails:
                    out.append({"kind": "floating_net", "subckt": sc["name"], "name": nd})
    return out


def pick_top(netlist_dir: str | Path) -> str:
    """The top circuit = a defined subckt that nothing instantiates; ties break toward the
    one that instantiates the most others, then alphabetically. '' when none."""
    info = parse_dir(netlist_dir)
    defs, insts = info["defs"], info["insts"]
    if not defs:
        return ""
    called = {c.lower() for lst in insts.values() for c in lst}
    tops = [m for m in defs if m.lower() not in called]
    if not tops:
        tops = list(defs)
    tops.sort(key=lambda m: (-len(insts.get(m, [])), m.lower()))
    return tops[0]


def ngspice_parse_check(path: str | Path, timeout: int = 60) -> str:
    """Let ngspice's parser validate the file (models resolved from the PDK when
    available). Returns '' when the parse is clean, else the Error lines."""
    p = Path(path).resolve()
    ngspice = os.getenv("NGSPICE_BIN", "ngspice")
    lib = _pdk_lib_line()
    deck = "* anoa parse check\n"
    if lib:
        deck += lib + "\n"
    deck += f".include {p}\n.control\nquit\n.endc\n.end\n"
    with tempfile.TemporaryDirectory(prefix="anoa_nl_") as td:
        deckf = Path(td) / "parse_check.sp"
        deckf.write_text(deck)
        try:
            proc = subprocess.run([ngspice, "-b", str(deckf)], capture_output=True,
                                  text=True, timeout=timeout, cwd=td)
        except FileNotFoundError:
            return ""          # ngspice not installed — structural lint already ran
        except subprocess.TimeoutExpired:
            return "ngspice parse check timed out"
        out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    errs = [ln.strip() for ln in out.splitlines()
            if re.search(r"^\s*(Error|ERROR)[:\s]", ln)
            and "no such file" not in ln.lower()]
    return "\n".join(errs[:20])
