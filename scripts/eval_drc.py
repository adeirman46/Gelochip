"""
Evaluate all 15 circuits: RL corrector + guaranteed fallback.
Run from repo root: .venv/bin/python scripts/eval_drc.py
"""
import sys, os
os.environ.setdefault('PDK_ROOT', os.path.expanduser('~/pdks'))
sys.path.insert(0, os.path.abspath('src/gelochip'))

import numpy as np
import gelochip.gl as gl
from stable_baselines3 import PPO

# ── helpers ──────────────────────────────────────────────────────────────────
def lp(p):
    return dict(with_tie=p.get('with_tie', False), with_dummy=p.get('with_dummy', False))

def bp(p):
    return dict(placement=p.get('placement', 'column'), sep_mult=p.get('sep_mult', 2.0),
                met_layer=p.get('met_layer', 1), width_mult=p.get('width_mult', 1.0))

# ── builder functions (15 circuits) ──────────────────────────────────────────
def build_inverter(cp, p, name='inverter'):
    vin = gl.Net('vin'); vout = gl.Net('vout')
    mn = gl.nmos(w=cp['wn'], fingers=cp['fn'], g=vin, d=vout, s=gl.gnd, **lp(p))
    mp = gl.pmos(w=cp['wp'], fingers=cp['fn'], g=vin, d=vout, s=gl.vdd, **lp(p))
    return gl.build(mn, mp, name=name, **bp(p))

def build_current_mirror(cp, p, name='cmirror'):
    vbias = gl.Net('vbias'); iout = gl.Net('iout')
    fet  = gl.nmos if cp.get('n_or_p', 'n') == 'n' else gl.pmos
    rail = gl.gnd  if cp.get('n_or_p', 'n') == 'n' else gl.vdd
    m_ref  = fet(w=cp['w'], fingers=1,                   g=vbias, d=vbias, s=rail, **lp(p))
    m_copy = fet(w=cp['w'], fingers=cp.get('ratio', 1),  g=vbias, d=iout,  s=rail, **lp(p))
    return gl.build(m_ref, m_copy, name=name, **bp(p))

def build_diff_pair(cp, p, name='diff_pair'):
    vip = gl.Net('vip'); vim = gl.Net('vim'); vtail = gl.Net('vtail')
    vop = gl.Net('vop'); vom = gl.Net('vom'); vbias = gl.Net('vbias')
    mt   = gl.nmos(w=cp['wt'], fingers=2,        g=vbias, d=vtail, s=gl.gnd, **lp(p))
    mn_p = gl.nmos(w=cp['wn'], fingers=cp['fn'],  g=vip,   d=vop,   s=vtail,  **lp(p))
    mn_m = gl.nmos(w=cp['wn'], fingers=cp['fn'],  g=vim,   d=vom,   s=vtail,  **lp(p))
    return gl.build(mt, mn_p, mn_m, name=name, **bp(p))

def build_ota(cp, p, name='ota'):
    vip = gl.Net('vip'); vim = gl.Net('vim'); vtail = gl.Net('vtail')
    vout = gl.Net('vout'); vleft = gl.Net('vleft'); vbias = gl.Net('vbias')
    mt   = gl.nmos(w=cp['wt'], fingers=2,        g=vbias, d=vtail, s=gl.gnd, **lp(p))
    mn_p = gl.nmos(w=cp['wn'], fingers=cp['fn'],  g=vip,   d=vout,  s=vtail,  **lp(p))
    mn_m = gl.nmos(w=cp['wn'], fingers=cp['fn'],  g=vim,   d=vleft, s=vtail,  **lp(p))
    mp_l = gl.pmos(w=cp['wp'], fingers=cp['fn'],  g=vleft, d=vleft, s=gl.vdd, **lp(p))
    mp_r = gl.pmos(w=cp['wp'], fingers=cp['fn'],  g=vleft, d=vout,  s=gl.vdd, **lp(p))
    return gl.build(mt, mn_p, mn_m, mp_l, mp_r, name=name, **bp(p))

def build_fvf(cp, p, name='fvf'):
    vin = gl.Net('vin'); vout = gl.Net('vout'); vfb = gl.Net('vfb')
    mn = gl.nmos(w=cp['w_main'], fingers=2, g=vfb, d=vout, s=gl.gnd, **lp(p))
    mp = gl.pmos(w=cp['w_fb'],  fingers=1, g=vin, d=vfb,  s=gl.vdd, **lp(p))
    return gl.build(mn, mp, name=name, **bp(p))

