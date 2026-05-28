"""
Correct DRC-failing dataset circuits with the Kaizen RAG agent, verify with a
real gf180 Magic DRC, and — only when DRC is genuinely clean (0 errors) —
write the corrected pure-glayout code into the dataset directory and promote
the block into the IP Library + ChromaDB + JSONL.

Honest by construction: nothing is marked "DRC-clean" unless Magic confirms it.

Run from repo root (needs Ollama serving qwen3.5:9b + magic + PDK_ROOT):
    .venv/bin/python scripts/correct_datasets.py                 # all failing
    .venv/bin/python scripts/correct_datasets.py transmission_gate fvf
"""
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("PDK_ROOT", os.path.expanduser("~/pdks"))
sys.path.insert(0, os.path.abspath("src"))

from gelochip.kaizen import agent, collections, config, studio  # noqa: E402

DATASETS = config.PROJECT_ROOT / "notebooks" / "datasets"

REQUESTS = {
    "transmission_gate":     "Design a DRC-clean CMOS transmission gate on the gf180 PDK.",
    "fvf":                   "Design a DRC-clean flipped voltage follower (FVF) on gf180.",
    "diff_pair_cmirrorbias": "Design a DRC-clean differential pair with current-mirror bias on gf180.",
    "low_voltage_cmirror":   "Design a DRC-clean low-voltage cascode current mirror on gf180.",
    "n_block":               "Design a DRC-clean FVF-based n-type input block on gf180.",
    "stacked_current_mirror":"Design a DRC-clean stacked NMOS current mirror on gf180.",
    "ota":                   "Design a DRC-clean 5-transistor OTA on gf180.",
    "opamp":                 "Design a DRC-clean single-stage op-amp on gf180.",
    "differential_to_single_ended_converter":
                             "Design a DRC-clean differential-to-single-ended converter on gf180.",
}


def failing_blocks() -> list[str]:
    out = []
    for d in sorted(DATASETS.iterdir()):
        ev = d / "eval_result.json"
        if d.is_dir() and ev.exists():
            m = json.loads(ev.read_text())
            s = (m.get("drc", {}) or {}).get("summary", {}) or {}
            if not ((m.get("drc", {}) or {}).get("is_pass") and s.get("total_errors") in (0, None)):
                out.append(d.name)
    return out


def correct(block_id: str) -> dict:
    req = REQUESTS.get(block_id, f"Design a DRC-clean {block_id.replace('_',' ')} on gf180.")
    job = str(config.OUTPUT_DIR / "corrected" / block_id)
    print(f"\n=== {block_id} ===\n  {req}")
    state = agent.run(req, job_dir=job,
                      on_event=lambda e: print(f"  [{e['node']}] {e['msg'][:90]}", flush=True))
    test = state.get("test", {})
    drc = test.get("drc", {})
    clean = bool(test.get("passed")) and not drc.get("skipped") and drc.get("total_errors") in (0, None)
    if not clean:
        print(f"  ✗ NOT promoted — errors={drc.get('total_errors')} skipped={drc.get('skipped')}")
        return {"block_id": block_id, "promoted": False}

    # Write corrected code into the dataset directory.
    code = state.get("code", "")
    (DATASETS / block_id / f"{block_id}_drc_clean.py").write_text(_strip(code))
    (DATASETS / block_id / "eval_result_corrected.json").write_text(json.dumps({
        "component_name": block_id, "source": "kaizen_corrected",
        "drc": {"is_pass": True, "summary": {"total_errors": 0}},
    }, indent=2))
    # Promote: IP Library + ChromaDB + JSONL.
    png = test.get("png_path")
    preview = f"/output/corrected/{block_id}/{Path(png).name}" if png else None
    studio.register_ip(block_id, block_id.replace("_", " ").title(), preview,
                       studio._pins_for(block_id), None, drc_pass=True, source="corrected")
    tid = collections.add_template(req, code, circuit=block_id, source="corrected")
    print(f"  ✓ PROMOTED → datasets/{block_id}/{block_id}_drc_clean.py + IP + {tid} + jsonl")
    return {"block_id": block_id, "promoted": True, "template_id": tid}


def _strip(code: str) -> str:
    import re
    m = re.search(r"```(?:python|py)?\s*\n(.*?)```", code, re.DOTALL)
    return (m.group(1) if m else code).strip()


def main() -> None:
    targets = sys.argv[1:] or failing_blocks()
    print("Targets:", targets)
    results = [correct(b) for b in targets]
    ok = [r["block_id"] for r in results if r.get("promoted")]
    print(f"\nPROMOTED {len(ok)}/{len(results)} DRC-clean: {ok}")


if __name__ == "__main__":
    main()
