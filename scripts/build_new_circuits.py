"""Build NEW RF/mmWave + analog-standard glayout circuits, heal to 0 DRC, and save
clean.py + GDS + preview into data/new_circuits/<name>/."""
import os, sys, json, tempfile, traceback
from pathlib import Path
os.environ.setdefault("PDK_ROOT", os.path.expanduser("~/pdks"))
sys.path.insert(0, "src/gelochip"); sys.path.insert(0, "src")
import gdsfactory as gf
import klayout.lay as klay
from glayout.util.drc_heal import heal_spacing
from gelochip.verification.drc_lvs import run_drc
ROOT = Path("/home/irman/Gelochip"); OUT = ROOT/"data/new_circuits"

HEADER = """import os, sys
os.environ.setdefault('PDK_ROOT', os.path.expanduser('~/pdks'))
sys.path.insert(0, '/home/irman/Gelochip/src/gelochip'); sys.path.insert(0, '/home/irman/Gelochip/src')
from glayout.pdk.gf180_mapped import gf180_mapped_pdk as PDK
from glayout.primitives.fet import nmos, pmos
from glayout.routing import c_route, L_route, straight_route
from glayout.placement.two_transistor_interdigitized import two_nfet_interdigitized, two_pfet_interdigitized
from glayout.util.comp_utils import evaluate_bbox
from gdsfactory.component import Component
"""

CIRCUITS = {
"cascode_amp": """
top = Component(name="CASCODE_AMP")
cs  = nmos(PDK, width=6, fingers=4, length=0.5, with_tie=True, with_dummy=True, with_substrate_tap=False)
cas = nmos(PDK, width=6, fingers=4, length=0.5, with_tie=True, with_dummy=True, with_substrate_tap=False)
rcs = top << cs; rcas = top << cas
bw, bh = evaluate_bbox(cs); rcas.movey(bh + 6)
top << straight_route(PDK, rcs.ports["multiplier_0_drain_N"], rcas.ports["multiplier_0_source_S"])
top.add_ports(rcs.get_ports_list(), prefix="in_")
top.add_ports(rcas.get_ports_list(), prefix="casc_")
component = top
""",
"cross_coupled_pair": """
top = Component(name="XCOUPLED_PAIR")
pair = two_nfet_interdigitized(PDK, numcols=4, with_tie=True, with_substrate_tap=False, tie_layers=("met2","met2"), width=4, length=0.5)
r = top << pair
top << c_route(PDK, r.ports["A_gate_E"], r.ports["B_drain_E"])
top << c_route(PDK, r.ports["B_gate_W"], r.ports["A_drain_W"])
top.add_ports(r.get_ports_list())
component = top
""",
"cmos_inverter": """
top = Component(name="CMOS_INVERTER")
n = nmos(PDK, width=4, fingers=2, length=0.5, with_tie=True, with_dummy=True, with_substrate_tap=False)
p = pmos(PDK, width=8, fingers=2, length=0.5, with_tie=True, with_dummy=True, with_substrate_tap=False)
rn = top << n; rp = top << p
bw, bh = evaluate_bbox(n); rp.movey(bh + 8)
top << straight_route(PDK, rn.ports["multiplier_0_drain_N"], rp.ports["multiplier_0_drain_S"])
top << c_route(PDK, rn.ports["multiplier_0_gate_W"], rp.ports["multiplier_0_gate_W"])
top.add_ports(rn.get_ports_list(), prefix="n_")
top.add_ports(rp.get_ports_list(), prefix="p_")
component = top
""",
"cascode_current_mirror": """
top = Component(name="CASCODE_CMIRROR")
bot = two_nfet_interdigitized(PDK, numcols=4, with_tie=True, with_substrate_tap=False, tie_layers=("met2","met2"), width=4, length=0.5)
casc = two_nfet_interdigitized(PDK, numcols=4, with_tie=True, with_substrate_tap=False, tie_layers=("met2","met2"), width=4, length=0.5)
rb = top << bot; rc = top << casc
bw, bh = evaluate_bbox(bot); rc.movey(bh + 6)
top << straight_route(PDK, rb.ports["A_drain_N"], rc.ports["A_source_S"])
top << straight_route(PDK, rb.ports["B_drain_N"], rc.ports["B_source_S"])
top << c_route(PDK, rb.ports["A_gate_W"], rb.ports["B_gate_W"])
top << c_route(PDK, rc.ports["A_gate_E"], rc.ports["B_gate_E"])
top.add_ports(rb.get_ports_list(), prefix="bot_")
top.add_ports(rc.get_ports_list(), prefix="casc_")
component = top
""",
}


