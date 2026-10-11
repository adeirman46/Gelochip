"""
AnoaChip on-chip passives — reference generators the layout agent studies + adapts.

Why this exists: glayout ships FET / BJT / MIMcap / resistor / guardring / via
primitives, but **no inductor** — and gdsfactory's `spiral_*` components are
PHOTONIC waveguide spirals, not RF metal inductors with the right PDK metal
stack. So an on-chip inductor has to be generated. This module provides:

  • `square_spiral_inductor(pdk, ...)`  — a parametric planar square spiral on the
    top thick metal + an underpass on a lower metal (via-stacked crossover),
    with reasonable default dimensions and a Mohan current-sheet inductance
    estimate. It returns a glayout/gdsfactory `Component` with labelled ports.

  • `estimate_L_nH(...)`                 — the Mohan/Wheeler inductance formula so
    the agent can size the spiral to a target inductance.

  • sizing guidance (module docstring + INDUCTOR_NOTE) the knowledge store seeds.

IMPORTANT design guidance the agent follows (see INDUCTOR_NOTE):
  A real few-nH passive spiral on gf180 is LARGE (~100–300 µm outer). When area
  matters, prefer a **gyrator-C active inductor** (2–3 transistors + a bias) which
  glayout can lay out directly with its FET primitives — transistor-sized, tunable,
  no custom geometry. Only draw a passive spiral when a true passive / high linearity
  is required (matching network, VCO tank, degeneration).
"""
from __future__ import annotations

import math
from typing import Tuple

# Vacuum permeability (H/m)
_MU0 = 4e-7 * math.pi

# Mohan "current sheet" coefficients per geometry (Mohan et al., JSSC 1999).
#   L = (c1 · µ0 · n² · d_avg / 2) · (ln(c2/rho) + c3·rho + c4·rho²)
#   d_avg = (d_out + d_in)/2 ;  rho = (d_out - d_in)/(d_out + d_in)  (fill ratio)
_MOHAN = {
    "square":   (1.27, 2.07, 0.18, 0.13),
    "hexagon":  (1.09, 2.23, 0.00, 0.17),
    "octagon":  (1.07, 2.29, 0.00, 0.19),
}


def estimate_L_nH(n_turns: float, d_out_um: float, d_in_um: float,
                  shape: str = "square") -> float:
    """Mohan current-sheet estimate of a planar spiral's inductance, in nH.
    d_out/d_in are the outer/inner side length (µm). Good to ~10% for n≥2."""
    c1, c2, c3, c4 = _MOHAN.get(shape, _MOHAN["square"])
    d_avg = (d_out_um + d_in_um) / 2e6           # µm → m
    rho = (d_out_um - d_in_um) / (d_out_um + d_in_um) if (d_out_um + d_in_um) else 0.0
    rho = max(rho, 1e-3)
    L = (c1 * _MU0 * (n_turns ** 2) * d_avg / 2.0) * \
        (math.log(c2 / rho) + c3 * rho + c4 * rho * rho)
    return L * 1e9                                # H → nH


def spiral_dims_for_L(target_nH: float, n_turns: int = 3, width_um: float = 8.0,
                      space_um: float = 3.0, shape: str = "square") -> dict:
    """Pick a reasonable outer size (µm) for a target inductance by solving the
    Mohan estimate for d_out at a fixed turn count / metal width / spacing.
    Returns {d_out_um, d_in_um, n_turns, width_um, space_um, est_nH}."""
    pitch = width_um + space_um
    # binary-search d_out so estimate_L ≈ target
    lo, hi = 30.0, 600.0
    for _ in range(40):
        d_out = 0.5 * (lo + hi)
        d_in = max(d_out - 2 * n_turns * pitch, 10.0)
        L = estimate_L_nH(n_turns, d_out, d_in, shape)
        if L < target_nH:
            lo = d_out
        else:
            hi = d_out
    d_out = round(0.5 * (lo + hi), 1)
    d_in = round(max(d_out - 2 * n_turns * pitch, 10.0), 1)
    return {"d_out_um": d_out, "d_in_um": d_in, "n_turns": n_turns,
            "width_um": width_um, "space_um": space_um,
            "est_nH": round(estimate_L_nH(n_turns, d_out, d_in, shape), 3)}


