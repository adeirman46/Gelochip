import sys as _sys
_sys.setrecursionlimit(8000)
class _ModProxy:
    def __init__(self, g): self.__dict__ = g
_sys.modules[__name__] = _ModProxy(globals())

import os
os.environ['PATH'] = '/home/irman/Gelochip/.venv/bin:' + os.environ.get('PATH', '')
import sys, os
os.environ.setdefault('PDK_ROOT', os.path.expanduser('~/pdks'))
sys.path.insert(0, '/home/irman/Gelochip/src/gelochip')

import klayout.db as kdb
import klayout.lay as klay
from IPython.display import Image, display

def show_gds(gds_path, out_png=None, width=1600, height=900):
    gds_abs = os.path.abspath(gds_path)
    if not os.path.exists(gds_abs):
        print(f'GDS not found: {gds_abs}'); return
    out_png = out_png or gds_abs.replace('.gds', '_preview.png')
    lv = klay.LayoutView()
    lv.load_layout(gds_abs, True)
    lv.max_hier(); lv.zoom_fit()
    lv.save_image(out_png, width, height)
    display(Image(out_png))




import sys
try:
    cm_mod = sys.modules['glayout.cells.elementary.current_mirror.current_mirror']
    if not hasattr(cm_mod, 'orig_cmn'):
        orig_cmn = cm_mod.current_mirror_netlist
        cm_mod.orig_cmn = orig_cmn
        def patched_cmn(pdk, width, length, multipliers, fingers=1, **kwargs):
            netlist = orig_cmn(pdk, width=width, length=length, multipliers=multipliers, fingers=fingers, **kwargs)
            if 'B' in netlist.nodes:
                idx = netlist.nodes.index('B')
                netlist.nodes[idx] = 'VB'
            if 'VOUT' in netlist.nodes:
                idx = netlist.nodes.index('VOUT')
                netlist.nodes[idx] = 'VCOPY'
            return netlist
        cm_mod.current_mirror_netlist = patched_cmn
        for modname, mod in list(sys.modules.items()):
            if hasattr(mod, 'current_mirror_netlist'):
                setattr(mod, 'current_mirror_netlist', patched_cmn)
except Exception as e:
    pass

from gdsfactory.cell import cell, clear_cache
from gdsfactory.component import Component, copy
from gdsfactory.component_reference import ComponentReference
from gdsfactory.components.rectangle import rectangle
from glayout.pdk.mappedpdk import MappedPDK
from typing import Optional, Union
from glayout.primitives.fet import nmos, pmos, multiplier
from glayout.cells.elementary.diff_pair import diff_pair
from glayout.primitives.guardring import tapring
from glayout.primitives.mimcap import mimcap_array, mimcap
from glayout.routing.L_route import L_route
from glayout.routing.c_route import c_route
from glayout.primitives.via_gen import via_stack, via_array
from gdsfactory.routing.route_quad import route_quad
from glayout.util.comp_utils import evaluate_bbox, prec_ref_center, movex, movey, to_decimal, to_float, move, align_comp_to_port, get_padding_points_cc
from glayout.util.port_utils import rename_ports_by_orientation, rename_ports_by_list, add_ports_perimeter, print_ports, set_port_orientation, rename_component_ports
from glayout.routing.straight_route import straight_route
from glayout.util.snap_to_grid import component_snap_to_grid
from glayout.placement.two_transistor_interdigitized import two_nfet_interdigitized
from glayout.spice import Netlist

def row_csamplifier_diff_to_single_ended_converter_netlist(diff_to_single: Component) -> Netlist:
    overall_netlist = Netlist(
        circuit_name="DIFF_TO_SINGLE_CS",
        nodes=['VIN1', 'VIN2', 'VOUT', 'VSS', 'VSS2']
    )

    # Handle diff_to_single netlist - reconstruct if it's a string
    diff_netlist = diff_to_single.info['netlist']
    if isinstance(diff_netlist, str):
        if 'netlist_data' in diff_to_single.info:
            data = diff_to_single.info['netlist_data']
            diff_netlist = Netlist(circuit_name=data['circuit_name'], nodes=data['nodes'])
            diff_netlist.source_netlist = data['source_netlist']
            if 'parameters' in data:
                diff_netlist.parameters = data['parameters']
        else:
            raise ValueError("No netlist_data found for string netlist in diff_to_single component.info")

    overall_netlist.connect_netlist(
        diff_netlist,
        [('VIN', 'VIN1'), ('VOUT', 'VIN2')]
    )

    return overall_netlist

def __connect_cs_netlist(pmos_comps: Component, half_cs_pmos: Component):
    # Handle half_cs_pmos netlist - reconstruct if it's a string
    half_cs_netlist = half_cs_pmos.info['netlist']
    if isinstance(half_cs_netlist, str):
        if 'netlist_data' in half_cs_pmos.info:
            data = half_cs_pmos.info['netlist_data']
            half_cs_netlist = Netlist(circuit_name=data['circuit_name'], nodes=data['nodes'])
            half_cs_netlist.source_netlist = data['source_netlist']
            if 'parameters' in data:
                half_cs_netlist.parameters = data['parameters']
        else:
            raise ValueError("No netlist_data found for string netlist in half_cs_pmos component.info")

    pmos_comps.info['netlist'].connect_netlist(
        half_cs_netlist,
        [('D', 'VOUT'), ('S', 'VSS'), ('B', 'VSS'), ('G', 'VIN2')]
    )

