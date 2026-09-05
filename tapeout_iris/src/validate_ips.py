"""Build every IP one at a time and validate it: render + foundry DRC + LVS.

DRC is the GF180 KLayout sign-off deck (run_drc.py --variant=D = 5LM,
mim_option=B), not magic -- magic's gf180mcuD tech has no MIM device and a much
thinner rule set.  LVS is netgen against the IP's own generated netlist.

The capacitor IPs have no SPICE device that magic can extract (that is the whole
MIM story), so instead of LVS they get a plate-separation check: the two plates
must come out as two distinct nets.
"""
import json, os, subprocess, sys, tempfile, glob, collections
import xml.etree.ElementTree as ET
from pathlib import Path

TAPEOUT = Path("/home/irman/gLayout/notebook/tapeout")
sys.path.insert(0, str(TAPEOUT))
OUT = Path("/home/irman/gLayout/notebook/rf_harvester_tapeout_out"); OUT.mkdir(exist_ok=True)
IMG = TAPEOUT / "img"; IMG.mkdir(exist_ok=True)
PDK_ROOT = os.environ["PDK_ROOT"]
DECK = Path(PDK_ROOT) / "gf180mcuD" / "libs.tech" / "klayout" / "drc" / "run_drc.py"


def foundry_drc(gds, topcell, tag):
    rundir = Path(tempfile.mkdtemp(prefix=f"drc_{tag}_"))
    r = subprocess.run([sys.executable, str(DECK), f"--path={gds}", "--variant=D",
                        f"--topcell={topcell}", f"--run_dir={rundir}", "--mp=4"],
                       capture_output=True, text=True,
                       env={**os.environ, "PYTHONPATH": ""}, cwd=str(rundir))
    tot = collections.Counter()
    for f in glob.glob(str(rundir / "*.lyrdb")):
        try: root = ET.parse(f).getroot()
        except Exception: continue
        for it in root.iter("item"):
            c = (it.findtext("category") or "").strip("'\"")
            if c: tot[c] += 1
    clean = "DRC run is clean" in (r.stdout + r.stderr) and sum(tot.values()) == 0
    return clean, dict(tot)


def netgen_lvs(comp, name, pdk, pdk_root, keep_labels=None):
    """LVS on a FLATTENED copy.

    `add_pin` puts the pin rectangle and its label inside a sub-component, so on a
    hierarchical GDS the top cell owns no labels and magic extracts it with "(no
    pins)" -- netgen then reports "Top level cell failed pin matching" even though
    the devices and nets match exactly.  The sign-off notebook flattened for the
    same reason (`signoff_views`).  The shipped GDS stays hierarchical; only this
    LVS copy is flat.
    """
    import io, contextlib
    nl = comp.info["netlist"]
    # The LVS design name must be the netlist's own subckt name, and the flattened
    # cell must be given exactly that name.  The source component therefore has to
    # be called something else: gdsfactory de-duplicates a repeated cell name to
    # NAME$1, and magic then loads an empty cell of the expected name.
    design = getattr(nl, "circuit_name", None) or name
    flat = comp.flatten()
    flat.name = design
    flat.info["netlist"] = nl
    gds = OUT / f"ip_{name}_lvsflat.gds"
    flat.write_gds(str(gds))
    net = OUT / f"ip_{name}.spice"
    net.write_text(nl.generate_netlist())
    if keep_labels is not None:
        # Blocks carry debug labels (VMID1, N1, ...) on their internal nets.  gf180
        # puts met*_pin and met*_label on one layer, so every label becomes a PORT --
        # and netgen then fails port matching because the source declares those nets
        # as internal.  Strip them from the LVS copy; the shipped GDS keeps them.
        import klayout.db as _kdb
        ly = _kdb.Layout(); ly.read(str(gds)); tc = ly.top_cell()
        removed = 0
        for lay in ((36,10), (42,10), (46,10), (81,10)):
            li = ly.find_layer(*lay)
            if li is None:
                continue
            keep = _kdb.Shapes()
            for sh in tc.shapes(li).each():
                if sh.is_text() and sh.text.string not in keep_labels:
                    removed += 1
                    continue
                keep.insert(sh)
            tc.shapes(li).clear(); tc.shapes(li).insert(keep)
        ly.write(str(gds))
        print(f"  stripped {removed} non-pin label(s) from the LVS copy")
    name = design
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            pdk.lvs_netgen(str(gds), name, pdk_root=pdk_root, netlist=str(net))
        out = buf.getvalue()
    except Exception as e:
        out = buf.getvalue() + f"\nEXC {type(e).__name__}: {e}"
    (OUT / f"ip_{name}_lvs.log").write_text(out)
    return "match uniquely" in out


