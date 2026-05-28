"""
gelochip.gl  —  PyTorch-style analog layout API.

Hierarchy (simple → advanced)
══════════════════════════════

Level 1 — Functional (quickest)
────────────────────────────────
    import gelochip.gl as gl

    vin, vout = gl.Net('vin'), gl.Net('vout')
    mp = gl.pmos(w=4, fingers=2, g=vin, d=vout, s=gl.vdd)
    mn = gl.nmos(w=2, fingers=2, g=vin, d=vout, s=gl.gnd)
    chip = gl.build(mp, mn, name='inverter')
    chip.show()   chip.drc()   chip.lvs()   chip.sim()

Level 2 — Module (like nn.Module)
──────────────────────────────────
    class Inverter(gl.Module):
        def __init__(self, wp=4.0, wn=2.0):
            super().__init__(gl.gf180)
            self.wp, self.wn = wp, wn

        def layout(self):
            vin  = self.pin('vin')
            vout = self.pin('vout')
            gl.pmos(w=self.wp, fingers=2, g=vin, d=vout, s=gl.vdd)
            gl.nmos(w=self.wn, fingers=2, g=vin, d=vout, s=gl.gnd)

    chip = Inverter(wp=4, wn=2).build()

Level 3 — Pre-built Cells (best-practice placement/routing built in)
──────────────────────────────────────────────────────────────────────
    class OTA(gl.Module):
        def layout(self):
            vip, vim = self.pin('vip'), self.pin('vim')
            vbias    = self.pin('vbias')
            vout     = self.pin('vout')
            vtail    = gl.Net('vtail')
            vleft    = gl.Net('vleft')

            # Tail current source (raw NMOS)
            gl.nmos(w=4, fingers=2, g=vbias, d=vtail, s=gl.gnd)

            # Diff pair (uses common-centroid ABBA placement internally)
            gl.diff_pair(w=3, fingers=4, vp=vip, vm=vim,
                         vtail=vtail, vout_p=vout, vout_m=vleft)

            # PMOS load mirror (uses interdigitized placement internally)
            gl.current_mirror(w=4, n_or_p='p', ref=vleft, copy=vout, rail=gl.vdd)

    chip = OTA().build()

Level 4 — Sequential / Parallel
─────────────────────────────────
    class TwoStage(gl.Sequential):
        def __init__(self):
            super().__init__(Stage1(), Stage2(), pdk=gl.gf180)

    pair = gl.Parallel(
        gl.nmos(w=3, fingers=4, g=vp, s=vtail, d=voutp),
        gl.nmos(w=3, fingers=4, g=vm, s=vtail, d=voutn),
    )

Level 5 — Raw escape hatch (full glayout power)
─────────────────────────────────────────────────
    from glayout.cells.composite.fvf_based_ota.n_block import n_block
    nb_comp = n_block(pdk, input_pair_params=(4, 2))
    nb = gl.raw(nb_comp,
                connections={'inp': vip, 'inn': vim, 'gnd': gl.gnd},
                port_map={'inp': 'gate_inA', 'inn': 'gate_inB'})

Power rails  →  gl.vdd  /  gl.gnd  (also gl.vcc / gl.vss as aliases)
"""

# ── Nets & power rails ────────────────────────────────────────────────────────
from gelochip.gl.net import Net, vdd, vcc, gnd, vss

# ── Primitive transistors ─────────────────────────────────────────────────────
from gelochip.gl.primitives import nmos, pmos, build

# ── Pre-built cells (optimal placement + routing already done) ────────────────
from gelochip.gl.cells import (
    current_mirror,
    diff_pair,
    fvf,
    transmission_gate,
    stacked_cmirror,
    mimcap,
    mimcap_array,
    res,
    via,
    bjt,
    raw,
)

# ── Module / containers ───────────────────────────────────────────────────────
from gelochip.gl.module import Module, Sequential, Parallel, Layout

# ── DRC corrector (RL runs inside gl.build() automatically) ──────────────────
from gelochip.gl.drc_corrector import make_env, DEFAULT_LAYOUT_PARAMS

# ── Device (for isinstance checks / advanced use) ─────────────────────────────
from gelochip.gl.device import Device

# ── PDK ───────────────────────────────────────────────────────────────────────

def _load_gf180():
    import os
    os.environ.setdefault("PDK_ROOT", os.path.expanduser("~/pdks"))
    from glayout.pdk.gf180_mapped import gf180_mapped_pdk
    return gf180_mapped_pdk


try:
    gf180 = _load_gf180()
except Exception:
    gf180 = None  # PDK not installed — pass pdk= explicitly


def set_pdk(pdk) -> None:
    """Set a process-wide default PDK (avoids passing pdk= to every call)."""
    import gelochip.gl as _gl
    _gl.gf180 = pdk   # update module-level name used by _resolve_pdk


def reload() -> None:
    """
    Force-reload all gelochip.gl submodules and refresh this module's namespace.

    Call this in Jupyter after editing gelochip source code — avoids full
    kernel restart::

        import gelochip.gl as gl
        gl.reload()   # picks up latest code instantly
    """
    import importlib as _il, sys as _sys
    _order = [
        "gelochip.gl.net",
        "gelochip.gl.device",
        "gelochip.gl.drc_corrector",
        "gelochip.gl.verify",
        "gelochip.gl.compiler",
        "gelochip.gl.primitives",
        "gelochip.gl.cells",
        "gelochip.gl.circuit",
        "gelochip.gl.blocks",
        "gelochip.gl.module",
        "gelochip.gl",
    ]
    for _m in _order:
        if _m in _sys.modules:
            try:
                _il.reload(_sys.modules[_m])
            except Exception as _e:
                print(f"[gl.reload] warning: {_m}: {_e}")
    # rebind public names so gl.nmos etc. point to fresh functions
    global nmos, pmos, build, make_env, DEFAULT_LAYOUT_PARAMS
    from gelochip.gl.primitives import nmos, pmos, build
    from gelochip.gl.drc_corrector import make_env, DEFAULT_LAYOUT_PARAMS
    print("[gl] reloaded — DRC sweep active (with_tie=True by default)")


# ── Public API ────────────────────────────────────────────────────────────────

__all__ = [
    # nets / rails
    "Net", "vdd", "vcc", "gnd", "vss",
    # primitives
    "nmos", "pmos", "build",
    # cells
    "current_mirror", "diff_pair", "fvf", "transmission_gate",
    "stacked_cmirror", "mimcap", "mimcap_array", "res", "via", "bjt",
    # advanced
    "raw",
    # module / composition
    "Module", "Sequential", "Parallel", "Layout",
    # device
    "Device",
    # pdk
    "gf180", "set_pdk", "reload",
    # RL corrector (auto_build removed — RL now runs inside gl.build() automatically)
    "make_env", "DEFAULT_LAYOUT_PARAMS",
]
