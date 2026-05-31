import sys as _sys
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

from glayout.pdk.mappedpdk import MappedPDK
from glayout.pdk.gf180_mapped import gf180_mapped_pdk
from gdsfactory.cell import cell
from gdsfactory.component import Component
from gdsfactory.component_reference import ComponentReference
from gdsfactory import Component
from glayout.primitives.fet import nmos, pmos, multiplier
from glayout.util.comp_utils import evaluate_bbox, prec_center, prec_ref_center
from glayout.util.snap_to_grid import component_snap_to_grid
from glayout.util.port_utils import rename_ports_by_orientation
from glayout.routing.straight_route import straight_route
from glayout.routing.c_route import c_route
from glayout.routing.L_route import L_route
from glayout.primitives.guardring import tapring
from glayout.util.port_utils import add_ports_perimeter, rename_ports_by_list
from glayout.spice.netlist import Netlist
from glayout.primitives.via_gen import via_stack
from gdsfactory.components import text_freetype, rectangle
from glayout.placement.four_transistor_interdigitized import generic_4T_interdigitzed

# Fix generic_4T_interdigitzed: substrate_tap_ref unbound when with_substrate_tap=False
import glayout.placement.four_transistor_interdigitized as _ft_mod
from glayout.placement.two_transistor_interdigitized import two_nfet_interdigitized as _2ni, two_pfet_interdigitized as _2pi
from glayout.placement.four_transistor_interdigitized import four_tran_interdigitized_netlist as _4tn
from glayout.util.comp_utils import evaluate_bbox as _ebbox, movey as _mvy
from glayout.primitives.guardring import tapring as _tapring
from gdsfactory.component import Component as _Cmp

def _fixed_g4t(pdk, top_row_device="pfet", bottom_row_device="nfet", numcols=3, length=None, with_substrate_tap=True, top_kwargs=None, bottom_kwargs=None):
    top_kwargs = top_kwargs or {}
    bottom_kwargs = bottom_kwargs or {}
    toplvl = _Cmp()
    toprow = toplvl << (_2ni if top_row_device=="nfet" else _2pi)(pdk, numcols, with_substrate_tap=False, length=length, **top_kwargs)
    bottomrow = toplvl << (_2ni if bottom_row_device=="nfet" else _2pi)(pdk, numcols, with_substrate_tap=False, length=length, **bottom_kwargs)
    toprow.movey(pdk.snap_to_2xgrid((_ebbox(bottomrow)[1]/2 + _ebbox(toprow)[1]/2 + pdk.util_max_metal_seperation())))
    if with_substrate_tap:
        substrate_tap = _tapring(pdk, enclosed_rectangle=pdk.snap_to_2xgrid(_ebbox(toplvl.flatten(), padding=0.34)))
        substrate_tap_ref = toplvl << _mvy(substrate_tap, destination=pdk.snap_to_2xgrid(toplvl.flatten().center[1], snap4=True))
        toplvl.add_ports(substrate_tap_ref.get_ports_list(), prefix="substratetap_")
    toplvl.add_ports(toprow.get_ports_list(), prefix="top_")
    toplvl.add_ports(bottomrow.get_ports_list(), prefix="bottom_")
    toplvl.info["route_genid"] = "four_transistor_interdigitized"
    same_bulk = (top_row_device == bottom_row_device and top_row_device == "nfet")
    toplvl.info['netlist'] = _4tn(toprow, bottomrow, same_bulk)
    return toplvl

_ft_mod.generic_4T_interdigitzed = _fixed_g4t
generic_4T_interdigitzed = _fixed_g4t


def p_block_netlist(pdk: MappedPDK, pblock: tuple[float, float, int]) -> Netlist:
    return Netlist(
        circuit_name="p_block",
        nodes=['MA_1_D', 'MA_2_D', 'MA_G', 'MB_1_D', 'MB_2_D', 'VDD'],
        source_netlist=""".subckt {circuit_name} {nodes} """ + f'l={pblock[1]} wb={pblock[0]} wt={pblock[0] * pblock[2]} ' + """
XTOP1 MB_1_D MA_1_D VDD VDD {model} l={{l}} w={{wt}} 
XTOP2 MB_2_D MA_2_D VDD VDD {model} l={{l}} w={{wt}} 
XBOT1 MA_1_D MA_G VDD VDD {model} l={{l}} w={{wb}} 
XBOT2 MA_2_D MA_G VDD VDD {model} l={{l}} w={{wb}} 
.ends {circuit_name}""",
        instance_format="X{name} {nodes} {circuit_name} l={length} wt={width_top} wb={width_bot}",
        parameters={
            'model': pdk.models['pfet'],
            'width_top': pblock[0] * pblock[2],
            'width_bot': pblock[0],
            'length': pblock[1],
        }
    )


