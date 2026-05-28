#!/usr/bin/env python3
"""
Generate SFT dataset for Qwen VL fine-tuning from all 15 glayout circuit notebooks.

Output structure:
  circuits/{circuit}/steps/   - before/after GDS + PNG per << operation
  circuits/{circuit}/samples.jsonl
  dataset_operations.jsonl    - operation-level samples (all 15 circuits)
  dataset_circuits.jsonl      - full-circuit samples (all 15 circuits)
  dataset_full.jsonl          - merged dataset

Usage:
  cd notebooks/sft_finetuning
  python generate_dataset.py
"""
import os, sys, json, re
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────
THIS_DIR = Path(__file__).parent.resolve()
WORKSPACE = THIS_DIR.parent.parent
DATASETS_DIR = WORKSPACE / "notebooks" / "datasets"
CIRCUITS_DIR = THIS_DIR / "circuits"

sys.path.insert(0, str(WORKSPACE / "src" / "gelochip"))
os.environ.setdefault("PDK_ROOT", os.path.expanduser("~/pdks"))

import nbformat
from step_recorder import StepRecorder
from renderer import render_gds, render_all_steps
from nl_templates import describe_operation, generate_instruction_variations

# ── Per-circuit metadata ────────────────────────────────────────────────────
CIRCUIT_CONFIGS: dict[str, dict] = {
    "current_mirror": {
        "name": "current mirror",
        "type": "current_mirror",
        "drc_pass": True,
        "description": (
            "A basic NFET/PFET current mirror that replicates a reference current "
            "using two interdigitized transistors with a diode-connected reference branch."
        ),
    },
    "diff_pair": {
        "name": "differential pair",
        "type": "diff_pair",
        "drc_pass": True,
        "description": (
            "A differential pair using two interdigitized transistors "
            "for high common-mode rejection and symmetric layout."
        ),
    },
    "diff_pair_stackedcmirror": {
        "name": "differential pair with stacked current mirror",
        "type": "diff_pair",
        "drc_pass": True,
        "description": (
            "A differential pair with a stacked current mirror load, "
            "providing high output impedance."
        ),
    },
    "diff_pair_cmirrorbias": {
        "name": "differential pair with current mirror bias",
        "type": "diff_pair",
        "drc_pass": False,
        "description": "A differential pair biased by a current mirror.",
    },
    "differential_to_single_ended_converter": {
        "name": "differential to single-ended converter",
        "type": "converter",
        "drc_pass": False,
        "description": "Converts a differential signal to a single-ended output using shared-gate PMOS loads.",
    },
    "fvf": {
        "name": "flipped voltage follower",
        "type": "fvf",
        "drc_pass": False,
        "description": "A flipped voltage follower (FVF) for low-dropout voltage regulation.",
    },
    "low_voltage_cmirror": {
        "name": "low voltage current mirror",
        "type": "current_mirror",
        "drc_pass": False,
        "description": "A low-voltage current mirror suitable for sub-1V supply applications.",
    },
    "n_block": {
        "name": "N block",
        "type": "primitive",
        "drc_pass": False,
        "description": "An N-type transistor block primitive with bias and signal ports.",
        "extra_source_files": [
            str(WORKSPACE / "src/gelochip/glayout/cells/composite/fvf_based_ota/n_block.py"),
        ],
    },
    "opamp": {
        "name": "operational amplifier",
        "type": "opamp",
        "drc_pass": False,
        "description": "A single-stage folded-cascode operational amplifier on gf180.",
        "extra_source_files": [
            str(WORKSPACE / "src/gelochip/glayout/cells/composite/opamp/opamp.py"),
        ],
    },
    "opamp_twostage": {
        "name": "two-stage operational amplifier",
        "type": "opamp",
        "drc_pass": True,
        "description": "A two-stage Miller-compensated operational amplifier with high gain.",
    },
    "ota": {
        "name": "operational transconductance amplifier",
        "type": "ota",
        "drc_pass": False,
        "description": "A class-AB OTA with super-source follower output stage.",
        "extra_source_files": [
            str(WORKSPACE / "src/gelochip/glayout/cells/composite/fvf_based_ota/ota.py"),
        ],
    },
    "p_block": {
        "name": "P block",
        "type": "primitive",
        "drc_pass": True,
        "description": "A P-type transistor block primitive with bias and signal ports.",
    },
    "row_csamplifier_diff_to_single_ended_converter": {
        "name": "row common-source amplifier with D-to-SE converter",
        "type": "amplifier",
        "drc_pass": True,
        "description": (
            "A row common-source amplifier combined with a differential "
            "to single-ended output converter."
        ),
    },
    "stacked_current_mirror": {
        "name": "stacked NFET current mirror",
        "type": "current_mirror",
        "drc_pass": False,
        "description": "A stacked NFET current mirror with high output impedance cascode configuration.",
    },
    "transmission_gate": {
        "name": "transmission gate",
        "type": "switch",
        "drc_pass": False,
        "description": "A CMOS transmission gate using complementary NFET and PFET transistors in parallel.",
    },
}

