v {xschem version=3.4.8 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
C {symbols/nfet_03v3.sym} 200 200 0 0 {name=M_D1 W=10u L=0.28u nf=2 m=1}
C {symbols/nfet_03v3.sym} 400 200 0 0 {name=M_D2 W=10u L=0.28u nf=2 m=1}
C {symbols/nfet_03v3.sym} 600 200 0 0 {name=M_D3 W=10u L=0.28u nf=2 m=1}
C {symbols/nfet_03v3.sym} 800 200 0 0 {name=M_D4 W=10u L=0.28u nf=2 m=1}

C {devices/capa.sym} 220 300 0 0 {name=C1 value=10p}
C {devices/capa.sym} 420 300 0 0 {name=C2 value=10p}
C {devices/capa.sym} 620 300 0 0 {name=C3 value=10p}

C {devices/res.sym} 900 260 0 0 {name=R_DUMMY1 value=1T}

N 100 170 220 170 {lab=VRECT_P}
N 220 170 180 170 {lab=VRECT_P}
N 180 170 180 200 {lab=VRECT_P}

N 220 230 220 250 {lab=N1}
N 220 250 340 250 {lab=N1}
N 340 250 340 170 {lab=N1}
N 340 170 420 170 {lab=N1}
N 420 170 380 170 {lab=N1}
N 380 170 380 200 {lab=N1}

N 420 230 420 250 {lab=N2}
N 420 250 540 250 {lab=N2}
N 540 250 540 170 {lab=N2}
N 540 170 620 170 {lab=N2}
N 620 170 580 170 {lab=N2}
N 580 170 580 200 {lab=N2}

N 620 230 620 250 {lab=N3}
N 620 250 740 250 {lab=N3}
N 740 250 740 170 {lab=N3}
N 740 170 820 170 {lab=N3}
N 820 170 780 170 {lab=N3}
N 780 170 780 200 {lab=N3}

N 820 230 900 230 {lab=VCP}
N 900 230 900 230 {lab=VCP}
N 900 290 900 300 {lab=0}

N 220 250 220 270 {lab=N1}
N 220 330 220 370 {lab=IN_N}

N 420 250 420 270 {lab=N2}
N 420 330 420 370 {lab=IN_P}

N 620 250 620 270 {lab=N3}
N 620 330 620 370 {lab=IN_N}

C {devices/ipin.sym} 100 170 0 0 {name=p1 lab=VRECT_P}
C {devices/ipin.sym} 220 370 0 0 {name=p2 lab=IN_N}
C {devices/ipin.sym} 420 370 0 0 {name=p3 lab=IN_P}
C {devices/opin.sym} 900 230 0 0 {name=p4 lab=VCP}

C {devices/lab_pin.sym} 220 170 0 0 {name=l1 lab=VRECT_P}
C {devices/lab_pin.sym} 180 200 0 0 {name=l2 lab=VRECT_P}
C {devices/lab_pin.sym} 220 230 0 0 {name=l3 lab=N1}
C {devices/lab_pin.sym} 220 200 0 0 {name=l4 lab=0}

C {devices/lab_pin.sym} 420 170 0 0 {name=l5 lab=N1}
C {devices/lab_pin.sym} 380 200 0 0 {name=l6 lab=N1}
C {devices/lab_pin.sym} 420 230 0 0 {name=l7 lab=N2}
C {devices/lab_pin.sym} 420 200 0 0 {name=l8 lab=0}

C {devices/lab_pin.sym} 620 170 0 0 {name=l9 lab=N2}
C {devices/lab_pin.sym} 580 200 0 0 {name=l10 lab=N2}
C {devices/lab_pin.sym} 620 230 0 0 {name=l11 lab=N3}
C {devices/lab_pin.sym} 620 200 0 0 {name=l12 lab=0}

C {devices/lab_pin.sym} 820 170 0 0 {name=l13 lab=N3}
C {devices/lab_pin.sym} 780 200 0 0 {name=l14 lab=N3}
C {devices/lab_pin.sym} 820 230 0 0 {name=l15 lab=VCP}
C {devices/lab_pin.sym} 820 200 0 0 {name=l16 lab=0}

C {devices/lab_pin.sym} 220 270 0 0 {name=l17 lab=N1}
C {devices/lab_pin.sym} 220 330 0 0 {name=l18 lab=IN_N}
C {devices/lab_pin.sym} 420 270 0 0 {name=l19 lab=N2}
C {devices/lab_pin.sym} 420 330 0 0 {name=l20 lab=IN_P}
C {devices/lab_pin.sym} 620 270 0 0 {name=l21 lab=N3}
C {devices/lab_pin.sym} 620 330 0 0 {name=l22 lab=IN_N}
C {devices/gnd.sym} 900 300 0 0 {name=g1 lab=0}
