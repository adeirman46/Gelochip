"""
Fast DRC evaluation: test with_tie=True guaranteed fallback for all 15 circuits.
Run from repo root: .venv/bin/python scripts/eval_fast.py
"""
import sys, os
os.environ.setdefault('PDK_ROOT', os.path.expanduser('~/pdks'))
sys.path.insert(0, os.path.abspath('src/gelochip'))

import gelochip.gl as gl

def lp(p):
    return dict(with_tie=p.get('with_tie', False), with_dummy=p.get('with_dummy', False))

def bp(p):
    return dict(placement=p.get('placement', 'column'), sep_mult=p.get('sep_mult', 2.0),
                met_layer=p.get('met_layer', 1), width_mult=p.get('width_mult', 1.0))

# ── builder functions (matches 00_train.ipynb) ───────────────────────────────
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

def build_diff_pair_stacked(cp, p, name='dp_stacked'):
    vip = gl.Net('vip'); vim = gl.Net('vim'); vtail = gl.Net('vtail')
    vop = gl.Net('vop'); vom = gl.Net('vom'); vbias = gl.Net('vbias'); vcasc = gl.Net('vcasc')
    mt   = gl.nmos(w=cp['w'],  fingers=2,        g=vbias, d=vcasc, s=gl.gnd, **lp(p))
    mc   = gl.nmos(w=cp['w'],  fingers=2,        g=vbias, d=vtail, s=vcasc,  **lp(p))
    mn_p = gl.nmos(w=cp['wn'], fingers=cp['fn'],  g=vip,   d=vop,   s=vtail,  **lp(p))
    mn_m = gl.nmos(w=cp['wn'], fingers=cp['fn'],  g=vim,   d=vom,   s=vtail,  **lp(p))
    return gl.build(mt, mc, mn_p, mn_m, name=name, **bp(p))

def build_twostage_ota(cp, p, name='twostage_ota'):
    vip = gl.Net('vip'); vim = gl.Net('vim'); vtail = gl.Net('vtail')
    vout = gl.Net('vout'); vleft = gl.Net('vleft'); vbias = gl.Net('vbias'); vcs = gl.Net('vcs')
    mt   = gl.nmos(w=cp['wt'],  fingers=2, g=vbias, d=vtail, s=gl.gnd, **lp(p))
    mn_p = gl.nmos(w=cp['wn'],  fingers=2, g=vip,   d=vout,  s=vtail,  **lp(p))
    mn_m = gl.nmos(w=cp['wn'],  fingers=2, g=vim,   d=vleft, s=vtail,  **lp(p))
    mp_l = gl.pmos(w=cp['wp'],  fingers=2, g=vleft, d=vleft, s=gl.vdd, **lp(p))
    mp_r = gl.pmos(w=cp['wp'],  fingers=2, g=vleft, d=vout,  s=gl.vdd, **lp(p))
    mcs  = gl.nmos(w=cp['wcs'], fingers=2, g=vout,  d=vcs,   s=gl.gnd, **lp(p))
    return gl.build(mt, mn_p, mn_m, mp_l, mp_r, mcs, name=name, **bp(p))

def build_p_block(cp, p, name='p_block'):
    vbias = gl.Net('vbias'); iout = gl.Net('iout'); vtail = gl.Net('vtail')
    mp_ref = gl.pmos(w=cp['wp'], fingers=2, g=vbias, d=vbias, s=gl.vdd, **lp(p))
    mp_out = gl.pmos(w=cp['wp'], fingers=2, g=vbias, d=iout,  s=gl.vdd, **lp(p))
    mt     = gl.nmos(w=cp['wt'], fingers=2, g=vbias, d=vtail, s=gl.gnd, **lp(p))
    mn_out = gl.nmos(w=cp['wn'], fingers=2, g=vbias, d=iout,  s=vtail,  **lp(p))
    return gl.build(mp_ref, mp_out, mt, mn_out, name=name, **bp(p))

def build_diff_to_single(cp, p, name='d2s'):
    vip = gl.Net('vip'); vim = gl.Net('vim'); vtail = gl.Net('vtail')
    vout = gl.Net('vout'); vleft = gl.Net('vleft'); vbias = gl.Net('vbias')
    mt   = gl.nmos(w=cp['wt'], fingers=2, g=vbias, d=vtail, s=gl.gnd, **lp(p))
    mn_p = gl.nmos(w=cp['wn'], fingers=2, g=vip,   d=vout,  s=vtail,  **lp(p))
    mn_m = gl.nmos(w=cp['wn'], fingers=2, g=vim,   d=vleft, s=vtail,  **lp(p))
    mp_l = gl.pmos(w=cp['wp'], fingers=2, g=vleft, d=vleft, s=gl.vdd, **lp(p))
    mp_r = gl.pmos(w=cp['wp'], fingers=2, g=vleft, d=vout,  s=gl.vdd, **lp(p))
    return gl.build(mt, mn_p, mn_m, mp_l, mp_r, name=name, **bp(p))