# ── Code extraction ─────────────────────────────────────────────────────────

def extract_circuit_code(notebook_path: Path) -> str:
    """
    Extract the main circuit code from a notebook.
    Returns cell-1 source trimmed to before the if-__name__ block,
    plus a standard invocation comment.
    """
    nb = nbformat.read(open(notebook_path), as_version=4)
    parts = []
    for i, cell in enumerate(nb.cells):
        if cell["cell_type"] != "code":
            continue
        if i == 0:
            continue  # skip env/path setup cell
        src = cell["source"]
        # Skip pure evaluation/spice cells
        if re.match(r"\s*(run_spice_gf180|if run_evaluation)", src):
            continue
        # Trim at the __main__ block
        if "if __name__" in src:
            src = src[: src.index("if __name__")].rstrip()
        if src.strip():
            parts.append(src)
    return "\n\n".join(parts)


def extract_lshift_lines(code: str) -> list[str]:
    """Extract all non-comment lines containing << from circuit code."""
    result = []
    for line in code.splitlines():
        stripped = line.strip()
        if " << " in stripped and not stripped.startswith("#"):
            result.append(stripped)
    return result


# ── Notebook execution ──────────────────────────────────────────────────────

def execute_with_recorder(notebook_path: Path, step_dir: Path, extra_source_files: list[str] | None = None) -> list[dict]:
    """
    Execute a notebook with StepRecorder installed.
    Only records << operations originating from the notebook's own code
    (not from glayout/gdsfactory library internals).
    Returns all user-level steps in order.
    """
    nb = nbformat.read(open(notebook_path), as_version=4)

    # Run from the notebook's directory so relative GDS paths work
    orig_dir = os.getcwd()
    os.chdir(notebook_path.parent)

    # Some notebooks cache the final GDS and skip regeneration if it exists.
    # Delete those cache files so the circuit function actually runs and << ops fire.
    for gds_file in notebook_path.parent.glob("*.gds"):
        try:
            gds_file.unlink()
        except Exception:
            pass

    namespace: dict = {"__name__": "__main__", "__file__": str(notebook_path)}

    # source_files: record << and add(ref) ops from notebook + any extra cell source files
    source_files = [str(notebook_path)] + (extra_source_files or [])
    recorder = StepRecorder(str(step_dir), source_files=source_files)
    recorder.install()
    try:
        for cell in nb.cells:
            if cell["cell_type"] != "code":
                continue
            try:
                # compile with notebook_path so call-stack filtering works
                exec(compile(cell["source"], str(notebook_path), "exec"), namespace)
            except SystemExit:
                pass
            except Exception:
                pass  # gracefully skip DRC / LVS / ngspice failures
    finally:
        recorder.uninstall()
        os.chdir(orig_dir)

    return recorder.get_top_level_steps()


# ── Sample generation ───────────────────────────────────────────────────────

def _rel(path: str) -> str:
    """Return path relative to THIS_DIR for JSONL image references."""
    try:
        return str(Path(path).relative_to(THIS_DIR))
    except ValueError:
        return path


def make_circuit_samples(
    circuit_key: str, config: dict, code: str, preview_png: str | None
) -> list[dict]:
    """Generate full-circuit training samples (text→code and image→code)."""
    name = config["name"]
    description = config["description"]
    drc_pass = config["drc_pass"]
    drc_note = " The layout is DRC-verified clean on gf180 PDK." if drc_pass else ""
    samples = []

    # Prompt variation 1: plain instruction
    samples.append({
        "conversations": [
            {
                "from": "human",
                "value": f"Generate complete glayout Python code for a {name} on gf180 PDK.",
            },
            {
                "from": "gpt",
                "value": (
                    f"Here is the complete glayout implementation of a {name}.{drc_note}\n\n"
                    f"```python\n{code}\n```"
                ),
            },
        ],
        "type": "circuit",
        "circuit": circuit_key,
        "drc_pass": drc_pass,
    })

    # Prompt variation 2: what-is + code
    samples.append({
        "conversations": [
            {
                "from": "human",
                "value": f"What is a {name} and how is it implemented in glayout for gf180 PDK?",
            },
            {
                "from": "gpt",
                "value": (
                    f"A {name} is {description}\n\n"
                    f"Here is the glayout Python implementation:\n\n```python\n{code}\n```"
                ),
            },
        ],
        "type": "circuit",
        "circuit": circuit_key,
        "drc_pass": drc_pass,
    })

    # Prompt variation 3: image → identify + reproduce
    if preview_png and Path(preview_png).exists():
        samples.append({
            "conversations": [
                {
                    "from": "human",
                    "value": (
                        "<image>\nIdentify this analog IC GDS layout and write "
                        "the complete glayout Python code to reproduce it."
                    ),
                },
                {
                    "from": "gpt",
                    "value": (
                        f"This is a **{name}**. {description}\n\n"
                        f"Complete glayout code:\n\n```python\n{code}\n```"
                    ),
                },
            ],
            "images": [_rel(preview_png)],
            "type": "circuit",
            "circuit": circuit_key,
            "drc_pass": drc_pass,
        })

    return samples


