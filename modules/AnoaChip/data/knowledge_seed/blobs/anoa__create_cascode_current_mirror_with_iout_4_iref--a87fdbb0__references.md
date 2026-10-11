## ref 0 — layout-error:create_a_cascode_current_mirror_with_iout_4_x_ir--39523e70
GLAYOUT LAYOUT ERROR for 'create a cascode current mirror with IOUT = 4 x IREF (ratio 1:4, gf180mcuD). The transient must show both branch current' (top `cascode_mirror`):
TypeError: Label() argument 7 must be int, not tuple

Full context:
BUILD: Traceback (most recent call last):
  File "/home/irman/AnoaChip/src/anoa_chip/glayout_harness.py", line 157, in main
    comp = build(pdk)
           ^^^^^^^^^^
  File "/home/irman/AnoaChip/output/create_a_cascode_current_mirror_with_iout_4_x_ir--39523e70/layout/cascode_mirror.py", line 94, in build
    comp.add(gdstk.Label("IREF", origin=comp.ports["IREF"].center, layer=label_layer))
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
TypeError: Label() argument 7 must be int, not tuple


When this recurs: fix it in layout/<top>.py or the config BEFORE rebuilding.

## ref 1 — layout-error:create_a_cascode_current_mirror_with_iout_4_x_ir--39523e70
GLAYOUT LAYOUT ERROR for 'create a cascode current mirror with IOUT = 4 x IREF (ratio 1:4, gf180mcuD). The transient must show both branch current' (top `cascode_mirror`):
KeyError: 'label'

