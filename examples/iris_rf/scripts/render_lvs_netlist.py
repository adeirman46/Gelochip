import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / 'config' / 'iris_config.json').read_text())


def cap_side_um(cap_pf: float) -> float:
    cap_f = cap_pf * 1e-12
    density_f_per_um2 = 2.0e-15
    return math.sqrt(cap_f / density_f_per_um2)


def main() -> None:
    template = (ROOT / 'netlist' / 'iris_lvs_template.cdl').read_text()
    replacements = {
        '{CINJ_SIDE}': f"{cap_side_um(CONFIG['rectifier']['inject_cap_pf']):.6f}",
        '{CSTAGE_SIDE}': f"{cap_side_um(CONFIG['charge_pump']['stage_cap_pf']):.6f}",
        '{CSTORE_SIDE}': f"{cap_side_um(CONFIG['charge_pump']['storage_cap_pf']):.6f}",
        '{BIAS_PMOS_W}': f"{CONFIG['rectifier']['bias_pmos_w_um']}",
        '{BIAS_PMOS_L}': f"{CONFIG['rectifier']['bias_pmos_l_um']}",
        '{BIAS_NMOS_W}': f"{CONFIG['rectifier']['bias_nmos_w_um']}",
        '{BIAS_NMOS_L}': f"{CONFIG['rectifier']['bias_nmos_l_um']}",
        '{RECT_PMOS_W}': f"{CONFIG['rectifier']['pmos_w_um']}",
        '{RECT_PMOS_L}': f"{CONFIG['rectifier']['pmos_l_um']}",
        '{RECT_PMOS_NF}': str(CONFIG['rectifier']['pmos_nf']),
        '{RECT_NMOS_W}': f"{CONFIG['rectifier']['nmos_w_um']}",
        '{RECT_NMOS_L}': f"{CONFIG['rectifier']['nmos_l_um']}",
        '{RECT_NMOS_NF}': str(CONFIG['rectifier']['nmos_nf']),
        '{CP_DIODE_W}': f"{CONFIG['charge_pump']['diode_w_um']}",
        '{CP_DIODE_L}': f"{CONFIG['charge_pump']['diode_l_um']}",
        '{CP_DIODE_NF}': str(CONFIG['charge_pump']['diode_nf']),
    }
    for key, value in replacements.items():
        template = template.replace(key, value)
    out = ROOT / 'netlist' / 'iris_lvs.cdl'
    out.write_text(template)
    print(out)


if __name__ == '__main__':
    main()
