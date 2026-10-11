"""Standalone Glayout build+verify harness — run as a SUBPROCESS by the pipeline
(glayout_tools.run_build) so a crashing/naughty layout script can never take the
app down, and so each build gets a fresh interpreter (gdsfactory caches
components by name aggressively).

Contract for the generated layout script (layout/<name>.py in a design dir):

    # the script MUST define:  build(pdk) -> Component
    from glayout import MappedPDK
    from glayout.primitives.fet import nmos, pmos
    from glayout.routing.smart_route import smart_route
    ...
    def build(pdk: MappedPDK) -> "Component":
        comp = Component(name="my_ota")
        ...place with movex/movey/center, route EVERY connection with
           c_route / L_route / straight_route / smart_route + via_stack,
           add ports with comp.add_port(s)...
        return comp

The harness then:
  1. imports the script, calls build(pdk) for the chosen PDK (sky130/gf180)
  2. names + flattens ports info, writes layout/<name>.gds and layout/<name>.svg
  3. writes layout/<name>_ports.txt   (every port name — routing/LVS debugging)
  4. writes netlist/<name>_layout.cdl (the glayout-generated schematic netlist
     carried in comp.info['netlist'], used by netgen as the LVS reference)
  5. optional --drc  : magic DRC   → layout/drc_<name>.json (+ .rpt)
  6. optional --lvs  : netgen LVS  → layout/lvs_<name>.json (+ .rpt)
  7. writes layout/verify_<name>.json with the full machine-readable result

Exit code 0 = build ok (verification verdicts live in the json, they do NOT
change the exit code — the pipeline decides what to do with a DRC/LVS fail).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import traceback
from pathlib import Path


def _load_pdk(name: str):
    if name.lower().startswith("gf180"):
        from glayout import gf180
        return gf180
    from glayout import sky130
    return sky130


def _parse_drc_report(report: str) -> dict:
    errors = []
    rule = ""
    for line in report.strip().splitlines():
        s = line.strip()
        if s == "-" * 40:
            continue
        if re.match(r"^[a-zA-Z]", s):
            rule = s
        elif re.match(r"^[0-9]", s):
            errors.append({"rule": rule, "details": s})
    ok = len(errors) == 0
    if not ok and re.search(r"count:\s*0\s*$", report, re.IGNORECASE):
        ok = True
    return {"is_pass": ok, "total_errors": len(errors), "error_details": errors[:80]}


def _parse_lvs_report(report: str) -> dict:
    res = {"is_pass": False, "conclusion": "LVS failed or inconclusive.",
           "total_mismatches": 0, "unmatched": []}
    if "Netlists match" in report or "Circuits match uniquely" in report:
        res["is_pass"] = True
        res["conclusion"] = "LVS Pass: netlists match."
    elif "Netlist mismatch" in report or "Netlists do not match" in report:
        res["conclusion"] = "LVS Fail: netlist mismatch."
    for line in report.splitlines():
        line = line.strip()
        m = re.search(r"Net:\s*([^|]+)\|\s*\(no matching net\)", line)
        if m:
            res["unmatched"].append({"type": "net", "name": m.group(1).strip(),
                                     "present_in": "layout"})
            continue
        m = re.search(r"\|\s*([^|]+?)\s*\(no matching net\)", line)
        if m:
            res["unmatched"].append({"type": "net", "name": m.group(1).strip(),
                                     "present_in": "schematic"})
            continue
        m = re.search(r"Instance:\s*([^|]+)\|\s*\(no matching instance\)", line)
        if m:
            res["unmatched"].append({"type": "instance", "name": m.group(1).strip(),
                                     "present_in": "layout"})
            continue
        m = re.search(r"\|\s*([^|]+?)\s*\(no matching instance\)", line)
        if m:
            res["unmatched"].append({"type": "instance", "name": m.group(1).strip(),
                                     "present_in": "schematic"})
    res["total_mismatches"] = len(res["unmatched"])
    if res["total_mismatches"] > 0:
        res["is_pass"] = False
        res["conclusion"] = "LVS Fail: mismatches found."
    return res


def _write_svg(gds_path: Path, svg_path: Path) -> bool:
    """Layout preview via gdstk (headless, no display needed)."""
    try:
        import gdstk
        lib = gdstk.read_gds(str(gds_path))
        tops = lib.top_level()
        if tops:
            tops[0].write_svg(str(svg_path), scaling=20)
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("design_dir")
    ap.add_argument("script", help="layout script path relative to design_dir")
    ap.add_argument("--name", default="", help="component/design name")
    ap.add_argument("--pdk", default="sky130")
    ap.add_argument("--drc", action="store_true")
    ap.add_argument("--lvs", action="store_true")
    args = ap.parse_args()

    design = Path(args.design_dir).resolve()
    script = (design / args.script).resolve()
    name = args.name or script.stem
    layout_dir = design / "layout"
    netlist_dir = design / "netlist"
    layout_dir.mkdir(parents=True, exist_ok=True)
    netlist_dir.mkdir(parents=True, exist_ok=True)
    result: dict = {"name": name, "pdk": args.pdk, "build": {"ok": False},
                    "drc": {"status": "not run"}, "lvs": {"status": "not run"}}
    verify_json = layout_dir / f"verify_{name}.json"

    def _finish(code: int) -> int:
        verify_json.write_text(json.dumps(result, indent=2, default=str))
        print(json.dumps(result, indent=2, default=str))
        return code

    # ---- 1. build ---------------------------------------------------------
    try:
        pdk = _load_pdk(args.pdk)
        spec = importlib.util.spec_from_file_location(f"anoa_layout_{name}", script)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        build = getattr(mod, "build", None)
        if build is None:
            result["build"]["error"] = ("script has no build(pdk) function — "
                                        "define `def build(pdk): ... return component`")
            return _finish(2)
        comp = build(pdk)
        if comp is None:
            result["build"]["error"] = "build(pdk) returned None instead of a Component"
            return _finish(2)
        try:
            comp.name = name
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001
        result["build"]["error"] = traceback.format_exc()[-4000:]
        return _finish(2)

    # ---- 2. artifacts ------------------------------------------------------
    gds = layout_dir / f"{name}.gds"
    try:
        comp.write_gds(str(gds))
    except Exception:  # noqa: BLE001
        # gdsfactory >=7 name-collision guard: flatten+copy then write
        result["build"]["error"] = traceback.format_exc()[-3000:]
        return _finish(2)

    ports = sorted(comp.ports.keys()) if hasattr(comp, "ports") else []
    (layout_dir / f"{name}_ports.txt").write_text("\n".join(ports) + "\n")
    svg_ok = _write_svg(gds, layout_dir / f"{name}.svg")

    # count text labels in the GDS — LVS matches nets by label, so a layout with ports
    # but no labels will fail LVS. Surfaced in the verdict (the ports+labels rule).
    n_labels = 0
    try:
        import gdstk
        lib = gdstk.read_gds(str(gds))
        for top in lib.top_level():
            n_labels += len(top.labels)
    except Exception:  # noqa: BLE001
        n_labels = -1

    ref_netlist = ""
    try:
        nl = comp.info.get("netlist") if hasattr(comp, "info") else None
        if nl is not None:
            ref_netlist = nl.generate_netlist()
            # a LAYOUT artifact (the LVS reference), NOT a design netlist — putting it in
            # netlist/ made pick_top choose ITS subckt (CASCODE_CMIRROR) as the design top
            # and broke the JSON-only routing on resume.
            (layout_dir / f"{name}_layout.cdl").write_text(ref_netlist)
    except Exception:  # noqa: BLE001
        pass

    result["build"].update({
        "ok": True, "gds": str(gds), "svg": svg_ok,
        "n_ports": len(ports), "ports": ports[:200],
        "n_labels": n_labels,
        "has_ref_netlist": bool(ref_netlist),
        "bbox_um": _bbox(comp),
    })

    # ---- 3. DRC ------------------------------------------------------------
    if args.drc:
        try:
            out_dir = layout_dir / f"{name}_drc_out"
            pdk.drc_magic(comp, name, output_file=str(out_dir))
            rpt = out_dir / "drc" / name / f"{name}.rpt"
            content = rpt.read_text() if rpt.exists() else ""
            summary = _parse_drc_report(content)
            result["drc"] = {"status": "pass" if summary["is_pass"] else "fail",
                             "report": str(rpt), **summary}
        except Exception:  # noqa: BLE001
            result["drc"] = {"status": "error",
                             "error": traceback.format_exc()[-2500:]}

    # ---- 4. LVS ------------------------------------------------------------
    if args.lvs:
        try:
            out_dir = layout_dir / f"{name}_lvs_out"
            pdk.lvs_netgen(layout=comp, design_name=name,
                           output_file_path=str(out_dir))
            rpt = out_dir / "lvs" / name / f"{name}_lvs.rpt"
            content = rpt.read_text() if rpt.exists() else ""
            summary = _parse_lvs_report(content)
            result["lvs"] = {"status": "pass" if summary["is_pass"] else "fail",
                             "report": str(rpt), **summary}
        except Exception:  # noqa: BLE001
            result["lvs"] = {"status": "error",
                             "error": traceback.format_exc()[-2500:]}

    return _finish(0)


def _bbox(comp) -> list:
    try:
        b = comp.bbox
        return [round(float(b[0][0]), 3), round(float(b[0][1]), 3),
                round(float(b[1][0]), 3), round(float(b[1][1]), 3)]
    except Exception:  # noqa: BLE001
        return []


if __name__ == "__main__":
    sys.exit(main())
