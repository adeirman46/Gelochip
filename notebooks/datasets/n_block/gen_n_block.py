#!/usr/bin/env python3
"""Generate n_block GDS layout (run directly, no nbconvert timeout)."""
import os, sys
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

from glayout.pdk.mappedpdk import MappedPDK
from glayout.pdk.gf180_mapped import gf180_mapped_pdk
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
from glayout.cells.composite.fvf_based_ota.low_voltage_cmirror import low_voltage_cmirror, low_voltage_cmirr_netlist

def n_block_netlist(fet_inA_ref, fet_inB_ref, fvf_1_ref, fvf_2_ref, cmirror, global_c_bias):
    netlist = Netlist(circuit_name='N_block', nodes=['IBIAS1', 'IBIAS2', 'GND', 'ILCM1', 'ILCM2', 'IFVF1','IFVF2', 'INP', 'INM', 'Min1_D', 'Min2_D', 'OUT_N_1', 'OUT_N_2'])
    netlist.connect_netlist(global_c_bias.info['netlist'], [('IBIAS1','IBIAS1'),('GND','GND'),('IBIAS2','IBIAS2'),('IOUT1','ILCM1'),('IOUT2','ILCM2')])
    # current_mirror has nodes ['VREF','VOUT','VSS','B'] — map to n_block top-level nodes
    netlist.connect_netlist(cmirror.info['netlist'], [('VREF','OUT_N_1'),('VOUT','OUT_N_2'),('VSS', 'GND'),('B','GND')])
    netlist.connect_netlist(fet_inA_ref.info['netlist'], [('D', 'Min1_D'),('G','INM'),('B','GND')])
    netlist.connect_netlist(fet_inB_ref.info['netlist'], [('D', 'Min2_D'),('G','INP'),('B','GND')])
    netlist.connect_netlist(fvf_1_ref.info['netlist'], [('VIN','INM'),('VOUT', 'INP'),('VBULK','GND'),('Ib','IFVF1')])
    netlist.connect_netlist(fvf_2_ref.info['netlist'], [('VIN','INP'),('VOUT', 'INM'),('VBULK','GND'),('Ib','IFVF2')])
    return netlist