def main():
    from ips import load
    from mimcap_b import mimcap_b
    from mim_verify import check as mim_check
    from render import render
    import klayout.db as kdb

    g = load(OUT)
    PDK, CFG = g["PDK"], g["CONFIG"]
    evaluate_bbox = g["evaluate_bbox"]

    ips = []
    ips.append(("unit_diode",  lambda: g["diode_nmos"](PDK, 4.0, 0.28, 2),      "fet"))
    ips.append(("rectifier",   lambda: g["rectifier"](PDK, CFG),                "fet"))
    ips.append(("startup_bias",lambda: g["startup_bias"](PDK, CFG),             "fet"))
    ips.append(("pump_ladder", lambda: g["pump_ladder"](PDK, CFG),              "fet"))
    ips.append(("load_diode",  lambda: g["load_diode"](PDK, CFG),               "fet"))
    ips.append(("mimb_unit",   lambda: mimcap_b(PDK, (28.0, 28.0)),             "cap"))
    ips.append(("cap_inject",  lambda: g["cap_block"](PDK, CFG, CFG["startup_bias"]["inject_cap_pf"]/2, max_cols=1), "cap"))
    ips.append(("cap_stage",   lambda: g["cap_block"](PDK, CFG, CFG["charge_pump"]["stage_cap_pf"], max_cols=1),     "cap"))
    ips.append(("cap_storage", lambda: g["cap_block_storage"](PDK, CFG),        "cap"))

    only = set(sys.argv[1:])
    if only:
        ips = [t for t in ips if t[0] in only]
    prev = OUT / "ip_validation.json"
    results = list(json.load(open(prev))) if (only and prev.exists()) else []
    results = [r for r in results if r["ip"] not in only]
    for name, build, kind in ips:
        print("=" * 78); print(f"IP: {name}")
        comp = build()
        comp.name = name          # keep lowercase; LVS renames its flat copy
        w, h = evaluate_bbox(comp)
        gds = OUT / f"ip_{name}.gds"
        comp.write_gds(str(gds))
        png = IMG / f"ip_{name}.png"
        render(gds, png, f"{name}  ({w:.1f} x {h:.1f} um)", figsize=(7, 7))
        drc_ok, drc_items = foundry_drc(gds, comp.name, name)
        row = dict(ip=name, kind=kind, w=round(w, 2), h=round(h, 2),
                   drc=drc_ok, drc_items=drc_items, png=str(png))
        if kind == "fet":
            row["lvs"] = netgen_lvs(comp, name, PDK, PDK_ROOT)
            row["check"] = "netgen LVS"
        else:
            probes = {}
            if name == "mimb_unit":
                probes = {"top": ("fusetop", 0.0, 0.0), "bot": ("met4", 0.0, 14.4)}
            else:
                tp = comp.ports["TOP_stub_N"].center; bp = comp.ports["BOT_stub_E" if "BOT_stub_E" in comp.ports else "BOT_stub_S"].center
                probes = {"top": ("met5", float(tp[0]), 0.0), "bot": ("met5", float(bp[0]), 0.0)}
            nets = mim_check(gds, probes, verbose=False)
            row["lvs"] = (nets["top"] is not None and nets["bot"] is not None
                          and nets["top"] != nets["bot"])
            row["check"] = "plate separation"
            row["pF"] = round(comp.info.get("capacitance_pf", 0.0), 3)
        results.append(row)
        print(f"  size {w:.2f} x {h:.2f} um | DRC {'CLEAN' if drc_ok else drc_items} "
              f"| {row['check']}: {'PASS' if row['lvs'] else 'FAIL'}"
              + (f" | {row.get('pF')} pF" if 'pF' in row else ""))

    order = [t[0] for t in (("unit_diode",),("rectifier",),("startup_bias",),("pump_ladder",),
             ("load_diode",),("mimb_unit",),("cap_inject",),("cap_stage",),("cap_storage",))]
    results.sort(key=lambda r: order.index(r["ip"]) if r["ip"] in order else 99)
    json.dump(results, open(OUT / "ip_validation.json", "w"), indent=1)
    print("\n" + "=" * 78)
    print(f"{'IP':14s} {'size (um)':>16s} {'DRC':>7s} {'check':>18s} {'result':>7s}")
    print("-" * 78)
    for r in results:
        print(f"{r['ip']:14s} {r['w']:7.1f} x {r['h']:6.1f} {'CLEAN' if r['drc'] else 'FAIL':>7s} "
              f"{r['check']:>18s} {'PASS' if r['lvs'] else 'FAIL':>7s}")
    ok = all(r["drc"] and r["lvs"] for r in results)
    print("-" * 78)
    print("ALL IPs CLEAN:", ok)
    return results


if __name__ == "__main__":
    main()