def make_operation_samples(steps: list[dict], lshift_lines: list[str], config: dict, circuit_key: str) -> list[dict]:
    """Generate operation-level training samples for each << step."""
    # Map recorded steps to source code lines by position
    for i, step in enumerate(steps):
        if i < len(lshift_lines):
            step["code_line"] = lshift_lines[i]
            step["nl_description"] = describe_operation(lshift_lines[i], circuit_key)

    samples = []
    for step in steps:
        code_line = step.get("code_line")
        if not code_line:
            continue
        for v in generate_instruction_variations(
            code_line,
            config["name"],
            before_png=step.get("before_png"),
            after_png=step.get("after_png"),
            step_num=step["step"],
        ):
            sample: dict = {
                "conversations": [
                    {"from": "human", "value": v["instruction"]},
                    {"from": "gpt", "value": v["response"]},
                ],
                "type": "operation",
                "circuit": circuit_key,
                "step": step["step"],
                "drc_pass": config["drc_pass"],
            }
            if v.get("has_image") and v.get("image") and Path(v["image"]).exists():
                sample["images"] = [_rel(v["image"])]
            samples.append(sample)
    return samples


# ── Per-circuit pipeline ────────────────────────────────────────────────────

def process_circuit(circuit_key: str) -> dict:
    config = CIRCUIT_CONFIGS[circuit_key]
    circuit_src_dir = DATASETS_DIR / circuit_key
    notebook_path = circuit_src_dir / f"{circuit_key}.ipynb"
    circuit_out_dir = CIRCUITS_DIR / circuit_key
    step_dir = circuit_out_dir / "steps"

    if not notebook_path.exists():
        print(f"  [SKIP] notebook not found")
        return {"operation_samples": [], "circuit_samples": []}

    step_dir.mkdir(parents=True, exist_ok=True)

    # Run notebook with StepRecorder
    extra_src = config.get("extra_source_files")
    print(f"  Executing notebook …")
    steps = execute_with_recorder(notebook_path, step_dir, extra_source_files=extra_src)
    print(f"  Captured {len(steps)} top-level << steps")

    # Render GDS → PNG for all steps
    steps = render_all_steps(steps)

    # Extract code lines
    code = extract_circuit_code(notebook_path)
    lshift_lines = extract_lshift_lines(code)
    print(f"  Found {len(lshift_lines)} << lines in source")

    # Save step metadata
    (circuit_out_dir / "steps.json").write_text(json.dumps(steps, indent=2))

    # Generate samples
    op_samples = make_operation_samples(steps, lshift_lines, config, circuit_key)
    preview_pngs = list(circuit_src_dir.glob("*_preview.png"))
    preview_png = str(preview_pngs[0]) if preview_pngs else None
    circ_samples = make_circuit_samples(circuit_key, config, code, preview_png)

    # Save per-circuit JSONL
    all_samples = op_samples + circ_samples
    with open(circuit_out_dir / "samples.jsonl", "w") as f:
        for s in all_samples:
            f.write(json.dumps(s) + "\n")

    print(
        f"  → {len(op_samples)} operation samples, {len(circ_samples)} circuit samples"
        + (" [DRC ✓]" if config["drc_pass"] else " [DRC ✗]")
    )
    return {"operation_samples": op_samples, "circuit_samples": circ_samples}


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    print(f"Generating SFT dataset from {len(CIRCUIT_CONFIGS)} circuits\n")
    CIRCUITS_DIR.mkdir(parents=True, exist_ok=True)

    all_op: list[dict] = []
    all_circ: list[dict] = []

    for circuit_key in CIRCUIT_CONFIGS:
        print(f"\n[{circuit_key}]")
        result = process_circuit(circuit_key)
        all_op.extend(result["operation_samples"])
        all_circ.extend(result["circuit_samples"])

    # Write combined outputs
    drc_circ = [s for s in all_circ if s.get("drc_pass")]

    for path, samples in [
        (THIS_DIR / "dataset_operations.jsonl", all_op),
        (THIS_DIR / "dataset_circuits.jsonl", all_circ),
        (THIS_DIR / "dataset_circuits_drc_only.jsonl", drc_circ),
        (THIS_DIR / "dataset_full.jsonl", all_op + all_circ),
        (THIS_DIR / "dataset_full_drc_only.jsonl", all_op + drc_circ),
    ]:
        with open(path, "w") as f:
            for s in samples:
                f.write(json.dumps(s) + "\n")
        print(f"  {len(samples):4d} samples → {path.name}")

    total = len(all_op) + len(all_circ)
    print(f"\nDone. {total} total samples ({len(all_op)} op + {len(all_circ)} circuit)")
    print(
        f"DRC-clean circuit samples: {len(drc_circ)}/{len(all_circ)} "
        f"→ dataset_full_drc_only.jsonl for strict training"
    )


if __name__ == "__main__":
    main()
