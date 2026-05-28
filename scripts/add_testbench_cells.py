"""
Append a SPICE-extraction + AC/transient testbench (matplotlib) cell to every
dataset notebook under notebooks/datasets/*. Idempotent — skips notebooks that
already contain the testbench marker. Existing DRC/LVS cells are left untouched
(LVS is kept in the dataset notebooks; the agent simply won't use it).

Run from repo root:
    .venv/bin/python scripts/add_testbench_cells.py
"""
import sys
from pathlib import Path

import nbformat

MARKER = "gelochip-testbench-cell"

TESTBENCH_SRC = f'''# ── SPICE extract + AC/Transient testbench (matplotlib) ──  [{MARKER}]
# Extracts the schematic SPICE subckt from the built layout and runs AC +
# transient testbenches in ngspice (gf180 typical models). NO LVS here — this
# is the verification the agent uses. The DRC/LVS cells above are kept as-is.
import os, sys
sys.path.insert(0, os.path.abspath("../../../src"))
import gdsfactory as _gf
from gelochip.kaizen import testbench as _tb

# Auto-locate the component built earlier in this notebook (has info["netlist"]).
_comp = next((v for v in reversed(list(globals().values()))
              if isinstance(v, _gf.Component)
              and getattr(v, "info", None) and v.info.get("netlist")), None)

if _comp is None:
    print("⚠ No built component with a netlist found — run the build cell above first.")
else:
    _ex = _tb.extract_spice(_comp)
    print("Extracted SPICE subckt:", _ex.get("circuit_name"), "nodes:", _ex.get("nodes"))
    _res = _tb.run_testbenches(component=_comp, out_dir="tb_out")
    print(f"Testbench passed={{_res['passed']}}  in={{_res.get('in_node')}}  out={{_res.get('out_node')}}")
    from IPython.display import Image, display
    for _k in ("ac", "tran"):
        _p = _res.get("plots", {{}}).get(_k)
        if _p:
            print(_k.upper(), "response:")
            display(Image(_p))
'''


def main() -> None:
    root = Path("notebooks/datasets")
    if not root.exists():
        sys.exit("run from repo root")
    added, skipped = [], []
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        nbpath = d / f"{d.name}.ipynb"
        if not nbpath.exists():
            # some dirs use a different stem — pick the only ipynb
            ipynbs = list(d.glob("*.ipynb"))
            if not ipynbs:
                continue
            nbpath = ipynbs[0]
        nb = nbformat.read(str(nbpath), as_version=4)
        if any(MARKER in c.source for c in nb.cells):
            skipped.append(nbpath.name)
            continue
        nb.cells.append(nbformat.v4.new_code_cell(TESTBENCH_SRC))
        nbformat.write(nb, str(nbpath))
        added.append(nbpath.name)
    print(f"Added testbench cell to {len(added)} notebooks:")
    for n in added:
        print("  +", n)
    if skipped:
        print(f"Skipped (already had it): {skipped}")


if __name__ == "__main__":
    main()
