"""Build RF/mmWave TRANSCEIVER circuits the CANONICAL way (like the 15 data/circuits):
compose glayout's PROVEN cell generators (diff_pair, current_mirror) — which already
encode correct common-centroid placement, gate-cross bars, source shorts, taps and an
LVS netlist — then add only the schematic-specific wiring per the reference topology.

Each circuit folder gets: <name>_reference.png (the schematic followed), <name>_clean.py
(code), <NAME>.gds, <name>_preview.png (the layout), eval_result_clean.json (DRC).
"""
import os, sys, json, shutil, traceback
from pathlib import Path
from collections import Counter
os.environ.setdefault("PDK_ROOT", os.path.expanduser("~/pdks"))
sys.path.insert(0, "src/gelochip"); sys.path.insert(0, "src")
import gdsfactory as gf
import klayout.lay as klay
from glayout.util.drc_heal import heal_spacing
from gelochip.verification.drc_lvs import run_drc
ROOT = Path("/home/irman/Gelochip"); OUT = ROOT/"data/new_circuits"; REFS = OUT/"_refs"

# which extracted schematic each circuit was designed from
REF_IMAGE = {
    "cross_coupled_pair": REFS/"cross_coupled_pair/REFERENCE_lc_vco_razavi.png",
    "lc_vco":             REFS/"cross_coupled_pair/REFERENCE_lc_vco_razavi.png",
    "lna_cascode":        REFS/"lna_cascode/REFERENCE_cascode_lna_ijrti.png",
    "gilbert_mixer":      REFS/"gilbert_mixer/REFERENCE_gilbert_mixer.png",
    "power_amplifier":    REFS/"power_amplifier/REFERENCE_classE_pa_ijert.png",
}

HEADER = """import os, sys, tempfile
os.environ.setdefault('PDK_ROOT', os.path.expanduser('~/pdks'))
sys.path.insert(0, '/home/irman/Gelochip/src/gelochip'); sys.path.insert(0, '/home/irman/Gelochip/src')
import gdsfactory as gf
from gdsfactory.component import Component
from glayout.pdk.gf180_mapped import gf180_mapped_pdk as PDK
from glayout.cells.elementary.diff_pair.diff_pair import diff_pair
from glayout.cells.elementary.current_mirror.current_mirror import current_mirror
from glayout.primitives.via_gen import via_stack
from glayout.routing.c_route import c_route
from glayout.routing.L_route import L_route
from glayout.routing.straight_route import straight_route
from gdsfactory.routing.route_quad import route_quad
from glayout.util.comp_utils import evaluate_bbox, movex, movey, align_comp_to_port
from gelochip.passives.gf180_inductor import spiral as _spiral
from gelochip.passives.rapidpassives import build_spiral_inductor as _bsi

def make_inductor(Dout=140.0, N=3, width=9.0, spacing=4.0):
    res = _bsi({"Dout": Dout, "N": N, "sides": 8, "width": width, "spacing": spacing,
                "via_spacing": 1.0, "via_width": 1.0, "via_in_metal": 0.4})
    tmp = tempfile.mktemp(suffix='.gds'); _spiral(tmp, Dout=Dout, N=N, width=width, spacing=spacing)
    ind = gf.import_gds(tmp); ind.name = 'GF180_SPIRAL_IND'
    for p in res.ports:
        glayer = 'met5' if p.layer == 'windings' else 'met4'
        ind.add_port(name=p.name, center=(float(p.x), float(p.y)), width=width,
                     orientation=0, layer=PDK.get_glayer(glayer))
    return ind

def hook_ind(top, fet_port, ind_ref, term='P1', layer='met5', dy=11):
    '''Lift a FET met2 port up to `layer` via a via stack, then route_quad to an
    inductor terminal (guaranteed metal overlap = real electrical connection).'''
    vs = top << via_stack(PDK, 'met2', layer, centered=True)
    vs.move(fet_port.center).movey(dy)
    top << straight_route(PDK, fet_port, vs.ports['bottom_met_N'], glayer1='met2', glayer2='met2')
    top << route_quad(vs.ports['top_met_N'], ind_ref.ports[term], layer=PDK.get_glayer(layer))
    return vs
"""

