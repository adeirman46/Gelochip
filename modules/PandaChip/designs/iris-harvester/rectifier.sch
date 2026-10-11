v {xschem version=3.4.8 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
N 300 -70 520 -70 {lab=IN_P}
N 520 -70 560 -70 {lab=IN_P}
N 560 -70 560 -40 {lab=IN_P}
N 560 -40 960 -40 {lab=IN_P}
N 960 -100 960 150 {lab=IN_P}
N 960 -100 920 -100 {lab=IN_P}
N 960 150 920 150 {lab=IN_P}
N 520 -70 520 120 {lab=IN_P}
N 300 70 340 70 {lab=IN_N}
N 340 -100 340 150 {lab=IN_N}
N 340 -100 480 -100 {lab=IN_N}
N 340 150 480 150 {lab=IN_N}
N 340 70 820 70 {lab=IN_N}
N 820 70 820 -70 {lab=IN_N}
N 820 -70 880 -70 {lab=IN_N}
N 820 70 820 120 {lab=IN_N}
N 820 120 880 120 {lab=IN_N}
N 520 -130 880 -130 {lab=VRECT_P}
N 880 -130 1040 -130 {lab=VRECT_P}
N 520 -130 520 -100 {lab=VRECT_P}
N 880 -130 880 -100 {lab=VRECT_P}
N 520 180 880 180 {lab=VRECT_N}
N 880 180 1040 180 {lab=VRECT_N}
N 520 180 520 150 {lab=VRECT_N}
N 880 180 880 150 {lab=VRECT_N}
N 660 380 700 380 {lab=VRECT_N}
N 700 380 700 180 {lab=VRECT_N}
N 660 320 660 300 {lab=0}
N 620 350 600 350 {lab=0}
C {symbols/pfet_03v3.sym} 500 -100 0 0 {name=M_P1 W=20u L=0.28u nf=2 m=1}
C {symbols/pfet_03v3.sym} 900 -100 0 1 {name=M_P2 W=20u L=0.28u nf=2 m=1}
C {symbols/nfet_03v3.sym} 500 150 0 0 {name=M_N1 W=20u L=0.28u nf=2 m=1}
C {symbols/nfet_03v3.sym} 900 150 0 1 {name=M_N2 W=20u L=0.28u nf=2 m=1}
C {symbols/nfet_03v3.sym} 640 350 0 0 {name=M_D1 W=10u L=0.28u nf=2 m=1}
C {devices/ipin.sym} 300 -70 0 0 {name=p1 lab=IN_P}
C {devices/ipin.sym} 300 70 0 0 {name=p2 lab=IN_N}
C {devices/opin.sym} 1040 -130 0 0 {name=p3 lab=VRECT_P}
C {devices/opin.sym} 1040 180 0 0 {name=p4 lab=VRECT_N}
C {devices/lab_pin.sym} 520 -70 0 0 {name=l1 lab=IN_P}
C {devices/lab_pin.sym} 480 -100 0 0 {name=l2 lab=IN_N}
C {devices/lab_pin.sym} 520 -130 0 0 {name=l3 lab=VRECT_P}
C {devices/lab_pin.sym} 520 -100 0 0 {name=l4 lab=VRECT_P}
C {devices/lab_pin.sym} 880 -70 0 0 {name=l5 lab=IN_N}
C {devices/lab_pin.sym} 920 -100 0 0 {name=l6 lab=IN_P}
C {devices/lab_pin.sym} 880 -130 0 0 {name=l7 lab=VRECT_P}
C {devices/lab_pin.sym} 880 -100 0 0 {name=l8 lab=VRECT_P}
C {devices/lab_pin.sym} 520 120 0 0 {name=l9 lab=IN_P}
C {devices/lab_pin.sym} 480 150 0 0 {name=l10 lab=IN_N}
C {devices/lab_pin.sym} 520 180 0 0 {name=l11 lab=VRECT_N}
C {devices/lab_pin.sym} 520 150 0 0 {name=l12 lab=VRECT_N}
C {devices/lab_pin.sym} 880 120 0 0 {name=l13 lab=IN_N}
C {devices/lab_pin.sym} 920 150 0 0 {name=l14 lab=IN_P}
C {devices/lab_pin.sym} 880 180 0 0 {name=l15 lab=VRECT_N}
C {devices/lab_pin.sym} 880 150 0 0 {name=l16 lab=VRECT_N}
C {devices/lab_pin.sym} 660 320 0 0 {name=l17 lab=0}
C {devices/lab_pin.sym} 620 350 0 0 {name=l18 lab=0}
C {devices/lab_pin.sym} 660 380 0 0 {name=l19 lab=VRECT_N}
C {devices/lab_pin.sym} 660 350 0 0 {name=l20 lab=0}
C {devices/lab_pin.sym} 600 350 0 0 {name=l21 lab=0}
C {devices/gnd.sym} 660 300 0 0 {name=g1 lab=0}
C {devices/gnd.sym} 600 350 0 0 {name=g2 lab=0}
T {Differential cross-coupled CMOS rectifier} 300 -220 0 0 0.3 0.3 {}
B 2 1120 -130 2080 90 {flags=graph
rawfile=/home/irman/PandaChip/designs/iris-harvester/rectifier_verify.raw
sim_type=tran
autoload=1
color="4 12"
y1=-1.8
y2=3
divy=4
x1=0
x2=3e-07
divx=8
node="in_p
in_n"
}
B 2 1120 130 2080 350 {flags=graph
rawfile=/home/irman/PandaChip/designs/iris-harvester/rectifier_verify.raw
sim_type=tran
autoload=1
color="4 12"
y1=-1.02
y2=2.64
divy=4
x1=0
x2=1.5e-07
divx=8
node="vrect_p
vrect_n"
}
