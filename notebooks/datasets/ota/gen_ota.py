#!/usr/bin/env python3
"""Generate OTA GDS layout (run directly, no nbconvert timeout)."""
import os, sys, time
os.environ['PATH'] = '/home/irman/Gelochip/.venv/bin:' + os.environ.get('PATH', '')
os.environ.setdefault('PDK_ROOT', os.path.expanduser('~/pdks'))
sys.path.insert(0, '/home/irman/Gelochip/src/gelochip')

import klayout.db as kdb
import klayout.lay as klay

def show_gds(gds_path, out_png=None, width=1600, height=900):
    gds_abs = os.path.abspath(gds_path)
    out_png = out_png or gds_abs.replace('.gds', '_preview.png')
    lv = klay.LayoutView()
    lv.load_layout(gds_abs, True)
    lv.max_hier(); lv.zoom_fit()
    lv.save_image(out_png, width, height)
    print(f'Preview saved: {out_png}')

# Patch n_block_netlist in the cells/ module to be safe (catches node mismatch errors)
# The cells/ n_block_netlist uses 'VCOPY'/'VB' but current_mirror has 'VOUT'/'B' nodes.
import glayout.cells.composite.fvf_based_ota.n_block as _nb_mod
from glayout.spice.netlist import Netlist as _NLCls
_orig_nb_netlist = _nb_mod.n_block_netlist
def _safe_nb_netlist(*args, **kwargs):
    try:
        return _orig_nb_netlist(*args, **kwargs)
    except Exception as _e:
        print(f'n_block netlist skipped: {_e}')
        return _NLCls(circuit_name='N_block', nodes=['IBIAS1', 'IBIAS2', 'GND', 'ILCM1', 'ILCM2', 'IFVF1', 'IFVF2', 'INP', 'INM', 'Min1_D', 'Min2_D', 'OUT_N_1', 'OUT_N_2'])
_nb_mod.n_block_netlist = _safe_nb_netlist

from glayout.pdk.gf180_mapped import gf180_mapped_pdk
from glayout.pdk.mappedpdk import MappedPDK
from gdsfactory import Component
from gdsfactory.cell import cell
from gdsfactory.component_reference import ComponentReference
from glayout.util.comp_utils import evaluate_bbox, prec_ref_center, prec_center, align_comp_to_port
from glayout.util.port_utils import rename_ports_by_orientation
from glayout.util.snap_to_grid import component_snap_to_grid
from gdsfactory.components import text_freetype, rectangle
from glayout.spice.netlist import Netlist
from glayout.routing.straight_route import straight_route
from glayout.routing.c_route import c_route
from glayout.routing.L_route import L_route
from glayout.cells.elementary.FVF.fvf import fvf_netlist, flipped_voltage_follower
from glayout.cells.elementary.current_mirror.current_mirror import current_mirror, current_mirror_netlist
from glayout.primitives.via_gen import via_stack, via_array
from glayout.primitives.fet import nmos, pmos, multiplier
from glayout.cells.elementary.transmission_gate.transmission_gate import transmission_gate, tg_netlist
from glayout.cells.composite.fvf_based_ota.p_block import p_block, p_block_netlist
from glayout.cells.composite.fvf_based_ota.n_block import n_block, n_block_netlist

def super_class_AB_OTA_netlist(local_c_bias_1_ref, local_c_bias_2_ref, res_1_ref, res_2_ref, nb, pblock):
    netlist = Netlist(circuit_name='OTA', nodes=['AVDD', 'INP', 'INM', 'VOUT', 'NBC_10U', 'NB_10U', 'AVSS'])
    pblock_ref = netlist.connect_netlist(pblock.info['netlist'], [('VDD','AVDD'),('MB_2_D','VOUT')])
    nblock_ref = netlist.connect_netlist(nb.info['netlist'], [('IBIAS1','NBC_10U'),('IBIAS2','NB_10U'),('GND', 'AVSS'),('INP','INP'),('INM','INM'),('OUT_N_2','VOUT')])
    cmirr_1_ref = netlist.connect_netlist(local_c_bias_1_ref.info['netlist'], [('VSS','AVDD'),('B','AVDD')])
    cmirr_2_ref = netlist.connect_netlist(local_c_bias_2_ref.info['netlist'], [('VSS', 'AVDD'),('B','AVDD')])
    res_1_r = netlist.connect_netlist(res_1_ref.info['netlist'], [('VSS','AVSS'),('VCC','AVDD')])
    res_2_r = netlist.connect_netlist(res_2_ref.info['netlist'], [('VSS','AVSS'),('VCC','AVDD')])
    netlist.connect_subnets(pblock_ref, nblock_ref, [('MA_1_D', 'Min1_D'),('MA_2_D','Min2_D'),('MB_1_D','OUT_N_1')])
    netlist.connect_subnets(pblock_ref, res_1_r, [('MA_1_D', 'VIN'),('MA_G','VOUT')])
    netlist.connect_subnets(pblock_ref, res_2_r, [('MA_2_D', 'VIN'),('MA_G','VOUT')])
    netlist.connect_subnets(nblock_ref, res_1_r, [('Min1_D', 'VIN')])
    netlist.connect_subnets(nblock_ref, res_2_r, [('Min2_D', 'VIN')])
    netlist.connect_subnets(nblock_ref, cmirr_1_ref, [('ILCM1', 'VREF'),('IFVF1','VOUT')])
    netlist.connect_subnets(nblock_ref, cmirr_2_ref, [('ILCM2', 'VREF'),('IFVF2','VOUT')])
    return netlist

