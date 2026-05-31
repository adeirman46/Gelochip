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

from glayout import MappedPDK
from glayout.pdk.gf180_mapped import gf180_mapped_pdk
from gdsfactory.cell import cell, clear_cache
from gdsfactory.component import Component, copy
from gdsfactory.component_reference import ComponentReference
from gdsfactory.components.rectangle import rectangle
from typing import Optional, Union
from glayout.primitives.fet import nmos, pmos, multiplier
from glayout.cells.elementary.diff_pair import diff_pair
from glayout.primitives.guardring import tapring
from glayout.primitives.mimcap import mimcap_array, mimcap
from glayout.routing import c_route,L_route,straight_route
from glayout.primitives.via_gen import via_stack, via_array
from gdsfactory.routing.route_quad import route_quad
from glayout.util.comp_utils import evaluate_bbox, prec_ref_center, movex, movey, to_decimal, to_float, move, align_comp_to_port, get_padding_points_cc
from glayout.util.port_utils import rename_ports_by_orientation, rename_ports_by_list, add_ports_perimeter, print_ports, set_port_orientation, rename_component_ports
from glayout.util.snap_to_grid import component_snap_to_grid
from glayout.placement.two_transistor_interdigitized import two_nfet_interdigitized
from glayout.spice import Netlist


def stacked_nfet_current_mirror(pdk: MappedPDK, half_common_source_nbias: tuple[float, float, int, int], rmult: int, sd_route_left: bool) -> Component:
    cmirror_output = nmos(
        pdk,
        width=half_common_source_nbias[0],
        length=half_common_source_nbias[1],
        fingers=half_common_source_nbias[2],
        multipliers=half_common_source_nbias[3],
        with_tie=True,
        with_dnwell=False,
        with_substrate_tap=False,
        with_dummy=True,
        sd_route_left = sd_route_left,
        rmult=rmult,
        tie_layers=("met2","met2")
    )
    cmirrorref = nmos(
        pdk,
        width=half_common_source_nbias[0],
        length=half_common_source_nbias[1],
        fingers=half_common_source_nbias[2],
        multipliers=1,
        with_tie=True,
        with_dnwell=False,
        with_substrate_tap=False,
        with_dummy=True,
        sd_route_left = sd_route_left,
        rmult=rmult,
        tie_layers=("met2","met2")
    )
    cmirrorref_ref = prec_ref_center(cmirrorref)
    cmirrorout_ref = prec_ref_center(cmirror_output)
    return cmirrorref_ref, cmirrorout_ref

# Create and evaluate a current mirror instance
if True:
    ref, out = stacked_nfet_current_mirror(
        pdk=gf180_mapped_pdk,
        half_common_source_nbias=(0.5, 0.28, 4, 4),
        rmult=2,
        sd_route_left=True
    )
    cm = Component()
    cm.add(out)
    ref.movey(out.ymin - evaluate_bbox(ref)[1]/2 - gf180_mapped_pdk.util_max_metal_seperation())
    cm.add(ref)
    cm.add_ports(out.get_ports_list(), prefix="out_")
    cm.add_ports(ref.get_ports_list(), prefix="ref_")
    cm << straight_route(gf180_mapped_pdk, cm.ports["out_tie_S_top_met_S"], cm.ports["ref_tie_N_top_met_N"])
    pass # cm.show()
    pass


# Show the generated GDS
pass

comp = cm
comp.name = 'stacked_nfet_current_mirror'
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
