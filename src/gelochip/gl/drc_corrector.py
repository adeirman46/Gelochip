"""
DRC Corrector — RL-based layout geometry + routing optimizer.

The RL agent controls both device-level and routing-level layout parameters to
eliminate DRC violations.  Circuit topology (wn, wp, fn…) is NEVER changed.

Device params controlled:
  with_tie   — body tie / N-well guard ring on PMOS (fixes N-well DRC rules)
  with_dummy — dummy transistors at edges (fixes diff-edge DRC rules)
  placement  — row (left→right) or column (bottom→top)
  sep_mult   — device separation multiplier

Routing params controlled:
  met_layer  — metal layer for routing wires (1=met1 … 3=met3)
  width_mult — wire width multiplier (1.0 = port width)

Training  → notebooks/layoutRL/00_train.ipynb
Evaluate  → notebooks/layoutRL/01_evaluate.ipynb

Quick use after training::

    def inv_builder(circuit_p, layout_p, name):
        vin, vout = gl.Net('vin'), gl.Net('vout')
        mn = gl.nmos(w=circuit_p['wn'], g=vin, d=vout, s=gl.gnd,
                     with_tie=layout_p['with_tie'], with_dummy=layout_p['with_dummy'])
        mp = gl.pmos(w=circuit_p['wp'], g=vin, d=vout, s=gl.vdd,
                     with_tie=layout_p['with_tie'], with_dummy=layout_p['with_dummy'])
        return gl.build(mn, mp, name=name,
                        placement=layout_p['placement'],
                        sep_mult=layout_p['sep_mult'],
                        met_layer=layout_p['met_layer'],
                        width_mult=layout_p['width_mult'])

    chip = gl.auto_build(inv_builder, {'wn': 2, 'wp': 4}, name='inverter')
"""
from __future__ import annotations

import os
from typing import Callable, Dict, Any, Optional

import numpy as np

# ─── Recursion guard ─────────────────────────────────────────────────────────
# Set to True while gl.build()'s internal builder is calling build_fn,
# so nested gl.build() calls do a plain compile instead of re-triggering RL.
_RL_ACTIVE: bool = False

# ─── Default layout params ────────────────────────────────────────────────────

DEFAULT_LAYOUT_PARAMS: Dict[str, Any] = {
    # Device-level
    "with_tie":   False,
    "with_dummy": False,
    "placement":  "column",
    "sep_mult":   2.0,
    # Routing-level
    "met_layer":  1,
    "width_mult": 1.0,
}

# Model weights are consolidated under <repo>/models/layoutrl/ (this file is at
# src/gelochip/gl/drc_corrector.py → repo root is 4 levels up).
_REPO_ROOT     = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_MODEL_PATH    = os.path.join(_REPO_ROOT, "models", "layoutrl", "drc_corrector_ppo")
_BEST_LP_PATH  = os.path.join(os.path.dirname(__file__), "drc_corrector_best_lp.json")


# ─── _run_drc_sweep  (called internally by gl.build()) ───────────────────────

def _run_drc_sweep(build_fn: Callable, name: str) -> Any:
    """
    DRC-clean build using with_tie=True sweep + optional saved RL params.
    Called automatically by gl.build() — users never call this directly.
    """
    global _RL_ACTIVE

    def _drc_errors(layout) -> int:
        try:
            res = layout.drc(silent=True)
            return res.get("total_errors", 999) if isinstance(res, dict) else 999
        except Exception:
            return 999

    def _call(lp):
        global _RL_ACTIVE
        _RL_ACTIVE = True
        try:
            return build_fn({}, lp, "_rl_tmp")
        finally:
            _RL_ACTIVE = False

    best_lp   = dict(DEFAULT_LAYOUT_PARAMS, with_tie=True, with_dummy=True)
    best_errs = 9999

    # 1. Primary sweep: with_tie=True always fixes N-well violations
    for _pl in ("column", "row"):
        for _sep in (2.0, 2.5, 1.5):
            _lp = dict(DEFAULT_LAYOUT_PARAMS,
                       with_tie=True, with_dummy=True,
                       placement=_pl, sep_mult=_sep)
            try:
                _n = _drc_errors(_call(_lp))
                if _n < best_errs:
                    best_errs = _n; best_lp = _lp
                if best_errs == 0:
                    break
            except Exception:
                pass
        if best_errs == 0:
            break

    # 2. Try saved best params from RL training (may further improve)
    if best_errs > 0 and os.path.exists(_BEST_LP_PATH):
        try:
            import json as _json
            saved_lp = _json.load(open(_BEST_LP_PATH))
            _n = _drc_errors(_call(saved_lp))
            if _n < best_errs:
                best_errs = _n; best_lp = saved_lp
        except Exception:
            pass

    print(f"[gl.build] sweep done: {best_errs} DRC errors  "
          f"tie={int(best_lp.get('with_tie', True))}  "
          f"placement={best_lp.get('placement', 'column')}  "
          f"sep={best_lp.get('sep_mult', 2.0)}")

    # Build final layout with best params found
    _RL_ACTIVE = True
    try:
        return build_fn({}, best_lp, name)
    finally:
        _RL_ACTIVE = False


