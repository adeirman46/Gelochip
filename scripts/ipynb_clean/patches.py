"""Per-circuit faithful DRC-fix patches applied to the notebook-extracted source.
Each entry is a list of (old, new) string replacements. They must be minimal and
preserve the canonical ipynb layout/topology (only nudge vias, route widths, etc.)."""

PATCHES = {
    # fvf: (1) spread the two right-side met2->met3 vias apart so the via2/m2
    # region is >=0.28 (V2.1+2*V2.3); (2) source->tie route to met1 min width 0.23.
    "fvf": [
        ('drain_2_via.move(fet_2_ref.ports["multiplier_0_drain_W"].center).movex(-1.5)',
         'drain_2_via.move(fet_2_ref.ports["multiplier_0_drain_W"].center).movex(-2.5)'),
        ('gate_2_via.move(fet_2_ref.ports["multiplier_0_gate_E"].center).movex(1)',
         'gate_2_via.move(fet_2_ref.ports["multiplier_0_gate_E"].center).movex(2)'),
        ('glayer1=tie_layers2[1], width=0.2*sd_rmult, fullbottom=True)',
         'glayer1=tie_layers2[1], width=0.23, fullbottom=True)'),
    ],
    # p_block: (1) narrow the two source->welltie met1 routes 0.6->0.3 (M1.2a
    # spacing to welltie ring); (2) extend the left gate-drain c_route so its met3
    # crossbar clears the adjacent met3 (M3.2a spacing).
    "p_block": [
        ("glayer1='met1', width=0.6)", "glayer1='met1', width=0.3)"),
        ('c_route(pdk, p_block.ports["top_A_0_gate_W"], p_block.ports["bottom_A_0_drain_W"])',
         'c_route(pdk, p_block.ports["top_A_0_gate_W"], p_block.ports["bottom_A_0_drain_W"], extension=1.5)'),
    ],
    # low_voltage_cmirror: (1) the two source->tie met1 routes to min width 0.24
    # (M1.1); (2) spread the two gate c_route met2 crossbars so they clear (M2.2a).
    # (Library fvf via-spread fix handles the nested-fvf via2 errors.)
    "low_voltage_cmirror": [
        ("glayer1='met1', width=0.2)", "glayer1='met1', width=0.24)"),
        ("extension=(1.2*width[0]+0.6), cglayer='met2')", "extension=(1.2*width[0]+1.4), cglayer='met2')"),
        ("extension=(1.2*width[0]-0.6), cglayer='met2')", "extension=(1.2*width[0]-1.4), cglayer='met2')"),
    ],
    # stacked_current_mirror: the standalone notebook builds the nfet cmirror with
    # half_common_source_nbias=(0.5, 0.15, 4, 4) -> gate LENGTH 0.15um, a sky130
    # value that is illegal on gf180 (min channel length 0.28um). That single bad
    # length cascades into 464 device-layer errors (varactor misdetect, DF.1a
    # diffusion width, PL.4 poly overhang, CO.4 contact). The sibling
    # diff_pair_stackedcmirror calls the SAME cell with length 2.0 and is 0 DRC, so
    # the cell is fine — only this length is wrong. Bump 0.15 -> 0.28 (gf180 min L),
    # preserving the canonical 4x4 device topology.
    # Also: the standalone caller adds BOTH returned refs at prec_ref_center (same
    # origin) so the two nmos overlap completely -> the giant 12.9x21.3 active and
    # the varactor/diffusion-overlap cascade. Inside diff_pair_stackedcmirror the
    # parent places these refs apart and ties them; standalone never does. Reproduce
    # the canonical ipynb look (one tall integrated guard-ringed structure: the mult4
    # output on top, the mult1 ref below, joined by a tie route) by stacking them
    # vertically and routing tie-to-tie — same topology as the ipynb intent, but each
    # device sits in clear space so it is DRC-clean (no overlap).
    "stacked_current_mirror": [
        ("half_common_source_nbias=(0.5, 0.15, 4, 4)",
         "half_common_source_nbias=(0.5, 0.28, 4, 4)"),
        ("    cm = Component()\n    cm.add(ref)\n    cm.add(out)",
         "    cm = Component()\n    cm.add(out)\n"
         "    ref.movey(out.ymin - evaluate_bbox(ref)[1]/2 - gf180_mapped_pdk.util_max_metal_seperation())\n"
         "    cm.add(ref)\n"
         "    cm.add_ports(out.get_ports_list(), prefix=\"out_\")\n"
         "    cm.add_ports(ref.get_ports_list(), prefix=\"ref_\")\n"
         "    cm << straight_route(gf180_mapped_pdk, cm.ports[\"out_tie_S_top_met_S\"], cm.ports[\"ref_tie_N_top_met_N\"])"),
    ],
    # differential_to_single_ended_converter: (1) blanket nwell over the shared-gate
    # PMOS block (center-row pmos are bare multipliers with no nwell -> gf180
    # varactor/missing-nwell); (2) met2->met4 (met5 min-area 0.5625um2 is 4x others);
    # (3) push the output-bus drain c_route so it clears the adjacent met3 column.
    # Residual metal-spacing is cleared by the KLayout heal step in mkclean.
    "differential_to_single_ended_converter": [
        ("    pbottom_AB = (shared_gate_comps << twomultpcomps).movey(-1 * ytranslation_pcenter)",
         "    pbottom_AB = (shared_gate_comps << twomultpcomps).movey(-1 * ytranslation_pcenter)\n"
         "    shared_gate_comps.add_padding(layers=(pdk.get_glayer(\"nwell\"),), default=0.2)"),
        ('via_stack(pdk, "met2","met5",fullbottom=True)', 'via_stack(pdk, "met2","met4",fullbottom=True)'),
        ('    pcomps_route_B_drain_extension = shared_gate_comps.xmax-ptop_AB.ports["R_drain_E"].center[0]+_max_metal_seperation_ps',
         '    pcomps_route_B_drain_extension = shared_gate_comps.xmax-ptop_AB.ports["R_drain_E"].center[0]+_max_metal_seperation_ps+0.5'),
    ],
}

