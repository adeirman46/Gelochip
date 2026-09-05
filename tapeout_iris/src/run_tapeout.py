"""Build the D05 tapeout package end to end and verify it."""
import ast, json, os, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, "/home/irman/gLayout/notebook/tapeout")
from slot_adapter import SlotSpec, core_pad_positions, build_chip

NB       = "/home/irman/gLayout/notebook/GLayout_RF_EnergyHarvester_Signoff.ipynb"
TGZ      = "/home/irman/gLayout/notebook/D05.def.tgz"
OUT      = Path("/home/irman/gLayout/notebook/rf_harvester_tapeout_out"); OUT.mkdir(exist_ok=True)
VARIANT  = os.environ.get("D05_VARIANT", "EH")
TOPCELL  = "D05_Gelochip"
NETMAP   = {"VSS": "VSS", "RFP": "RFP", "RFN": "RFN", "VOUT": "VOUT", "VCC": "VRECT"}
PDK_ROOT = os.environ["PDK_ROOT"]
DEF_CELLS = [4, 6, 7, 9, 11, 13, 15, 17, 19, 21, 23]


def notebook_defs():
    def defs_only(src):
        tree = ast.parse(src); keep = []
        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom)):
                keep.append(n)
            elif isinstance(n, ast.Assign):
                t = [x.id for x in n.targets if isinstance(x, ast.Name)]
                if t and all(v.isupper() or v.startswith("PDK") for v in t):
                    keep.append(n)
        return "\n".join(ast.get_source_segment(src, n) for n in keep)
    nb = json.load(open(NB))
    code = ["import os, io, re, shutil, time, subprocess, tempfile, contextlib, warnings",
            "from pathlib import Path", "warnings.filterwarnings('ignore')",
            "try:\n    from loguru import logger as _l; _l.remove()\nexcept Exception:\n    pass",
            f"OUTDIR = {str(OUT)!r}"]
    code += [defs_only("".join(nb["cells"][i]["source"])) for i in DEF_CELLS]
    g = {}
    exec(compile("\n\n".join(code), "<nbdefs>", "exec"), g)
    return g


def sanitize(src_gds, dst_gds, top_new, prefix):
    """Rename every cell to a tool-safe, collision-proof name and set the top."""
    import klayout.db as kdb
    ly = kdb.Layout(); ly.read(str(src_gds))
    tops = ly.top_cells()
    assert len(tops) == 1, f"expected exactly one top cell, got {[c.name for c in tops]}"
    old_top, renames = tops[0].name, []
    used = set()
    for c in ly.each_cell():
        if c.cell_index() == tops[0].cell_index():
            new = top_new
        else:
            base = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in c.name)
            new = f"{prefix}{base}"
        n, k = new, 1
        while n in used:
            k += 1; n = f"{new}_{k}"
        used.add(n)
        if n != c.name:
            renames.append((c.name, n))
        c.name = n
    ly.write(str(dst_gds))
    return old_top, renames, len(list(ly.each_cell()))


def audit(gds, spec, top_expected):
    import klayout.db as kdb
    ly = kdb.Layout(); ly.read(str(gds)); dbu = ly.dbu
    tops = ly.top_cells(); top = tops[0]
    R = {"file": str(gds), "size_bytes": os.path.getsize(gds), "dbu": dbu,
         "n_cells": len(list(ly.each_cell())), "n_top_cells": len(tops),
         "top_cell": top.name, "top_ok": top.name == top_expected,
         "bad_names": [c.name for c in ly.each_cell()
                       if not c.name.replace("_", "").isalnum()],
         "hierarchical": len(list(ly.each_cell())) > 1}
    bb = top.dbbox()
    R["bbox"] = (bb.left, bb.bottom, bb.right, bb.top)
    W, H = spec.size_um
    R["in_slot"] = (bb.left >= -1e-9 and bb.bottom >= -1e-9
                    and bb.right <= W + 1e-9 and bb.top <= H + 1e-9)
    R["boundary_present"] = False
    bl = ly.find_layer(0, 0)
    if bl is not None:
        reg = kdb.Region(top.begin_shapes_rec(bl))
        b = reg.bbox()
        R["boundary_present"] = (
            abs(b.left * dbu) < 1e-6 and abs(b.bottom * dbu) < 1e-6
            and abs(b.right * dbu - W) < 1e-6 and abs(b.top * dbu - H) < 1e-6)
        R["boundary_bbox"] = (b.left*dbu, b.bottom*dbu, b.right*dbu, b.top*dbu)
    # Metal2 obstruction check -- THE new requirement
    m2 = kdb.Region(top.begin_shapes_rec(ly.layer(36, 0))); m2.merge()
    R["obstructions"] = spec.obstruction_report(m2, dbu)
    # boundary pins present on Metal2 with a label
    li_lab = ly.layer(36, 10)
    labs = {}
    it = top.begin_shapes_rec(li_lab)
    while not it.at_end():
        if it.shape().is_text():
            t = it.shape().text.transformed(it.trans())
            labs.setdefault(it.shape().text.string, []).append((t.x*dbu, t.y*dbu))
        it.next()
    R["m2_labels"] = labs
    R["pins_ok"] = {}
    for pin, info in spec.pins.items():
        x0, y0, x1, y1 = info["box"]
        box = kdb.DBox(x0, y0, x1, y1).to_itype(dbu)
        cov = (m2 & kdb.Region(box)).area() * dbu * dbu
        want = (x1 - x0) * (y1 - y0)
        R["pins_ok"][pin] = dict(labelled=pin in labs,
                                 m2_cover_um2=round(cov, 4),
                                 def_box_um2=round(want, 4),
                                 covered=cov >= want - 1e-6)
    return R