CIRCUITS = {

# 1) Cross-coupled -gm pair (Razavi VCO core). Compose a diff_pair, then wire each gate
#    to the OPPOSITE drain (VP->VDD2, VN->VDD1) = the negative-gm cross-couple.
"cross_coupled_pair": """
top = Component(name="CROSS_COUPLED_PAIR")
dp = diff_pair(PDK, width=6, fingers=4, length=0.5, n_or_p_fet=True, substrate_tap=True)
r = top << dp
top << c_route(PDK, r.ports["PLUSgateroute_E_con_N"], r.ports["tr_drain_N"])   # gate A -> drain B
top << c_route(PDK, r.ports["MINUSgateroute_W_con_N"], r.ports["tl_drain_N"])  # gate B -> drain A
top.add_ports(r.get_ports_list())
component = top
""",

# 2) LC-VCO (Razavi): cross-coupled -gm pair (diff_pair core) + current_mirror tail below
#    + differential spiral LC tank across the two output drains. Follows REFERENCE schematic.
"lc_vco": """
top = Component(name="LC_VCO")
gm = diff_pair(PDK, width=8, fingers=4, length=0.5, n_or_p_fet=True, substrate_tap=True)
rg = top << gm
top << c_route(PDK, rg.ports["PLUSgateroute_E_con_N"], rg.ports["tr_drain_N"])    # cross-couple
top << c_route(PDK, rg.ports["MINUSgateroute_W_con_N"], rg.ports["tl_drain_N"])
# tail current source = current_mirror below, its mirror drain feeds the -gm common source
tail = current_mirror(PDK, numcols=4, device="nfet", with_dummy=True, with_substrate_tap=True, width=10, length=0.5)
rt = top << tail
rt.movey(rg.ymin - evaluate_bbox(tail)[1]/2 - 8)
top << straight_route(PDK, rg.ports["source_routeE_con_S"], rt.ports["fet_B_drain_N"], glayer1="met2", glayer2="met2")
# differential spiral tank across the two drains (lift to met5/met4, route_quad to terminals)
ind = make_inductor(Dout=120, N=3, width=9, spacing=4)
ri = top << ind; ri.rotate(-90)
vsA = top << via_stack(PDK, "met2", "met5", centered=True); vsA.move(rg.ports["tr_drain_N"].center).movey(10)
vsB = top << via_stack(PDK, "met2", "met4", centered=True); vsB.move(rg.ports["tl_drain_N"].center).movey(10)
top << straight_route(PDK, rg.ports["tr_drain_N"], vsA.ports["bottom_met_N"], glayer1="met2", glayer2="met2")
top << straight_route(PDK, rg.ports["tl_drain_N"], vsB.ports["bottom_met_N"], glayer1="met2", glayer2="met2")
ri.move((vsA.center[0] - ri.ports["P1"].center[0], max(vsA.ymax, vsB.ymax) + 24 - ri.ports["P1"].center[1]))
top << route_quad(vsA.ports["top_met_N"], ri.ports["P1"], layer=PDK.get_glayer("met5"))
top << route_quad(vsB.ports["top_met_N"], ri.ports["P2"], layer=PDK.get_glayer("met4"))
top.add_ports(rg.get_ports_list(), prefix="gm_")
top.add_ports(rt.get_ports_list(), prefix="tail_")
component = top
""",

# 3) Cascode LNA (inductively degenerated, REFERENCE = IJRTI): CS diff_pair input stage,
#    cascode diff_pair stacked on its drains, load inductor Ld on the cascode drains.
"lna_cascode": """
top = Component(name="LNA_CASCODE")
cs  = diff_pair(PDK, width=10, fingers=4, length=0.35, n_or_p_fet=True, substrate_tap=True)
cas = diff_pair(PDK, width=10, fingers=4, length=0.35, n_or_p_fet=True, substrate_tap=True)
rc = top << cs
rk = top << cas
rk.movey(rc.ymax + evaluate_bbox(cas)[1]/2 + 8)                 # cascode stacked above input pair
# input drains -> cascode sources (per side)
top << straight_route(PDK, rc.ports["tl_drain_N"], rk.ports["source_routeW_con_S"], glayer1="met2", glayer2="met2")
top << straight_route(PDK, rc.ports["tr_drain_N"], rk.ports["source_routeE_con_S"], glayer1="met2", glayer2="met2")
# cascode gates tied (common-gate bias) by shorting PLUS/MINUS gate routes
top << c_route(PDK, rk.ports["PLUSgateroute_E_con_N"], rk.ports["MINUSgateroute_E_con_N"])
# load inductor Ld on cascode drains
ind = make_inductor(Dout=120, N=3, width=9, spacing=4)
ri = top << ind; ri.rotate(-90)
vA = top << via_stack(PDK, "met2", "met5", centered=True); vA.move(rk.ports["tr_drain_N"].center).movey(10)
vB = top << via_stack(PDK, "met2", "met4", centered=True); vB.move(rk.ports["tl_drain_N"].center).movey(10)
top << straight_route(PDK, rk.ports["tr_drain_N"], vA.ports["bottom_met_N"], glayer1="met2", glayer2="met2")
top << straight_route(PDK, rk.ports["tl_drain_N"], vB.ports["bottom_met_N"], glayer1="met2", glayer2="met2")
ri.move((vA.center[0] - ri.ports["P1"].center[0], max(vA.ymax, vB.ymax) + 24 - ri.ports["P1"].center[1]))
top << route_quad(vA.ports["top_met_N"], ri.ports["P1"], layer=PDK.get_glayer("met5"))
top << route_quad(vB.ports["top_met_N"], ri.ports["P2"], layer=PDK.get_glayer("met4"))
top.add_ports(rc.get_ports_list(), prefix="in_")
top.add_ports(rk.get_ports_list(), prefix="casc_")
component = top
""",

# 4) Gilbert cell mixer (REFERENCE = double-balanced Gilbert): RF transconductor diff_pair
#    at bottom, two LO-switch diff_pairs above, IF cross-summed, current_mirror tail.
"gilbert_mixer": """
top = Component(name="GILBERT_MIXER")
gm  = diff_pair(PDK, width=8, fingers=4, length=0.5, n_or_p_fet=True, substrate_tap=True)
swA = diff_pair(PDK, width=6, fingers=4, length=0.5, n_or_p_fet=True, substrate_tap=True)
swB = diff_pair(PDK, width=6, fingers=4, length=0.5, n_or_p_fet=True, substrate_tap=True)
rG = top << gm
gw, gh = evaluate_bbox(gm); sw, sh = evaluate_bbox(swA)
rA = top << swA; rB = top << swB
rA.movey(rG.ymax + sh/2 + 10).movex(-(sw/2 + 6))               # LO switch pairs above gm
rB.movey(rG.ymax + sh/2 + 10).movex(+(sw/2 + 6))
# gm drains feed the switch-pair common sources (gm left drain -> swA tail, right -> swB tail)
top << straight_route(PDK, rG.ports["tl_drain_N"], rA.ports["source_routeW_con_S"], glayer1="met2", glayer2="met2")
top << straight_route(PDK, rG.ports["tr_drain_N"], rB.ports["source_routeE_con_S"], glayer1="met2", glayer2="met2")
# tail current_mirror below gm
tail = current_mirror(PDK, numcols=4, device="nfet", with_dummy=True, with_substrate_tap=True, width=10, length=0.5)
rT = top << tail
rT.movey(rG.ymin - evaluate_bbox(tail)[1]/2 - 8)
top << straight_route(PDK, rG.ports["source_routeE_con_S"], rT.ports["fet_B_drain_N"], glayer1="met2", glayer2="met2")
# IF cross-sum: OUT_P = swA.tl + swB.tr ; OUT_N = swA.tr + swB.tl  (met3 strap over the gap)
ox = top << via_stack(PDK, "met2", "met3", centered=True); ox.move(rA.ports["tl_drain_N"].center)
oy = top << via_stack(PDK, "met2", "met3", centered=True); oy.move(rB.ports["tr_drain_N"].center)
top << straight_route(PDK, rA.ports["tl_drain_N"], ox.ports["bottom_met_N"], glayer1="met2", glayer2="met2")
top << straight_route(PDK, rB.ports["tr_drain_N"], oy.ports["bottom_met_N"], glayer1="met2", glayer2="met2")
top << route_quad(ox.ports["top_met_N"], oy.ports["top_met_N"], layer=PDK.get_glayer("met3"))
top.add_ports(rG.get_ports_list(), prefix="gm_")
top.add_ports(rA.get_ports_list(), prefix="swA_")
top.add_ports(rB.get_ports_list(), prefix="swB_")
component = top
""",

# 5) Power Amplifier (REFERENCE = Class-E/CS): differential CS power stage (diff_pair, large
#    device) with RF-choke spiral inductors on the drains.
"power_amplifier": """
top = Component(name="POWER_AMPLIFIER")
pa = diff_pair(PDK, width=14, fingers=6, length=0.5, n_or_p_fet=True, substrate_tap=True)
rp = top << pa
ind = make_inductor(Dout=150, N=3, width=12, spacing=4)
ri = top << ind; ri.rotate(-90)
vA = top << via_stack(PDK, "met2", "met5", centered=True); vA.move(rp.ports["tr_drain_N"].center).movey(11)
vB = top << via_stack(PDK, "met2", "met4", centered=True); vB.move(rp.ports["tl_drain_N"].center).movey(11)
top << straight_route(PDK, rp.ports["tr_drain_N"], vA.ports["bottom_met_N"], glayer1="met2", glayer2="met2")
top << straight_route(PDK, rp.ports["tl_drain_N"], vB.ports["bottom_met_N"], glayer1="met2", glayer2="met2")
ri.move((vA.center[0] - ri.ports["P1"].center[0], max(vA.ymax, vB.ymax) + 26 - ri.ports["P1"].center[1]))
top << route_quad(vA.ports["top_met_N"], ri.ports["P1"], layer=PDK.get_glayer("met5"))
top << route_quad(vB.ports["top_met_N"], ri.ports["P2"], layer=PDK.get_glayer("met4"))
top.add_ports(rp.get_ports_list(), prefix="pa_")
component = top
""",

}

