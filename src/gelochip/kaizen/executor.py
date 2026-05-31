"""
gelochip.kaizen.executor  —  the agent's "test" step.

Takes a string of generated glayout Python code, executes it in an isolated
namespace, locates the resulting gdsfactory ``Component``, writes a GDS, runs a
gf180 DRC via Magic, and renders a PNG preview. The structured result is what
the Critic node grades and what the web UI displays.

This is deliberately *not* a security sandbox — generated code is executed
in-process. It is meant for trusted local agent use only.
"""
from __future__ import annotations

import io
import os
import re
import traceback
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

from gelochip.kaizen import config

# Variable names the generated code is asked to bind its final layout to.
_RESULT_NAMES = ("component", "comp", "top", "chip", "layout", "result", "c")


def _strip_code_fence(code: str) -> str:
    """Pull python out of a ```python ... ``` markdown fence if present."""
    m = re.search(r"```(?:python|py)?\s*\n(.*?)```", code, re.DOTALL)
    return (m.group(1) if m else code).strip()


def _resolve_component(ns: dict) -> Any | None:
    """Find a gdsfactory Component (or gelochip.gl wrapper) in the namespace."""
    try:
        from gdsfactory import Component
    except Exception:
        Component = None

    def unwrap(obj):
        # gelochip.gl returns Layout/GDSResult wrappers exposing `.component`.
        if Component is not None and isinstance(obj, Component):
            return obj
        comp = getattr(obj, "component", None) or getattr(obj, "_comp", None)
        if Component is not None and isinstance(comp, Component):
            return comp
        return None

    for name in _RESULT_NAMES:
        if name in ns:
            c = unwrap(ns[name])
            if c is not None:
                return c
    # Fall back to any Component-like value in the namespace.
    for val in ns.values():
        c = unwrap(val)
        if c is not None:
            return c
    # Common glayout pattern: a @cell factory function was defined but never
    # called. Try calling it (no args, then pdk=gf180) to obtain the Component.
    c = _call_factory(ns, unwrap)
    if c is not None:
        return c
    return None


def _call_factory(ns: dict, unwrap):
    try:
        from glayout.pdk.gf180_mapped import gf180_mapped_pdk
    except Exception:
        gf180_mapped_pdk = None

    # Functions/factories *defined in the snippet* (incl. gdsfactory @cell, which
    # copies __module__ via functools.wraps) — not imported helpers like nmos.
    def is_local(v):
        if not callable(v) or isinstance(v, type):
            return False
        mod = getattr(v, "__module__", "") or getattr(getattr(v, "__wrapped__", None), "__module__", "")
        return mod == "__kaizen__"

    cands = [v for k, v in ns.items() if not k.startswith("_") and is_local(v)]
    for fn in cands:
        for args in ((), (gf180_mapped_pdk,)) if gf180_mapped_pdk is not None else ((),):
            try:
                c = unwrap(fn(*args))
                if c is not None:
                    return c
            except Exception:
                continue
    return None