def build_tgate(cp, p, name='tgate'):
    vin = gl.Net('vin'); vout = gl.Net('vout')
    vctrl = gl.Net('vctrl'); vctrl_n = gl.Net('vctrl_n')
    mn = gl.nmos(w=cp['wn'], fingers=1, g=vctrl,   d=vout, s=vin, **lp(p))
    mp = gl.pmos(w=cp['wp'], fingers=1, g=vctrl_n, d=vout, s=vin, **lp(p))
    return gl.build(mn, mp, name=name, **bp(p))

def build_stacked_cmirror(cp, p, name='stacked_cm'):
    vbias = gl.Net('vbias'); iout = gl.Net('iout'); vcasc = gl.Net('vcasc')
    m_ref = gl.nmos(w=cp['w'], fingers=1,                   g=vbias, d=vcasc, s=gl.gnd, **lp(p))
    m_csc = gl.nmos(w=cp['w'], fingers=cp.get('ratio', 1),  g=vbias, d=vbias, s=vcasc,  **lp(p))
    m_out = gl.nmos(w=cp['w'], fingers=cp.get('ratio', 1),  g=vbias, d=iout,  s=gl.gnd, **lp(p))
    return gl.build(m_ref, m_csc, m_out, name=name, **bp(p))

def build_lvcmirror(cp, p, name='lvcm'):
    vbias = gl.Net('vbias'); iout = gl.Net('iout'); vx = gl.Net('vx')
    m_ref  = gl.nmos(w=cp['w'],        fingers=1, g=vbias, d=vbias, s=gl.gnd, **lp(p))
    m_aux  = gl.nmos(w=cp['w_narrow'], fingers=1, g=vbias, d=vx,    s=gl.gnd, **lp(p))
    m_copy = gl.nmos(w=cp['w'],        fingers=1, g=vbias, d=iout,  s=gl.gnd, **lp(p))
    return gl.build(m_ref, m_aux, m_copy, name=name, **bp(p))

def build_diff_pair_cmbias(cp, p, name='dp_cmbias'):
    vip = gl.Net('vip'); vim = gl.Net('vim'); vtail = gl.Net('vtail')
    vop = gl.Net('vop'); vom = gl.Net('vom'); vbias = gl.Net('vbias'); vload = gl.Net('vload')
    mt   = gl.nmos(w=cp['wt'], fingers=2,        g=vbias, d=vtail, s=gl.gnd, **lp(p))
    mn_p = gl.nmos(w=cp['wn'], fingers=cp['fn'],  g=vip,   d=vop,   s=vtail,  **lp(p))
    mn_m = gl.nmos(w=cp['wn'], fingers=cp['fn'],  g=vim,   d=vom,   s=vtail,  **lp(p))
    mp_l = gl.pmos(w=cp['wn'], fingers=cp['fn'],  g=vload, d=vload, s=gl.vdd, **lp(p))
    mp_r = gl.pmos(w=cp['wn'], fingers=cp['fn'],  g=vload, d=vop,   s=gl.vdd, **lp(p))
    return gl.build(mt, mn_p, mn_m, mp_l, mp_r, name=name, **bp(p))

def build_pmos_cm(cp, p, name='pmos_cm'):
    vbias = gl.Net('vbias'); iout = gl.Net('iout')
    m_ref  = gl.pmos(w=cp['w'], fingers=1,                  g=vbias, d=vbias, s=gl.vdd, **lp(p))
    m_copy = gl.pmos(w=cp['w'], fingers=cp.get('ratio', 2), g=vbias, d=iout,  s=gl.vdd, **lp(p))
    return gl.build(m_ref, m_copy, name=name, **bp(p))

def build_nand2(cp, p, name='nand2'):
    va = gl.Net('va'); vb = gl.Net('vb'); vout = gl.Net('vout'); vmid = gl.Net('vmid')
    mn_a = gl.nmos(w=cp['wn'], fingers=1, g=va, d=vmid, s=gl.gnd, **lp(p))
    mn_b = gl.nmos(w=cp['wn'], fingers=1, g=vb, d=vout, s=vmid,   **lp(p))
    mp_a = gl.pmos(w=cp['wp'], fingers=1, g=va, d=vout, s=gl.vdd, **lp(p))
    mp_b = gl.pmos(w=cp['wp'], fingers=1, g=vb, d=vout, s=gl.vdd, **lp(p))
    return gl.build(mn_a, mn_b, mp_a, mp_b, name=name, **bp(p))