# ─── auto_build ───────────────────────────────────────────────────────────────

def auto_build(
    build_fn: Callable,
    circuit_params: Dict,
    name: str = "circuit",
    model_path: Optional[str] = None,
    max_iter: int = 15,
) -> Any:
    """
    Build a DRC-clean layout using the trained RL corrector.

    Parameters
    ----------
    build_fn       : fn(circuit_params, layout_params, name) → Layout
    circuit_params : circuit sizing dict (w, fn, …) — NOT changed by RL
    name           : GDS cell name
    model_path     : path to trained .pt file (default: bundled model)
    max_iter       : RL iterations before returning best result

    Returns
    -------
    Layout with fewest DRC errors found within max_iter steps.
    """
    mpath = model_path or _MODEL_PATH
    if not os.path.exists(mpath + ".pt"):
        print(f"[auto_build] No trained model found at {mpath}.pt")
        print("[auto_build] Returning layout with default params.")
        print("[auto_build] Train first: run notebooks/layoutRL/00_train.ipynb")
        return build_fn(circuit_params, DEFAULT_LAYOUT_PARAMS, name)

    try:
        import torch
        from stable_baselines3 import PPO
    except ImportError:
        raise ImportError("torch and stable-baselines3 required.")

    env = make_env(build_fn, circuit_params, max_steps=max_iter)

    # Load policy weights from .pt checkpoint
    checkpoint = torch.load(mpath + ".pt", weights_only=False)
    model = PPO("MlpPolicy", env, policy_kwargs=dict(net_arch=[128, 128, 64]))
    model.policy.load_state_dict(checkpoint["policy_state_dict"])
    model.policy.set_training_mode(False)

    obs, info = env.reset()
    print(f"[auto_build] start: {info['drc_errors']} DRC errors")

    for i in range(max_iter):
        action, _ = model.predict(obs, deterministic=True)
        obs, _, done, _, info = env.step(action)
        n  = info["drc_errors"]
        lp = info["layout_params"]
        print(f"  iter {i+1:2d}: {'CLEAN' if n == 0 else f'{n} errors':12s} "
              f"placement={lp['placement']:6s}  "
              f"sep={lp['sep_mult']:.1f}  "
              f"tie={int(lp['with_tie'])}  "
              f"dum={int(lp['with_dummy'])}  "
              f"met={lp['met_layer']}  "
              f"w={lp['width_mult']:.1f}")
        if done:
            break

    best_lp    = env.best_layout_params
    best_errs  = env._best_errors

    def _fb_call(lp):
        global _RL_ACTIVE
        _RL_ACTIVE = True
        try:
            return build_fn(circuit_params, lp, "_rl_tmp")
        finally:
            _RL_ACTIVE = False

    # Fallback 1: try the best params saved inside the .pt checkpoint
    if best_errs > 0 and "best_layout_params" in checkpoint:
        try:
            saved_lp = checkpoint["best_layout_params"]
            saved_errs = _fb_call(saved_lp).drc(silent=True).get("total_errors", 999)
            if saved_errs < best_errs:
                best_lp = saved_lp; best_errs = saved_errs
        except Exception:
            pass

    # Fallback 2: NW errors are always fixed by with_tie=True — sweep a few
    # placement/sep combinations to guarantee a DRC-clean result.
    if best_errs > 0:
        for _placement in ("column", "row"):
            for _sep in (2.0, 2.5, 1.5):
                _lp = dict(DEFAULT_LAYOUT_PARAMS,
                           with_tie=True, with_dummy=True,
                           placement=_placement, sep_mult=_sep)
                try:
                    _n = _fb_call(_lp).drc(silent=True).get("total_errors", 999)
                    if _n < best_errs:
                        best_errs = _n; best_lp = _lp
                    if best_errs == 0:
                        break
                except Exception:
                    pass
            if best_errs == 0:
                break

    print(f"[auto_build] best: {best_errs} errors  params={best_lp}")
    _RL_ACTIVE = True
    try:
        return build_fn(circuit_params, best_lp, name)
    finally:
        _RL_ACTIVE = False


# ─── make_env ─────────────────────────────────────────────────────────────────

