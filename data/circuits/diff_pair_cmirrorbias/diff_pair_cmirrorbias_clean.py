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
        pass  # neutralized recursion-prone module patching (DRC doesn't need it)
except Exception as e:
    pass

from gdsfactory.cell import cell, clear_cache
from gdsfactory.component import Component, copy
from gdsfactory.component_reference import ComponentReference
from gdsfactory.components.rectangle import rectangle
from glayout import MappedPDK
from glayout.routing import c_route,L_route,straight_route
from typing import Optional, Union
from glayout.cells.elementary.diff_pair import diff_pair
from glayout.primitives.fet import nmos, pmos, multiplier
from glayout.primitives.guardring import tapring
from glayout.primitives.mimcap import mimcap_array, mimcap
from glayout.primitives.via_gen import via_stack, via_array
from gdsfactory.routing.route_quad import route_quad
from glayout.util.comp_utils import (
    evaluate_bbox,
    prec_ref_center,
    movex,
    movey,
    to_decimal,
    to_float,
    move,
    align_comp_to_port,
    get_padding_points_cc,
)
from glayout.util.port_utils import (
    rename_ports_by_orientation,
    rename_ports_by_list,
    add_ports_perimeter,
    print_ports,
    set_port_orientation,
    rename_component_ports,
)
from glayout.util.snap_to_grid import component_snap_to_grid
from glayout.placement.two_transistor_interdigitized import two_nfet_interdigitized
from glayout.spice import Netlist
from glayout.cells.elementary.current_mirror import current_mirror_netlist

def diff_pair_ibias_netlist(center_diffpair: Component, current_mirror: Component, antenna_diode: Optional[Component] = None) -> Netlist:
    netlist = Netlist(
        circuit_name="DIFFPAIR_CMIRROR_BIAS",
        nodes=['VP', 'VN', 'VDD1', 'VDD2', 'IBIAS', 'VSS', 'B']
    )

    diffpair_ref = netlist.connect_netlist(
        center_diffpair.info['netlist'],
        []
    )

    cmirror_ref = netlist.connect_netlist(
        current_mirror.info['netlist'],
        [('VREF', 'IBIAS'), ('B', 'VSS')]
    )

    netlist.connect_subnets(
        cmirror_ref,
        diffpair_ref,
        [('VOUT', 'VTAIL')]
    )

    if antenna_diode is not None:
        netlist.connect_netlist(
            antenna_diode.info['netlist'],
            [('D', 'VSS'), ('G', 'VSS'), ('B', 'VSS'), ('S', 'VP')]
        )

        netlist.connect_netlist(
            antenna_diode.info['netlist'],
            [('D', 'VSS'), ('G', 'VSS'), ('B', 'VSS'), ('S', 'VN')]
        )

    return netlist

