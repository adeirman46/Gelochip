"""Full tapeout flow on the MIM-B design: core -> slot -> fill -> audit."""
import json, os, sys
from pathlib import Path
sys.path.insert(0, "/home/irman/gLayout/notebook/tapeout")
from slot_adapter import SlotSpec, core_pad_positions, build_chip
from ips import load
from fill import fill
from validate_ips import netgen_lvs
import top_v2
import klayout.db as kdb

NBDIR   = Path("/home/irman/gLayout/notebook")
OUT     = NBDIR / "rf_harvester_tapeout_out"; OUT.mkdir(exist_ok=True)
TGZ     = NBDIR / "D05.def.tgz"
VARIANT = os.environ.get("D05_VARIANT", "EH")
TOPCELL = "D05_Gelochip"
NETMAP  = {"VSS": "VSS", "RFP": "RFP", "RFN": "RFN", "VOUT": "VOUT", "VCC": "VRECT"}


def sanitize(src, dst, top_new, prefix="D05_"):
    ly = kdb.Layout(); ly.read(str(src))
    tops = ly.top_cells()
    assert len(tops) == 1, [c.name for c in tops]
    used, ren = set(), []
    for c in ly.each_cell():
        new = top_new if c.cell_index() == tops[0].cell_index() else \
              prefix + "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in c.name)
        n, k = new, 1
        while n in used:
            k += 1; n = f"{new}_{k}"
        used.add(n)
        if n != c.name: ren.append((c.name, n))
        c.name = n
    ly.write(str(dst))
    return len(list(ly.each_cell())), ren


def main():
    spec = SlotSpec(TGZ, VARIANT)
    print("SLOT:", spec)
    g = load(OUT)
    PDK, CFG = g["PDK"], g["CONFIG"]

    out = {}
    for view, with_caps in (("full", True), ("fet", False)):
        print(f"\n{'='*70}\n=== {view.upper()} view\n{'='*70}")
        core = top_v2.build(PDK, CFG, g, with_caps=with_caps, rail_pads=False)
        core_gds = OUT / f"v2_core_{view}.gds"
        core.write_gds(str(core_gds))
        pads = dict(core.info["rail_pads"])   # no labelled core pads at chip level
        print("core met4 rail pads:", {k: (round(x,2), round(y,2)) for k,(x,y) in pads.items()})

        name = TOPCELL if view == "full" else f"{TOPCELL}_FET"
        # Leave a 115 um channel west of the core for the five routing lanes
        # (24/40/56/72/88 um) plus clearance; centre the core vertically.
        bb = core.bbox
        cw = float(bb[1][0] - bb[0][0]); ch = float(bb[1][1] - bb[0][1])
        W, H = spec.size_um
        offset = (115.0 - float(bb[0][0]), (H - ch) / 2.0 - float(bb[0][1]))
        if 115.0 + cw > W - 5.0:
            offset = (W - 5.0 - cw - float(bb[0][0]), offset[1])
        chip, rep = build_chip(PDK, core, spec, pads, NETMAP, name=name + "_raw",
                               core_offset=offset)
        from glayout.spice.netlist import Netlist
        # The chip has five PHYSICAL pins, but the blocks also carry debug labels
        # on VMID1/VMID2/N1/N2 and gf180 puts met*_pin and met*_label on the same
        # layer -- so every one of those labels extracts as a PORT.  Declare them
        # in the source too, otherwise netgen fails port matching on nets that are
        # electrically correct.  info.yaml records that only five are bonded out.
        nl = Netlist(circuit_name=name.upper(),
                     nodes=["VSS", "RFP", "RFN", "VOUT", "VCC",
                            "VMID1", "VMID2", "N1", "N2"])
        nl.connect_netlist(core.info["netlist"],
                           [("VSS","VSS"),("RFP","RFP"),("RFN","RFN"),
                            ("VOUT","VOUT"),("VRECT","VCC"),
                            ("VMID1","VMID1"),("VMID2","VMID2"),
                            ("N1","N1"),("N2","N2")])
        chip.info["netlist"] = nl
        if view == "fet":
            # LVS on a FLATTENED copy.  Hierarchically, the boundary router meets
            # the core's rails by abutment and the core cell has no ports of its
            # own (they were removed to avoid duplicate chip pins), so magic does
            # not propagate the connection and netgen fails port matching.
            lvs_ok = netgen_lvs(chip, "chip_fet", PDK, os.environ["PDK_ROOT"])
            print("chip-level LVS (flattened):", "MATCH" if lvs_ok else "MISMATCH")
            out["lvs"] = lvs_ok
        raw = OUT / f"{name}_raw.gds"; chip.write_gds(str(raw))
        pre = OUT / f"{name}_nofill.gds"
        ncells, ren = sanitize(raw, pre, name)
        print(f"sanitized: {ncells} cells, {len(ren)} renamed")
        (OUT / f"{name}_source.spice").write_text(nl.generate_netlist())

        final = OUT / f"{name}.gds"
        if view == "full":
            print("dummy fill:")
            rpt = fill(pre, final,
                       keepouts_um=[tuple(o) for o in spec.m2_obstructions])
            out["fill"] = rpt
        else:
            import shutil; shutil.copy(pre, final)
        ly = kdb.Layout(); ly.read(str(final)); t = ly.top_cell(); bb = t.dbbox()
        print(f"{name}: {len(list(ly.each_cell()))} cells, top={t.name}, "
              f"bbox=({bb.left:.1f},{bb.bottom:.1f})-({bb.right:.1f},{bb.top:.1f})")
        out[view] = dict(gds=str(final), cells=len(list(ly.each_cell())),
                         top=t.name, bbox=(bb.left, bb.bottom, bb.right, bb.top))
    json.dump(out, open(OUT / "tapeout_v2_report.json", "w"), indent=1, default=str)
    print("\nwrote", OUT / "tapeout_v2_report.json")


if __name__ == "__main__":
    main()
