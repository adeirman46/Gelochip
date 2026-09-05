"""The complete IP library for the D05 tapeout, block by block.

The transistor IPs are loaded verbatim from the signed-off notebook
(`GLayout_RF_EnergyHarvester_Signoff.ipynb`) by AST-filtering its definition
cells, so they are byte-identical to the blocks that already passed DRC and LVS.
Only the capacitors are new: GLayout's `mimcap` is a metal short on GF180, so the
banks are rebuilt on the real MIM-B stack (see `mimcap_b.py`).
"""
import ast, json, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
NB = Path("/home/irman/gLayout/notebook/GLayout_RF_EnergyHarvester_Signoff.ipynb")
DEF_CELLS = [4, 6, 7, 9, 11, 13, 15, 17, 19, 21, 23]


def _defs_only(src):
    tree = ast.parse(src); keep = []
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom)):
            keep.append(n)
        elif isinstance(n, ast.Assign):
            t = [x.id for x in n.targets if isinstance(x, ast.Name)]
            if t and all(v.isupper() or v.startswith("PDK") for v in t):
                keep.append(n)
    return "\n".join(ast.get_source_segment(src, n) for n in keep)


def load(outdir):
    """Return the notebook's definition namespace, with the capacitors replaced."""
    nb = json.load(open(NB))
    code = ["import os, io, re, shutil, time, subprocess, tempfile, contextlib, warnings",
            "from pathlib import Path", "warnings.filterwarnings('ignore')",
            "try:\n    from loguru import logger as _l; _l.remove()\nexcept Exception:\n    pass",
            f"OUTDIR = {str(outdir)!r}"]
    code += [_defs_only("".join(nb["cells"][i]["source"])) for i in DEF_CELLS]
    src = "\n\n".join(code)
    g = {}
    exec(compile(src, "<signoff-defs>", "exec"), g)
    g["_SRC"] = src        # inspect.getsource() cannot read exec'd code
    g["component_snap_to_grid"] = lambda c: c          # keep hierarchy
    g["cap_block"], g["cap_block_storage"] = make_cap_blocks(g)
    return g


# ------------------------------------------------------------------ capacitors
def make_cap_blocks(g):
    """MIM-B replacements for the notebook's cap_block / cap_block_storage.

    The old ones drew GLayout mimcaps (met2/CAP_MK/via2/met3 = a short) and
    exposed met3 stubs.  These build real MIM-B banks and expose the same
    TOP_stub_N / BOT_stub_S port names, but on **met5** -- MIMTM.10 forbids
    contacting the Metal4 bottom plate from below, so both terminals are met5.
    """
    from mimcap_b import mimcap_b_array
    from gdsfactory import Component
    evaluate_bbox = g["evaluate_bbox"]

    def _bank(pdk, target_pf, ff, max_cols, max_unit=28.0):
        """Choose unit size and array shape to hit target_pf as closely as the
        MIMTM.8b 10000 um^2 per-cap limit allows."""
        need_um2 = target_pf * 1000.0 / ff
        n = 1
        while need_um2 / n > min(10000.0, max_unit * max_unit):
            n += 1
        cols = min(max_cols, n)
        rows = -(-n // cols)
        n = rows * cols
        side = (need_um2 / n) ** 0.5
        side = max(side, 5.0)                       # MIMTM.8a: area >= 25 um^2
        side = round(side * 200) / 200.0            # snap to the 5 nm grid
        arr = mimcap_b_array(pdk, rows=rows, columns=cols, size=(side, side),
                             ff_per_um2=ff)
        print(f"[mimcap_b] {target_pf} pF -> {rows}x{cols} of {side:.3f} um square"
              f" = {arr.info['capacitance_pf']:.3f} pF"
              f"  ({evaluate_bbox(arr)[0]:.1f} x {evaluate_bbox(arr)[1]:.1f} um)")
        return arr

    def _wrap(pdk, arr):
        c = Component()
        ref = c << arr
        c.add_ports(ref.get_ports_list())
        c.add_port(name="TOP_stub_N", port=c.ports["TOP_W"])
        c.add_port(name="BOT_stub_S", port=c.ports["BOT_E"])
        c.info["capacitance_pf"] = arr.info["capacitance_pf"]
        c.info["fusetop_area_um2"] = arr.info["fusetop_area_um2"]
        return c

    def cap_block(pdk, cfg, target_pf, max_cols=6, name="capbank"):
        return _wrap(pdk, _bank(pdk, target_pf, cfg["caps"]["mim_ff_per_um2"], max_cols))

    def cap_block_storage(pdk, cfg):
        return _wrap(pdk, _bank(pdk, cfg["caps"]["storage_cap_pf"],
                                cfg["caps"]["mim_ff_per_um2"], 7))

    return cap_block, cap_block_storage


def source_of(g, name):
    """Source text of a function defined in the exec'd sign-off namespace.

    `inspect.getsource` fails on exec'd code ("could not get source code"), so the
    definition text is kept in g["_SRC"] and the function is recovered from it.
    """
    tree = ast.parse(g["_SRC"])
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return ast.get_source_segment(g["_SRC"], n)
    raise KeyError(f"{name} not found in the sign-off definitions")
