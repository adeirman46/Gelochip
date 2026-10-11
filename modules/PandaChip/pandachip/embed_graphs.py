"""Append autoloading waveform graphs to an xschem schematic.

Usage:
    .venv/bin/python -m pandachip.embed_graphs <sch> <raw> "node1 node2" ["nodeA;expr" ...]

Each quoted group becomes one stacked graph pane (xschem `B 2` object with
rawfile= + autoload=1, so waveforms appear as soon as the schematic opens).
Panes are placed to the right of the schematic's current extent. Y ranges
are taken from the rawfile. Skips schematics that already contain graphs.
"""

from __future__ import annotations

import math
import re
import sys
from pathlib import Path

from .rawread import read_raw

PANE_W, PANE_H, GAP = 960, 220, 40

# Visually distinct xschem layer colors, cycled per trace in a pane
# (green, cyan, red, yellow, white, then fallbacks).
TRACE_COLORS = [4, 12, 5, 8, 7, 9, 11, 6]


def extent(sch_text: str) -> tuple[int, int]:
    max_x, min_y = 0, 0
    for m in re.finditer(r"^[CN] (?:\{[^}]*\} )?(-?\d+) (-?\d+)(?: (-?\d+) (-?\d+))?",
                         sch_text, re.M):
        xs = [int(m.group(1))] + ([int(m.group(3))] if m.group(3) else [])
        ys = [int(m.group(2))] + ([int(m.group(4))] if m.group(4) else [])
        max_x = max(max_x, *xs)
        min_y = min(min_y, *ys)
    return max_x, min_y


def _vec(raw: dict, name: str) -> list[float] | None:
    for k, v in raw["vectors"].items():
        if k.lower() in (name.lower(), f"v({name.lower()})"):
            return v
    return None


def _dominant_period(t: list[float], v: list[float]) -> float | None:
    """Period of the strongest spectral component, via a coarse FFT."""
    try:
        import numpy as np
    except ImportError:
        return None
    n = 1 << 12
    tu = np.linspace(t[0], t[-1], n)
    yu = np.interp(tu, np.asarray(t), np.asarray(v))
    yu = yu - yu.mean()
    spec = np.abs(np.fft.rfft(yu * np.hanning(n)))
    freqs = np.fft.rfftfreq(n, (tu[-1] - tu[0]) / (n - 1))
    idx = int(np.argmax(spec[1:])) + 1
    if freqs[idx] <= 0:
        return None
    return float(1.0 / freqs[idx])


def y_range(raw: dict, nodes: list[str]) -> tuple[float, float]:
    lo, hi = None, None
    for node in nodes:
        expr = node.split(";", 1)[-1]
        toks = expr.split()
        v: list[float] | None
        if len(toks) == 3 and toks[2] == "-":
            a, b = _vec(raw, toks[0]), _vec(raw, toks[1])
            v = [x - y for x, y in zip(a, b)] if a and b else None
        else:
            v = _vec(raw, toks[0])
        if v:
            lo = min(v) if lo is None else min(lo, min(v))
            hi = max(v) if hi is None else max(hi, max(v))
    if lo is None or hi == lo:
        return 0.0, 3.3
    pad = 0.1 * (hi - lo)
    return lo - pad, hi + pad


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--append"]
    append = "--append" in sys.argv[1:]
    sch = Path(args[0]).resolve()
    raw_path = Path(args[1]).resolve()
    groups = [g.split() if ";" not in g else [g] for g in args[2:]]
    if not groups:
        print("no node groups given", file=sys.stderr)
        sys.exit(2)

    text = sch.read_text()
    if "flags=graph" in text and not append:
        print(f"{sch.name}: graphs already present, skipping")
        return
    raw = read_raw(raw_path)
    scale = raw["meta"]["variables"][0]
    t = raw["vectors"][scale]
    is_ac = scale.lower() == "frequency"

    x0, y_top = extent(text)
    x0 += 80
    blocks = []
    for i, nodes in enumerate(groups):
        gy1 = y_top + i * (PANE_H + GAP)
        gy2 = gy1 + PANE_H
        if is_ac:
            # AC panes read in dB (db20 expression), log frequency axis.
            mags = [m for n in nodes for m in (_vec(raw, n.split(";", 1)[-1].split()[0]) or [])]
            peak_db = 20 * math.log10(max(mags)) if mags else 60.0
            lo, hi = 0.0, math.ceil(peak_db / 10) * 10 + 10
            nodes = [n if ";" in n else f"{n}_dB;{n} db20()" for n in nodes]
        else:
            lo, hi = y_range(raw, nodes)
        node_attr = "\n".join(nodes)
        extra = "logx=1\nunitx=1\n" if is_ac else ""
        x_end = t[-1]
        if not is_ac:
            # Window transient panes to ~15 cycles of the dominant tone so
            # fast waveforms are readable instead of a solid block.
            first = nodes[0].split(";", 1)[-1].split()[0]
            v = _vec(raw, first)
            if v:
                period = _dominant_period(t, v)
                if period and 15 * period < (t[-1] - t[0]):
                    x_end = t[0] + 15 * period
        colors = " ".join(str(TRACE_COLORS[j % len(TRACE_COLORS)])
                          for j in range(len(nodes)))
        blocks.append(
            f"B 2 {x0} {gy1} {x0 + PANE_W} {gy2} {{flags=graph\n"
            f"rawfile={raw_path}\n"
            f"sim_type={'ac' if is_ac else 'tran'}\n"
            f"autoload=1\n"
            f"color=\"{colors}\"\n"
            f"y1={lo:.3g}\ny2={hi:.3g}\ndivy=4\n"
            + (f"x1={math.log10(max(t[0], 1e-3)):.3g}\nx2={math.log10(t[-1]):.3g}\ndivx=6\n{extra}"
               if is_ac else f"x1={t[0]:.3g}\nx2={x_end:.3g}\ndivx=8\n{extra}")
            + f"node=\"{node_attr}\"\n}}")
    if not text.endswith("\n"):
        text += "\n"
    sch.write_text(text + "\n".join(blocks) + "\n")
    print(f"{sch.name}: added {len(blocks)} graph pane(s)")


if __name__ == "__main__":
    main()
