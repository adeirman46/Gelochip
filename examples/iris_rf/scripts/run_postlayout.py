import csv
import json
import math
import re
import subprocess
from pathlib import Path

import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / 'config' / 'iris_config.json').read_text())
PAR = json.loads((ROOT / 'layout' / 'route_parasitics.json').read_text())
RESULTS = ROOT / 'results'
POST = RESULTS / 'postlayout'
POST.mkdir(parents=True, exist_ok=True)


def rc(net: str):
    data = PAR.get(net, {'r_ohm': 0.0, 'c_f': 0.0})
    return data['r_ohm'], data['c_f']


def deck(pin_dbm: float, freq_hz: float, wave_csv: Path, rawfile: Path) -> str:
    pdk_root = (ROOT.parent / CONFIG['pdk_root'] / CONFIG['process'] / 'libs.tech' / 'ngspice').resolve()
    rvrect, cvrect = rc('vrect')
    rvout, cvout = rc('vout')
    rrfp, crfp = rc('rfp')
    rrfn, crfn = rc('rfn')
    rn1, cn1 = rc('n1')
    rn2, cn2 = rc('n2')
    match_gain = CONFIG['matching_network']['effective_voltage_gain']
    return f'''* IRIS post-layout RC-augmented simulation deck
.options savecurrents reltol=1e-4 vabstol=1e-8 iabstol=1e-12 method=gear
.temp 27
.param pin_dbm={pin_dbm}
.param freq_hz={freq_hz}
.param load_res={CONFIG['load_res_ohm']}
.param pin_w = 1e-3*pow(10,pin_dbm/10)
.param vhalf_peak = sqrt(100*pin_w)*{match_gain}
.include {pdk_root / 'design.ngspice'}
.lib {pdk_root / 'sm141064.ngspice'} typical
VSP srcp 0 SIN(0 {{vhalf_peak}} {{freq_hz}})
VSN srcn 0 SIN(0 {{-vhalf_peak}} {{freq_hz}})
RSP srcp rfp_ext 25
RSN srcn rfn_ext 25
RRFP rfp_ext rfp {rrfp}
CRFP rfp 0 {crfp}
RRFN rfn_ext rfn {rrfn}
CRFN rfn 0 {crfn}
XHARV rfp rfn vout_ext 0 iris_harvester_post
RVOUT vout_ext vout {rvout}
CVOUT vout 0 {cvout}
RLOAD vout 0 {CONFIG['load_res_ohm']}
.tran 0.2n 80u 0 0.2n
.meas tran vrect_avg AVG v(vrect) from=60u to=80u
.meas tran vout_avg AVG v(vout) from=60u to=80u
.meas tran vout_max MAX v(vout) from=60u to=80u
.control
run
wrdata {wave_csv.resolve()} time v(vout) v(vrect) v(rfp) v(rfn)
write {rawfile.resolve()}
quit
.endc
.subckt iris_harvester_post rfp rfn vout vss
RVR1 vrect_int vrect {rvrect}
CVR1 vrect 0 {cvrect}
XBIAS rfp rfn gatep gaten vrect_int vss iris_startup_bias
XRECT rfp rfn gatep gaten vrect_int vss iris_rectifier
XPUMP rfp rfn vrect_int n1_int n2_int vout vss iris_charge_pump_post
.ends iris_harvester_post
.subckt iris_startup_bias rfp rfn gatep gaten vrect vss
RGP gatep rfp 1m
RGN gaten rfn 1m
CINJP rfn gatep {CONFIG['rectifier']['inject_cap_pf']}p
CINJN rfp gaten {CONFIG['rectifier']['inject_cap_pf']}p
MPBIASP gatep vrect vrect vrect pmos_3p3 w={CONFIG['rectifier']['bias_pmos_w_um']}u l={CONFIG['rectifier']['bias_pmos_l_um']}u nf=1 m=1
MPBIASN gaten vrect vrect vrect pmos_3p3 w={CONFIG['rectifier']['bias_pmos_w_um']}u l={CONFIG['rectifier']['bias_pmos_l_um']}u nf=1 m=1
MNBIASP gatep vss vss vss nmos_3p3 w={CONFIG['rectifier']['bias_nmos_w_um']}u l={CONFIG['rectifier']['bias_nmos_l_um']}u nf=1 m=1
MNBIASN gaten vss vss vss nmos_3p3 w={CONFIG['rectifier']['bias_nmos_w_um']}u l={CONFIG['rectifier']['bias_nmos_l_um']}u nf=1 m=1
.ends iris_startup_bias
.subckt iris_rectifier rfp rfn gatep gaten vrect vss
MPP1 vrect gaten rfp vrect pmos_3p3 w={CONFIG['rectifier']['pmos_w_um']}u l={CONFIG['rectifier']['pmos_l_um']}u nf={CONFIG['rectifier']['pmos_nf']} m=1
MPP2 vrect gatep rfn vrect pmos_3p3 w={CONFIG['rectifier']['pmos_w_um']}u l={CONFIG['rectifier']['pmos_l_um']}u nf={CONFIG['rectifier']['pmos_nf']} m=1
MNN1 rfp gaten vss vss nmos_3p3 w={CONFIG['rectifier']['nmos_w_um']}u l={CONFIG['rectifier']['nmos_l_um']}u nf={CONFIG['rectifier']['nmos_nf']} m=1
MNN2 rfn gatep vss vss nmos_3p3 w={CONFIG['rectifier']['nmos_w_um']}u l={CONFIG['rectifier']['nmos_l_um']}u nf={CONFIG['rectifier']['nmos_nf']} m=1
.ends iris_rectifier
.subckt iris_charge_pump_post rfp rfn vrect n1 n2 vout vss
RN1A n1_int n1 {rn1}
CN1A n1 0 {cn1}
RN2A n2_int n2 {rn2}
CN2A n2 0 {cn2}
MCP1 vrect vrect n1_int n1_int nmos_3p3 w={CONFIG['charge_pump']['diode_w_um']}u l={CONFIG['charge_pump']['diode_l_um']}u nf={CONFIG['charge_pump']['diode_nf']} m=1
MCP2 n1 n1 n2_int n2_int nmos_3p3 w={CONFIG['charge_pump']['diode_w_um']}u l={CONFIG['charge_pump']['diode_l_um']}u nf={CONFIG['charge_pump']['diode_nf']} m=1
MCP3 n2 n2 vout vout nmos_3p3 w={CONFIG['charge_pump']['diode_w_um']}u l={CONFIG['charge_pump']['diode_l_um']}u nf={CONFIG['charge_pump']['diode_nf']} m=1
CCP1 rfp n1 {CONFIG['charge_pump']['stage_cap_pf']}p
CCP2 rfn n2 {CONFIG['charge_pump']['stage_cap_pf']}p
CCP3 rfp vout {CONFIG['charge_pump']['stage_cap_pf']}p
CSTORE vout vss {CONFIG['charge_pump']['storage_cap_pf']}p
.ends iris_charge_pump_post
.end
'''


