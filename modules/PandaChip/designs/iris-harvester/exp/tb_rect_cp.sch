v {xschem version=3.4.8 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
C {rectifier.sym} 700 200 0 0 {name=X4}
C {devices/vsource.sym} 500 210 0 0 {name=V1 value="SIN(0.6 1.0 50MEG)"}
C {devices/vsource.sym} 560 250 0 0 {name=V2 value="SIN(0.6 1.0 50MEG 0 0 180)"}
C {devices/res.sym} 800 210 0 0 {name=RL value=1MEG}
N 500 180 660 180 {lab=IN_P}
N 560 220 660 220 {lab=IN_N}
N 500 240 500 260 {lab=0}
N 560 280 560 300 {lab=0}
N 740 180 800 180 {lab=VRECT_P}
N 740 220 740 260 {lab=VRECT_N}
N 800 240 800 260 {lab=0}
C {devices/lab_pin.sym} 500 180 0 0 {name=l1 lab=IN_P}
C {devices/lab_pin.sym} 560 220 0 0 {name=l2 lab=IN_N}
C {devices/lab_pin.sym} 740 180 0 0 {name=l3 lab=VRECT_P}
C {devices/lab_pin.sym} 740 260 0 0 {name=l4 lab=VRECT_N}
C {devices/lab_pin.sym} 500 260 0 0 {name=l5 lab=0}
C {devices/gnd.sym} 500 260 0 0 {name=g1 lab=0}
C {devices/lab_pin.sym} 560 300 0 0 {name=l6 lab=0}
C {devices/gnd.sym} 560 300 0 0 {name=g2 lab=0}
C {devices/lab_pin.sym} 800 260 0 0 {name=l7 lab=0}
C {devices/gnd.sym} 800 260 0 0 {name=g3 lab=0}
C {charge_pump.sym} 900 200 0 0 {name=X5}
N 740 180 860 180 {lab=VRECT_P}
N 860 200 860 240 {lab=IN_P}
N 860 220 860 220 {lab=IN_N}
N 940 200 1000 200 {lab=VOUT}
C {devices/lab_pin.sym} 860 240 0 0 {name=l20 lab=IN_P}
C {devices/lab_pin.sym} 860 220 0 0 {name=l21 lab=IN_N}
C {devices/lab_pin.sym} 1000 200 0 0 {name=l22 lab=VOUT}
C {devices/code_shown.sym} 500 400 0 0 {name=CONTROL only_toplevel=true value=".include /foss/pdks/gf180mcuD/libs.tech/ngspice/design.ngspice
.lib /foss/pdks/gf180mcuD/libs.tech/ngspice/sm141064.ngspice typical
.tran 1n 1u
.save all"}