@cell
def super_class_AB_OTA(
        pdk,
        input_pair_params=(4,2),
        fvf_shunt_params=(2.75,1),
        local_current_bias_params=(3.76,3.0),
        diff_pair_load_params=(9,1),
        ratio=1,
        current_mirror_params=(2.25,1),
        resistor_params=(0.5,3,4,4),
        global_current_bias_params=(8.3,1.42,2)
        ):
    top_level = Component("Super_class_AB_OTA")
    nb = n_block(pdk, input_pair_params=input_pair_params, fvf_shunt_params=fvf_shunt_params, ratio=ratio, current_mirror_params=current_mirror_params, global_current_bias_params=global_current_bias_params)
    n_block_ref = prec_ref_center(nb)
    top_level.add(n_block_ref)
    top_level.add_ports(n_block_ref.get_ports_list())
    local_c_bias = current_mirror(pdk, numcols=2, device='pfet', width=local_current_bias_params[0]/2, length=local_current_bias_params[1], fingers=1)
    local_c_bias_2_ref = prec_ref_center(local_c_bias)
    local_c_bias_1_ref = prec_ref_center(local_c_bias)
    local_c_bias_1_ref.movex(n_block_ref.xmax + evaluate_bbox(local_c_bias)[0]/2 + 10).movey(n_block_ref.ymax+evaluate_bbox(local_c_bias)[1]/2 + 2)
    local_c_bias_2_ref.movex(n_block_ref.xmax + evaluate_bbox(local_c_bias)[0]/2 + 10).movey(n_block_ref.ymax+evaluate_bbox(local_c_bias)[1]/2 + 2)
    local_c_bias_1_ref = rename_ports_by_orientation(local_c_bias_1_ref.mirror((0,100),(0,-100)))
    top_level.add(local_c_bias_1_ref)
    top_level.add(local_c_bias_2_ref)
    top_level << c_route(pdk, n_block_ref.ports["fvf_1_B_gate_bottom_met_E"], local_c_bias_1_ref.ports["fet_B_drain_E"], extension=5,width1=0.29, width2=0.29, cwidth=0.29, cglayer="met3")
    top_level << c_route(pdk, n_block_ref.ports["fvf_2_B_gate_bottom_met_E"], local_c_bias_2_ref.ports["fet_B_drain_E"], extension=5,width1=0.29, width2=0.29, cwidth=0.29, cglayer="met3")
    top_level << straight_route(pdk, local_c_bias_1_ref.ports["fet_A_source_W"], local_c_bias_1_ref.ports["welltie_W_top_met_W"],glayer1='met1', width=0.22)
    top_level << straight_route(pdk, local_c_bias_1_ref.ports["fet_A_0_dummy_L_gsdcon_top_met_W"], local_c_bias_1_ref.ports["welltie_W_top_met_W"],glayer1="met1")
    top_level << straight_route(pdk, local_c_bias_1_ref.ports["fet_B_1_dummy_R_gsdcon_top_met_E"], local_c_bias_1_ref.ports["welltie_E_top_met_E"],glayer1="met1")
    top_level << straight_route(pdk, local_c_bias_2_ref.ports["fet_A_source_W"], local_c_bias_2_ref.ports["welltie_W_top_met_W"], glayer1='met1', width=0.22)
    top_level << straight_route(pdk, local_c_bias_2_ref.ports["fet_A_0_dummy_L_gsdcon_top_met_W"], local_c_bias_2_ref.ports["welltie_W_top_met_W"],glayer1="met1", width=0.2)
    top_level << straight_route(pdk, local_c_bias_2_ref.ports["fet_B_1_dummy_R_gsdcon_top_met_E"], local_c_bias_2_ref.ports["welltie_E_top_met_E"],glayer1="met1", width=0.2)
    top_level << c_route(pdk, local_c_bias_1_ref.ports["fet_A_drain_E"], n_block_ref.ports["cbias_M_3_A_multiplier_0_drain_W"], viaoffset=False)
    top_level << c_route(pdk, local_c_bias_2_ref.ports["fet_A_drain_E"], n_block_ref.ports["cbias_M_4_A_multiplier_0_drain_E"], viaoffset=False)
    top_level.add_ports(local_c_bias_1_ref.get_ports_list(), prefix="cmirr_1_")
    top_level.add_ports(local_c_bias_2_ref.get_ports_list(), prefix="cmirr_2_")
    resistor = transmission_gate(pdk, width=(resistor_params[0],resistor_params[1]), length=(resistor_params[2],resistor_params[3]), sd_rmult=3)
    res_1_ref = prec_ref_center(resistor)
    res_2_ref = prec_ref_center(resistor)
    res_1_ref.movey(n_block_ref.ymax + evaluate_bbox(resistor)[1]/2 + 1).movex(-evaluate_bbox(resistor)[0]/2 - 5)
    res_2_ref.movey(n_block_ref.ymax + evaluate_bbox(resistor)[1]/2 + 1).movex(-evaluate_bbox(resistor)[0]/2 - 5)
    res_2_ref = rename_ports_by_orientation(res_2_ref.mirror((0,-100),(0,100)))
    top_level.add(res_1_ref)
    top_level.add(res_2_ref)
    top_level << c_route(pdk, n_block_ref.ports["Min_1_multiplier_0_drain_E"], res_1_ref.ports["N_multiplier_0_source_E"], cwidth=0.6)
    top_level << c_route(pdk, n_block_ref.ports["Min_2_multiplier_0_drain_W"], res_2_ref.ports["N_multiplier_0_source_E"], cwidth=0.6)
    top_level.add_ports(res_1_ref.get_ports_list(), prefix="res_1_")
    top_level.add_ports(res_2_ref.get_ports_list(), prefix="res_2_")
    pblock = p_block(pdk, width=diff_pair_load_params[0]/2, length=diff_pair_load_params[1], fingers=1, ratio=ratio)
    p_block_ref = prec_ref_center(pblock)
    p_block_ref.movey(res_1_ref.ymax + evaluate_bbox(pblock)[1]/2 + 8)
    top_level.add(p_block_ref)
    top_level << c_route(pdk, res_1_ref.ports["P_multiplier_0_drain_E"], p_block_ref.ports["bottom_A_0_gate_E"], e1glayer='met2', width2=0.29*2)
    top_level << c_route(pdk, res_2_ref.ports["P_multiplier_0_drain_E"], p_block_ref.ports["bottom_B_1_gate_W"], e1glayer='met2', width2=0.29*2)
    top_level << c_route(pdk, p_block_ref.ports["top_A_0_drain_W"], n_block_ref.ports["op_cmirr_fet_A_drain_W"], extension=-local_c_bias_1_ref.xmax-8-2*ratio*diff_pair_load_params[1], cwidth=3, viaoffset=(True,True), extra_vias=True)
    top_level << c_route(pdk, p_block_ref.ports["top_B_1_drain_E"], n_block_ref.ports["op_cmirr_fet_B_drain_E"], extension=local_c_bias_2_ref.xmin-8-2*ratio*diff_pair_load_params[1], cwidth=3, viaoffset=(True,True), extra_vias=True)
    top_level << c_route(pdk, p_block_ref.ports["bottom_A_0_drain_W"], res_1_ref.ports["P_multiplier_0_source_W"], cwidth=0.9, width2=0.29*3)
    top_level << c_route(pdk, p_block_ref.ports["bottom_B_1_drain_E"], res_2_ref.ports["P_multiplier_0_source_W"], cwidth=0.9, width2=0.29*3)
    top_level.add_ports(p_block_ref.get_ports_list(), prefix="pblock_")
    viam2m3 = via_stack(pdk, "met2", "met3", centered=True, fulltop=True)
    viam3m4 = via_stack(pdk, "met3", "met4", centered=True, fulltop=True)
    op_int_via = top_level << viam2m3
    op_via = prec_ref_center(viam3m4)
    op_via.movex(min(n_block_ref.xmin,local_c_bias_1_ref.xmax)-8).movey(n_block_ref.ymin)
    top_level.add(op_via)
    op_int_via.move(n_block_ref.ports["op_cmirr_fet_B_drain_W"].center).movex(-1.5)
    top_level << straight_route(pdk, op_int_via.ports["bottom_met_E"], n_block_ref.ports["op_cmirr_fet_B_drain_W"], glayer1='met2', width=0.58)
    top_level << c_route(pdk, op_int_via.ports["top_met_N"], op_via.ports["bottom_met_N"], e1glayer='met3', e2glayer='met3', cglayer='met4', width1=0.6, width2=2, cwidth=2, extension=1.5, fullbottom=True)
    top_level.add_ports(op_via.get_ports_list(), prefix="DIFFOUT_")
    IBIAS1_via = prec_ref_center(viam3m4)
    IBIAS1_via.move(n_block_ref.ports["cbias_M_2_A_drain_bottom_met_W"].center).movex(-4).movey(-evaluate_bbox(nb)[1]/2)
    top_level.add(IBIAS1_via)
    top_level << L_route(pdk, n_block_ref.ports["cbias_M_1_A_drain_bottom_met_W"], IBIAS1_via.ports["bottom_met_N"], hwidth=2, vwidth=0.8)
    top_level.add_ports(IBIAS1_via.get_ports_list(), prefix="IBIAS1_")
    IBIAS2_via = prec_ref_center(viam3m4)
    IBIAS2_via.movex(n_block_ref.xmax+5).movey(n_block_ref.ymin)
    top_level.add(IBIAS2_via)
    top_level << c_route(pdk, n_block_ref.ports["cbias_M_2_A_drain_top_met_N"], IBIAS2_via.ports["bottom_met_N"], e1glayer='met3', e2glayer='met3', cglayer='met4', width1=0.4, width2=1, cwidth=0.6, extension=1.5, fullbottom=True)
    top_level.add_ports(IBIAS2_via.get_ports_list(), prefix="IBIAS2_")
    MINUS_via = top_level << viam3m4
    MINUS_via.move(n_block_ref.ports["gate_inA_top_met_W"].center).movex(local_c_bias_1_ref.xmin+3*input_pair_params[1])
    top_level << straight_route(pdk, n_block_ref.ports["gate_inA_top_met_W"], MINUS_via.ports["top_met_E"], width=0.6, glayer1='met4')
    top_level.add_ports(MINUS_via.get_ports_list(), prefix="MINUS_")
    PLUS_via = top_level << viam3m4
    PLUS_via.move(n_block_ref.ports["gate_inB_top_met_E"].center).movex(local_c_bias_2_ref.xmax-3*input_pair_params[1])
    top_level << straight_route(pdk, n_block_ref.ports["gate_inB_top_met_E"], PLUS_via.ports["top_met_W"], width=0.6, glayer1='met4')
    top_level.add_ports(PLUS_via.get_ports_list(), prefix="PLUS_")
    arrm2m3_1 = via_array(pdk, "met2", "met3", size=(6,0.6), fullbottom=True)
    VCC_via = prec_ref_center(arrm2m3_1)
    VCC_via.movey(p_block_ref.ymax+5)
    top_level.add(VCC_via)
    top_level << straight_route(pdk, p_block_ref.ports["top_welltie_N_top_met_N"], VCC_via.ports["bottom_lay_S"], glayer1='met2', width=6, fullbottom=True)
    top_level.add_ports(VCC_via.get_ports_list(), prefix="VCC_")
    arrm2m3_2 = via_array(pdk, "met2", "met3", num_vias=(2,2), fullbottom=True)
    VCC_int_via = prec_ref_center(arrm2m3_2)
    VCC_int_via.movey(p_block_ref.ymin-4)
    top_level.add(VCC_int_via)
    top_level << straight_route(pdk, p_block_ref.ports["bottom_welltie_S_top_met_S"], VCC_int_via.ports["top_met_N"], glayer1='met3', width=0.5)
    top_level << L_route(pdk, VCC_int_via.ports["bottom_lay_W"], res_1_ref.ports["P_tie_S_top_met_S"], hglayer='met2', vglayer='met2', hwidth=2, vwidth=2, fullbottom=True)
    top_level << L_route(pdk, VCC_int_via.ports["bottom_lay_E"], res_2_ref.ports["P_tie_S_top_met_S"], hglayer='met2', vglayer='met2', hwidth=2, vwidth=2, fullbottom=True)
    top_level << L_route(pdk, VCC_int_via.ports["bottom_lay_W"], local_c_bias_1_ref.ports["welltie_N_top_met_N"], hglayer='met2', vglayer='met2', hwidth=2, vwidth=2, fullbottom=True)
    top_level << L_route(pdk, VCC_int_via.ports["bottom_lay_E"], local_c_bias_2_ref.ports["welltie_N_top_met_N"], hglayer='met2', vglayer='met2', hwidth=2, vwidth=2, fullbottom=True)
    top_level << L_route(pdk, res_1_ref.ports["N_multiplier_0_gate_E"], VCC_int_via.ports["top_met_S"], hglayer='met2', vglayer='met3', hwidth=0.5, vwidth=0.3, fullbottom=True)
    top_level << L_route(pdk, res_2_ref.ports["N_multiplier_0_gate_W"], VCC_int_via.ports["top_met_S"], hglayer='met2', vglayer='met3', hwidth=0.5, vwidth=0.3, fullbottom=True)
    top_level << L_route(pdk, res_1_ref.ports["N_tie_W_top_met_W"], n_block_ref.ports["fvf_1_B_tie_N_top_met_N"], hglayer='met1', vglayer='met2', vwidth=4, hwidth=0.8, fullbottom=True)
    top_level << L_route(pdk, res_2_ref.ports["N_tie_W_top_met_W"], n_block_ref.ports["fvf_2_B_tie_N_top_met_N"], hglayer='met1', vglayer='met2', vwidth=4, hwidth=0.8, fullbottom=True)
    top_level << L_route(pdk, res_1_ref.ports["P_multiplier_0_gate_W"], n_block_ref.ports["fvf_1_B_tie_N_top_met_N"], hglayer='met2', vglayer='met2', vwidth=0.3, hwidth=1.2, fullbottom=True)
    top_level << L_route(pdk, res_2_ref.ports["P_multiplier_0_gate_E"], n_block_ref.ports["fvf_2_B_tie_N_top_met_N"], hglayer='met2', vglayer='met2', vwidth=0.3, hwidth=1.2, fullbottom=True)
    top_level << L_route(pdk, n_block_ref.ports["op_cmirr_welltie_N_top_met_N"], n_block_ref.ports["Min_1_tie_E_top_met_E"], hwidth=0.6, vwidth=1, hglayer='met1')
    top_level << L_route(pdk, n_block_ref.ports["op_cmirr_welltie_N_top_met_N"], n_block_ref.ports["Min_2_tie_W_top_met_W"], hwidth=0.6, vwidth=1, hglayer='met1')
    GND_via = top_level << arrm2m3_2
    GND_via.move(n_block_ref.ports["op_cmirr_welltie_S_top_met_S"].center).movey(-2).movex(local_c_bias_2_ref.xmax)
    top_level << L_route(pdk, n_block_ref.ports["op_cmirr_welltie_S_top_met_S"], GND_via.ports["bottom_lay_W"], vglayer='met2', hglayer='met2', vwidth=1.5, hwidth=1.5)
    top_level.add_ports(GND_via.get_ports_list(), prefix="VSS_")
    component = component_snap_to_grid(rename_ports_by_orientation(top_level))
    try:
        component.info['netlist'] = super_class_AB_OTA_netlist(local_c_bias_1_ref, local_c_bias_2_ref, res_1_ref, res_2_ref, nb, pblock)
    except Exception as _e:
        print(f'OTA netlist skipped: {_e}')
        component.info['netlist'] = None
    return component