@cell
def n_block(
        pdk,
        input_pair_params=(4,2),
        fvf_shunt_params=(2.75,1),
        current_mirror_params=(2.25,1),
        ratio=1,
        global_current_bias_params=(8.3,1.42,2)
        ):
    top_level = Component("n_block")
    fet_in = nmos(pdk, width=input_pair_params[0], length=input_pair_params[1], fingers=1, with_dnwell=False, with_tie=True, with_substrate_tap=False, sd_rmult=3)
    fet_inA_ref = prec_ref_center(fet_in)
    fet_inB_ref = prec_ref_center(fet_in)
    fet_inA_ref.movex(-evaluate_bbox(fet_in)[0]/2 - pdk.util_max_metal_seperation())
    fet_inB_ref.movex(evaluate_bbox(fet_in)[0]/2 + pdk.util_max_metal_seperation())
    top_level.add(fet_inA_ref)
    top_level.add(fet_inB_ref)
    viam2m3 = via_stack(pdk, "met2", "met3", centered=True)
    viam3m4 = via_stack(pdk, "met3", "met4", centered=True)
    gate_inA_via = top_level << viam3m4
    gate_inB_via = top_level << viam3m4
    source_inA_via = top_level << viam2m3
    source_inB_via = top_level << viam2m3
    gate_inA_via.move(fet_inA_ref.ports["multiplier_0_gate_W"].center).movex(-evaluate_bbox(fet_in)[0]/4).movey(-evaluate_bbox(fet_in)[1]/2)
    gate_inB_via.move(fet_inB_ref.ports["multiplier_0_gate_E"].center).movex(evaluate_bbox(fet_in)[0]/4).movey(-evaluate_bbox(fet_in)[1]/2)
    source_inA_via.move(fet_inA_ref.ports["multiplier_0_source_W"].center).movex(-evaluate_bbox(fet_in)[0]/4)
    source_inB_via.move(fet_inB_ref.ports["multiplier_0_source_E"].center).movex(evaluate_bbox(fet_in)[0]/4)
    top_level << L_route(pdk, fet_inA_ref.ports["multiplier_0_gate_W"], gate_inA_via.ports["bottom_met_N"], hglayer="met2", vglayer="met3")
    top_level << L_route(pdk, fet_inB_ref.ports["multiplier_0_gate_E"], gate_inB_via.ports["bottom_met_N"], hglayer="met2", vglayer="met3")
    top_level << straight_route(pdk, fet_inA_ref.ports["multiplier_0_source_W"], source_inA_via.ports["bottom_met_E"], width=0.29*2)
    top_level << straight_route(pdk, fet_inB_ref.ports["multiplier_0_source_E"], source_inB_via.ports["bottom_met_W"], width=0.29*2)
    top_level.add_ports(fet_inA_ref.get_ports_list(), prefix="Min_1_")
    top_level.add_ports(fet_inB_ref.get_ports_list(), prefix="Min_2_")
    top_level.add_ports(gate_inA_via.get_ports_list(), prefix="gate_inA_")
    top_level.add_ports(gate_inB_via.get_ports_list(), prefix="gate_inB_")
    fvf = flipped_voltage_follower(pdk, width=(input_pair_params[0],fvf_shunt_params[0]), length=(input_pair_params[1],fvf_shunt_params[1]), fingers=(1,1), sd_rmult=3, with_dnwell=False)
    fvf_1_ref = prec_ref_center(fvf)
    fvf_2_ref = prec_ref_center(fvf)
    fvf_1_ref.movex(fet_inB_ref.xmax + evaluate_bbox(fvf)[0]/2 + pdk.util_max_metal_seperation())
    fvf_2_ref.movex(fet_inB_ref.xmax + evaluate_bbox(fvf)[0]/2 + pdk.util_max_metal_seperation())
    fvf_1_ref = rename_ports_by_orientation(fvf_1_ref.mirror((0,-100),(0,100)))
    top_level.add(fvf_1_ref)
    top_level.add(fvf_2_ref)
    gate_fvf_1A_via = top_level << viam2m3
    gate_fvf_2A_via = top_level << viam2m3
    gate_fvf_1A_via.move(fvf_1_ref.ports["A_multiplier_0_gate_S"].center).movex(-evaluate_bbox(fet_in)[0]/4).movey(-evaluate_bbox(fet_in)[1]/1.5)
    gate_fvf_2A_via.move(fvf_2_ref.ports["A_multiplier_0_gate_S"].center).movex(evaluate_bbox(fet_in)[0]/4).movey(-evaluate_bbox(fet_in)[1]/1.5)
    top_level << L_route(pdk, fvf_1_ref.ports["A_multiplier_0_gate_E"], gate_fvf_1A_via.ports["top_met_N"], hglayer="met2", vglayer="met3")
    top_level << L_route(pdk, fvf_2_ref.ports["A_multiplier_0_gate_E"], gate_fvf_2A_via.ports["top_met_N"], hglayer="met2", vglayer="met3")
    top_level << L_route(pdk, gate_inA_via.ports["bottom_met_S"], gate_fvf_1A_via.ports["top_met_E"], hglayer="met2", vglayer="met3")
    top_level << L_route(pdk, gate_inB_via.ports["bottom_met_S"], gate_fvf_2A_via.ports["top_met_W"], hglayer="met2", vglayer="met3")
    top_level << c_route(pdk, source_inA_via.ports["top_met_N"], fvf_2_ref.ports["A_source_top_met_N"], extension=0.8*evaluate_bbox(fet_in)[1], width1=0.4, width2=0.4, cwidth=0.5, e1glayer="met3", e2glayer="met3", cglayer="met2")
    top_level << c_route(pdk, source_inB_via.ports["top_met_N"], fvf_1_ref.ports["A_source_top_met_N"], extension=1.1*evaluate_bbox(fet_in)[1], width1=0.4, width2=0.4, cwidth=0.5, e1glayer="met3", e2glayer="met3", cglayer="met2")
    top_level.add_ports(fvf_1_ref.get_ports_list(), prefix="fvf_1_")
    top_level.add_ports(fvf_2_ref.get_ports_list(), prefix="fvf_2_")
    cmirror = current_mirror(pdk, numcols=2, with_substrate_tap=False, width=current_mirror_params[0], length=current_mirror_params[1], fingers=ratio, sd_rmult=3)
    cmirr_ref = prec_ref_center(cmirror)
    cmirr_ref.movey(fvf_1_ref.ymin - (evaluate_bbox(cmirror)[1] + evaluate_bbox(fvf)[1])/2)
    top_level.add(cmirr_ref)
    top_level << straight_route(pdk, cmirr_ref.ports["fet_A_source_W"], cmirr_ref.ports["welltie_W_top_met_W"], glayer1='met1', width=0.6)
    top_level << straight_route(pdk, cmirr_ref.ports["fet_A_0_dummy_L_gsdcon_top_met_W"],cmirr_ref.ports["welltie_W_top_met_W"],glayer1="met1", width=0.5)
    top_level << straight_route(pdk, cmirr_ref.ports["fet_B_1_dummy_R_gsdcon_top_met_E"],cmirr_ref.ports["welltie_E_top_met_E"],glayer1="met1", width=0.5)
    top_level.add_ports(cmirr_ref.get_ports_list(), prefix="op_cmirr_")
    global_c_bias = low_voltage_cmirror(pdk, width=(global_current_bias_params[0]/2,global_current_bias_params[1]), length=global_current_bias_params[2], fingers=(2,1))
    global_c_bias_ref = prec_ref_center(global_c_bias)
    global_c_bias_ref.movey(cmirr_ref.ymin - evaluate_bbox(global_c_bias)[1]/2 - 8*pdk.util_max_metal_seperation())
    top_level.add(global_c_bias_ref)
    top_level.add_ports(global_c_bias_ref.get_ports_list(), prefix="cbias_")
    fet_1 = nmos(pdk, width=input_pair_params[0], length=input_pair_params[1], fingers=1, with_dnwell=False, with_tie=True, with_substrate_tap=False, sd_rmult=3)
    fet_2 = nmos(pdk, width=input_pair_params[0], length=input_pair_params[1], fingers=1, with_dnwell=False, with_tie=True, with_substrate_tap=False, sd_rmult=3)
    fvf_1 = flipped_voltage_follower(pdk, width=(input_pair_params[0],fvf_shunt_params[0]), length=(input_pair_params[1],fvf_shunt_params[1]), fingers=(1,1), sd_rmult=3, with_dnwell=False)
    fvf_2 = flipped_voltage_follower(pdk, width=(input_pair_params[0],fvf_shunt_params[0]), length=(input_pair_params[1],fvf_shunt_params[1]), fingers=(1,1), sd_rmult=3, with_dnwell=False)
    component = component_snap_to_grid(rename_ports_by_orientation(top_level))
    try:
        netlist_obj = n_block_netlist(fet_inA_ref, fet_inB_ref, fvf_1_ref, fvf_2_ref, cmirror, global_c_bias)
        component.info['netlist'] = str(netlist_obj)
    except Exception as _e:
        print(f'n_block netlist skipped: {_e}')
        component.info['netlist'] = ''
    return component

print("Generating n_block layout...")
import time
t0 = time.time()
comp = n_block(gf180_mapped_pdk)
print(f"Layout generated in {time.time()-t0:.1f}s")

comp.name = 'N_BLOCK'
out_dir = os.path.dirname(os.path.abspath(__file__))
gds_path = os.path.join(out_dir, 'n_block.gds')
comp.write_gds(gds_path)
print(f"GDS saved: {gds_path}")
show_gds(gds_path)

# Save netlist for notebook reuse
netlist_str = comp.info.get('netlist', '')
if netlist_str and isinstance(netlist_str, str):
    nl_path = os.path.join(out_dir, 'n_block_netlist.spice')
    with open(nl_path, 'w') as f:
        f.write(netlist_str)
    print(f"Netlist saved: {nl_path}")
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
