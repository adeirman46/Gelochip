"""Export real xschem schematic renderings (light background, true device
symbols, embedded waveform graphs) to PNG for the PDF report.

Runs the container's xschem under a virtual X display (xvfb-run) with the
gf180 PDK library sourced and a light colour scheme, and uses xschem's
native ``print png`` for a full-extent, faithfully-coloured image — the
same picture the GUI shows. Falls back to the matplotlib renderer
(pandachip.schematic_render) if xschem/Docker is unavailable.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

CONTAINER = "pandachip-eda"
PDK = "gf180mcuD"
# repo is bind-mounted at this lowercase alias too; xschem/ngspice need it
LC_ROOT = "/home/irman/pandachip"

_RC = """source /foss/pdks/gf180mcuD/libs.tech/xschem/xschemrc
set dark_colorscheme 0
set draw_grid 0
after 3500 {{
  xschem zoom_full
  xschem print png {{{target}}}
  exit
}}
"""


def _container_path(host: Path) -> str:
    s = str(host)
    if s.startswith("/home/irman/PandaChip"):
        return s.replace("/home/irman/PandaChip", LC_ROOT, 1)
    return s


def _strip_graphs(text: str) -> str:
    """Remove embedded waveform graph panes (B 2 ... {flags=graph ...}) so
    the report figure shows the CIRCUIT ONLY, at full size."""
    out, lines, i = [], text.splitlines(), 0
    while i < len(lines):
        ln = lines[i]
        if ln.lstrip().startswith("B ") and "flags=graph" in ln:
            depth = ln.count("{") - ln.count("}")
            i += 1
            while i < len(lines) and depth > 0:
                depth += lines[i].count("{") - lines[i].count("}")
                i += 1
            continue
        out.append(ln)
        i += 1
    return "\n".join(out)


def export_schematic(sch: Path, out_png: Path) -> bool:
    """Render one .sch (circuit only, no graph panes) to out_png via native
    xschem. Returns success."""
    sch = Path(sch).resolve()
    out_png = Path(out_png).resolve()
    run_dir = sch.parent
    rc = run_dir / "report" / "_xschem_export.rc"
    rc.parent.mkdir(exist_ok=True)
    # temp circuit-only copy alongside the original (keeps relative sym paths)
    clean = run_dir / f"_report_{sch.stem}.sch"
    clean.write_text(_strip_graphs(sch.read_text(errors="replace")))
    render_name = clean.name
    target_c = _container_path(out_png)
    rc.write_text(_RC.format(target=target_c))
    if not shutil.which("docker"):
        return False
    subprocess.run(["docker", "exec", CONTAINER, "sh", "-c",
                    "pkill -9 xschem; pkill -9 Xvfb; true"],
                   capture_output=True, timeout=30)
    cmd = [
        "docker", "exec",
        "-e", "PATH=/foss/tools/bin:/usr/bin:/bin",
        "-e", f"PDK={PDK}", "-e", "PDK_ROOT=/foss/pdks",
        "-w", _container_path(run_dir), CONTAINER,
        "xvfb-run", "-a", "-s", "-screen 0 2200x1600x24",
        "xschem", "--rcfile", _container_path(rc), render_name,
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=90)
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "exec", CONTAINER, "sh", "-c",
                        "pkill -9 xschem; pkill -9 Xvfb; true"],
                       capture_output=True, timeout=30)
    clean.unlink(missing_ok=True)
    ok = out_png.exists() and out_png.stat().st_size > 2000
    if ok and shutil.which("convert"):  # trim whitespace, pad a little
        subprocess.run(["convert", str(out_png), "-trim", "+repage",
                        "-bordercolor", "white", "-border", "20", str(out_png)],
                       capture_output=True, timeout=60)
    rc.unlink(missing_ok=True)
    return ok


def render(sch: Path, out_png: Path, title: str | None = None) -> Path:
    """Native xschem render, matplotlib fallback."""
    if export_schematic(sch, out_png):
        return out_png
    from .schematic_render import render_schematic
    return render_schematic(sch, out_png, title)


if __name__ == "__main__":
    import sys
    p = render(Path(sys.argv[1]), Path(sys.argv[2]))
    print("wrote", p)