def render_preview(gds_path: str, png_path: str, width: int = 900, height: int = 700) -> bool:
    """Render a GDS to PNG. klayout offscreen first, gdsfactory/matplotlib fallback."""
    try:
        import klayout.lay as lay

        lv = lay.LayoutView()
        lv.load_layout(gds_path, True)
        lv.max_hier()
        lv.zoom_fit()
        lv.save_image(png_path, width, height)
        if os.path.exists(png_path) and os.path.getsize(png_path) > 0:
            return True
    except Exception:
        pass
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import gdsfactory as gf

        comp = gf.import_gds(gds_path)
        ax = comp.plot()
        fig = ax.get_figure() if hasattr(ax, "get_figure") else plt.gcf()
        fig.savefig(png_path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        return os.path.exists(png_path)
    except Exception:
        return False


def run_layout_code(code: str, job_dir: str | Path, name: str = "kaizen_top",
                    run_drc: bool = True, run_testbench: bool = False) -> dict:
    """
    Execute generated glayout code and verify it.

    Returns a dict the Critic/web UI consumes::

        ok            bool   — code executed and produced a Component
        passed        bool   — ok AND (DRC clean or DRC skipped)
        stage         str    — where it stopped: exec | build | drc | done
        error         str    — traceback / failure reason ("" if none)
        stdout        str    — captured prints from the code
        gds_path      str|"" — written GDS
        png_path      str|"" — rendered preview
        drc           dict   — run_drc() result (is_pass / total_errors / details)
    """
    job = Path(job_dir)
    job.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("PDK_ROOT", config.PDK_ROOT)

    def _sub(kind: str) -> Path:
        """Artifact subfolder inside the job/project dir (code/data/database/images).
        Keeps each run tidy: code=.py, data=.gds, database=.spice, images=.png."""
        d = job / kind
        d.mkdir(parents=True, exist_ok=True)
        return d

    result: dict[str, Any] = {
        "ok": False, "passed": False, "stage": "exec", "error": "",
        "stdout": "", "gds_path": "", "png_path": "", "drc": {},
        "spice": "", "spice_path": "", "testbench": {},
    }

    src = _strip_code_fence(code)
    (_sub("code") / f"{name}.py").write_text(src)
    ns: dict[str, Any] = {"__name__": "__kaizen__"}
    buf = io.StringIO()

    # 1. Execute the generated code. Pure-glayout snippets often append an
    #    ngspice sim harness that may raise *after* the layout is already built;
    #    `exec` keeps every binding made before the failing line, so we record
    #    the error but still try to recover the Component below.
    exec_error = ""
    try:
        with redirect_stdout(buf):
            exec(compile(src, f"{name}.py", "exec"), ns)
    except Exception:
        exec_error = traceback.format_exc()

    # 2. Locate the produced layout (works for any gdsfactory Component).
    comp = _resolve_component(ns)
    if comp is None:
        result.update(stage="build", stdout=buf.getvalue(),
                      error=exec_error or "No gdsfactory Component found in the "
                            "generated code. Build a layout and leave it in a variable.")
        return result
    result["ok"] = True
    if exec_error:
        # Component built, but a later line (usually sim) failed — non-fatal.
        result["error"] = exec_error

    # 3. Write GDS + preview.
    gds_path = str(_sub("data") / f"{name}.gds")
    try:
        comp.write_gds(gds_path)
        result["gds_path"] = gds_path
    except Exception:
        result.update(stage="build", error=traceback.format_exc(), stdout=buf.getvalue())
        return result

    png_path = str(_sub("images") / f"{name}.png")
    if render_preview(gds_path, png_path):
        result["png_path"] = png_path

    # 4. DRC. Run with CWD = job dir so Magic/Netgen scratch (.ext/.nodes/
    #    *_drc_out/…) lands inside the (git-ignored) output dir, never the repo root.
    if run_drc:
        _cwd = os.getcwd()
        try:
            from gelochip.verification.drc_lvs import run_drc as _run_drc

            os.chdir(_sub("database"))   # contain Magic scratch (*_drc_out/.ext)
            drc = _run_drc(gds_path, getattr(comp, "name", name), comp, pdk=config.PDK)
            result["drc"] = drc
            result["stage"] = "drc"
            if drc.get("skipped"):
                result["passed"] = True   # tools unavailable → don't block the loop
            else:
                result["passed"] = bool(drc.get("is_pass"))
        except Exception:
            result.update(error=traceback.format_exc())
            result["drc"] = {"is_pass": False, "error": result["error"]}
        finally:
            os.chdir(_cwd)
    else:
        result["passed"] = True

    # 5. SPICE extraction + AC/transient testbench (no LVS). Best-effort.
    if run_testbench:
        try:
            from gelochip.kaizen import testbench as _tb

            ex = _tb.extract_spice(comp)
            result["spice"] = ex.get("spice", "")
            if ex.get("ok"):
                spice_file = _sub("database") / f"{name}.spice"
                spice_file.write_text(result["spice"])
                result["spice_path"] = str(spice_file)
                tb = _tb.run_testbenches(component=comp, out_dir=str(_sub("images") / "tb"))
                result["testbench"] = {
                    "passed": tb.get("passed"),
                    "ac_plot": tb.get("plots", {}).get("ac", ""),
                    "tran_plot": tb.get("plots", {}).get("tran", ""),
                    "in_node": tb.get("in_node"), "out_node": tb.get("out_node"),
                }
        except Exception as e:
            result["testbench"] = {"error": str(e)}

    result["stage"] = "done"
    result["stdout"] = buf.getvalue()
    return result
