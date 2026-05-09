"""
Per-job output directory manager.

Every pipeline run gets its own sub-directory under GELOCHIP_OUTPUT_DIR
(default: <project_root>/outputs/).  The manager creates the tree on init
and exposes helper methods to save / retrieve each artifact type.

Directory layout for one job::

    outputs/{job_id}/
    ├── spec.json             – parsed CircuitSpec
    ├── params.json           – sized component parameters
    ├── summary.md            – final answer from Summarizer
    ├── papers/
    │   ├── papers.json       – metadata for all retrieved papers
    │   └── {arxiv_id}/
    │       ├── paper.pdf     – downloaded paper PDF
    │       ├── fig_0.png
    │       └── fig_1.png
    ├── layout/
    │   ├── layout.py         – generated GLayout Python code
    │   ├── output.gds        – GDSII layout
    │   └── output_preview.png
    └── verification/
        ├── drc_report.txt    – Magic DRC output
        ├── lvs_report.txt    – Netgen LVS output
        ├── testbench.sp      – ngspice testbench
        ├── output_pex.spice  – post-layout PEX netlist (if Magic ran)
        └── sim_results.json  – ngspice simulation results
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any


def _default_root() -> Path:
    """Return <project_root>/outputs/ or the env-var override."""
    env = os.getenv("GELOCHIP_OUTPUT_DIR")
    if env:
        return Path(env)
    # Walk up from this file to find the project root (contains pyproject.toml)
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists():
            return parent / "outputs"
    # Fallback: current working directory
    return Path.cwd() / "outputs"


class OutputManager:
    """Manages all file I/O for a single Gelochip pipeline run."""

    def __init__(self, job_id: str, root: Path | None = None):
        self.job_id = job_id
        self.root   = (root or _default_root()) / job_id
        self._mkdir(self.root)
        self._mkdir(self.root / "papers")
        self._mkdir(self.root / "layout")
        self._mkdir(self.root / "verification")

    # ── Convenience paths ────────────────────────────────────────────────────

    @property
    def spec_path(self)         -> Path: return self.root / "spec.json"
    @property
    def params_path(self)       -> Path: return self.root / "params.json"
    @property
    def summary_path(self)      -> Path: return self.root / "summary.md"
    @property
    def papers_dir(self)        -> Path: return self.root / "papers"
    @property
    def papers_meta_path(self)  -> Path: return self.root / "papers" / "papers.json"
    @property
    def layout_dir(self)        -> Path: return self.root / "layout"
    @property
    def layout_code_path(self)  -> Path: return self.root / "layout" / "layout.py"
    @property
    def gds_path(self)          -> Path: return self.root / "layout" / "output.gds"
    @property
    def gds_preview_path(self)  -> Path: return self.root / "layout" / "output_preview.png"
    @property
    def verification_dir(self)  -> Path: return self.root / "verification"
    @property
    def drc_report_path(self)   -> Path: return self.root / "verification" / "drc_report.txt"
    @property
    def lvs_report_path(self)   -> Path: return self.root / "verification" / "lvs_report.txt"
    @property
    def testbench_path(self)    -> Path: return self.root / "verification" / "testbench.sp"
    @property
    def pex_spice_path(self)    -> Path: return self.root / "verification" / "output_pex.spice"
    @property
    def sim_results_path(self)  -> Path: return self.root / "verification" / "sim_results.json"

    def paper_figures_dir(self, paper_id: str) -> Path:
        d = self.papers_dir / paper_id
        self._mkdir(d)
        return d

    # ── Savers ───────────────────────────────────────────────────────────────

    def save_spec(self, spec: dict[str, Any]) -> None:
        self._write_json(self.spec_path, spec)

    def save_params(self, params: dict[str, Any]) -> None:
        # Strip internal analytics key before saving
        clean = {k: v for k, v in params.items() if not k.startswith("_")}
        self._write_json(self.params_path, clean)

    def save_papers(self, papers: list[dict[str, Any]]) -> None:
        self._write_json(self.papers_meta_path, papers)

    def save_layout_code(self, code: str) -> None:
        self.layout_code_path.write_text(code, encoding="utf-8")

    def save_gds(self, src_gds_path: str) -> str:
        """Copy an existing GDS into the job layout dir. Returns new path string."""
        src = Path(src_gds_path)
        if src.exists() and src != self.gds_path:
            shutil.copy2(src, self.gds_path)
        return str(self.gds_path)

    def save_drc_report(self, report: str) -> None:
        self.drc_report_path.write_text(report, encoding="utf-8")

    def save_lvs_report(self, report: str) -> None:
        self.lvs_report_path.write_text(report, encoding="utf-8")

    def save_testbench(self, testbench: str) -> None:
        self.testbench_path.write_text(testbench, encoding="utf-8")

    def save_sim_results(self, results: dict[str, Any]) -> None:
        self._write_json(self.sim_results_path, results)

    def save_summary(self, text: str) -> None:
        self.summary_path.write_text(text, encoding="utf-8")

    # ── Utility ───────────────────────────────────────────────────────────────

    def manifest(self) -> dict[str, Any]:
        """Return a dict of all existing output files (for API responses)."""
        out: dict[str, Any] = {"job_id": self.job_id, "root": str(self.root), "files": {}}
        for rel in [
            "spec.json", "params.json", "summary.md",
            "papers/papers.json",
            "layout/layout.py", "layout/output.gds", "layout/output_preview.png",
            "verification/drc_report.txt", "verification/lvs_report.txt",
            "verification/testbench.sp", "verification/output_pex.spice",
            "verification/sim_results.json",
        ]:
            p = self.root / rel
            if p.exists():
                out["files"][rel] = str(p)
        # paper figures and PDFs
        paper_figs: list[str] = []
        paper_pdfs: list[str] = []
        if self.papers_dir.is_dir():
            for paper_dir in self.papers_dir.iterdir():
                if paper_dir.is_dir():
                    paper_figs.extend(str(f) for f in sorted(paper_dir.glob("*.png")))
                    paper_pdfs.extend(str(f) for f in sorted(paper_dir.glob("*.pdf")))
        if paper_figs:
            out["files"]["paper_figures"] = paper_figs
        if paper_pdfs:
            out["files"]["paper_pdfs"] = paper_pdfs
        return out

    # ── Internal ─────────────────────────────────────────────────────────────

    @staticmethod
    def _mkdir(p: Path) -> None:
        p.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _write_json(path: Path, data: Any) -> None:
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