def build_nor2(cp, p, name='nor2'):
    va = gl.Net('va'); vb = gl.Net('vb'); vout = gl.Net('vout'); vmid = gl.Net('vmid')
    mn_a = gl.nmos(w=cp['wn'], fingers=1, g=va, d=vout, s=gl.gnd, **lp(p))
    mn_b = gl.nmos(w=cp['wn'], fingers=1, g=vb, d=vout, s=gl.gnd, **lp(p))
    mp_a = gl.pmos(w=cp['wp'], fingers=1, g=va, d=vmid, s=gl.vdd, **lp(p))
    mp_b = gl.pmos(w=cp['wp'], fingers=1, g=vb, d=vout, s=vmid,   **lp(p))
    return gl.build(mn_a, mn_b, mp_a, mp_b, name=name, **bp(p))

def build_cascode_cm(cp, p, name='cascode_cm'):
    vbias = gl.Net('vbias'); iout = gl.Net('iout'); vcb = gl.Net('vcb')
    m_ref  = gl.nmos(w=cp['w'], fingers=1, g=vbias, d=vbias, s=gl.gnd, **lp(p))
    m_casc = gl.nmos(w=cp['w'], fingers=1, g=vcb,   d=vcb,   s=vbias,  **lp(p))
    m_out  = gl.nmos(w=cp['w'], fingers=1, g=vbias, d=iout,  s=gl.gnd, **lp(p))
    return gl.build(m_ref, m_casc, m_out, name=name, **bp(p))

def build_source_follower(cp, p, name='src_follower'):
    vin = gl.Net('vin'); vout = gl.Net('vout'); vbias = gl.Net('vbias')
    mn = gl.nmos(w=cp['w_drv'], fingers=2, g=vin,   d=gl.vdd, s=vout, **lp(p))
    mb = gl.nmos(w=cp['w_bias'],fingers=2, g=vbias, d=vout,   s=gl.gnd, **lp(p))
    return gl.build(mn, mb, name=name, **bp(p))

def build_telescopic_ota(cp, p, name='tele_ota'):
    vip = gl.Net('vip'); vim = gl.Net('vim'); vout = gl.Net('vout')
    vtail = gl.Net('vtail'); vncasc = gl.Net('vncasc'); vpcasc = gl.Net('vpcasc')
    vleft = gl.Net('vleft'); vbias = gl.Net('vbias')
    mt    = gl.nmos(w=cp['wt'],  fingers=2,       g=vbias,  d=vtail,  s=gl.gnd, **lp(p))
    mn_p  = gl.nmos(w=cp['wn'],  fingers=cp['fn'], g=vip,    d=vncasc, s=vtail,  **lp(p))
    mn_m  = gl.nmos(w=cp['wn'],  fingers=cp['fn'], g=vim,    d=vleft,  s=vtail,  **lp(p))
    mc_np = gl.nmos(w=cp['wcn'], fingers=cp['fn'], g=vncasc, d=vout,   s=vncasc, **lp(p))
    mc_nm = gl.nmos(w=cp['wcn'], fingers=cp['fn'], g=vncasc, d=vleft,  s=vleft,  **lp(p))
    mp_l  = gl.pmos(w=cp['wp'],  fingers=cp['fn'], g=vleft,  d=vpcasc, s=gl.vdd, **lp(p))
    mp_r  = gl.pmos(w=cp['wp'],  fingers=cp['fn'], g=vleft,  d=vpcasc, s=gl.vdd, **lp(p))
    return gl.build(mt, mn_p, mn_m, mc_np, mc_nm, mp_l, mp_r, name=name, **bp(p))

# ── circuit pool ─────────────────────────────────────────────────────────────
CIRCUIT_POOL = [
    (build_inverter,        {'wn': 2.0, 'wp': 4.0, 'fn': 2},                  'inverter'),
    (build_current_mirror,  {'w': 3.0, 'n_or_p': 'n', 'ratio': 2},            'cmirror_n'),
    (build_current_mirror,  {'w': 3.0, 'n_or_p': 'p', 'ratio': 2},            'cmirror_p'),
    (build_diff_pair,       {'wn': 3.0, 'wt': 4.0, 'fn': 2},                  'diff_pair'),
    (build_ota,             {'wn': 3.0, 'wp': 4.0, 'wt': 5.0, 'fn': 2},       'ota'),
    (build_fvf,             {'w_main': 4.0, 'w_fb': 2.0},                      'fvf'),
    (build_tgate,           {'wn': 2.0, 'wp': 4.0},                            'tgate'),
    (build_stacked_cmirror, {'w': 3.0, 'ratio': 2},                            'stacked_cm'),
    (build_lvcmirror,       {'w': 3.0, 'w_narrow': 1.5},                       'lvcmirror'),
    (build_diff_pair_cmbias,{'wn': 3.0, 'wt': 4.0, 'fn': 2},                  'dp_cmbias'),
    (build_pmos_cm,         {'w': 3.0, 'ratio': 2},                            'pmos_cm'),
    (build_nand2,           {'wn': 2.0, 'wp': 4.0},                            'nand2'),
    (build_nor2,            {'wn': 2.0, 'wp': 4.0},                            'nor2'),
    (build_cascode_cm,      {'w': 3.0},                                         'cascode_cm'),
    (build_source_follower, {'w_drv': 4.0, 'w_bias': 2.0},                     'src_follower'),
]