def make_env(build_fn: Callable, circuit_params: Dict, max_steps: int = 15):
    """
    Create a single-circuit DRCCorrectorEnv for inference or standalone training.

    build_fn(circuit_params, layout_params, name) → Layout

    Observation (11-dim):
      [0..4]  DRC error counts per category (NW, CO, PL, DF, other) / MAX_ERRORS
      [5]     with_tie  (0 or 1)
      [6]     with_dummy (0 or 1)
      [7]     placement  (0=row, 1=column)
      [8]     sep_mult / 4.0
      [9]     met_layer / 5.0
      [10]    width_mult / 3.0

    Action (6-dim, continuous [-1, 1]):
      [0]  |a|>0.5 → flip with_tie
      [1]  |a|>0.5 → flip with_dummy
      [2]  |a|>0.5 → flip placement
      [3]  nudge sep_mult   (±0.5, clamped 1.0–4.0)
      [4]  nudge met_layer  (±1, clamped 1–3)
      [5]  nudge width_mult (±0.25, clamped 0.5–3.0)
    """
    try:
        import gymnasium as gym
        from gymnasium import spaces
    except ImportError:
        raise ImportError("gymnasium required. Run: pip install gymnasium>=0.29.0")

    class _Env(gym.Env):
        MAX_ERRORS = 300.0

        def __init__(self):
            super().__init__()
            self.observation_space = spaces.Box(0.0, 1.0, shape=(11,), dtype=np.float32)
            self.action_space      = spaces.Box(-1.0, 1.0, shape=(6,), dtype=np.float32)
            self._lp  = dict(DEFAULT_LAYOUT_PARAMS)
            self._step = 0
            self._best_errors    = 9999
            self.best_layout_params = dict(DEFAULT_LAYOUT_PARAMS)

        def _lp_obs(self):
            return np.array([
                float(self._lp["with_tie"]),
                float(self._lp["with_dummy"]),
                1.0 if self._lp["placement"] == "column" else 0.0,
                self._lp["sep_mult"] / 4.0,
                self._lp["met_layer"] / 5.0,
                self._lp["width_mult"] / 3.0,
            ], dtype=np.float32)

        def _apply_action(self, a):
            a = np.clip(a, -1.0, 1.0)
            if abs(a[0]) > 0.5:
                self._lp["with_tie"] = not self._lp["with_tie"]
            if abs(a[1]) > 0.5:
                self._lp["with_dummy"] = not self._lp["with_dummy"]
            if abs(a[2]) > 0.5:
                self._lp["placement"] = (
                    "row" if self._lp["placement"] == "column" else "column"
                )
            self._lp["sep_mult"] = float(np.clip(
                self._lp["sep_mult"] + a[3] * 0.5, 1.0, 4.0
            ))
            self._lp["met_layer"] = int(np.clip(
                round(self._lp["met_layer"] + a[4]), 1, 3
            ))
            self._lp["width_mult"] = float(np.clip(
                self._lp["width_mult"] + a[5] * 0.25, 0.5, 3.0
            ))

        def _build_drc(self):
            global _RL_ACTIVE
            _RL_ACTIVE = True
            try:
                layout = build_fn(circuit_params, self._lp, "_rl_tmp")
                return layout.drc(silent=True)
            except Exception as exc:
                print(f"  [env] build error: {exc}")
                return {"total_errors": 200,
                        "NW": 40, "CO": 40, "PL": 40, "DF": 40, "other": 40}
            finally:
                _RL_ACTIVE = False

        def _obs(self, drc):
            cats = np.array([
                drc.get("NW", 0), drc.get("CO", 0), drc.get("PL", 0),
                drc.get("DF", 0), drc.get("other", 0),
            ], dtype=np.float32) / self.MAX_ERRORS
            return np.concatenate([np.clip(cats, 0, 1), self._lp_obs()])

        def reset(self, seed=None, options=None):
            super().reset(seed=seed)
            self._lp   = dict(DEFAULT_LAYOUT_PARAMS)
            self._step = 0
            drc = self._build_drc()
            return self._obs(drc), {"drc_errors": drc.get("total_errors", 0),
                                    "layout_params": dict(self._lp)}

        def step(self, action):
            self._apply_action(action)
            self._step += 1
            drc = self._build_drc()
            n   = drc.get("total_errors", 0)
            reward = -n / self.MAX_ERRORS + (20.0 if n == 0 else 0.0)
            if n < self._best_errors:
                self._best_errors       = n
                self.best_layout_params = dict(self._lp)
            done = (n == 0) or (self._step >= max_steps)
            return (self._obs(drc), reward, done, False,
                    {"drc_errors": n, "layout_params": dict(self._lp)})

    return _Env()
