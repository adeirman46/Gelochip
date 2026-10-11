v {xschem version=3.4.8 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
C {symbols/pfet_03v3.sym} 400 200 0 0 {name=M_P1 W=20u L=0.28u nf=2 m=1}
C {symbols/pfet_03v3.sym} 600 200 0 0 {name=M_P2 W=20u L=0.28u nf=2 m=1}
C {symbols/nfet_03v3.sym} 400 400 0 0 {name=M_N1 W=20u L=0.28u nf=2 m=1}
C {symbols/nfet_03v3.sym} 600 400 0 0 {name=M_N2 W=20u L=0.28u nf=2 m=1}
C {symbols/nfet_03v3.sym} 500 600 0 0 {name=M_D1 W=10u L=0.28u nf=2 m=1}

C {devices/vsource.sym} 700 130 0 0 {name=V_DUMMY1 value=0}
C {devices/vsource.sym} 700 500 0 0 {name=V_DUMMY2 value=0}

N 420 170 620 170 {lab=VRECT_P}
N 420 170 420 200 {lab=VRECT_P}
N 620 170 620 200 {lab=VRECT_P}
N 520 170 520 100 {lab=VRECT_P}
N 520 100 700 100 {lab=VRECT_P}

N 420 430 620 430 {lab=VRECT_N}
N 420 400 420 430 {lab=VRECT_N}
N 620 400 620 430 {lab=VRECT_N}

N 520 430 560 430 {lab=VRECT_N}
N 560 430 560 630 {lab=VRECT_N}
N 560 630 520 630 {lab=VRECT_N}
N 560 430 700 430 {lab=VRECT_N}
N 700 430 700 470 {lab=VRECT_N}

N 520 570 480 570 {lab=0}
N 480 570 480 600 {lab=0}
N 480 600 520 600 {lab=0}
N 520 600 520 570 {lab=0}

N 700 160 700 190 {lab=DUMMY_NET1}
N 700 530 700 560 {lab=DUMMY_NET2}

N 420 230 420 370 {lab=IN_P}
N 580 200 580 400 {lab=IN_P}
N 420 300 580 300 {lab=IN_P}
N 420 300 300 300 {lab=IN_P}

N 620 230 620 370 {lab=IN_N}
N 380 200 380 400 {lab=IN_N}
N 380 320 620 320 {lab=IN_N}
N 380 320 300 320 {lab=IN_N}

C {devices/ipin.sym} 300 300 0 0 {name=p1 lab=IN_P}
C {devices/ipin.sym} 300 320 0 0 {name=p2 lab=IN_N}
C {devices/opin.sym} 520 100 0 0 {name=p3 lab=VRECT_P}
C {devices/opin.sym} 700 430 0 0 {name=p4 lab=VRECT_N}

C {devices/lab_pin.sym} 420 230 0 0 {name=l1 lab=IN_P}
C {devices/lab_pin.sym} 380 200 0 0 {name=l2 lab=IN_N}
C {devices/lab_pin.sym} 420 170 0 0 {name=l3 lab=VRECT_P}
C {devices/lab_pin.sym} 420 200 0 0 {name=l4 lab=VRECT_P}

C {devices/lab_pin.sym} 620 230 0 0 {name=l5 lab=IN_N}
C {devices/lab_pin.sym} 580 200 0 0 {name=l6 lab=IN_P}
C {devices/lab_pin.sym} 620 170 0 0 {name=l7 lab=VRECT_P}
C {devices/lab_pin.sym} 620 200 0 0 {name=l8 lab=VRECT_P}

C {devices/lab_pin.sym} 420 370 0 0 {name=l9 lab=IN_P}
C {devices/lab_pin.sym} 380 400 0 0 {name=l10 lab=IN_N}
C {devices/lab_pin.sym} 420 430 0 0 {name=l11 lab=VRECT_N}
C {devices/lab_pin.sym} 420 400 0 0 {name=l12 lab=VRECT_N}

C {devices/lab_pin.sym} 620 370 0 0 {name=l13 lab=IN_N}
C {devices/lab_pin.sym} 580 400 0 0 {name=l14 lab=IN_P}
C {devices/lab_pin.sym} 620 430 0 0 {name=l15 lab=VRECT_N}
C {devices/lab_pin.sym} 620 400 0 0 {name=l16 lab=VRECT_N}

C {devices/lab_pin.sym} 520 570 0 0 {name=l17 lab=0}
C {devices/lab_pin.sym} 480 600 0 0 {name=l18 lab=0}
C {devices/lab_pin.sym} 520 630 0 0 {name=l19 lab=VRECT_N}
C {devices/lab_pin.sym} 520 600 0 0 {name=l20 lab=0}

C {devices/gnd.sym} 520 570 0 0 {name=g1 lab=0}
C {devices/lab_pin.sym} 700 190 0 0 {name=l21 lab=DUMMY_NET1}
C {devices/lab_pin.sym} 700 560 0 0 {name=l22 lab=DUMMY_NET2}
