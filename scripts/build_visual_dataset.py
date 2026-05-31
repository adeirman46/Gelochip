"""Build a *visual chain-of-thought* layout dataset.

For each canonical circuit we re-run its committed clean.py build, but trace every
top-level construction step (each `comp << ...` placement/route in the design file).
After each step we render the current layout to a PNG. The result is, per circuit, a
sequence of (cumulative_code, step_code, image) — the agent learns the *sequence* and
sees the layout grow, instead of memorising one giant file.

Output:
  data/visual_dataset/images/<circuit>/step_NN.png   per-step renders (+ final.png)
  data/visual_dataset/dataset.jsonl                  one consolidated dataset

Run: .venv/bin/python scripts/build_visual_dataset.py <circuit|all>
"""
from __future__ import annotations
import os, sys, json, traceback
from pathlib import Path

ROOT = Path("/home/irman/Gelochip")
os.environ.setdefault("PDK_ROOT", os.path.expanduser("~/pdks"))
sys.path.insert(0, str(ROOT / "src" / "gelochip"))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "data" / "glayout_code"))   # reuse nl_templates
try:
    from nl_templates import describe_operation
except Exception:
    def describe_operation(code_line, circuit_name=""):
        return ""

OUT = ROOT / "data" / "visual_dataset"
IMG = OUT / "images"

CIRCUITS = [
    "current_mirror", "diff_pair", "transmission_gate", "fvf", "p_block",
    "low_voltage_cmirror", "differential_to_single_ended_converter",
    "diff_pair_stackedcmirror", "n_block", "opamp", "opamp_twostage",
    "row_csamplifier_diff_to_single_ended_converter", "stacked_current_mirror",
    "diff_pair_cmirrorbias", "ota",
]


def _render(component, png_path: Path):
    """Render a (possibly partial) gdsfactory Component to a PNG via KLayout."""
    import klayout.lay as klay
    import tempfile
    png_path.parent.mkdir(parents=True, exist_ok=True)
    gds = tempfile.mktemp(suffix=".gds")
    component.write_gds(gds)
    lv = klay.LayoutView()
    lv.load_layout(gds, True)
    lv.max_hier(); lv.zoom_fit()
    lv.save_image(str(png_path), 900, 900)
    os.remove(gds)


def _is_construction_frame(fn: str, design_file: str) -> bool:
    """A `<<` is a real *construction* step if it was written in the circuit's own
    design file or in a glayout cell definition (composite/elementary). Deep
    primitive/util/routing internals (`fet`, `via_gen`, `comp_utils`, `c_route`…)
    are NOT construction the agent should learn — they are plumbing."""
    return fn == design_file or "/glayout/cells/" in fn