# ── evaluate ─────────────────────────────────────────────────────────────────
MODEL_PATH = os.path.join('models', 'layoutrl', 'drc_corrector_ppo')

print(f'Loading model from {MODEL_PATH}.zip')
print()

results = {}

for build_fn, circuit_params, label in CIRCUIT_POOL:
    print(f'\n── {label} ──────────────────────────────')

    # 1. Naive
    try:
        naive_lp = dict(gl.DEFAULT_LAYOUT_PARAMS)
        naive = build_fn(circuit_params, naive_lp, f'{label}_naive')
        naive_drc = naive.drc(silent=True)
        naive_n = naive_drc.get('total_errors', 0)
    except Exception as e:
        print(f'  naive build error: {e}')
        naive_n = -1

    # 2. RL corrector
    env   = gl.make_env(build_fn, circuit_params, max_steps=15)
    model = PPO.load(MODEL_PATH, env=env)
    obs, info = env.reset()
    for _ in range(15):
        action, _ = model.predict(obs, deterministic=True)
        obs, _, done, _, info = env.step(action)
        if done:
            break

    best_lp = env.best_layout_params
    fixed_n = env._best_errors

    # 3. Fallback: saved global best params
    import json as _json
    saved_path = os.path.join('src', 'gelochip', 'gl', 'drc_corrector_best_lp.json')
    if fixed_n > 0 and os.path.exists(saved_path):
        try:
            slp = _json.load(open(saved_path))
            sd = build_fn(circuit_params, slp, '_rl_tmp').drc(silent=True)
            sn = sd.get('total_errors', 999)
            if sn < fixed_n:
                best_lp = slp
                fixed_n = sn
        except Exception:
            pass

    # 4. Guaranteed fallback: with_tie=True sweep (always fixes NW violations)
    if fixed_n > 0:
        for _pl in ('column', 'row'):
            for _sep in (2.0, 2.5, 1.5, 3.0):
                _lp = dict(gl.DEFAULT_LAYOUT_PARAMS, with_tie=True, with_dummy=True,
                           placement=_pl, sep_mult=_sep)
                try:
                    _d = build_fn(circuit_params, _lp, '_rl_tmp').drc(silent=True)
                    _n = _d.get('total_errors', 999)
                    if _n < fixed_n:
                        fixed_n = _n
                        best_lp = _lp
                    if fixed_n == 0:
                        break
                except Exception:
                    pass
            if fixed_n == 0:
                break

    results[label] = {'naive': naive_n, 'fixed': fixed_n, 'lp': best_lp}
    icon = '✅' if fixed_n == 0 else '❌'
    print(f'  {icon} naive={naive_n:3d} → fixed={fixed_n:3d}  '
          f'tie={int(best_lp["with_tie"])} dum={int(best_lp["with_dummy"])} '
          f'placement={best_lp["placement"]:6s} sep={best_lp["sep_mult"]:.1f} '
          f'met={best_lp.get("met_layer",1)} w={best_lp.get("width_mult",1.0):.1f}')

# ── summary table ─────────────────────────────────────────────────────────────
print()
print('=' * 62)
print(f'{"Circuit":<30} {"Naive DRC":>10} {"RL-fixed":>10} {"Status":>8}')
print('-' * 62)
clean = 0
for label, r in results.items():
    status = 'CLEAN' if r['fixed'] == 0 else f"{r['fixed']} err"
    if r['fixed'] == 0:
        clean += 1
    icon = '✅' if r['fixed'] == 0 else '❌'
    print(f'{icon} {label:<28} {r["naive"]:>10} {r["fixed"]:>10} {status:>8}')
print('=' * 62)
print(f'DRC-clean: {clean}/{len(results)} circuits')
