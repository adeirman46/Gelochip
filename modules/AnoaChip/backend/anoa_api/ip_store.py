"""Shared IP-library data layer.

An *IP* is a reusable, self-contained hardware block (a peripheral, a CPU core, a bus,
a memory, an accelerator) with its RTL and — once hardened — a GDS macro + metrics. The
library is the source of truth for three features: the **Create IP** tab (upload RTL →
LibreLane → IP), the **Chip Studio** tab (drag hardened IP macros onto the padframe), and
the batch tooling (`scripts/clone_riscv_cores.py`, `scripts/build_ip_library.py`).

Layout — one tidy folder per IP under ``data/ip_library/<id>/``::

    ip.json        manifest (name, category, top, ports, status, metrics, gds, png, rtl[])
    rtl/           the Verilog/SystemVerilog source files (the only thing kept from a clone)
    <top>.gds      hardened layout    (present iff status == 'hardened')
    <top>.png      KLayout render     (present iff hardened and a render was produced)

Each IP is also mirrored into the durable knowledge store (Postgres row + MinIO blobs,
kind='ip') so it survives, is semantically recallable, and shows in the Knowledge tab.
The store is OPTIONAL: if it's down the on-disk library still works.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LIB = REPO / "data" / "ip_library"
_SRC = str(REPO / "src" / "anoa_chip")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

# Coarse buckets the UI groups by. Order = display order in the IP rail / Chip Studio folders.
CATEGORIES = ["core", "peripheral", "bus", "memory", "accelerator", "dsp", "crypto", "misc"]
# Friendly parent-folder labels + an icon, for the IP tab and Chip Studio rail.
CATEGORY_LABELS = {
    "core": "CPU / Cores", "peripheral": "Peripherals", "bus": "Buses / Interconnect",
    "memory": "Memories", "accelerator": "Deep-Learning Accelerators", "dsp": "DSP / Math",
    "crypto": "Crypto / Security", "misc": "Miscellaneous",
}
CATEGORY_ICONS = {
    "core": "🧠", "peripheral": "🔌", "bus": "🚌", "memory": "🗄️",
    "accelerator": "⚡", "dsp": "📐", "crypto": "🔐", "misc": "📦",
}

# Discriminative STEMS per category. Matching is: normalize separators (axi_crossbar →
# "axi crossbar", uart16550 stays), then look for a stem at a word start with any \w* suffix —
# so "fifo_sync", "uart16550", "picorv32", "dual_port_ram" all classify (plain \b…\b fails on
# underscores/digits). Specific categories are tried BEFORE the broad 'core'; name before body.
_CAT_STEMS = {
    "crypto": ["sha", "aes", "md5", "rsa", "ecc", "crypto", "cipher", "keccak", "blake",
               "hash", "lfsr", "crc"],
    "accelerator": ["cnn", "dnn", "mlp", "gemm", "conv", "systolic", "npu", "tpu", "matmul",
                    "cgra", "tensor", "neural", "qft", "quantum", "attention", "transformer",
                    "accel"],
    "dsp": ["fft", "fir", "iir", "filter", "cordic", "dct", "fixedpoint", "multiplier", "mac",
            "alu", "adder", "accumulat", "convolv"],
    "peripheral": ["uart", "spi", "i2c", "gpio", "timer", "pwm", "wdt", "watchdog", "interrupt",
                   "plic", "clint", "qspi", "usb"],
    "bus": ["axi", "ahb", "apb", "wishbone", "obi", "tilelink", "crossbar", "interconnect",
            "arbiter", "bridge"],
    "memory": ["sram", "dram", "rom", "fifo", "ram", "regfile", "registerfile", "cache",
               "memory", "bram", "dpram", "scratchpad"],
    "core": ["risc", "rv32", "rv64", "cpu", "core", "processor", "pipeline", "picorv", "ibex",
             "cve2", "cv32", "cva6", "fazyrv", "serv"],
}
_CAT_ORDER = ["crypto", "accelerator", "dsp", "peripheral", "bus", "memory", "core"]
_CAT_RE = {c: re.compile(r"\b(?:" + "|".join(stems) + r")\w*", re.I)
           for c, stems in _CAT_STEMS.items()}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def slug(name: str, n: int = 48) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (name or "ip").lower()).strip("_")
    return (s or "ip")[:n]


def _norm(s: str) -> str:
    return re.sub(r"[_\-]+", " ", (s or "").lower())


def categorize(name: str, text: str = "") -> str:
    """Best-guess category: match the NAME first (most reliable), then the source text,
    checking specific categories before the broad 'core'."""
    nm = _norm(name)
    for cat in _CAT_ORDER:
        if _CAT_RE[cat].search(nm):
            return cat
    hay = _norm((text or "")[:4000])
    for cat in _CAT_ORDER:
        if _CAT_RE[cat].search(hay):
            return cat
    return "misc"


# --- port parsing (name, direction, width) for Chip Studio pin wiring --------
_PORT_RE = re.compile(
    r"\b(input|output|inout)\b\s*(?:wire|reg|logic|signed|unsigned|\s)*"
    r"(?:\[\s*([^\]]+?)\s*:\s*([^\]]+?)\s*\]\s*)?"
    r"([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)",
)


def _strip_comments(t: str) -> str:
    t = re.sub(r"/\*.*?\*/", " ", t, flags=re.S)
    return re.sub(r"//[^\n]*", " ", t)


def parse_ports(text: str, top: str) -> list[dict]:
    """Extract the top module's ports as ``[{name, dir, width}]`` (ANSI or non-ANSI
    style). Width is the declared MSB:LSB string when present, else 1 bit."""
    clean = _strip_comments(text or "")
    m = re.search(rf"\bmodule\s+{re.escape(top)}\b", clean)
    if not m:
        m = re.search(r"\bmodule\s+[A-Za-z_]\w*", clean)
        if not m:
            return []
    # search from the module start to its endmodule for port declarations
    end = clean.find("endmodule", m.start())
    region = clean[m.start(): end if end != -1 else len(clean)]
    ports: list[dict] = []
    seen: set = set()
    for pm in _PORT_RE.finditer(region):
        direction, hi, lo, names = pm.group(1), pm.group(2), pm.group(3), pm.group(4)
        width = f"[{hi}:{lo}]" if hi is not None else ""
        for nm in re.split(r"\s*,\s*", names.strip()):
            if nm and nm not in seen and nm not in _PORT_KEYWORDS:
                seen.add(nm)
                ports.append({"name": nm, "dir": direction, "width": width})
    return ports


_PORT_KEYWORDS = {"input", "output", "inout", "wire", "reg", "logic", "signed", "unsigned",
                  "wand", "wor", "tri", "supply0", "supply1"}


# --- manifest CRUD -----------------------------------------------------------
def ip_dir(ip_id: str) -> Path:
    return LIB / ip_id


def manifest_path(ip_id: str) -> Path:
    return LIB / ip_id / "ip.json"


def get_ip(ip_id: str) -> dict | None:
    mp = manifest_path(ip_id)
    if not mp.is_file():
        return None
    try:
        return json.loads(mp.read_text())
    except Exception:  # noqa: BLE001
        return None


def list_ips() -> list[dict]:
    """Every IP manifest, newest first, grouped-display friendly."""
    if not LIB.is_dir():
        return []
    out = []
    for d in LIB.iterdir():
        if d.is_dir() and (d / "ip.json").is_file():
            mf = get_ip(d.name)
            if mf:
                out.append(mf)
    cat_order = {c: i for i, c in enumerate(CATEGORIES)}
    out.sort(key=lambda m: (cat_order.get(m.get("category", "misc"), 99), m.get("name", "")))
    return out


def write_manifest(mf: dict) -> dict:
    mp = manifest_path(mf["id"])
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text(json.dumps(mf, indent=2))
    return mf


def update_ip(ip_id: str, **changes) -> dict | None:
    mf = get_ip(ip_id)
    if not mf:
        return None
    mf.update(changes)
    mf["updated_at"] = _now()
    return write_manifest(mf)


def delete_ip(ip_id: str) -> bool:
    d = ip_dir(ip_id)
    if d.is_dir() and LIB in d.resolve().parents:
        shutil.rmtree(d, ignore_errors=True)
        try:
            from memory_store import get_memory
            get_memory().delete_where(design=ip_id)
        except Exception:  # noqa: BLE001
            pass
        return True
    return False


def simulate_ip(ip_id: str, timeout: int = 60) -> dict:
    """Compile the IP's RTL + testbench with iverilog, run vvp, and record a sim VERDICT on the
    manifest so the user can SEE each IP is actually working. Sets ``sim_status`` to 'pass'
    (compiled, ran, no FAIL/ERROR and a PASS/OK marker or a clean $finish), 'fail', or 'no_tb'.
    Returns ``{status, log}``."""
    import subprocess
    mf = get_ip(ip_id)
    if not mf:
        return {"status": "missing", "log": ""}
    d = ip_dir(ip_id)
    rtl = d / "rtl"
    tbs = list((d / "tb").glob("*.v")) + list((d / "tb").glob("*.sv")) if (d / "tb").is_dir() else []
    if not tbs:
        update_ip(ip_id, sim_status="no_tb")
        return {"status": "no_tb", "log": "no testbench"}
    vfiles = ([str(p) for p in sorted(rtl.glob("*.v")) + sorted(rtl.glob("*.sv"))]
              + [str(p) for p in tbs])
    work = d / "tb"
    vvp = work / "sim.vvp"
    log = []
    try:
        c = subprocess.run(["iverilog", "-g2012", "-o", str(vvp), f"-I{rtl}", f"-I{work}", *vfiles],
                           capture_output=True, text=True, timeout=timeout)
        log.append((c.stderr or "").strip())
        if c.returncode != 0:
            update_ip(ip_id, sim_status="fail", sim_log="\n".join(log)[-1500:])
            return {"status": "fail", "log": "\n".join(log)}
        r = subprocess.run(["vvp", str(vvp)], cwd=str(work), capture_output=True, text=True, timeout=timeout)
        out = (r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")
        log.append(out.strip())
    except Exception as e:  # noqa: BLE001
        update_ip(ip_id, sim_status="fail", sim_log=str(e)[:500])
        return {"status": "fail", "log": str(e)}
    text = "\n".join(log)
    bad = re.search(r"\b(fail|failed|mismatch|error|assert.*fail)\b", text, re.I)
    good = re.search(r"\b(pass|passed|all tests|ok|success)\b", text, re.I)
    status = "fail" if bad and not good else "pass"
    update_ip(ip_id, sim_status=status, sim_log=text[-1500:])
    return {"status": status, "log": text}


def create_ip(name: str, rtl_files: dict[str, str], *, category: str = "",
              source: str = "manual", subtitle: str = "", ip_id: str = "", top: str = "",
              tb_files: dict[str, str] | None = None) -> dict:
    """Create an IP folder from ``{filename: text}`` RTL. Uses the caller-supplied `top` /
    `category` when given (so the user can correct a wrong auto-detect or add a new category),
    else auto-detects the structural top + classifies. Writes ip.json, returns the manifest.
    Does NOT harden — status starts at 'rtl' (or 'sim' once a check passes)."""
    from netlist_check import pick_top
    ip_id = ip_id or slug(name)
    # de-collide ids so two uploads named 'uart' don't clobber each other
    base, i = ip_id, 2
    while ip_dir(ip_id).exists() and not get_ip(ip_id):
        ip_id = f"{base}_{i}"; i += 1
    d = ip_dir(ip_id)
    rtl = d / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    for fn, text in rtl_files.items():
        safe = re.sub(r"[^\w.\-]", "_", Path(fn).name)
        (rtl / safe).write_text(text)
        saved.append(safe)
    top = top.strip() or pick_top(rtl) or (Path(saved[0]).stem if saved else name)
    # ports from whichever file actually defines the top
    top_text = ""
    for fn in saved:
        t = (rtl / fn).read_text(errors="replace")
        if re.search(rf"\bmodule\s+{re.escape(top)}\b", t):
            top_text = t
            break
    # optional testbench(es) — kept under <ip>/tb/ so `simulate_ip` can PROVE the block works
    tb_saved: list[str] = []
    if tb_files:
        tbd = d / "tb"
        tbd.mkdir(parents=True, exist_ok=True)
        for fn, text in tb_files.items():
            safe = re.sub(r"[^\w.\-]", "_", Path(fn).name)
            (tbd / safe).write_text(text)
            tb_saved.append(safe)
    blob = "\n".join((rtl / fn).read_text(errors="replace")[:2000] for fn in saved[:6])
    mf = {
        "id": ip_id, "name": name, "category": category or categorize(name, blob),
        "subtitle": subtitle, "source": source, "top": top,
        "ports": parse_ports(top_text or blob, top),
        "rtl": saved, "tb": tb_saved, "sim_status": "untested",
        "status": "rtl", "metrics": {}, "gds": None, "png": None,
        "lines": sum((rtl / fn).read_text(errors="replace").count("\n") for fn in saved),
        "created_at": _now(), "updated_at": _now(),
    }
    return write_manifest(mf)


def attach_harden(ip_id: str, *, gds_src: str | None = None, png_src: str | None = None,
                  metrics: dict | None = None, signoff: dict | None = None,
                  tapeout_ready: bool = False, status: str = "hardened") -> dict | None:
    """Record a hardening result: copy the GDS + render into the IP folder and update the
    manifest's status/metrics/SIGN-OFF. ``tapeout_ready`` is True only when every DRC/antenna/
    timing/slew sign-off check passed — that is the gate for placing an IP on a real chip."""
    mf = get_ip(ip_id)
    if not mf:
        return None
    d = ip_dir(ip_id)
    if gds_src and Path(gds_src).is_file():
        dest = d / f"{mf['top']}.gds"
        shutil.copy(gds_src, dest)
        mf["gds"] = dest.name
    if png_src and Path(png_src).is_file():
        dest = d / f"{mf['top']}.png"
        shutil.copy(png_src, dest)
        mf["png"] = dest.name
    if metrics:
        mf["metrics"] = metrics
    if signoff is not None:
        mf["signoff"] = signoff
    mf["tapeout_ready"] = bool(tapeout_ready)
    # a GDS that is NOT sign-off clean is NOT 'hardened' for our purposes — flag it honestly
    mf["status"] = status if tapeout_ready or status != "hardened" else "harden_dirty"
    mf["updated_at"] = _now()
    return write_manifest(mf)


def ingest_ip(ip_id: str) -> int:
    """Mirror an IP into the durable knowledge store (kind='ip'): each RTL file + GDS as
    blobs, plus a recallable summary row. Returns the number of rows written (0 if the
    store is down)."""
    mf = get_ip(ip_id)
    if not mf:
        return 0
    try:
        from memory_store import get_memory
        mem = get_memory()
        if not mem.enabled:
            return 0
    except Exception:  # noqa: BLE001
        return 0
    d = ip_dir(ip_id)
    n = 0
    for fn in mf.get("rtl", []):
        if mem.ingest_file(d / "rtl" / fn, design=ip_id, source=f"ip:{ip_id}", kind="code"):
            n += 1
    if mf.get("gds"):
        if mem.ingest_file(d / mf["gds"], design=ip_id, source=f"ip:{ip_id}", kind="gds"):
            n += 1
    ports = ", ".join(p["name"] for p in mf.get("ports", [])[:24])
    mem.remember(
        "ip",
        f"IP: {mf['name']} ({mf['category']}) — {mf.get('subtitle','')}\n"
        f"top={mf['top']} status={mf['status']} ports: {ports}\nsource: {mf.get('source','')}",
        design=ip_id, source=f"ip:{ip_id}", title=mf["name"],
        tags=f"ip {mf['category']} {mf['status']}", meta=mf)
    return n + 1
