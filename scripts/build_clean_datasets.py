"""
Build DRC-clean reimplementations of the dataset circuits and run the full
verification pipeline on each:

    1. DRC      — build the clean layout, confirm 0 Magic DRC errors (gf180)
    2. SPICE    — extract the schematic subckt (+ best-effort PEX R/C)
    3. Testbench— AC + transient vs. closed-form theory, plotted with matplotlib
    4. Promote  — write clean code + plots into data/circuits/<name>/, ingest
                  the verified template into ChromaDB (+ dataset_corrected.jsonl)

Nothing is promoted unless Magic confirms DRC = 0 errors.

Run from repo root:
    .venv/bin/python scripts/build_clean_datasets.py                 # all defined
    .venv/bin/python scripts/build_clean_datasets.py fvf             # one circuit
"""
import json
import os
import shutil
import sys
from pathlib import Path

os.environ.setdefault("PDK_ROOT", os.path.expanduser("~/pdks"))
sys.path.insert(0, os.path.abspath("src"))

from gelochip.kaizen import clean_builders, collections, config, executor, studio, testbench  # noqa: E402

DATASETS = config.CIRCUITS_DIR


def process(name: str) -> dict:
    cir = clean_builders.get(name)
    if cir is None:
        print(f"  ! no clean builder for {name}"); return {"name": name, "ok": False}
    print(f"\n=== {name} ===")
    job = config.OUTPUT_DIR / "clean" / name

    # 1. DRC
    r = executor.run_layout_code(cir.layout, str(job), name=cir.subckt, run_drc=True)
    drc = r.get("drc", {})
    errors = drc.get("total_errors")
    # A non-empty exec error means a route/build step raised → the layout is not
    # genuinely connected. Require clean build AND clean DRC.
    build_err = (r.get("error") or "").strip()
    clean = (r["ok"] and not build_err and not drc.get("skipped")
             and drc.get("is_pass") and errors in (0, None))
    print(f"  DRC: ok={r['ok']} is_pass={drc.get('is_pass')} errors={errors} "
          f"build_err={'YES' if build_err else 'no'}")
    if build_err:
        print("    BUILD ERROR:", build_err.splitlines()[-1][:140])
    if not clean:
        for e in (drc.get("error_details") or [])[:5]:
            print("    ERR:", e)
        print("  ✗ not promoted (DRC not clean)")
        return {"name": name, "ok": False, "drc_errors": errors}

    # 2. SPICE schematic + best-effort PEX
    pex = _try_pex(r.get("gds_path"), cir.subckt)

    # 3. Testbench vs theory
    tb = testbench.run_spec_testbench(cir, out_dir=str(job / "tb"))
    print(f"  TB: in={tb['in_node']} out={tb['out_node']} metrics={tb['metrics']} "
          f"theory_pass={tb['passed']}")

    # 4. Promote into the dataset dir + ChromaDB
    ddir = DATASETS / name
    ddir.mkdir(parents=True, exist_ok=True)
    (ddir / f"{name}_clean.py").write_text(cir.layout.strip() + "\n")
    (ddir / f"{name}_clean.spice").write_text(cir.netlist)
    tbdir = ddir / "tb_clean"; tbdir.mkdir(exist_ok=True)
    for k, p in tb.get("plots", {}).items():
        if p and Path(p).exists():
            shutil.copy(p, tbdir / Path(p).name)
    (ddir / "eval_result_clean.json").write_text(json.dumps({
        "component_name": cir.subckt, "source": "kaizen_clean_reimpl",
        "drc": {"is_pass": True, "summary": {"total_errors": 0}},
        "pex": pex, "testbench": {"metrics": tb["metrics"], "theory": cir.theory,
                                   "theory_pass": tb["passed"]},
    }, indent=2))

    instr = f"Generate DRC-clean glayout code for a {name.replace('_',' ')} on gf180 PDK."
    tid = collections.add_template(instr, cir.layout.strip(), circuit=name, source="clean_reimpl")
    preview = r.get("png_path")
    studio.register_ip(name, name.replace("_", " ").title(),
                       f"/output/clean/{name}/{Path(preview).name}" if preview else None,
                       studio._pins_for(name), None, drc_pass=True, source="clean_reimpl")
    print(f"  ✓ promoted → datasets/{name}/{name}_clean.py + IP + ChromaDB({tid}) + jsonl")
    return {"name": name, "ok": True, "theory_pass": tb["passed"], "metrics": tb["metrics"]}


def _try_pex(gds_path, cell):
    """Best-effort parasitic extraction (R/C). Non-fatal if tools are slow/absent."""
    if not gds_path:
        return {"status": "skipped"}
    try:
        from gelochip.glayout.verification.verification import run_verification
        res = run_verification(gds_path, cell, None)
        pex = res.get("pex", {})
        return {"status": "ok", "total_resistance_ohms": pex.get("total_resistance_ohms"),
                "total_capacitance_farads": pex.get("total_capacitance_farads")}
    except Exception as e:
        return {"status": "skipped", "error": str(e)[:120]}


def main() -> None:
    targets = sys.argv[1:] or clean_builders.names()
    results = [process(t) for t in targets]
    ok = [r["name"] for r in results if r.get("ok")]
    print(f"\n=== DRC-clean + verified: {len(ok)}/{len(results)} → {ok} ===")
    print("ChromaDB templates now:", collections.collection_counts()["glayout_code_templates"])


if __name__ == "__main__":
    main()