def magic_drc(gds, top, tag):
    magicrc = Path(PDK_ROOT) / "gf180mcuD" / "libs.tech" / "magic" / "gf180mcuD.magicrc"
    tcl = (f"crashbackups stop\ndrc euclidean on\ndrc style drc(full)\n"
           f"gds read {gds}\nload {top} -dereference\nselect top cell\nexpand\n"
           f"drc check\ndrc catchup\n"
           f'puts "DRC_COUNT_BEGIN"\nputs [drc list count total]\nputs "DRC_COUNT_END"\n'
           f'puts "DRC_WHY_BEGIN"\nforeach v [drc listall why] {{ puts $v }}\nputs "DRC_WHY_END"\n'
           f"quit -noprompt\n")
    with tempfile.NamedTemporaryFile("w", suffix=".tcl", delete=False) as f:
        f.write(tcl); sp = f.name
    r = subprocess.run(f"magic -rcfile {magicrc} -noconsole -dnull < {sp}",
                       shell=True, capture_output=True, text=True, cwd=str(OUT))
    log = OUT / f"{tag}_drc.log"; log.write_text(r.stdout + "\n--- STDERR ---\n" + r.stderr)
    out = r.stdout
    cnt = None
    if "DRC_COUNT_BEGIN" in out:
        seg = out.split("DRC_COUNT_BEGIN")[1].split("DRC_COUNT_END")[0].strip()
        try: cnt = int(seg.splitlines()[-1].strip())
        except Exception: cnt = seg
    why = (out.split("DRC_WHY_BEGIN")[1].split("DRC_WHY_END")[0].strip()
           if "DRC_WHY_BEGIN" in out else "")
    return cnt, why, str(log)


# ============================================================== build
g = notebook_defs()
PDK, CONFIG = g["PDK"], g["CONFIG"]
g["component_snap_to_grid"] = lambda c: c        # keep the hierarchy intact
if os.environ.get("FIX_CAPS", "1") == "1":
    from cap_fix import make_cap_blocks           # repair the shorted MIM plates
    g["cap_block"], g["cap_block_storage"] = make_cap_blocks(g)
    print("cap_block / cap_block_storage: PATCHED (MIM plate short fixed)")
spec = SlotSpec(TGZ, VARIANT)
print("SLOT:", spec)

blocks = {"rect": g["rectifier"](PDK, CONFIG), "bias": g["startup_bias"](PDK, CONFIG),
          "pump": g["pump_ladder"](PDK, CONFIG), "load": g["load_diode"](PDK, CONFIG)}

results = {}
for view, with_caps in (("full", True), ("fet", False)):
    print(f"\n{'='*70}\n=== {view.upper()} view\n{'='*70}")
    core = g["harvester_top"](PDK, CONFIG, with_caps=with_caps, blocks=blocks)
    core.name = f"RFEH_CORE_{view.upper()}"
    core_gds = OUT / f"core_{view}.gds"
    core.write_gds(str(core_gds))
    pads = {k: v[0] for k, v in core_pad_positions(core_gds).items()}
    print("core met4 rail pads:", {k: (round(x,3), round(y,3)) for k,(x,y) in pads.items()})

    topname = TOPCELL if view == "full" else f"{TOPCELL}_FET"
    chip, rep = build_chip(PDK, core, spec, pads, NETMAP, name=topname + "_raw")
    if view == "full":
        chip.info["cap_values"] = core.info["cap_values"]
    # chip-level netlist: the core with VRECT presented as the VCC slot pin
    from glayout.spice.netlist import Netlist
    nl = Netlist(circuit_name=topname.upper(), nodes=["VSS", "RFP", "RFN", "VOUT", "VCC"])
    nl.connect_netlist(core.info["netlist"],
                       [("VSS","VSS"),("RFP","RFP"),("RFN","RFN"),
                        ("VOUT","VOUT"),("VRECT","VCC")])
    chip.info["netlist"] = nl

    raw = OUT / f"{topname}_raw.gds"; chip.write_gds(str(raw))
    final = OUT / f"{topname}.gds"
    old, renames, ncells = sanitize(raw, final, topname, "D05_")
    print(f"sanitized: top {old!r} -> {topname!r}, {ncells} cells, {len(renames)} renamed")
    print("  sample renames:", renames[:4])

    A = audit(final, spec, topname)
    results[view] = dict(report=rep, audit=A, gds=str(final))
    print(f"AUDIT {topname}: cells={A['n_cells']} hierarchical={A['hierarchical']} "
          f"top_ok={A['top_ok']} in_slot={A['in_slot']} boundary={A['boundary_present']} "
          f"bad_names={A['bad_names']}")
    print("  bbox:", tuple(round(v,3) for v in A["bbox"]))
    for o in A["obstructions"]:
        print(f"  M2 obstruction {o['rect']}: area={o['area_um2']:.4f} um2 -> "
              f"{'CLEAR' if o['clear'] else 'VIOLATION'}")
    for p, v in A["pins_ok"].items():
        print(f"  pin {p:5s} labelled={v['labelled']} m2 cover {v['m2_cover_um2']:.3f}/"
              f"{v['def_box_um2']:.3f} um2 -> {'OK' if v['covered'] and v['labelled'] else 'FAIL'}")
    open(OUT / f"{topname}_source.spice", "w").write(nl.generate_netlist())

json.dump({k: {"report": v["report"], "audit": v["audit"], "gds": v["gds"]}
           for k, v in results.items()}, open(OUT / "tapeout_report.json", "w"),
          indent=1, default=str)
print("\nwrote", OUT / "tapeout_report.json")
