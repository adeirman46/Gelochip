"""Generators for the ALIGN notebooks (run with the project .venv python):

    ../../.venv/bin/python _build_notebook.py

  • sky130_examples.ipynb — 5 sky130 circuits: SPICE -> GDS (ALIGN) -> KLayout
  • gf180_align.ipynb     — EVERY examples/ topology rewritten as a gf180 netlist (same topology,
                            gf180 models + valid sizing), one cell each: SPICE -> gf180 GDS (ALIGN +
                            GF180_PDK) -> gf180 DRC + LVS -> KLayout. Cells are robust: a topology
                            that won't route on the planar gf180 PDK notes it and Run-All continues.
"""
import re
from pathlib import Path
import nbformat as nbf

ALIGN_DIR = Path(__file__).resolve().parent
EX = ALIGN_DIR / "examples"


def read_sp(relpath):
    return (ALIGN_DIR / relpath).read_text().strip()


def to_gf180(text):
    """Rewrite a netlist for gf180: gf180 models, uniform W (5*Fin_pitch), even NF — same topology."""
    out = []
    for line in text.splitlines():
        s = line.split()
        if s and s[0][0] in "mM" and len(s) >= 6 and not line.lstrip().startswith("*"):
            ml = s[5].lower()
            s[5] = "pfet_03v3" if ("pfet" in ml or "pmos" in ml or ml == "p") else "nfet_03v3"
            for i, tok in enumerate(s[6:], start=6):
                if re.match(r"(?i)^w=[0-9.eE+-]+$", tok):
                    s[i] = "w=1.05e-6"
                else:
                    m = re.match(r"(?i)^nf=([0-9]+)$", tok)
                    if m:
                        nf = int(m.group(1))
                        s[i] = f"nf={nf if nf % 2 == 0 else nf + 1}"
            line = " ".join(s)
        out.append(line)
    return "\n".join(out)


def build(cells_fn, out_name):
    nb = nbf.v4.new_notebook()
    cells = []
    md = lambda s: cells.append(nbf.v4.new_markdown_cell(s.strip("\n")))
    code = lambda s: cells.append(nbf.v4.new_code_cell(s.strip("\n")))
    cells_fn(md, code)
    nb["cells"] = cells
    nb["metadata"] = {"kernelspec": {"display_name": "Python 3 (project .venv)",
                                     "language": "python", "name": "python3"},
                      "language_info": {"name": "python"}}
    nbf.write(nb, ALIGN_DIR / out_name)
    print("wrote", ALIGN_DIR / out_name, "with", len(cells), "cells")


SETUP = ('import os, sys\n'
         'os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")\n'
         'from spice2gds import spice2gds, show_gds, available_pdks\n'
         'from gf180_check import gf180_drc, gf180_lvs\n'
         'print("PDKs:", available_pdks())')


# ── sky130: 5 examples (plain) ───────────────────────────────────────
SKY130 = [("inverter", "Inverter"), ("buffer", "Buffer"),
          ("current_mirror_ota", "Current-mirror OTA"),
          ("five_transistor_ota", "Five-transistor OTA"), ("telescopic_ota", "Telescopic OTA")]


def sky130_nb(md, code):
    md("# sky130 · SPICE → GDS (ALIGN) → KLayout\n\n5 circuits on the open **sky130** PDK. "
       "**Run All** (~3–4 min); one-time `bash setup_align.sh`, project `.venv` kernel.")
    md("### Setup")
    code('import os, sys\nos.environ.setdefault("QT_QPA_PLATFORM","offscreen")\n'
         'from spice2gds import spice2gds, show_gds, available_pdks\nprint("PDKs:", available_pdks())')
    for i, (name, desc) in enumerate(SKY130, 1):
        md(f"## {i} · {desc} — `{name}`")
        code(f'NETLIST = r"""\n{read_sp(f"examples/sky130/{name}/{name}.sp")}\n"""\n\n'
             f'gds = spice2gds("{name}", NETLIST, pdk="SKY130_PDK")\nshow_gds(gds)')


# ── gf180: every examples/ topology, rewritten for gf180 ─────────────
def _designs():
    designs, seen = [], set()
    for sp in sorted(EX.glob("sky130/*/*.sp")) + sorted(EX.glob("*/*.sp")):
        if sp.stem == sp.parent.name and sp.stem not in seen:
            seen.add(sp.stem)
            designs.append((sp.stem, sp))
    return designs


def gf180_nb(md, code):
    designs = _designs()
    md("# gf180 · all examples → GDS (ALIGN) → DRC + LVS → KLayout\n\n"
       f"Every one of the **{len(designs)} `examples/` topologies**, rewritten as a gf180 netlist "
       "(same topology, gf180 models `nfet_03v3`/`pfet_03v3`, valid sizing) and placed & routed by "
       "ALIGN on **GF180MCU** via `GF180_PDK`. Each cell runs **gf180 DRC** (geometry vs real gf180 "
       "rules) + **LVS** (device extraction vs the netlist) via the `klayout` module in your venv — "
       "no Magic, no conda. Cells are robust: a topology that won't route on the planar gf180 PDK "
       "notes it and Run-All continues.\n\n"
       "> `GF180_PDK` geometry is sky130-scaled, so `gf180_drc` reports violations (not yet DRC-clean; "
       "tapeout needs PDK-rule + generator tuning). **Run All is long.** `bash setup_align.sh` first.")
    md("### Setup")
    code(SETUP)
    for i, (name, sp) in enumerate(designs, 1):
        md(f"## {i} · `{name}`")
        code(f'NETLIST = r"""\n{to_gf180(sp.read_text())}\n"""\n\n'
             f'try:\n'
             f'    gds = spice2gds("{name}", NETLIST, pdk="GF180_PDK")\n'
             f'    gf180_drc(gds); gf180_lvs(gds, NETLIST); show_gds(gds)\n'
             f'except Exception as e:\n'
             f'    print("{name}: did not route on GF180_PDK —", str(e).splitlines()[-1][:90])')


build(sky130_nb, "sky130_examples.ipynb")
build(gf180_nb, "gf180_align.ipynb")
