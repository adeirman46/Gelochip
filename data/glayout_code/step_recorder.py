"""
StepRecorder: patches Component.__lshift__ to capture before/after GDS snapshots
at every placement/routing operation during circuit construction.

Only records << operations called directly from notebook-level code (not deep inside
glayout/gdsfactory library internals). This is done by inspecting the call stack:
if the immediate caller's filename matches the notebook source, we record; otherwise
we skip (it's an internal operation inside a primitive).
"""
import sys
from pathlib import Path

try:
    from gdsfactory.component import Component
except ImportError:
    Component = None


class StepRecorder:
    """
    Context manager that intercepts notebook-level << operations on gdsfactory
    Components, saving before/after GDS snapshots at each step.

    Pass source_files (list of paths) so only << calls originating from those
    files are recorded — everything inside glayout/gdsfactory internals is ignored.
    """

    def __init__(self, output_dir: str, source_files: list[str] | None = None):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        # File paths whose << calls we should record (notebook .ipynb path)
        self._source_files: list[str] = source_files or []
        self.steps: list[dict] = []
        self._step_count = 0
        self._original_lshift = None
        self._original_add = None

    def __enter__(self):
        self.install()
        return self

    def __exit__(self, *args):
        self.uninstall()

    def _is_user_level(self, depth: int = 1) -> bool:
        """Return True if the caller at `depth` frames up originates from a tracked source file."""
        if not self._source_files:
            return True
        try:
            caller_file = sys._getframe(depth + 1).f_code.co_filename
        except Exception:
            return False
        return any(src in caller_file for src in self._source_files)

    def _record_step(self, self_comp, ref_parent_name: str, original_fn, ref_arg):
        """Common recording logic shared by patched __lshift__ and add."""
        step_num = self._step_count

        before_path = self.output_dir / f"step_{step_num:03d}_before.gds"
        try:
            self_comp.write_gds(str(before_path))
            before_ok = True
        except Exception:
            before_ok = False

        result = original_fn(self_comp, ref_arg)
        self._step_count += 1

        after_path = self.output_dir / f"step_{step_num:03d}_after.gds"
        try:
            self_comp.write_gds(str(after_path))
            bbox_area = (
                abs((self_comp.xmax - self_comp.xmin) * (self_comp.ymax - self_comp.ymin))
                if self_comp.references
                else 0.0
            )
            after_ok = True
        except Exception:
            after_ok = False
            bbox_area = 0.0

        self.steps.append({
            "step": step_num,
            "component_name": self_comp.name,
            "ref_added": ref_parent_name,
            "before_gds": str(before_path) if before_ok else None,
            "after_gds": str(after_path) if after_ok else None,
            "before_png": None,
            "after_png": None,
            "bbox_area": bbox_area,
            "num_refs": len(self_comp.references),
            "code_line": None,
            "nl_description": None,
        })
        return result

    def install(self):
        if Component is None:
            raise ImportError("gdsfactory not available")

        orig_lshift = Component.__lshift__
        orig_add = Component.add
        self._original_lshift = orig_lshift
        self._original_add = orig_add
        recorder = self

        def patched_lshift(self_comp, ref):
            if not recorder._is_user_level(depth=1):
                return orig_lshift(self_comp, ref)
            ref_name = ref.parent.name if hasattr(ref, "parent") else "unknown"
            return recorder._record_step(self_comp, ref_name, orig_lshift, ref)

        def patched_add(self_comp, element):
            # Only intercept ComponentReference adds (not ports, labels, etc.)
            try:
                from gdsfactory.component_reference import ComponentReference as CR
                is_ref = isinstance(element, CR)
            except ImportError:
                is_ref = hasattr(element, "parent")

            if not is_ref or not recorder._is_user_level(depth=1):
                return orig_add(self_comp, element)
            ref_name = element.parent.name if hasattr(element, "parent") else "unknown"
            return recorder._record_step(self_comp, ref_name, orig_add, element)

        Component.__lshift__ = patched_lshift
        Component.add = patched_add

    def uninstall(self):
        if Component is None:
            return
        if self._original_lshift is not None:
            Component.__lshift__ = self._original_lshift
            self._original_lshift = None
        if self._original_add is not None:
            Component.add = self._original_add
            self._original_add = None

    def get_top_level_steps(self) -> list[dict]:
        """Return all recorded steps in order (already filtered to user-level ops)."""
        return list(self.steps)