def square_spiral_inductor(pdk, target_nH: float = 2.0, n_turns: int = 3,
                           width_um: float = 8.0, space_um: float = 3.0,
                           top_glayer: str = "met5", underpass_glayer: str = "met4"):
    """A parametric planar SQUARE spiral inductor as a glayout/gdsfactory Component.

    Geometry: `n_turns` concentric square rings on `top_glayer` (the thickest top
    metal for the best Q), connected turn-to-turn, with the inner terminal brought
    out under the winding on `underpass_glayer` (via-stacked crossover). Ports
    `P1`/`P2` are added + LABELLED so LVS/PEX can see them.

    Dimensions are sized to `target_nH` (Mohan estimate) with sane metal width /
    spacing. Returns the Component. Requires gdstk + glayout's Component.
    """
    import gdstk
    from glayout.backend import Component

    dims = spiral_dims_for_L(target_nH, n_turns, width_um, space_um)
    d_out = dims["d_out_um"]
    pitch = width_um + space_um

    comp = Component(name=f"ind_{target_nH:g}nH")
    try:
        layer = pdk.get_glayer(top_glayer)          # (layer, datatype) tuple
    except Exception:  # noqa: BLE001
        layer = (71, 20)                            # fallback metal layer

    # Build the spiral centreline as a polyline, then give it width → a path.
    # Start at the outer top-left, wind inward clockwise; each turn shrinks by pitch.
    pts = []
    half = d_out / 2.0
    x, y = -half, half
    step = 0
    for _t in range(n_turns):
        pts += [(x, y), (half - step, y)]           # →  top edge
        x = half - step
        pts += [(x, -half + step)]                  # ↓  right edge
        y = -half + step
        pts += [(-half + step + pitch, y)]          # ←  bottom edge (leave a gap for the next turn)
        x = -half + step + pitch
        step += pitch
        pts += [(x, half - step)]                   # ↑  left edge
        y = half - step
    fp = gdstk.FlexPath([(px, py) for px, py in pts], width_um,
                        layer=layer[0], datatype=layer[1], simple_path=True)
    comp.add(fp)

    # underpass: a short segment on the lower metal bringing the inner end out
    try:
        u = pdk.get_glayer(underpass_glayer)
    except Exception:  # noqa: BLE001
        u = (69, 20)
    inner = -half + step
    comp.add(gdstk.rectangle((inner, -width_um / 2), (half, width_um / 2),
                             layer=u[0], datatype=u[1]))

    # ports P1 (outer) + P2 (inner via underpass), with text LABELS (LVS matches by label)
    for name, (lx, ly), lyr in (("P1", (-half, half), layer), ("P2", (half, 0.0), u)):
        try:
            comp.add_port(name=name, center=(lx, ly), width=width_um,
                          orientation=0, layer=lyr)
        except Exception:  # noqa: BLE001
            pass
        comp.add(gdstk.Label(name, (lx, ly), layer=lyr[0], texttype=lyr[1]))

    comp.info["inductor"] = {"target_nH": target_nH, **dims,
                             "top_glayer": top_glayer, "underpass_glayer": underpass_glayer}
    return comp


# ---- guidance seeded into the knowledge store ------------------------------- #
INDUCTOR_NOTE = (
    "ON-CHIP INDUCTOR — glayout has NO inductor primitive, and gdsfactory's spiral_* "
    "components are PHOTONIC waveguides (not RF metal inductors). Options, smallest first:\n"
    "1) GYRATOR-C ACTIVE INDUCTOR (preferred when area-constrained): synthesize the "
    "inductance from 2-3 transistors + a bias (a transconductor loop). glayout lays this out "
    "directly with nmos/pmos + routing — transistor-sized (µm²), tunable, no custom geometry. "
    "Use it for LNA/mixer loads, active filters, phase shift. Trade-off: adds noise/power and "
    "needs headroom.\n"
    "2) PASSIVE SPIRAL (when a true passive is required — matching, VCO tank, source "
    "degeneration): use anoa_chip.passives.square_spiral_inductor(pdk, target_nH=...). It sizes "
    "a planar square spiral on the top thick metal (met5) with an underpass on met4, and adds "
    "LABELLED ports P1/P2. A ~1-2 nH spiral is ~80-200 µm across on gf180 — plan the floorplan "
    "for it. Fewer turns / stacked metals / higher operating frequency all shrink it.\n"
    "3) MEANDER (sub-nH, compact, low Q) for tiny series inductance.\n"
    "Estimate/size with estimate_L_nH() / spiral_dims_for_L() (Mohan current-sheet formula). "
    "ALWAYS label the two terminals so LVS/PEX see them."
)

MIMCAP_NOTE = (
    "MIMCAP — glayout HAS a mimcap primitive: `from glayout.primitives.mimcap import mimcap`; "
    "`cap = mimcap(pdk, size=(W_um, L_um))` builds a metal-insulator-metal cap of the given "
    "capmet area, with ports `top_met_*` (edges of the metal ABOVE capmet) and `bottom_met_*` "
    "(edges of the metal BELOW). It attaches its own comp.info['netlist'] (an X-instance of the "
    "PDK mimcap subckt). Combine it into a design like the glayout opamp tutorial does for Miller "
    "compensation:\n"
    "  cref = comp << mimcap(pdk, size=(cc_w, cc_l))\n"
    "  # place it, then ROUTE both plates to the transistor terminals:\n"
    "  comp << smart_route(pdk, cref.ports['top_met_E'], m1.ports['drain_E'], comp, comp)\n"
    "  comp << smart_route(pdk, cref.ports['bottom_met_W'], m2.ports['gate_W'], comp, comp)\n"
    "Use `mimcap_array(pdk, rows, cols, size)` for a bigger cap (it internally straight_routes "
    "the array plates together). Size the cap from the config (cc_pf); on gf180 the capmet "
    "density is ~1-2 fF/µm² so a 1 pF cap is a few hundred µm² — account for it in the floorplan. "
    "Route mimcap plates with c_route/L_route/straight_route+via_stack like any other net, and "
    "expose + LABEL any plate that becomes an external port."
)