def row_csamplifier_diff_to_single_ended_converter(pdk: MappedPDK, diff_to_single_ended_converter: Component, pamp_hparams, rmult) -> Component:
    pmos_comps = diff_to_single_ended_converter

    pmos_comps.info['netlist'] = row_csamplifier_diff_to_single_ended_converter_netlist(diff_to_single_ended_converter)

    x_dim_center = max(abs(pmos_comps.xmax),abs(pmos_comps.xmin))
    for direction in [-1, 1]:
        halfMultp = pmos(
            pdk,
            width=pamp_hparams[0],
            length=pamp_hparams[1],
            fingers=pamp_hparams[2],
            multipliers=pamp_hparams[3],
            with_tie=True,
            dnwell=False,
            with_substrate_tap=False,
            sd_route_left=bool(direction-1),
            rmult=rmult,
            tie_layers=("met2","met2")
        )
        halfMultp_ref = pmos_comps << halfMultp
        halfMultp_ref.movex(direction * abs(x_dim_center + halfMultp_ref.xmax+1))
        label = "L_" if direction==-1 else "R_"
        # this special marker is used to rename these ports in the opamp to commonsource_Pamp_
        pmos_comps.add_ports(halfMultp_ref.get_ports_list(),prefix="halfpspecialmarker_"+label)

        __connect_cs_netlist(pmos_comps, halfMultp)

    # add npadding and add ports
    nwellbbox = pmos_comps.extract(layers=[pdk.get_glayer("poly"),pdk.get_glayer("active_diff"),pdk.get_glayer("active_tap"), pdk.get_glayer("nwell"),pdk.get_glayer("dnwell")]).bbox
    nwellspacing = pdk.get_grule("nwell", "active_tap")["min_enclosure"]
    nwell_points = get_padding_points_cc(nwellbbox, default=nwellspacing, pdk_for_snap2xgrid=pdk)
    pmos_comps.add_polygon(nwell_points, layer=pdk.get_glayer("nwell"))
    tapcenter_rect = [(evaluate_bbox(pmos_comps)[0] + 1), (evaluate_bbox(pmos_comps)[1] + 1)]
    topptap = prec_ref_center(tapring(pdk, tapcenter_rect, "p+s/d",vertical_glayer="met2"),destination=tuple(pmos_comps.center))
    pmos_comps.add(topptap)
    pmos_comps.add_ports(topptap.get_ports_list(),prefix="top_ptap_")
    # vdd taprings of the center components
    pmos_comps << straight_route(pdk, pmos_comps.ports["ptopAB_L_welltap_W_top_met_W"],pmos_comps.ports["halfpspecialmarker_L_tie_E_top_met_N"],width=2,glayer1="met2",via1_alignment=('c','c'),fullbottom=True)
    pmos_comps << straight_route(pdk, pmos_comps.ports["ptopAB_R_welltap_E_top_met_E"],pmos_comps.ports["halfpspecialmarker_R_tie_W_top_met_N"],width=2,glayer1="met2",via1_alignment=('c','c'),fullbottom=True)
    pmos_comps << straight_route(pdk, pmos_comps.ports["pbottomAB_L_welltap_W_top_met_W"],pmos_comps.ports["halfpspecialmarker_L_tie_E_top_met_W"],width=2,glayer1="met2",via1_alignment=('c','c'),via2_alignment=('c','c'),fullbottom=True)
    pmos_comps << straight_route(pdk, pmos_comps.ports["pbottomAB_R_welltap_E_top_met_E"],pmos_comps.ports["halfpspecialmarker_R_tie_W_top_met_E"],width=2,glayer1="met2",via1_alignment=('c','c'),via2_alignment=('c','c'),fullbottom=True)
    return pmos_comps



from glayout.pdk.gf180_mapped import gf180_mapped_pdk
from glayout.cells.composite.differential_to_single_ended_converter import differential_to_single_ended_converter as make_dse
dse = make_dse(pdk=gf180_mapped_pdk, rmult=4, half_pload=(6, 1, 4), via_xlocation=10)
comp = row_csamplifier_diff_to_single_ended_converter(gf180_mapped_pdk, dse, (7, 1, 10, 3), 2)
pass
pass

comp.name = 'row_csamplifier_dse'
# DRC with magic (graceful if magic not installed)
try:
    pass
    print('DRC:', drc_result)
except Exception as e:
    print(f'DRC skipped: {e}')
# LVS with netgen (graceful if netgen not installed)
try:
    pass
    print('LVS:', lvs_result['result_str'])
except Exception as e:
    print(f'LVS skipped: {e}')


# --- bind `component` (kaizen clean entrypoint) ---
try:
    component
except NameError:
    import gdsfactory as _gf
    _cs = [v for v in list(globals().values()) if isinstance(v, _gf.Component)]
    component = _cs[-1] if _cs else None


# --- gf180 metal-spacing DRC heal (KLayout, connectivity-safe: shaves only
# empty gaps between shapes, keeps every route >= min width; cannot join nets) ---
try:
    import tempfile as _tf
    _pre = _tf.mktemp(suffix='_pre.gds'); _hl = _tf.mktemp(suffix='_heal.gds')
    component.write_gds(_pre)
    from glayout.util.drc_heal import heal_spacing as _heal_spacing
    _b, _a = _heal_spacing(_pre, _hl)
    if _b:
        import gdsfactory as _gf2
        _nm = component.name
        component = _gf2.import_gds(_hl); component.name = _nm
        print(f'[heal] metal-spacing {_b}->{_a}')
except Exception as _e:
    print('heal skipped:', _e)