Full context:
BUILD: Traceback (most recent call last):
  File "/home/irman/AnoaChip/src/anoa_chip/glayout_harness.py", line 157, in main
    comp = build(pdk)
           ^^^^^^^^^^
  File "/home/irman/AnoaChip/output/create_a_cascode_current_mirror_with_iout_4_x_ir--39523e70/layout/cascode_mirror.py", line 88, in build
    label_layer = pdk.get_glayer("label")
                  ^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/irman/AnoaChip/.venv/lib/python3.12/site-packages/pydantic/deprecated/decorator.py", line 56, in wrapper_function
    return vd.call(*args, **kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/irman/AnoaChip/.venv/lib/python3.12/site-packages/pydantic/deprecated/decorator.py", line 151, in call
    return self.execute(m)
           ^^^^^^^^^^^^^^^
  File "/home/irman/AnoaChip/.venv/lib/python3.12/site-packages/pydantic/deprecated/decorator.py", line 227, in execute
    return self.raw_function(**d, **var_kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/irman/gLayout/src/glayout/pdk/mappedpdk.py", line 1006, in get_glayer
    direct_mapping = self.glayers[layer]
                     ~~~~~~~~~~~~^^^^^^^
KeyError: 'label'


When this recurs: fix it in layout/<top>.py or the config BEFORE rebuilding.

## ref 2 — layout-error:create_a_cascode_current_mirror_with_iout_4_x_ir--39523e70
GLAYOUT LAYOUT ERROR for 'create a cascode current mirror with IOUT = 4 x IREF (ratio 1:4, gf180mcuD). The transient must show both branch current' (top `cascode_mirror`):
ValueError: LVS report not found!

Full context:
LVS ERROR: Traceback (most recent call last):
  File "/home/irman/AnoaChip/src/anoa_chip/glayout_harness.py", line 231, in main
    pdk.lvs_netgen(layout=comp, design_name=name,
  File "/home/irman/AnoaChip/.venv/lib/python3.12/site-packages/pydantic/deprecated/decorator.py", line 56, in wrapper_function
    return vd.call(*args, **kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/irman/AnoaChip/.venv/lib/python3.12/site-packages/pydantic/deprecated/decorator.py", line 151, in call
    return self.execute(m)
           ^^^^^^^^^^^^^^^
  File "/home/irman/AnoaChip/.venv/lib/python3.12/site-packages/pydantic/deprecated/decorator.py", line 227, in execute
    return self.raw_function(**d, **var_kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/irman/gLayout/src/glayout/pdk/mappedpdk.py", line 907, in lvs_netgen
    raise ValueError("LVS report not found!")
ValueError: LVS report not found!


When this recurs: fix it in layout/<top>.py or the config BEFORE rebuilding.

## ref 3 — anoachip-validated (DRC+LVS pass on gf180mcuD)
A cascode mirror = a simple mirror PLUS a stacked cascode pair for high output resistance (Rout ≈ gm·ro²). Layout reasoning: bottom row = mirror pair M1(ref,diode)/M2(out); top row = cascode pair M3(ref,diode)/M4(out). generic_4T_interdigitzed places both rows pre-spaced with a netlist. Nets: ref branch IREF→M3.d, M3.s→M1.d (N1), M1.s→rail; out branch IOUT→M4.d, M4.s→M2.d (N2), M2.s→rail; gates: M3.g=M4.g=IREF (top diode), M1.g=M2.g=N1 (bottom diode). Routing sides: rail short + both stack routes on E (nested 3/6/9·ms); both gate shorts + diodes on W (nested 3/6·ms). Compliance: needs Vgs+Vov headroom; wide-swing variant re-biases the cascode gates from a separate branch (see glayout low_voltage_cmirror).

## ref 4 — anoachip-validated
# cascode_mirror — 1:4 cascode current mirror (nfet): IOUT = 4 x IREF.
# ARCHITECTURE: one interdigitized PAIR PER BRANCH (glayout's proven placer, edge ports):
#   ref branch  = two_nfet_interdigitized(numcols=K):        A = M1 (mirror), B = M3 (cascode)
#   out branch  = two_nfet_interdigitized(numcols=K*4): A = M2, B = M4
# -> every device is the SAME unit cell; the output branch simply has 4x more unit
# cells, the textbook unit-cell way to build an exact 1:4 ratio. Both cells have the
# same height, ports at the edges, no route ever crosses a device.
from glayout import MappedPDK
from glayout.placement.two_transistor_interdigitized import (two_nfet_interdigitized,
                                                             two_pfet_interdigitized)
from glayout.primitives.guardring import tapring
from glayout.routing.c_route import c_route
from glayout.routing.straight_route import straight_route
from glayout.spice.netlist import Netlist
from glayout.util.comp_utils import evaluate_bbox, prec_center
from glayout.backend import Component
import gdstk

_pair = two_nfet_interdigitized


def build(pdk: MappedPDK) -> Component:
    W, L, NF, K, RATIO = 4.0, 1.0, 1, 1, 4
    comp = Component(name="cascode_mirror")
    ms = pdk.util_max_metal_seperation()

    # dummies OUTSIDE only — the facing (gap) edges stay dummy-free so the cross-gap
    # routes have a clean channel (a gap-side dummy showers M1/poly spacing errors)
    refc = _pair(pdk, numcols=K, dummy=(True, False), width=W, length=L, fingers=NF,
                 with_tie=False, with_substrate_tap=False)
    outc = _pair(pdk, numcols=K * RATIO, dummy=(False, True), width=W, length=L, fingers=NF,
                 with_tie=False, with_substrate_tap=False)
    ref = comp << refc                                  # A=M1 mirror, B=M3 cascode
    out = comp << outc                                  # A=M2 mirror, B=M4 cascode
    out.movex(evaluate_bbox(refc)[0] / 2 + evaluate_bbox(outc)[0] / 2 + 4 * ms)

    # ---- 

## ref 5 — layout-error:cascode_current_mirror_1_4--8cb4a85f
GLAYOUT LAYOUT ERROR for 'Cascode current mirror 1:4' (top `cascode_mirror_1x4`):
ValueError:

Full context:
BUILD: Traceback (most recent call last):
  File "/home/irman/AnoaChip/src/anoa_chip/glayout_harness.py", line 157, in main
    comp = build(pdk)
           ^^^^^^^^^^
  File "/home/irman/AnoaChip/output/cascode_current_mirror_1_4--8cb4a85f/layout/cascode_mirror_1x4.py", line 71, in build
    comp.movey(destination=-(comp.ymax + comp.ymin) / 2)
  File "/home/irman/AnoaChip/.venv/lib/python3.12/site-packages/gdsfactory/component_layout.py", line 333, in movey
    return self.move(origin=(0, origin), destination=(0, destination))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/irman/AnoaChip/.venv/lib/python3.12/site-packages/gdsfactory/component.py", line 2046, in move
    raise ValueError(move_error_message)
ValueError: 
You cannot move a Component. You can create a new Component, add a reference to the other Component and then move the reference.

For example:

# BAD
c = gf.components.straight()
c.xmin = 10

# GOOD
c = gf.Component()
ref = c.add_ref(gf.components.straight()) # or ref = c << gf.components.straight()
ref.xmin = 10



When this recurs: fix it in layout/<top>.py or the config BEFORE rebuilding.

## ref 6 — layout-error:cascode_current_mirror_1_4--8cb4a85f
GLAYOUT LAYOUT ERROR for 'Cascode current mirror 1:4' (top `cascode_mirror_1x4`):
KeyError: 'text'

Full context:
BUILD: Traceback (most recent call last):
  File "/home/irman/AnoaChip/src/anoa_chip/glayout_harness.py", line 157, in main
    comp = build(pdk)
           ^^^^^^^^^^
  File "/home/irman/AnoaChip/output/cascode_current_mirror_1_4--8cb4a85f/layout/cascode_mirror_1x4.py", line 66, in build
    label_layer = pdk.get_glayer("text")
                  ^^^^^^^^^^^^^^^^^^^^^^
  File "/home/irman/AnoaChip/.venv/lib/python3.12/site-packages/pydantic/deprecated/decorator.py", line 56, in wrapper_function
    return vd.call(*args, **kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/irman/AnoaChip/.venv/lib/python3.12/site-packages/pydantic/deprecated/decorator.py", line 151, in call
    return self.execute(m)
           ^^^^^^^^^^^^^^^
  File "/home/irman/AnoaChip/.venv/lib/python3.12/site-packages/pydantic/deprecated/decorator.py", line 227, in execute
    return self.raw_function(**d, **var_kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/irman/gLayout/src/glayout/pdk/mappedpdk.py", line 1006, in get_glayer
    direct_mapping = self.glayers[layer]
                     ~~~~~~~~~~~~^^^^^^^
KeyError: 'text'


When this recurs: fix it in layout/<top>.py or the config BEFORE rebuilding.

## ref 7 — layout-error:cascode_current_mirror_1_4--8cb4a85f
GLAYOUT LAYOUT ERROR for 'Cascode current mirror 1:4' (top `cascode_mirror_1x4`):
KeyError: 'label'

Full context:
BUILD: Traceback (most recent call last):
  File "/home/irman/AnoaChip/src/anoa_chip/glayout_harness.py", line 157, in main
    comp = build(pdk)
           ^^^^^^^^^^
  File "/home/irman/AnoaChip/output/cascode_current_mirror_1_4--8cb4a85f/layout/cascode_mirror_1x4.py", line 78, in build
    label_layer = pdk.get_glayer("label")
                  ^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/irman/AnoaChip/.venv/lib/python3.12/site-packages/pydantic/deprecated/decorator.py", line 56, in wrapper_function
    return vd.call(*args, **kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/irman/AnoaChip/.venv/lib/python3.12/site-packages/pydantic/deprecated/decorator.py", line 151, in call
    return self.execute(m)
           ^^^^^^^^^^^^^^^
  File "/home/irman/AnoaChip/.venv/lib/python3.12/site-packages/pydantic/deprecated/decorator.py", line 227, in execute
    return self.raw_function(**d, **var_kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/irman/gLayout/src/glayout/pdk/mappedpdk.py", line 1006, in get_glayer
    direct_mapping = self.glayers[layer]
                     ~~~~~~~~~~~~^^^^^^^
KeyError: 'label'


When this recurs: fix it in layout/<top>.py or the config BEFORE rebuilding.

## ref 8 — https://github.com/daniellovell/AMSDesignBench
// ===== AMSDesignBench/data/dev/templates/ota/ota001/netlist.sp =====
M1 n1 vinp ntail 0 nch W=2u L=0.18u
M2 n2 vinn ntail 0 nch W=2u L=0.18u
Mtail ntail vbias_n 0 0 nch W=1u L=0.5u
Mp1 vout n2 VDD VDD pch W=4u L=0.18u
Mp2 n1 n1 VDD VDD pch W=4u L=0.18u
VDD VDD 0 1.8
Cload vout 0 1p



// ===== AMSDesignBench/data/dev/templates/ota/ota002/netlist.sp =====
M3 N003 vip N005 0 nch W=2u L=0.18u
M4 N004 vin N005 0 nch W=2u L=0.18u
M2 von vb3 N003 0 nch W=1u L=0.18u
M1 vop vb3 N004 0 nch W=1u L=0.18u
M5 N005 vtail 0 0 nch W=1u L=0.5u
M6 von vb2 N001 VDD pch W=2u L=0.18u
M7 vop vb2 N002 VDD pch W=2u L=0.18u
M8 N001 vb1 VDD VDD pch W=4u L=0.18u
M9 N002 vb1 VDD VDD pch W=4u L=0.18u
C1 vop 0 1p
C2 von 0 1p
VDD VDD 0 1.8


// ===== AMSDesignBench/data/dev/templates/ota/ota003/netlist.sp =====
M1 n1 vinp ntail 0 nch W=2u L=0.18u
M2 n2 vinn ntail 0 nch W=2u L=0.18u
Mtail ntail vbias_n 0 0 nch W=1u L=0.5u
M3 n1 n1 VDD VDD pch W=2u L=0.18u      
M4 n2 n1 VDD VDD pch W=2u L=0.18u
M5 nmir n1 VDD VDD pch W=4u L=0.18u
M6 vout n1 VDD VDD pch W=4u L=0.18u
M7 nmir nmir 0 0 nch W=2u L=0.18u  
M8 vout nmir 0 0 nch W=2u L=0.18u  

VDD VDD 0 1.8
Cload vout 0 1p



// ===== AMSDesignBench/data/dev/templates/ota/ota004/netlist.sp =====

VDD vdd 0 1.8
VBP vbp 0 0.9
VBN vbn 0 0.7
VINP vinp 0 0
VINN vinn 0 0

Cload vout 0 1p

M1 n1   vinp ntail 0 NMOS W=10u L=0.18u
M2 vint vinn ntail 0 NMOS W=10u L=0.18u   
M3 n1   n1   vdd   vdd PMOS W=20u L=0.18u   
M4 vint n1   vdd   vdd PMOS W=20u L=0.18u   
M5 ntail vbn  0     0 NMOS W=5u  L=0.18u    

M6 vout vint 0     0 NMOS W=40u L=0.18u
M7 vout vbp vdd   vdd PMOS W=40u L=0.18u



// ===== AMSDesignBench/data/dev/templates/ota/ota005/netlist.sp =====
M3 N004 vip N006 0 nch W=2u L=0.18u
M4 N005 vin N006 0 nch W=2u L=0.18u
M1 vop vb3 N005 0 nch W=1u L=0.18u
M2 N003 vb3 N004 0 nch W=1u L=0.18u
M5 N006 vtail 0 0 nch W=1u L=0.5u
M6 N003 N003 N001 VDD pch W=2u L=0.18u
M7 vop N003 N002 VDD pch W=2u L=0.18u
M8 N001 N001 VDD VDD pch W=4u L=0.18u
M9 N002 N001 VDD

## ref 9 — https://github.com/StefanSchippers/xschem
// ===== xschem/xschem_library/examples/symbol_include.cir =====
* example of a subcircuit contained in a file

.subckt symbol_include z y[5] y[4] y[3] y[2]
+ VCC VSS
+ A[2] A[1] A[0] B C W=10 L=1 
...
...
.ends


// ===== xschem/xschem_library/examples/symbol_include2.cir =====
* example of a subcircuit contained in a file

.subckt symbol_include Z VCC VSS
+ A B C W=10 L=1 
...
...
.ends


// ===== xschem/xschem_library/inst_sch_select/comp3_file.cir =====
* comp3_file.cir

.subckt comp3_file PLUS OUT MINUS
v1 x 0 1
e1 out x plus minus 0.5
.ends


// ===== xschem/xschem_library/inst_sch_select/comp3_pex2.cir =====
.subckt comp3_pex2 PLUS MINUS OUT
** parasitic netlist
cparax1 net1 0 70f
cparax2 net2 0 70f
cparax3 net3 0 70f
cparax4 net4 0 70f
cparax5 net5 0 70f
cparaxout out 0 80f
M1 net1 GN1 0 0 nmos w=4u l=0.4u m=1
M2 GN1 GN1 0 0 nmos w=4u l=0.4u m=1
I0 VCC GN1 30u
M3 net2 MINUS net1 0 nmos w=1.5u l=0.2u m=1
M4 net3 PLUS net1 0 nmos w=1.5u l=0.2u m=1
M5 net2 net2 VCC VCC pmos w=6u l=0.3u m=1
M6 net3 net2 VCC VCC pmos w=6u l=0.3u m=1
M14 net4 net3 VCC VCC pmos w=6u l=0.3u m=1
.save v(gn1)
.save v(net2)
M7 net4 GN1 0 0 nmos w=4u l=0.4u m=1
M8 net5 net4 0 0 nmos w=1u l=0.4u m=1
M9 net5 net4 VCC VCC pmos w=2u l=0.4u m=1
M10 OUT net5 0 0 nmos w=1u l=0.4u m=1
M11 OUT net5 VCC VCC pmos w=2u l=0.4u m=1
M13 net4 net4 net5 0 nmos w=2u l=0.1u m=1
M12 net5 net5 net4 0 nmos w=2u l=0.1u m=1
C2 GN1 0 200f m=1
.ends


// ===== xschem/xschem_library/inst_sch_select/comp3_read.cir =====
.subckt comp3_read MINUS OUT PLUS
** parasitic netlist
cparax1 net1 0 150f
cparax2 net2 0 150f
cparax3 net3 0 150f
cparax4 net4 0 150f
cparax5 net5 0 150f
cparaxout out 0 180f
M1 net1 GN1 0 0 nmos w=4u l=0.4u m=1
M2 GN1 GN1 0 0 nmos w=4u l=0.4u m=1
I0 VCC GN1 30u
M3 net2 MINUS net1 0 nmos w=1.5u l=0.2u m=1
M4 net3 PLUS net1 0 nmos w=1.5u l=0.2u m=1
M5 net2 net2 VCC VCC pmos w=6u l=0.3u m=1
M6 net3 net2 VCC VCC pmos w=6u l=0.3u m=1
M14 net4 net3 VCC VCC pmos w=6u l=0.3u m=1
.save v(gn1)
.save v(net2

## ref 10 — https://github.com/ChrisZonghaoLi/sky130_ldo_rl
// ===== sky130_ldo_rl/netgen/example_por.spice =====
* NGSPICE file created from example_por.ext - technology: sky130A

.subckt sky130_fd_pr__cap_mim_m3_2_W5U4AW VSUBS m4_n3179_n3100# c2_n3079_n3000#
X0 c2_n3079_n3000# m4_n3179_n3100# sky130_fd_pr__cap_mim_m3_2 l=3e+07u w=3e+07u
.ends

.subckt sky130_fd_sc_hvl__buf_8 A VGND VNB VPB VPWR X
X0 VPWR A a_45_443# VPB sky130_fd_pr__pfet_g5v0d10v5 ad=2.9175e+12p pd=2.189e+07u as=8.475e+11p ps=7.13e+06u w=1.5e+06u l=500000u
X1 VGND a_45_443# X VNB sky130_fd_pr__nfet_g5v0d10v5 ad=1.45875e+12p pd=1.289e+07u as=8.4e+11p ps=8.24e+06u w=750000u l=500000u
X2 VPWR a_45_443# X VPB sky130_fd_pr__pfet_g5v0d10v5 ad=0p pd=0u as=1.68e+12p ps=1.424e+07u w=1.5e+06u l=500000u
X3 VGND a_45_443# X VNB sky130_fd_pr__nfet_g5v0d10v5 ad=0p pd=0u as=0p ps=0u w=750000u l=500000u
X4 VGND a_45_443# X VNB sky130_fd_pr__nfet_g5v0d10v5 ad=0p pd=0u as=0p ps=0u w=750000u l=500000u
X5 a_45_443# A VGND VNB sky130_fd_pr__nfet_g5v0d10v5 ad=4.2375e+11p pd=4.13e+06u as=0p ps=0u w=750000u l=500000u
X6 X a_45_443# VGND VNB sky130_fd_pr__nfet_g5v0d10v5 ad=0p pd=0u as=0p ps=0u w=750000u l=500000u
X7 X a_45_443# VGND VNB sky130_fd_pr__nfet_g5v0d10v5 ad=0p pd=0u as=0p ps=0u w=750000u l=500000u
X8 VGND A a_45_443# VNB sky130_fd_pr__nfet_g5v0d10v5 ad=0p pd=0u as=0p ps=0u w=750000u l=500000u
X9 VPWR a_45_443# X VPB sky130_fd_pr__pfet_g5v0d10v5 ad=0p pd=0u as=0p ps=0u w=1.5e+06u l=500000u
X10 X a_45_443# VGND VNB sky130_fd_pr__nfet_g5v0d10v5 ad=0p pd=0u as=0p ps=0u w=750000u l=500000u
X11 X a_45_443# VGND VNB sky130_fd_pr__nfet_g5v0d10v5 ad=0p pd=0u as=0p ps=0u w=750000u l=500000u
X12 VPWR a_45_443# X VPB sky130_fd_pr__pfet_g5v0d10v5 ad=0p pd=0u as=0p ps=0u w=1.5e+06u l=500000u
X13 VPWR a_45_443# X VPB sky130_fd_pr__pfet_g5v0d10v5 ad=0p pd=0u as=0p ps=0u w=1.5e+06u l=500000u
X14 VPWR A a_45_443# VPB sky130_fd_pr__pfet_g5v0d10v5 ad=0p pd=0u as=0p ps=0u w=1.5e+06u l=500000u
X15 a_45_443# A VPWR VPB sky130_fd_pr__pfet_g5v0d10v5 ad=0p pd=0u as=0p ps=0u w=1.5e+06u l=500000u

## ref 11 — https://github.com/daniellovell/cascode
// ===== cascode/tests/fixtures/pdk/sky130/models/all.spice =====
* SKY130 Spice File.
*.option scale=1.0u
.include "parameters/lod.spice"
.param
+ lv_dlc_rotweak = .00e-9
+ lvhvt_dlc_rotweak = .00e-9
+ lvt_dlc_rotweak = .00e-9
+ hv_dlc_rotweak = .00e-9
+ sky130_fd_pr__nfet_01v8__dlc_rotweak = lv_dlc_rotweak
+ sky130_fd_pr__esd_nfet_01v8__dlc_rotweak = lv_dlc_rotweak
+ sky130_fd_pr__nfet_01v8_lvt__dlc_rotweak = lvt_dlc_rotweak
+ sky130_fd_pr__pfet_01v8__dlc_rotweak = lv_dlc_rotweak
+ sky130_fd_pr__pfet_01v8_lvt__dlc_rotweak = lvt_dlc_rotweak
+ sky130_fd_pr__pfet_01v8_hvt__dlc_rotweak = lvhvt_dlc_rotweak
+ sky130_fd_pr__esd_nfet_g5v0d10v5__dlc_rotweak = hv_dlc_rotweak
+ sky130_fd_pr__esd_pfet_g5v0d10v5__dlc_rotweak = hv_dlc_rotweak
+ sky130_fd_pr__nfet_03v3_nvt__dlc_rotweak = hv_dlc_rotweak
+ sky130_fd_pr__nfet_05v0_nvt__dlc_rotweak = hv_dlc_rotweak
+ sky130_fd_pr__nfet_g5v0d10v5__dlc_rotweak = hv_dlc_rotweak
+ sky130_fd_pr__pfet_g5v0d10v5__dlc_rotweak = hv_dlc_rotweak
+ sky130_fd_pr__pfet_g5v0d16v0__dlc_rotweak = hv_dlc_rotweak
+ sky130_fd_pr__special_nfet_pass__dlc_rotweak = lv_dlc_rotweak
+ sky130_fd_pr__special_nfet_pass_lowleakage__dlc_rotweak = lv_dlc_rotweak
+ sky130_fd_pr__special_nfet_pass_flash__dlc_rotweak = hv_dlc_rotweak
+ sky130_fd_pr__special_nfet_latch__dlc_rotweak = lv_dlc_rotweak
+ sky130_fd_pr__special_nfet_latch_lowleakage__dlc_rotweak = lv_dlc_rotweak
+ sky130_fd_pr__special_pfet_pass__dlc_rotweak = lv_dlc_rotweak
+ sky130_fd_pr__special_pfet_pass_lowleakage__dlc_rotweak = lv_dlc_rotweak
+ sky130_fd_bs_flash__special_sonosfet_star__dlc_rotweak = hv_dlc_rotweak
+ sky130_fd_bs_flash__special_sonosfet_original__dlc_rotweak = hv_dlc_rotweak
+ sonos_eeol_dlc_rotweak = hv_dlc_rotweak
+ sonos_peol_dlc_rotweak = hv_dlc_rotweak
* include all individual diode models
.include "parasitics/sky130_fd_pr__model__parasitic__diode_ps2nw.model.spice"
.include "../cells/diode_pw2nd_05v5/sky130_fd_pr__diode_pw2nd_05v5.model.spice"
.include "../cells/diode_pd2nw_05v5

## ref 12 — https://github.com/Aniumbott/SPICE-Files
// ===== SPICE-Files/Dependencies/cmos.cir =====
*coms u20ec055
.include cmos_130nm.txt
M1 d g 0 0 NMOS w=0.25u L=0.13u
Vds d 0 1.2
Vgs g 0 1.2
.dc Vgs 0.1 1.2 0.001
*.dc vds 0.1 1.2 0.001
.control
run
plot -i(Vds) 
.endc
.end

// ===== SPICE-Files/Dependencies/pmos.cir =====
*pmos u20ec055
.include cmos_130nm.txt
M1 D G S Su PMOS W=1u L=0.13u
Vs  S 0 0v
Vsu Su 0 0v
Vgs G S 1.2v
Vds D S -1.2V
.dc Vgs -2 0 0.01
*.dc Vds -1.2 0 0.01
.control
run
plot i(Vds)
.endc
.end

// ===== SPICE-Files/NMOS and PMOS/nmos.cir =====
* DC analysis of a NMOS transistor
.include "../Dependencies/cmos_90nm.txt"
M1 d g 0 0 NMOS w=0.25u L=0.9u
Vds d 0 1.2
Vgs g 0 1.2

* DC analysis
.dc Vds 0.1 1.2 0.001

.control
run
set color0 = white;
set xbrushwidth = 3.5;
plot -i(Vds) 
.endc
.end

// ===== SPICE-Files/NMOS and PMOS/pmos.cir =====
* DC analysis of a PMOS transistor
.include "../Dependencies/cmos_130nm.txt"
M1 D G S Su PMOS W=1u L=0.13u
Vs  S 0 0v
Vsu Su 0 0v
Vgs G S 1.2v
Vds D S -1.2V

* DC analysis
.dc Vds -1.2 0 0.01

.control
run
set color0 = white;
set xbrushwidth = 3.5;
plot i(Vds)
.endc
.end

// ===== SPICE-Files/MOS Logic/pseudo_nmos_inverter.cir =====
* Pseudo NMOS inverter usng NMOS and PMOS
.include "../Dependencies/cmos_90nm.txt"
M1 dd G out dd PMOS W=0.1u L=0.13u
M2 out in 0 0 NMOS w=0.1u L=0.09u

Vgs in 0 1.2
Vdd dd 0 1.2

* DC analysis
.dc Vgs 0 1.2 0.01

.control
run
set color0 = white
set xbrushwidth = 3.5
plot v(out) 
.endc
.end

// ===== SPICE-Files/MOS Logic/resistive_load_inverter.cir =====
* NMOS Inverter with resistive load with different channel widths
.include "../Dependencies/cmos_90nm.txt"

.subckt inv inp out wid = 1u
    M1 out inp 0 0 nmos W = wid L = 0.090u
    r1 d out 100k
    VDS D 0 1.2
.ends

X1 in out1 inv wid = 0.2u
X2 in out2 inv wid = 0.4u
X3 in out3 inv wid = 0.6u
X4 in out4 inv wid = 0.8u
X5 in out5 inv wid = 1u

vgs in 0 1.2
.dc Vgs 0 1.2 0.01

.control
run
set color0 = white
set xbrushwidth = 3.5
plot v(out1) v(out2) v(out3) v(out4) v(out5)
.e

## ref 13 — https://github.com/USCPOSH/AMPSE
// ===== AMPSE/Module/Comparator/PTM45_COMP_5.14.2019/Netlists/hspice/comparator_p.sp =====
$hspice version of comparator

.param C=1.5p dif_pair=530n inv=160n inv_comp=190n latch_comp=177n 
+    nand_comp=191n nand_w=160n nor_w=286n reset_comp=180n switch=1.06u 
+    fs=100x fin=31/64*fs delay=5n width=0.2*1/fs period=1/fs periodx10=period*10
.inc /Users/garng/XDM_work/data-model/netlists/forUSC/Hspice/Library/45nm_MGK.pm

*// Library name: POSH_TI_SAR_Parameterized
*// Cell name: NAND2_comp
*// View name: schematic
.subckt NAND2_comp A B VDD VSS D
    M1 net7 B VSS VSS nmos w=nand_comp l=45n m=20
    M0 D A net7 VSS nmos w=nand_comp l=45n m=20
    M3 D B VDD VDD pmos w=26/9*nand_comp l=45n m=10
    M2 D A VDD VDD pmos w=26/9*nand_comp l=45n m=10
.ends NAND2_comp
*// End of subcircuit definition.

*// Library name: POSH_TI_SAR_Parameterized
*// Cell name: comparator_p
*// View name: schematic
M10 VOUTN net16 VSS VSS nmos w=inv_comp l=45n m=10
M3 net16 net9 VSS VSS nmos w=latch_comp l=45n m=10
M5 net16 CLKC VSS VSS nmos w=reset_comp l=45n m=5
M4 net9 CLKC VSS VSS nmos w=reset_comp l=45n m=5
M7 VOUTP net9 VSS VSS nmos w=inv_comp l=45n m=10
M6 net9 net16 VSS VSS nmos w=latch_comp l=45n m=10
M9 VOUTN net16 VDD VDD pmos w=26/9*inv_comp l=45n m=10
M0 net12 CLKC VDD VDD pmos w=2*dif_pair l=45n m=10
M2 net16 VINN net12 VDD pmos w=dif_pair l=45n m=5
M1 net9 VINP net12 VDD pmos w=dif_pair l=45n m=5
M8 VOUTP net9 VDD VDD pmos w=26/9*inv_comp l=45n m=10
X1 VOUTP VOUTN VDD VSS RDY NAND2_comp

VDD VDD 0 1.1
VSS VSS 0 0
V1 CLKC 0 pulse 1.1 0 'delay' 500p 500p 'width' 'period'
V2 VINN 0 PWL 0 0 30e-9 0 31e-9 1.1 60e-9 1.1
V3 VINP 0 PWL 0 0 10e-9 0 11e-9 1.1 40e-9 1.1 41e-9 0 60e-9 0
C1 VOUTN 0 1p
C2 VOUTP 0 1p
C3 RDY 0 1p

.tran 10e-12 60n start=0 
.print tran v(clkc) v(vinn) v(vinp) v(voutn) v(voutp) v(rdy)


// ===== AMPSE/Block/ADC/VCO_ADC/TSMC65_VCO_ADC_1.3.2020/netlists_sanitized/hspice/inbuf_buf2_SPICE.sp =====
** Generated for: hspiceD
** Generated on: Jan  8 15:54:29 2020

## ref 14 — https://camilotejeiro.github.io/2017/10/06/aic-1-3-10-mos-current-mirror-cascode-stage.html
[Nurture the Joy of Learning](https://camilotejeiro.github.io/)
[About](https://camilotejeiro.github.io/about.html)
# AIC-1.3.10: Current Mirrors -- MOS Current Mirror With Cascode Stage
Oct 6, 2017 
## Schematic Diagram
![MOS Current Mirror With Cascode Stage Schematic](https://camilotejeiro.github.io/linked_files/2017-10-06-aic-1-3-10-mos-current-mirror-cascode-stage_1.svg)
## SPICE Simulations
_For the SPICE simulation code, see[“Source Code”](https://camilotejeiro.github.io/2017/10/06/aic-1-3-10-mos-current-mirror-cascode-stage.html#source-code) section below._
### Operating Point Analysis
Here, we are calculating the DC voltages (bias voltages) at every node of our circuit.
**Results:** Node DC measurements (re-formatted for display).

```
Node                    Measurements
----                    ------------
n1                      .8593 V
n2                      1.0 V
n3                      1.3593 V
n4                      .4921 V
n_pos                   3.0 V
v1#branch               -50.0 uA
v2#branch               -49.4728 uA
(v2#branch/v1#branch)   .9895

```

### DC Analysis
In our DC analysis, we are measuring the variation of the mirrored output current under different loads.
We are applying a DC sweep to V2 (our load voltage) from 0 to 3V in 0.1V increments.
We are plotting the output current magnitude vs drain voltage. (our load voltage at n2)
![MOS Current Mirror With Cascode Stage Simulation DC](https://camilotejeiro.github.io/linked_files/2017-10-06-aic-1-3-10-mos-current-mirror-cascode-stage_2.svg)
### Monte Carlo Analysis
In our Montecarlo analysis, we are measuring the effect of transistors’ mismatch on the performance of our current mirror i.e. how small variations in individual transistors when added together can affect the performance of the overall circuit.
The Monte Carlo simulation was performed for 100 runs with a sigma value of 3.
As per the book reference (in the simulation chapter) for MOS transistors: It is important to model vari