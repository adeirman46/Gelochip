"""Per-project output directory: outputs/kaizen/<project>_<date>/.

Replaces the old opaque UUID job folders with a readable
``<slug-of-the-prompt>_<YYYY-MM-DD>`` directory, pre-created with the six
artifact subfolders the pipeline writes into:

    <project>_<date>/
    ├── code/       generated glayout + spice .py
    ├── data/       GDS + params/spec .json
    ├── database/   SPICE netlist + DRC scratch + per-job research DB
    ├── images/     previews + AC/transient plots
    ├── link/       researched paper / repo URLs (links.json)
    └── text/       summary.md + DRC/LVS reports + event log
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from gelochip.kaizen import config

SUBDIRS = ("code", "data", "database", "images", "link", "text")


def slugify(prompt: str, maxlen: int = 48) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (prompt or "").lower()).strip("_")
    return (slug[:maxlen].rstrip("_")) or "design"


def make_project_dir(prompt: str, job_id: str | None = None, root: Path | None = None) -> Path:
    """Create (and return) outputs/kaizen/<slug>_<date>/ with the 6 subfolders.

    On same-prompt-same-day collision a short job-id suffix keeps it unique while
    staying readable (``..._<date>_<6hex>``)."""
    root = root or config.OUTPUT_DIR
    base = f"{slugify(prompt)}_{date.today().isoformat()}"
    d = root / base
    if d.exists() and job_id:
        d = root / f"{base}_{job_id[:6]}"
    for sub in SUBDIRS:
        (d / sub).mkdir(parents=True, exist_ok=True)
    return d