# The opamp-family notebooks patch `current_mirror_netlist` onto every module in a
# loop that can recurse infinitely outside Jupyter; it only renames netlist nodes
# (irrelevant for DRC). Neutralize the loop body so these build standalone.
_PATCH_CMN_LOOP = (
    "        for modname, mod in list(sys.modules.items()):\n"
    "            if hasattr(mod, 'current_mirror_netlist'):\n"
    "                setattr(mod, 'current_mirror_netlist', patched_cmn)",
    "        pass  # neutralized recursion-prone module patching (DRC doesn't need it)",
)
for _n in ("opamp", "opamp_twostage", "diff_pair_cmirrorbias"):
    PATCHES.setdefault(_n, []).append(_PATCH_CMN_LOOP)

# ota is special: it DEPENDS on the VOUT->VCOPY rename being propagated to the
# current-mirror sub-modules (it connect_netlist's with a 'VCOPY' node at the top
# level). Neutralizing the loop removes the rename -> "'VCOPY' is not in list".
# Instead of neutralizing, replace the sys.modules-walk (recursion-prone) with an
# explicit, non-recursive patch of the current_mirror source module so the rename
# still happens but the build doesn't blow the stack.
_PATCH_CMN_LOOP_OTA = (
    "        for modname, mod in list(sys.modules.items()):\n"
    "            if hasattr(mod, 'current_mirror_netlist'):\n"
    "                setattr(mod, 'current_mirror_netlist', patched_cmn)",
    # The real bug: the current_mirror() builder attaches its netlist by calling
    # current_mirror_interdigitized_netlist() DIRECTLY (current_mirror.py:208), not
    # via the current_mirror_netlist alias the notebook rebinds. So patch the real
    # function name too — that is what actually puts VCOPY/VB into the netlist.
    "        import glayout.cells.elementary.current_mirror.current_mirror as _cmm0\n"
    "        _cmm0.current_mirror_netlist = patched_cmn\n"
    "        _cmm0.current_mirror_interdigitized_netlist = patched_cmn",
)
# THE root cause of ota's "'VCOPY' is not in list": the top-of-cell patch grabs the
# current_mirror module via sys.modules[...], but that module isn't imported until
# ~60 lines later, so in a fresh (non-Jupyter) run the lookup KeyErrors, the bare
# try/except swallows it, and the entire VOUT->VCOPY / B->VB rename is silently
# skipped. Import the module explicitly so the patch actually installs.
_PATCH_CMN_IMPORT_OTA = (
    "    cm_mod = sys.modules['glayout.cells.elementary.current_mirror.current_mirror']",
    "    import importlib as _il\n"
    "    cm_mod = _il.import_module('glayout.cells.elementary.current_mirror.current_mirror')",
)
PATCHES.setdefault("ota", []).append(_PATCH_CMN_IMPORT_OTA)
PATCHES.setdefault("ota", []).append(_PATCH_CMN_LOOP_OTA)