# ── same CIRCUIT_POOL as 00_train.ipynb ──────────────────────────────────────
CIRCUIT_POOL = [
    (build_inverter,           {'wn': 2.0, 'wp': 4.0, 'fn': 2},                  'inverter'),
    (build_inverter,           {'wn': 4.0, 'wp': 8.0, 'fn': 4},                  'inverter_large'),
    (build_current_mirror,     {'w': 4.0, 'ratio': 1, 'n_or_p': 'n'},            'cmirror_n'),
    (build_current_mirror,     {'w': 4.0, 'ratio': 2, 'n_or_p': 'p'},            'cmirror_p'),
    (build_diff_pair,          {'wn': 3.0, 'wt': 4.0, 'fn': 2},                  'diff_pair'),
    (build_fvf,                {'w_main': 6.6, 'w_fb': 3.3},                      'fvf'),
    (build_tgate,              {'wn': 2.0, 'wp': 2.0},                            'tgate'),
    (build_ota,                {'wn': 3.0, 'wp': 4.0, 'wt': 4.0, 'fn': 2},       'ota'),
    (build_stacked_cmirror,    {'w': 4.0, 'ratio': 1},                            'stacked_cm'),
    (build_lvcmirror,          {'w': 4.0, 'w_narrow': 1.5},                       'lvcm'),
    (build_diff_pair_cmbias,   {'wn': 3.0, 'wt': 4.0, 'fn': 2},                  'dp_cmbias'),
    (build_diff_pair_stacked,  {'wn': 3.0, 'w': 4.0, 'fn': 2},                   'dp_stacked'),
    (build_twostage_ota,       {'wn': 3.0, 'wp': 4.0, 'wt': 4.0, 'wcs': 8.0},   'twostage_ota'),
    (build_p_block,            {'wp': 3.0, 'wn': 4.0, 'wt': 4.0},                'p_block'),
    (build_diff_to_single,     {'wn': 3.0, 'wp': 4.0, 'wt': 4.0},                'd2s'),
]

# ── evaluate with guaranteed fallback (no RL model needed) ────────────────────
SWEEP_PARAMS = [
    dict(with_tie=True, with_dummy=True,  placement='column', sep_mult=2.0, met_layer=1, width_mult=1.0),
    dict(with_tie=True, with_dummy=True,  placement='column', sep_mult=2.5, met_layer=1, width_mult=1.0),
    dict(with_tie=True, with_dummy=False, placement='column', sep_mult=2.0, met_layer=1, width_mult=1.0),
    dict(with_tie=True, with_dummy=True,  placement='row',    sep_mult=2.0, met_layer=1, width_mult=1.0),
    dict(with_tie=True, with_dummy=True,  placement='column', sep_mult=1.5, met_layer=1, width_mult=1.0),
    dict(with_tie=True, with_dummy=True,  placement='column', sep_mult=3.0, met_layer=1, width_mult=1.0),
    dict(with_tie=True, with_dummy=True,  placement='row',    sep_mult=2.5, met_layer=1, width_mult=1.0),
]

import json
best_lp_path = os.path.join('src', 'gelochip', 'gl', 'drc_corrector_best_lp.json')
if os.path.exists(best_lp_path):
    saved_lp = json.load(open(best_lp_path))
else:
    saved_lp = None

results = {}
for build_fn, circuit_params, label in CIRCUIT_POOL:
    print(f'\n── {label}', flush=True)

    best_n  = 9999
    best_lp = SWEEP_PARAMS[0]

    # Try saved best params first
    if saved_lp:
        try:
            d = build_fn(circuit_params, saved_lp, '_rl_tmp').drc(silent=True)
            n = d.get('total_errors', 999)
            if n < best_n:
                best_n = n; best_lp = saved_lp
        except Exception as e:
            print(f'  [saved] error: {e}', flush=True)

    if best_n > 0:
        for sp in SWEEP_PARAMS:
            try:
                d = build_fn(circuit_params, sp, '_rl_tmp').drc(silent=True)
                n = d.get('total_errors', 999)
                if n < best_n:
                    best_n = n; best_lp = sp
                if best_n == 0:
                    break
            except Exception as e:
                print(f'  [sweep] error: {e}', flush=True)

    results[label] = {'fixed': best_n, 'lp': best_lp}
    icon = '✅' if best_n == 0 else '❌'
    print(f'  {icon} {best_n} errors | tie={int(best_lp["with_tie"])} '
          f'dum={int(best_lp["with_dummy"])} {best_lp["placement"]} '
          f'sep={best_lp["sep_mult"]:.1f}', flush=True)

# ── summary ───────────────────────────────────────────────────────────────────
print()
print('=' * 55)
print(f'{"Circuit":<28} {"Errors":>8} {"Status":>10}')
print('-' * 55)
clean = 0
for label, r in results.items():
    status = 'CLEAN' if r['fixed'] == 0 else f"{r['fixed']} err"
    icon = '✅' if r['fixed'] == 0 else '❌'
    if r['fixed'] == 0: clean += 1
    print(f'{icon} {label:<26} {r["fixed"]:>8} {status:>10}')
print('=' * 55)
print(f'DRC-clean: {clean}/{len(results)} circuits')
