v {xschem version=3.4.8 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
N 100 0 160 0 {lab=RF_BOOST}
N 100 100 160 100 {lab=VBIAS}
N 260 -40 320 -40 {lab=RF_P}
N 380 -40 440 -40 {lab=IN_P}
N 260 40 320 40 {lab=RF_N}
N 380 40 440 40 {lab=IN_N}
N 300 100 400 100 {lab=VBIAS}
N 300 -100 400 -100 {lab=VBIAS}
N 300 -100 300 100 {lab=VBIAS}

C {devices/res.sym} 440 -10 0 0 {name=R_DUMMY1 value=1T}
C {devices/res.sym} 440 90 0 0 {name=R_DUMMY2 value=1T}
N 440 -40 440 -40 {lab=IN_P}
N 440 40 440 40 {lab=IN_N}
N 440 20 440 30 {lab=0}
N 440 120 440 130 {lab=0}

C {devices/ipin.sym} 100 0 0 0 {name=p1 lab=RF_BOOST}
C {devices/ipin.sym} 100 100 0 0 {name=p2 lab=VBIAS}
C {devices/opin.sym} 440 -40 0 0 {name=p3 lab=IN_P}
C {devices/opin.sym} 440 40 0 0 {name=p4 lab=IN_N}
C {devices/capa.sym} 350 -40 1 0 {name=C1 value=10p}
C {devices/capa.sym} 350 40 1 0 {name=C2 value=10p}
C {devices/res.sym} 400 -70 0 0 {name=R1 value=100k}
C {devices/res.sym} 400 70 0 0 {name=R2 value=100k}
C {devices/code_shown.sym} 200 -100 0 0 {name=BALUN only_toplevel=false value="E1 RF_P 0 RF_BOOST 0 1
E2 RF_N 0 RF_BOOST 0 -1"}
C {devices/lab_pin.sym} 160 0 0 0 {name=l1 lab=RF_BOOST}
C {devices/lab_pin.sym} 160 100 0 0 {name=l2 lab=VBIAS}
C {devices/lab_pin.sym} 260 -40 0 0 {name=l3 lab=RF_P}
C {devices/lab_pin.sym} 260 40 0 0 {name=l4 lab=RF_N}
C {devices/lab_pin.sym} 440 -40 0 0 {name=l5 lab=IN_P}
C {devices/lab_pin.sym} 440 40 0 0 {name=l6 lab=IN_N}
C {devices/lab_pin.sym} 300 100 0 0 {name=l7 lab=VBIAS}
C {devices/lab_pin.sym} 400 -100 0 0 {name=l8 lab=VBIAS}
C {devices/lab_pin.sym} 400 -40 0 0 {name=l9 lab=IN_P}
C {devices/lab_pin.sym} 400 40 0 0 {name=l10 lab=IN_N}
C {devices/lab_pin.sym} 400 100 0 0 {name=l11 lab=VBIAS}
C {devices/gnd.sym} 440 30 0 0 {name=g1 lab=0}
C {devices/gnd.sym} 440 130 0 0 {name=g2 lab=0}