def parse(log_text: str):
    measures = {}
    for match in re.finditer(r'(^|\n)\s*([a-zA-Z0-9_]+)\s*=\s*([-+0-9.eE]+)', log_text):
        measures[match.group(2)] = float(match.group(3))
    return measures


def run_case(pin_dbm: float, freq_hz: float):
    tag = f"post_f{int(freq_hz/1e6):03d}mhz_p{pin_dbm:+03.0f}dbm".replace('+','p').replace('-','m')
    deck_path = POST / f'{tag}.spice'
    log_path = POST / f'{tag}.log'
    wave_path = POST / f'{tag}_wave.csv'
    raw_path = POST / f'{tag}.raw'
    deck_path.write_text(deck(pin_dbm, freq_hz, wave_path, raw_path))
    ngspice_bin = (ROOT.parent / CONFIG['ngspice_bin']).resolve()
    proc = subprocess.run([str(ngspice_bin), '-b', '-o', str(log_path), str(deck_path)], cwd=POST, capture_output=True, text=True)
    log_text = log_path.read_text(errors='ignore') if log_path.exists() else ''
    log_text += proc.stdout + proc.stderr
    if proc.returncode != 0:
        raise RuntimeError(log_text)
    measures = parse(log_text)
    pin_w = 1e-3 * (10 ** (pin_dbm / 10.0))
    vout = measures.get('vout_avg', float('nan'))
    pce = (vout * vout / CONFIG['load_res_ohm'] / pin_w) if pin_w > 0 and not math.isnan(vout) else float('nan')
    return {
        'case': tag, 'freq_hz': freq_hz, 'pin_dbm': pin_dbm, 'pin_w': pin_w,
        'vrect_avg': measures.get('vrect_avg'), 'vout_avg': vout, 'vout_max': measures.get('vout_max'), 'pce': pce,
        'deck': str(deck_path.relative_to(ROOT)), 'log': str(log_path.relative_to(ROOT)), 'wave_csv': str(wave_path.relative_to(ROOT)), 'rawfile': str(raw_path.relative_to(ROOT))
    }


def write(rows):
    csv_path = RESULTS / 'postlayout_summary.csv'
    json_path = RESULTS / 'postlayout_summary.json'
    with csv_path.open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader(); writer.writerows(rows)
    json_path.write_text(json.dumps({'results': rows}, indent=2))
    freq_hz = CONFIG['target_frequency_hz']
    rows_f = sorted([row for row in rows if row['freq_hz'] == freq_hz], key=lambda row: row['pin_dbm'])
    fig, axes = plt.subplots(2, 1, figsize=(8, 10), dpi=150)
    x = [row['pin_dbm'] for row in rows_f]
    axes[0].plot(x, [row['vout_avg'] for row in rows_f], marker='o')
    axes[0].axhline(1.2, color='tab:red', linestyle='--')
    axes[0].set_xlabel('Input power (dBm)'); axes[0].set_ylabel('Average output voltage (V)'); axes[0].grid(True, alpha=0.3)
    axes[1].plot(x, [100 * row['pce'] for row in rows_f], marker='o', color='tab:orange')
    axes[1].set_xlabel('Input power (dBm)'); axes[1].set_ylabel('Estimated post-layout PCE (%)'); axes[1].grid(True, alpha=0.3)
    fig.tight_layout(); fig.savefig(RESULTS / 'postlayout_summary.png'); plt.close(fig)


if __name__ == '__main__':
    rows = []
    for freq_hz in CONFIG['frequency_sweep_hz']:
        for pin_dbm in CONFIG['power_sweep_dbm']:
            rows.append(run_case(pin_dbm, freq_hz))
    write(rows)
    print(json.dumps(rows, indent=2))
