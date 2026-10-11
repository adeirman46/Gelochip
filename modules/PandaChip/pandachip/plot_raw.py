"""Plot vectors from an ngspice rawfile to PNG.

Usage:
    .venv/bin/python -m pandachip.plot_raw sim/dbm_tb.raw out.png IF_P IF_N --diff IF_P IF_N
"""

from __future__ import annotations

import argparse

from .rawread import read_raw


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("raw")
    ap.add_argument("png")
    ap.add_argument("vectors", nargs="*")
    ap.add_argument("--diff", nargs=2, metavar=("P", "N"),
                    help="also plot P-N differential trace")
    ap.add_argument("--tmax", type=float, help="clip time axis at this value")
    args = ap.parse_args()

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    raw = read_raw(args.raw)
    vec = raw["vectors"]
    scale = raw["meta"]["variables"][0]
    t = vec[scale]

    def find(name: str) -> list[float]:
        for k in vec:
            if k.lower() in (name.lower(), f"v({name.lower()})"):
                return vec[k]
        raise SystemExit(f"vector {name} not in {list(vec)[:20]}")

    n_axes = (1 if args.vectors else 0) + (1 if args.diff else 0)
    fig, axes = plt.subplots(n_axes, 1, figsize=(12, 3.2 * n_axes),
                             sharex=True, squeeze=False)
    axes_flat = [a for row in axes for a in row]
    idx = 0
    lim = None
    if args.tmax:
        lim = next((i for i, x in enumerate(t) if x > args.tmax), len(t))

    if args.vectors:
        ax = axes_flat[idx]
        idx += 1
        for name in args.vectors:
            y = find(name)
            ax.plot(t[:lim], y[:lim], label=name, linewidth=0.8)
        ax.legend(loc="upper right")
        ax.set_ylabel("V")
        ax.grid(alpha=0.3)

    if args.diff:
        ax = axes_flat[idx]
        p, n = (find(x) for x in args.diff)
        d = [a - b for a, b in zip(p, n)]
        ax.plot(t[:lim], d[:lim], color="crimson", linewidth=0.8,
                label=f"{args.diff[0]} - {args.diff[1]}")
        ax.legend(loc="upper right")
        ax.set_ylabel("V (diff)")
        ax.grid(alpha=0.3)

    axes_flat[-1].set_xlabel(scale)
    fig.suptitle(raw["meta"].get("title", args.raw), fontsize=10)
    fig.tight_layout()
    fig.savefig(args.png, dpi=130)
    print(f"wrote {args.png}")


if __name__ == "__main__":
    main()