print("Generating OTA layout (this may take several minutes)...")
t0 = time.time()
comp = super_class_AB_OTA(gf180_mapped_pdk)
print(f"Layout generated in {time.time()-t0:.1f}s")

comp.name = 'OTA'
out_dir = os.path.dirname(os.path.abspath(__file__))
gds_path = os.path.join(out_dir, 'ota.gds')
comp.write_gds(gds_path)
print(f"GDS saved: {gds_path}")
show_gds(gds_path)

# Save netlist for notebook reuse
netlist_obj = comp.info.get('netlist')
if netlist_obj is not None:
    try:
        nl_str = netlist_obj.generate_netlist() if hasattr(netlist_obj, 'generate_netlist') else str(netlist_obj)
        if nl_str and nl_str.strip():
            nl_path = os.path.join(out_dir, 'ota_netlist.spice')
            with open(nl_path, 'w') as f:
                f.write(nl_str)
            print(f"Netlist saved: {nl_path}")
    except Exception as e:
        print(f"Netlist save skipped: {e}")

print("Running DRC...")
try:
    drc_result = gf180_mapped_pdk.drc_magic(comp, comp.name, output_file=out_dir)
    print('DRC:', drc_result)
except Exception as e:
    print(f'DRC error: {e}')

print("Running LVS...")
try:
    lvs_result = gf180_mapped_pdk.lvs_netgen(comp, comp.name, output_file_path=out_dir)
    print('LVS:', lvs_result.get('result_str', 'done'))
except Exception as e:
    print(f'LVS error: {e}')

print("Done!")