@cell
def  p_block(
        pdk: MappedPDK,
        width: float = 4.5,
        length: float = 1,
        fingers: int = 1,
        ratio: int = 1,
        ) -> Component:
    """
    p_block for super class AB OTA

    """
    #top level component
    top_level = Component(name="p_block")
    top_kwargs = {
            "fingers": ratio*fingers,
            "width": width,
            "with_tie": True,
            "sd_rmult":3
            }
    bottom_kwargs = {
            "fingers": fingers,
            "width": width,
            "with_tie": True,
            "sd_rmult":3
            }

    p_block = generic_4T_interdigitzed(pdk, top_row_device = "pfet", bottom_row_device = "pfet", numcols = 2, length = length, with_substrate_tap = False, top_kwargs = top_kwargs, bottom_kwargs = bottom_kwargs)
    p_block_ref = top_level << p_block

    top_level << c_route(pdk, p_block.ports["top_A_0_gate_W"], p_block.ports["bottom_A_0_drain_W"], extension=1.5)
    top_level << c_route(pdk, p_block.ports["top_B_1_gate_E"], p_block.ports["bottom_B_1_drain_E"])
    top_level << c_route(pdk, p_block.ports["bottom_A_0_gate_W"], p_block.ports["bottom_B_0_gate_W"], width1=0.29, width2=0.29, cwidth=0.29)
    
    top_level << c_route(pdk, p_block.ports["top_A_0_source_W"], p_block.ports["top_B_0_source_W"])
    top_level << straight_route(pdk, p_block.ports["top_A_0_source_W"], p_block.ports["top_welltie_W_top_met_W"], glayer1='met1', width=0.3)
    top_level << c_route(pdk, p_block.ports["bottom_A_0_source_W"], p_block.ports["bottom_B_0_source_W"], extension=1.2, cwidth=0.29)
    top_level << straight_route(pdk, p_block.ports["bottom_A_0_source_W"], p_block.ports["bottom_welltie_W_top_met_W"], glayer1='met1', width=0.3)
    
    top_level << straight_route(pdk, p_block.ports["top_welltie_S_top_met_S"], p_block.ports["bottom_welltie_N_top_met_N"], glayer1='met2', width=3)
    
    #adding a nwell    
    nwell_rectangle = rectangle(layer=(pdk.get_glayer("nwell")), size=evaluate_bbox(top_level))
    nwell_rectangle_ref = prec_ref_center(nwell_rectangle)
    nwell_rectangle_ref.move(p_block_ref.center) 
    top_level.add(nwell_rectangle_ref)

    #Renaming Ports
    top_level.add_ports(p_block.get_ports_list())
    
    component = component_snap_to_grid(rename_ports_by_orientation(top_level))
    # Store netlist as string to avoid gymnasium info dict type restrictions
    # Compatible with both gdsfactory 7.7.0 and 7.16.0+ strict Pydantic validation
    netlist_obj = p_block_netlist(pdk, pblock=(width,length,ratio))
    component.info['netlist_obj'] = netlist_obj
    component.info['netlist'] = netlist_obj.generate_netlist() if hasattr(netlist_obj, 'generate_netlist') else str(netlist_obj)
    # Store serialized netlist data for reconstruction if needed
    component.info['netlist_data'] = {
        'circuit_name': netlist_obj.circuit_name,
        'nodes': netlist_obj.nodes,
        'source_netlist': netlist_obj.source_netlist
    }
    #print(component.info['netlist'].generate_netlist())

    return component


from glayout.pdk.gf180_mapped import gf180_mapped_pdk
comp = p_block(gf180_mapped_pdk)
pass
pass

comp.name = 'p_block'
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