def build_circuit_steps(circuit: str) -> dict:
    """Exec the circuit's clean.py with `<<` traced; capture per-step code + image.

    Steps are captured at the glayout *cell* level (each sub-block is built once,
    thanks to @cell caching), giving a bottom-up narrative: watch each sub-block
    grow, then watch the blocks compose into the full circuit.
    """
    import linecache
    clean_py = ROOT / "data" / "circuits" / circuit / f"{circuit}_clean.py"
    src = clean_py.read_text()
    fname = str(clean_py)
    code_obj = compile(src, fname, "exec")

    import gdsfactory as gf
    from gdsfactory.component import Component

    # Bust caches so the FULL construction is traced (some circuits — ota — short
    # out via a written GDS cache; and gdsfactory @cell caches sub-blocks). Without
    # this, ota loads its prebuilt GDS and we capture only the top-level assembly,
    # not the n_block / p_block / fvf sub-blocks being built.
    for cache in ("ota.gds", "ota_netlist.spice"):
        try:
            os.remove(cache)
        except OSError:
            pass
    try:
        gf.clear_cache()
    except Exception:
        pass

    steps: list[dict] = []
    last_line: dict[str, int] = {}      # per-file last captured line
    state = {"n": 0}
    img_dir = IMG / circuit
    orig_lshift = Component.__lshift__
    orig_add = Component.add

    def _snapshot(self, fn: str, lineno: int):
        prev = last_line.get(fn, lineno - 1)
        start = max(prev, lineno - 8)            # cap context to ~8 lines
        chunk = "".join(linecache.getline(fn, i) for i in range(start + 1, lineno + 1)).rstrip()
        op_line = linecache.getline(fn, lineno).strip()    # the << / .add line itself
        last_line[fn] = lineno
        try:
            png = img_dir / f"step_{state['n']:02d}.png"
            _render(self, png)
        except Exception:
            return                               # partial comp not renderable yet
        steps.append({
            "step": state["n"],
            "block": Path(fn).stem if fn != fname else circuit,
            "instruction": describe_operation(op_line, circuit),   # natural language
            "code": chunk,
            "image": str(png.relative_to(ROOT)),
        })
        state["n"] += 1

    def traced_lshift(self, other):
        ref = orig_lshift(self, other)
        frame = sys._getframe(1)
        fn = frame.f_code.co_filename
        if _is_construction_frame(fn, fname):
            _snapshot(self, fn, frame.f_lineno)
        return ref

    def traced_add(self, *a, **k):
        ref = orig_add(self, *a, **k)
        # only trace `.add()` written in the circuit's own design file (inline
        # assembly like stacked_current_mirror's cm.add(out)/cm.add(ref)); library
        # cells already use `<<`, captured above.
        frame = sys._getframe(1)
        if frame.f_code.co_filename == fname:
            _snapshot(self, fname, frame.f_lineno)
        return ref

    Component.__lshift__ = traced_lshift
    Component.add = traced_add
    # __name__ == "__main__" so the clean.py's _ModProxy self-registration works
    # (that is what lets gdsfactory @cell/pydantic resolve MappedPDK et al.)
    ns: dict = {"__name__": "__main__"}
    err = None
    try:
        exec(code_obj, ns)
    except Exception:
        err = traceback.format_exc().splitlines()[-1]
    finally:
        Component.__lshift__ = orig_lshift
        Component.add = orig_add

    # final full-layout render from the bound `component`
    comp = ns.get("component")
    final_png = None
    if comp is not None:
        try:
            final_png = img_dir / "final.png"
            _render(comp, final_png)
        except Exception as e:
            print(f"   [final render failed] {e}")
    print(f"[{circuit}] captured {len(steps)} steps"
          + (f"  (build note: {err})" if err else ""))
    return {
        "circuit": circuit,
        "n_steps": len(steps),
        "steps": steps,
        "final_image": str(final_png.relative_to(ROOT)) if final_png else None,
        "build_error": err,
    }


def _record(r: dict) -> dict:
    """One consolidated visual-CoT jsonl record for a circuit."""
    nice = r["circuit"].replace("_", " ")
    return {
        "circuit": r["circuit"],
        "instruction": f"Build a DRC-clean {nice} layout on the gf180 PDK, "
                       f"step by step. After each placement/route, look at the "
                       f"rendered layout and decide the next step.",
        "n_steps": r["n_steps"],
        "steps": r["steps"],            # ordered [{step, block, code, image}]
        "final_image": r["final_image"],
        "build_error": r["build_error"],
    }


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    circuits = CIRCUITS if which == "all" else [which]
    OUT.mkdir(parents=True, exist_ok=True)
    results = [build_circuit_steps(c) for c in circuits]
    if len(circuits) > 1:
        # one consolidated jsonl: one line per circuit, full drawn sequence
        out = OUT / "dataset.jsonl"
        with out.open("w") as f:
            for r in results:
                f.write(json.dumps(_record(r)) + "\n")
        total = sum(r["n_steps"] for r in results)
        print(f"\nwrote {out}: {len(results)} circuits, {total} total steps")
        for r in results:
            note = f"  ⚠ {r['build_error']}" if r["build_error"] else ""
            print(f"  {r['circuit']:48s} {r['n_steps']:4d} steps{note}")
    else:
        # single circuit: update just this circuit's record in dataset.jsonl
        out = OUT / "dataset.jsonl"
        rec = _record(results[0])
        if out.exists():
            recs = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
            recs = [r for r in recs if r.get("circuit") != rec["circuit"]] + [rec]
            order = {c: i for i, c in enumerate(CIRCUITS)}
            recs.sort(key=lambda r: order.get(r["circuit"], 999))
            with out.open("w") as f:
                for r in recs:
                    f.write(json.dumps(r) + "\n")
            print(f"updated {rec['circuit']} in {out}: {rec['n_steps']} steps "
                  f"(build_error={rec['build_error']})")
        else:
            print(json.dumps(rec, indent=2)[:1200])


if __name__ == "__main__":
    main()