# Belt-and-suspenders: the monkeypatch chain that renames the current_mirror nodes
# (VOUT->VCOPY, B->VB) is fragile across the deep OTA build (caching / which alias
# the builder calls). The two nodes OTA actually connects on are local_c_bias's, so
# force the rename directly on that component's netlist right after it is built —
# idempotent (skips if already renamed) and independent of the monkeypatch.
_PATCH_LCB_RENAME = (
    "    local_c_bias = current_mirror(pdk, numcols=2, device='pfet', width=local_current_bias_params[0]/2, length=local_current_bias_params[1], fingers=1)",
    "    local_c_bias = current_mirror(pdk, numcols=2, device='pfet', width=local_current_bias_params[0]/2, length=local_current_bias_params[1], fingers=1)\n"
    "    _lcb_nl = local_c_bias.info['netlist']\n"
    "    for _old, _new in (('VOUT', 'VCOPY'), ('B', 'VB')):\n"
    "        if _old in _lcb_nl.nodes:\n"
    "            _lcb_nl.nodes[_lcb_nl.nodes.index(_old)] = _new",
)
PATCHES.setdefault("ota", []).append(_PATCH_LCB_RENAME)

# THE actual uncaught crash (from the full traceback): n_block.py:26 n_block_netlist
# does `connect_netlist(cmirror.info['netlist'], [...,('VCOPY','OUT_N_2'),('VB','GND')])`
# — the cmirror INSIDE n_block never got the VOUT->VCOPY rename in a standalone run,
# and unlike OTA's top-level netlist call this one is NOT wrapped. The n_block GEOMETRY
# is already built (n_block.py:145) before this LVS-only call, and DRC needs only
# geometry (LVS isn't run), so make n_block_netlist non-fatal. The OTA notebook already
# monkeypatches the sibling low_voltage_cmirr_netlist the same way; mirror it. Scoped to
# the OTA build (patch lives in ota's clean source), so the n_block circuit is untouched.
_PATCH_NBLOCK_NL_OTA = (
    "    _lvcm_mod._patched_nl = True",
    "    _lvcm_mod._patched_nl = True\n"
    "\n"
    "import glayout.cells.composite.fvf_based_ota.n_block as _nb_mod\n"
    "if not hasattr(_nb_mod, '_patched_nbnl'):\n"
    "    _orig_nbnl = _nb_mod.n_block_netlist\n"
    "    def _safe_nbnl(*_a, **_k):\n"
    "        try:\n"
    "            return _orig_nbnl(*_a, **_k)\n"
    "        except Exception as _e:\n"
    "            print(f'n_block netlist skipped: {_e}')\n"
    "            from glayout.spice.netlist import Netlist as _NB_NL\n"
    "            _empty = _NB_NL(circuit_name='N_BLOCK', nodes=[])\n"
    "            _empty.source_netlist = ''\n"
    "            return _empty\n"
    "    _nb_mod.n_block_netlist = _safe_nbnl\n"
    "    _nb_mod._patched_nbnl = True",
)
PATCHES.setdefault("ota", []).append(_PATCH_NBLOCK_NL_OTA)

# Per-circuit util_sep override: opamp's met2/3/4 routing needs 0.6um separation so
# the corner (Euclidean) spacing violations become shaveable gaps for the heal step.
_UTILSEP_06 = (
    "from glayout.pdk.gf180_mapped import gf180_mapped_pdk",
    "from glayout.pdk.gf180_mapped import gf180_mapped_pdk\n"
    "import glayout.pdk.mappedpdk as _mp; _mp.GF180_MIN_METAL_SEP = 0.6",
)
for _n in ("opamp", "opamp_twostage"):
    PATCHES.setdefault(_n, []).insert(0, _UTILSEP_06)

# n_block: SOLVED. The residual 3 Via2-width came from an L_route corner dropping
# TWO via2 cuts diagonally offset by ~0.25um in BOTH axes; in Magic's derived
# contact (via2 & met2 & met3) the diagonal pair merges into a staircase whose
# re-entrant neck is 0.25 < 0.28 -> width error. An isolated 0.26 cut passes, so the
# fix is to re-align the staircase pair onto a common column (vertical stack). This
# is now a phase in glayout/util/drc_heal._align_staircase_vias (baked into the heal
# step), connectivity-safe (the moved cut must stay inside the met2&met3 overlap, so
# it bridges the exact same two nets). Diagnosed via fast DRC-only loop (~2s) on the
# already-built GDS instead of the ~40min rebuild. No per-circuit patch needed.


def apply(name, src):
    for old, new in PATCHES.get(name, []):
        if old not in src:
            print(f"[patch] {name}: anchor not found (skipped): {old[:55]!r}")
            continue
        src = src.replace(old, new)
    return src