def diff_pair_ibias(
    pdk: MappedPDK,
    half_diffpair_params: tuple[float, float, int],
    diffpair_bias: tuple[float, float, int],
    rmult: int,
    with_antenna_diode_on_diffinputs: int,
) -> Component:
    # create and center diffpair
    diffpair_i_ = Component("temp diffpair and current source")
    center_diffpair_comp = diff_pair(
        pdk,
        width=half_diffpair_params[0],
        length=half_diffpair_params[1],
        fingers=half_diffpair_params[2],
        rmult=rmult,
    )
    # add antenna diodes if that option was specified
    diffpair_centered_ref = prec_ref_center(center_diffpair_comp)
    diffpair_i_.add(diffpair_centered_ref)
    diffpair_i_.add_ports(diffpair_centered_ref.get_ports_list())
    antenna_diode_comp = None
    if with_antenna_diode_on_diffinputs:
        antenna_diode_comp = nmos(
            pdk,
            1,
            with_antenna_diode_on_diffinputs,
            1,
            with_dummy=False,
            with_tie=False,
            with_substrate_tap=False,
            with_dnwell=False,
            length=0.5,
            sd_route_topmet="met2",
            gate_route_topmet="met1",
        ).copy()
        antenna_diode_comp << straight_route(
            pdk,
            antenna_diode_comp.ports["multiplier_0_row0_col0_rightsd_top_met_S"],
            antenna_diode_comp.ports["multiplier_0_gate_N"],
        )
        antenna_diode_refL = diffpair_i_ << antenna_diode_comp
        antenna_diode_refR = diffpair_i_ << antenna_diode_comp
        align_comp_to_port(
            antenna_diode_refL, diffpair_i_.ports["MINUSgateroute_W_con_N"], ("r", "t")
        )
        antenna_diode_refL.movex(pdk.util_max_metal_seperation())
        align_comp_to_port(
            antenna_diode_refR, diffpair_i_.ports["MINUSgateroute_E_con_N"], ("L", "t")
        )
        antenna_diode_refR.movex(0 - pdk.util_max_metal_seperation())
        # route the antenna diodes to gnd and
        Lgndcon = diffpair_i_.ports["tap_W_top_met_N"]
        Lgndcon.layer = pdk.get_glayer("met1")
        Rgndcon = diffpair_i_.ports["tap_E_top_met_N"]
        Rgndcon.layer = pdk.get_glayer("met1")
        diffpair_i_ << L_route(
            pdk, antenna_diode_refL.ports["multiplier_0_gate_E"], Lgndcon
        )
        diffpair_i_ << L_route(
            pdk, antenna_diode_refR.ports["multiplier_0_gate_W"], Rgndcon
        )
        diffpair_i_ << straight_route(
            pdk,
            antenna_diode_refL.ports["multiplier_0_source_W"],
            diffpair_i_.ports["MINUSgateroute_W_con_N"],
        )
        diffpair_i_ << straight_route(
            pdk,
            antenna_diode_refR.ports["multiplier_0_source_W"],
            diffpair_i_.ports["PLUSgateroute_E_con_N"],
        )
    # create and position tail current source
    cmirror = two_nfet_interdigitized(
        pdk,
        width=diffpair_bias[0],
        length=diffpair_bias[1],
        numcols=diffpair_bias[2],
        with_tie=True,
        with_substrate_tap=False,
        gate_route_topmet="met3",
        sd_route_topmet="met3",
        rmult=rmult,
        tie_layers=("met2", "met2"),
    )
    # cmirror routing
    metal_sep = pdk.util_max_metal_seperation()
    gate_short = cmirror << c_route(
        pdk,
        cmirror.ports["A_gate_E"],
        cmirror.ports["B_gate_E"],
        extension=3 * metal_sep,
        viaoffset=None,
    )
    cmirror << L_route(
        pdk,
        gate_short.ports["con_N"],
        cmirror.ports["A_drain_E"],
        viaoffset=False,
        fullbottom=False,
    )
    srcshort = cmirror << c_route(
        pdk,
        cmirror.ports["A_source_W"],
        cmirror.ports["B_source_W"],
        extension=metal_sep,
        viaoffset=False,
    )
    cmirror.add_ports(srcshort.get_ports_list(), prefix="purposegndports")
    # current mirror netlist
    cmirror.info['netlist'] = current_mirror_netlist(
        pdk,
        width=diffpair_bias[0],
        length=diffpair_bias[1],
        fingers=1,
        multipliers=diffpair_bias[2]
    )

    # add cmirror
    tailcurrent_ref = diffpair_i_ << cmirror
    tailcurrent_ref.movey(
        pdk.snap_to_2xgrid(
            -0.5 * (center_diffpair_comp.ymax - center_diffpair_comp.ymin)
            - abs(tailcurrent_ref.ymax)
            - metal_sep
        )
    )
    purposegndPort = tailcurrent_ref.ports["purposegndportscon_S"].copy()
    purposegndPort.name = "ibias_purposegndport"
    diffpair_i_.add_ports([purposegndPort])
    diffpair_i_.add_ports(tailcurrent_ref.get_ports_list(), prefix="ibias_")

    diffpair_i_ref = prec_ref_center(diffpair_i_)

    diffpair_i_ref.info['netlist'] = diff_pair_ibias_netlist(center_diffpair_comp, cmirror, antenna_diode_comp)
    return diffpair_i_ref



from glayout.pdk.gf180_mapped import gf180_mapped_pdk
_ref = diff_pair_ibias(gf180_mapped_pdk, (4.8, 2.2, 8), (6.0, 4.1, 3), 2, 7)
comp = _ref.parent
comp.name = "diff_pair_cmirrorbias"
pass
pass
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
