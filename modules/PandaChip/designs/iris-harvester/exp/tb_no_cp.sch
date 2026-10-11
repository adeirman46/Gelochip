v {xschem version=3.4.8 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
C {matching.sym} 300 200 0 0 {name=X1}
C {bias.sym} 300 400 0 0 {name=X2}
C {splitter.sym} 500 200 0 0 {name=X3}
C {rectifier.sym} 700 200 0 0 {name=X4}


C {devices/vsource.sym} 100 200 0 0 {name=V_RF value="SIN(0 0.632 50MEG)"}
C {devices/res.sym} 180 170 1 0 {name=R_S value=50}
C {devices/vsource.sym} 100 400 0 0 {name=V_DD value=3.3}

C {devices/capa.sym} 1050 230 0 0 {name=C_STORE value=100p}
C {devices/res.sym} 1150 230 0 0 {name=R_LOAD value=1MEG}

N 100 170 150 170 {lab=RF_SRC}
N 210 170 260 170 {lab=RF_IN}
N 260 170 260 200 {lab=RF_IN}
N 100 230 100 260 {lab=0}

N 100 370 300 370 {lab=VDD}
N 300 370 300 360 {lab=VDD}
N 100 430 100 460 {lab=0}

N 340 200 460 200 {lab=RF_BOOST}
N 460 200 460 180 {lab=RF_BOOST}

N 340 400 460 400 {lab=VBIAS}
N 460 400 460 220 {lab=VBIAS}

N 540 180 660 180 {lab=IN_P}
N 540 220 660 220 {lab=IN_N}

N 740 180 860 180 {lab=VRECT_P}
N 740 220 800 220 {lab=VRECT_N}
N 800 220 800 260 {lab=VRECT_N}

N 600 180 600 140 {lab=IN_P}
N 600 140 860 140 {lab=IN_P}
N 860 140 860 200 {lab=IN_P}

N 600 220 600 260 {lab=IN_N}
N 600 260 860 260 {lab=IN_N}
N 860 260 860 220 {lab=IN_N}

N 940 200 1050 200 {lab=VOUT}
N 1050 200 1150 200 {lab=VOUT}

N 1050 260 1050 290 {lab=0}
N 1150 260 1150 290 {lab=0}

C {devices/lab_pin.sym} 150 170 0 0 {name=l1 lab=RF_SRC}
C {devices/lab_pin.sym} 260 200 0 0 {name=l2 lab=RF_IN}
C {devices/lab_pin.sym} 100 260 0 0 {name=l3 lab=0}
C {devices/gnd.sym} 100 260 0 0 {name=g1 lab=0}

C {devices/lab_pin.sym} 300 360 0 0 {name=l4 lab=VDD}
C {devices/lab_pin.sym} 100 460 0 0 {name=l5 lab=0}
C {devices/gnd.sym} 100 460 0 0 {name=g2 lab=0}

C {devices/lab_pin.sym} 460 180 0 0 {name=l6 lab=RF_BOOST}
C {devices/lab_pin.sym} 460 220 0 0 {name=l7 lab=VBIAS}

C {devices/lab_pin.sym} 600 180 0 0 {name=l8 lab=IN_P}
C {devices/lab_pin.sym} 600 220 0 0 {name=l9 lab=IN_N}

C {devices/lab_pin.sym} 800 180 0 0 {name=l10 lab=VRECT_P}
C {devices/lab_pin.sym} 800 220 0 0 {name=l11 lab=VRECT_N}

C {devices/lab_pin.sym} 1000 200 0 0 {name=l12 lab=VOUT}
C {devices/lab_pin.sym} 1050 290 0 0 {name=l13 lab=0}
C {devices/gnd.sym} 1050 290 0 0 {name=g3 lab=0}
C {devices/lab_pin.sym} 1150 290 0 0 {name=l14 lab=0}
C {devices/gnd.sym} 1150 290 0 0 {name=g4 lab=0}

C {devices/code_shown.sym} 100 600 0 0 {name=CONTROL only_toplevel=true value=".include /foss/pdks/gf180mcuD/libs.tech/ngspice/design.ngspice
.lib /foss/pdks/gf180mcuD/libs.tech/ngspice/sm141064.ngspice typical
.tran 1n 10u
.save all"}
