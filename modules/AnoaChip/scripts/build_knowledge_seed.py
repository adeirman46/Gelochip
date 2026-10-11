#!/usr/bin/env python3
"""
Rebuild AnoaChip's knowledge seed from the local gLayout checkout.

The user's ask: "Hapus semua knowledge database dan isi dari .ipynb dan .py dari
cells/ atau blocks/ dari folder glayout/". So this script:

  1. WIPES the durable knowledge store (or just the seed rows if the DB is down),
  2. INGESTS, as reusable `code` / `reference` knowledge:
       • every gLayout cell generator  (src/glayout/cells/**/*.py) — the real
         placement + routing patterns the layout agent should imitate;
       • every routing/primitive module (src/glayout/routing/*.py,
         src/glayout/primitives/*.py) — how c_route / L_route / straight_route /
         via_stack are used;
       • every tutorial / notebook      (tutorial/*.ipynb, notebook/*.ipynb),
         converted to text with jupytext — worked OTA / current-mirror / FVF
         examples end-to-end;
       • any example SPICE netlists      (*.sp / *.spice) found in the checkout;
  3. adds a handful of distilled `note` lessons (the AnoaChip routing/finishing
     rules), and
  4. EXPORTS the committed seed (data/knowledge_seed/) so a fresh clone starts warm.

Usage:
    uv run python scripts/build_knowledge_seed.py                 # uses ../gLayout
    uv run python scripts/build_knowledge_seed.py /path/to/gLayout
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src" / "anoa_chip"))

from memory_store import get_memory  # noqa: E402


def _notebook_to_text(path: Path) -> str:
    """.ipynb → markdown/py text (jupytext if available, else a plain cell dump)."""
    try:
        import jupytext
        nb = jupytext.read(str(path))
        return jupytext.writes(nb, fmt="py:percent")
    except Exception:  # noqa: BLE001
        try:
            import json
            nb = json.loads(path.read_text())
            out = []
            for c in nb.get("cells", []):
                src = "".join(c.get("source", []))
                if c.get("cell_type") == "markdown":
                    out.append("# --- markdown ---\n" + src)
                else:
                    out.append(src)
            return "\n\n".join(out)
        except Exception:  # noqa: BLE001
            return ""


# The distilled AnoaChip rules — always seeded so the agent recalls them even with
# an otherwise empty store.
_RULES = [
    ("routing: pick the right primitive",
     "Route every net with the correct primitive: straight_route ONLY for inline parallel "
     "ports; c_route for offset parallel ports; L_route for perpendicular ports; smart_route "
     "picks automatically. Bridge metal layers with via_stack. A straight_route between "
     "non-inline ports silently generates NOTHING, which makes LVS report the net as 'only in "
     "schematic'."),
    ("devices: bare first, tie/tap/dummy last",
     "Generate nmos()/pmos() with with_tie=False, with_substrate_tap=False, with_dummy=False "
     "FIRST. Route the circuit and get LVS clean on the bare devices, THEN add substrate ties, "
     "guard ring (tapring) and dummies as finishing steps and re-verify. Never take the default "
     "device sizing — pass width/length/fingers/multipliers from the design config."),
    ("placement: explicit movex/movey/center",
     "Place every device reference explicitly with movex/movey/center (align with evaluate_bbox "
     "and align_comp_to_port). Never leave two devices overlapping or a reference at the origin."),
    ("ports: expose and connect",
     "Every Component must add_port/add_ports for VDD, VSS, every input/output and bias so "
     "routing and LVS can see the pins. Every port on a netlist .subckt must be used in the body "
     "— a dangling port or a single-terminal net is a floating node that fails LVS."),
    ("labels: every layout pin needs a text label",
     "EVERY layout must expose PORTS **and LABELS**: after add_ports, place a text label on each "
     "external pin's metal (glayout add_glayout_labels / labelled_ports, or a gdstk/gdsfactory "
     "Label on the PDK label layer at the port center). magic/netgen LVS matches nets by these "
     "labels, so an unlabelled pin reads as unconnected even when it is routed. No layout ships "
     "without a port and a label for every external pin (VDD, VSS, inputs, outputs, bias)."),
    ("config-first self-improve",
     "Generate config/<name>.json (spec table + every sizing parameter) BEFORE the netlist or "
     "layout. When a spec fails, MUTATE the config parameters (W/L/fingers, bias current, "
     "compensation cap) and regenerate — never hand-patch the generated output. Save each "
     "improvement as a lesson."),
]


def _passive_rules():
    """The inductor + mimcap guidance (imported from anoa_chip.passives so it stays in
    one place)."""
    try:
        import sys as _s
        _s.path.insert(0, str(REPO_ROOT / "src" / "anoa_chip"))
        from passives import INDUCTOR_NOTE, MIMCAP_NOTE
        return [("inductor: none in glayout — spiral gen / active inductor", INDUCTOR_NOTE),
                ("mimcap: glayout primitive + how to combine into a design", MIMCAP_NOTE)]
    except Exception:  # noqa: BLE001
        return []


_RULES += _passive_rules()


def main() -> int:
    gl = Path(sys.argv[1]) if len(sys.argv) > 1 else (REPO_ROOT.parent / "gLayout")
    src = gl / "src" / "glayout"
    if not src.exists():
        print(f"! gLayout checkout not found at {gl} — pass the path as an argument.")
        return 2

    mem = get_memory()
    if not getattr(mem, "enabled", False):
        print("! Knowledge store is DISABLED/unreachable (docker compose up -d?). "
              "Rules/files can't be ingested; nothing to export.")
        return 1

    print(f"→ gLayout: {gl}")
    # 1) WIPE the store so the seed is EXACTLY the gLayout knowledge (user's ask).
    try:
        wiped = mem.wipe() if hasattr(mem, "wipe") else 0
        print(f"  wiped {wiped} existing row(s)" if wiped else "  (store cleared)")
    except Exception as e:  # noqa: BLE001
        print(f"  (could not wipe — appending instead: {e})")

    n = 0
    # 2a) cell generators + routing/primitive modules → `code`
    code_roots = [src / "cells", src / "routing", src / "primitives",
                  src / "placement"]
    for root in code_roots:
        if not root.exists():
            continue
        for p in sorted(root.rglob("*.py")):
            if "__pycache__" in p.parts or p.name == "__init__.py":
                continue
            txt = p.read_text(errors="replace")
            if len(txt) < 80:
                continue
            title = f"glayout {p.relative_to(src)}"
            if mem.remember("code", txt[:12000], design="glayout",
                            source=f"glayout:{p.relative_to(gl)}", title=title[:120],
                            tags="glayout cell routing primitive"):
                n += 1
    print(f"  ingested {n} glayout code module(s)")

    # 2b) tutorials / notebooks → `reference`
    nb_dirs = [gl / "tutorial", gl / "notebook"]
    nn = 0
    for d in nb_dirs:
        if not d.exists():
            continue
        for p in sorted(d.glob("*.ipynb")):
            txt = _notebook_to_text(p)
            if len(txt) < 120:
                continue
            if mem.remember("reference", txt[:14000], design="glayout",
                            source=f"glayout:{p.relative_to(gl)}", title=f"tutorial {p.stem}"[:120],
                            tags="glayout tutorial notebook example"):
                nn += 1
    print(f"  ingested {nn} tutorial/notebook(s)")

    # 2c) example SPICE netlists → `code`
    ns = 0
    for p in sorted(src.rglob("*.sp")) + sorted(src.rglob("*.spice")):
        if "__pycache__" in p.parts:
            continue
        txt = p.read_text(errors="replace")
        if ".subckt" not in txt.lower() and len(txt) < 200:
            continue
        if mem.remember("code", txt[:10000], design="glayout",
                        source=f"glayout:{p.relative_to(gl)}", title=f"netlist {p.name}"[:120],
                        tags="spice netlist example"):
            ns += 1
    print(f"  ingested {ns} example netlist(s)")

    # 3) distilled rules → `note`
    for title, body in _RULES:
        if mem.remember("note", body, design="anoachip", source="rules",
                        title=title[:120], tags="rule routing finishing"):
            n += 1
    print(f"  seeded {len(_RULES)} distilled rule(s)")

    total = mem.stats().get("total", "?")
    print(f"→ store now holds {total} item(s)")

    # 4) export the committed seed so a fresh clone starts warm
    try:
        exported = mem.export_seed()
        print(f"→ exported committed seed: {exported} row(s) → data/knowledge_seed/")
    except Exception as e:  # noqa: BLE001
        print(f"! export_seed failed: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