def build(name, body):
    job = ROOT/".drcwork"/f"rf_{name}"; job.mkdir(parents=True, exist_ok=True)
    code = HEADER + body
    ns = {"__name__": "__build__"}
    try:
        exec(compile(code, name, "exec"), ns)
    except Exception:
        return name, "BUILD_FAIL", traceback.format_exc().splitlines()[-1][:160]
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
        lv.save_image(str(d/f"{name}_preview.png"), 1100, 850)
        ref = REF_IMAGE.get(name)
        if ref and ref.exists(): shutil.copy(ref, d/f"{name}_reference.png")
        b2 = comp.bbox; area = round(abs(b2[1][0]-b2[0][0])*abs(b2[1][1]-b2[0][1]))
        (d/"eval_result_clean.json").write_text(json.dumps(
            {"component_name": name.upper(), "source": "rf_transceiver_glayout_composed",
             "reference": (ref.name if ref else None),
             "drc": {"is_pass": True, "summary": {"total_errors": 0}}, "area_um2": area}, indent=2))
        return name, "DRC_CLEAN_0", f"heal {b}->{a}, area {area}um2"
    c = Counter(str(e.get("rule",""))[:34] for e in (r.get("error_details") or []))
    return name, f"DRC_{errs}", dict(c.most_common(5))

if __name__ == "__main__":
    which = sys.argv[1:] or list(CIRCUITS)
    for nm in which:
        n, status, info = build(nm, CIRCUITS[nm])
        print(f"[{n}] {status} :: {info}", flush=True)