CIRCUITS["gilbert_mixer"] = """
top = Component(name="GILBERT_MIXER")
gm  = two_nfet_interdigitized(PDK, numcols=2, with_tie=True, with_substrate_tap=False, tie_layers=("met2","met2"), width=6, length=0.5)
qa  = two_nfet_interdigitized(PDK, numcols=2, with_tie=True, with_substrate_tap=False, tie_layers=("met2","met2"), width=4, length=0.5)
qb  = two_nfet_interdigitized(PDK, numcols=2, with_tie=True, with_substrate_tap=False, tie_layers=("met2","met2"), width=4, length=0.5)
rg = top << gm; r1 = top << qa; r2 = top << qb
bw, bh = evaluate_bbox(gm); qw, qh = evaluate_bbox(qa)
r1.movey(bh + 8).movex(-(bw/2) - 2)
r2.movey(bh + 8).movex(+(bw/2) + 2)
top << straight_route(PDK, rg.ports["A_drain_N"], r1.ports["A_source_S"])
top << straight_route(PDK, rg.ports["B_drain_N"], r2.ports["A_source_S"])
top.add_ports(rg.get_ports_list(), prefix="rf_")
top.add_ports(r1.get_ports_list(), prefix="loA_")
top.add_ports(r2.get_ports_list(), prefix="loB_")
component = top
"""
CIRCUITS["common_gate_lna"] = """
top = Component(name="CG_LNA")
cg  = two_nfet_interdigitized(PDK, numcols=3, with_tie=True, with_substrate_tap=False, tie_layers=("met2","met2"), width=8, length=0.5)
cas = two_nfet_interdigitized(PDK, numcols=3, with_tie=True, with_substrate_tap=False, tie_layers=("met2","met2"), width=8, length=0.5)
rg = top << cg; rc = top << cas
bw, bh = evaluate_bbox(cg); rc.movey(bh + 7)
top << straight_route(PDK, rg.ports["A_drain_N"], rc.ports["A_source_S"])
top << straight_route(PDK, rg.ports["B_drain_N"], rc.ports["B_source_S"])
top << c_route(PDK, rc.ports["A_gate_E"], rc.ports["B_gate_E"])
top.add_ports(rg.get_ports_list(), prefix="in_")
top.add_ports(rc.get_ports_list(), prefix="casc_")
component = top
"""
CIRCUITS["lo_buffer"] = """
top = Component(name="LO_BUFFER")
n = two_nfet_interdigitized(PDK, numcols=3, with_tie=True, with_substrate_tap=False, tie_layers=("met2","met2"), width=4, length=0.5)
p = two_pfet_interdigitized(PDK, numcols=3, with_tie=True, with_substrate_tap=False, tie_layers=("met2","met2"), width=8, length=0.5)
rn = top << n; rp = top << p
bw, bh = evaluate_bbox(n); rp.movey(bh + 10)
top << straight_route(PDK, rn.ports["A_drain_N"], rp.ports["A_source_S"])
top << straight_route(PDK, rn.ports["B_drain_N"], rp.ports["B_source_S"])
top << c_route(PDK, rn.ports["A_gate_W"], rp.ports["A_gate_W"])
top << c_route(PDK, rn.ports["B_gate_E"], rp.ports["B_gate_E"])
top.add_ports(rn.get_ports_list(), prefix="n_")
top.add_ports(rp.get_ports_list(), prefix="p_")
component = top
"""

def build(name, body):
    job = ROOT/".drcwork"/f"new_{name}"; job.mkdir(parents=True, exist_ok=True)
    code = HEADER + body
    ns = {"__name__": "__build__"}
    try:
        exec(compile(code, name, "exec"), ns)
    except Exception:
        return name, "BUILD_FAIL", traceback.format_exc().splitlines()[-1][:120]
    comp = ns.get("component")
    if comp is None: return name, "NO_COMP", ""
    raw = str(job/f"{name}.gds"); comp.write_gds(raw)
    healed = str(job/f"{name}_healed.gds")
    try: b, a = heal_spacing(raw, healed)
    except Exception: healed = raw; b = a = -1
    cc = gf.import_gds(healed); cc.name = name.upper()
    r = run_drc(healed, name.upper(), cc, pdk="gf180")
    errs = r.get("total_errors")
    if errs == 0:
        d = OUT/name; d.mkdir(parents=True, exist_ok=True)
        (d/f"{name}_clean.py").write_text(code)
        gf.import_gds(healed).write_gds(str(d/f"{name.upper()}.gds"))
        lv = klay.LayoutView(); lv.load_layout(healed, True); lv.max_hier(); lv.zoom_fit()
        lv.save_image(str(d/f"{name}_preview.png"), 900, 700)
        b2 = comp.bbox; area = round(abs(b2[1][0]-b2[0][0])*abs(b2[1][1]-b2[0][1]))
        (d/"eval_result_clean.json").write_text(json.dumps(
            {"component_name": name.upper(), "source": "new_circuit_glayout",
             "drc": {"is_pass": True, "summary": {"total_errors": 0}}, "area_um2": area}, indent=2))
        return name, "DRC_CLEAN_0", f"heal {b}->{a}, area {area}um2"
    from collections import Counter
    c = Counter(str(e.get("rule",""))[:30] for e in (r.get("error_details") or []))
    return name, f"DRC_{errs}", dict(c.most_common(4))

if __name__ == "__main__":
    which = sys.argv[1:] or list(CIRCUITS)
    for nm in which:
        n, status, info = build(nm, CIRCUITS[nm])
        print(f"[{n}] {status} :: {info}", flush=True)
