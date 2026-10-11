"""Generate default waveform PNGs for every rawfile in a run workspace.

Usage:
    .venv/bin/python -m pandachip.autoplot designs/<run-id>

Writes waves_<rawstem>.png next to the workspace root (skips files whose
PNG is newer than the raw) and prints one relative PNG path per line.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

from .rawread import read_raw


def _dominant_period(t: list[float], v: list[float]) -> float | None:
    """Period of the strongest spectral component, for the zoom window."""
    try:
        import numpy as np
        if len(t) < 64:
            return None
        y = np.asarray(v, dtype=float)
        y = y - y.mean()
        if not y.any():
            return None
        dt = (t[-1] - t[0]) / (len(t) - 1)
        spec = np.abs(np.fft.rfft(y))
        spec[0] = 0.0
        k = int(spec.argmax())
        if k == 0:
            return None
        freq = k / (len(y) * dt)
        return 1.0 / freq if freq > 0 else None
    except Exception:
        return None


def plot(raw_path: Path, png: Path) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    raw = read_raw(raw_path)
    names = raw["meta"]["variables"]
    scale = names[0]
    t = raw["vectors"][scale]
    volts = [n for n in names[1:] if n.startswith("v(")][:6]
    is_ac = scale.lower() == "frequency"

    if is_ac:
        fig, ax = plt.subplots(figsize=(11, 4.2))
        for n in volts:
            y = [20 * math.log10(v) if v > 0 else -300.0
                 for v in raw["vectors"][n]]
            ax.plot(t, y, linewidth=0.9, label=n)
        ax.set_xscale("log")
        ax.set_ylabel("gain (dB)")
        ax.set_xlabel("frequency (Hz)")
        ax.grid(alpha=0.3)
        ax.legend(loc="best", fontsize=8)
        ax.set_title(raw_path.name, fontsize=10)
        fig.tight_layout()
        fig.savefig(png, dpi=125)
        plt.close(fig)
        return png

    # Transient: full envelope on top, steady-state zoom below so the
    # actual cycles and the sampling timestep are visible.
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7.5))
    best, best_vpp = None, -1.0
    for n in volts:
        y = raw["vectors"][n]
        ax1.plot(t, y, linewidth=0.7, label=n)
        vpp = (max(y) - min(y)) if y else 0.0
        if vpp > best_vpp:
            best, best_vpp = y, vpp
    ax1.set_ylabel("V")
    ax1.grid(alpha=0.3)
    ax1.legend(loc="best", fontsize=8)
    ax1.set_title(f"{raw_path.name} - full range", fontsize=10)

    # Zoom on the FASTEST strong oscillation among the traces - keying on
    # the biggest swing picks slow charge-up envelopes and zooms on nothing.
    span = t[-1] - t[0]
    dt = span / max(len(t) - 1, 1)
    periods = []
    for n in volts:
        pd = _dominant_period(t, raw["vectors"][n])
        if pd and 4 * dt <= pd <= span / 4:
            periods.append(pd)
    window = 12 * min(periods) if periods else span * 0.02
    window = max(min(window, span * 0.1), 50 * dt)
    window = min(window, span)
    t0 = t[-1] - window
    i0 = next((i for i, x in enumerate(t) if x >= t0), 0)
    for n in volts:
        ax2.plot(t[i0:], raw["vectors"][n][i0:], linewidth=0.9,
                 marker=".", markersize=2.5, label=n)
    ax2.set_ylabel("V")
    ax2.set_xlabel("time (s)")
    ax2.grid(alpha=0.3)
    ax2.set_title("steady-state zoom (last ~12 cycles, sample points "
                  "visible)", fontsize=9)
    fig.tight_layout()
    fig.savefig(png, dpi=125)
    plt.close(fig)
    return png


def auto_plots(run_dir: Path) -> list[str]:
    made: list[str] = []
    for raw_path in sorted(list(run_dir.glob("*.raw")) + list(run_dir.glob("sim/*.raw")) + list(run_dir.glob("exp/*.raw"))):
        png = run_dir / f"waves_{raw_path.stem}.png"
        if not (png.exists() and png.stat().st_mtime >= raw_path.stat().st_mtime):
            try:
                plot(raw_path, png)
            except Exception as exc:
                print(f"skip {raw_path.name}: {exc}", file=sys.stderr)
                continue
        made.append(str(png.relative_to(run_dir)))
    return made


def main() -> None:
    run_dir = Path(sys.argv[1]).resolve()
    for rel in auto_plots(run_dir):
        print(rel)


if __name__ == "__main__":
    main()
