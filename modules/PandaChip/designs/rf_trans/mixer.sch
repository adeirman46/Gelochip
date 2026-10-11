v {xschem version=3.4.8 file_version=1.2}
G {}
K {}
V {}
S {}
E {}

C {symbols/nfet_03v3.sym} 400 600 0 0 {name=M1 W=50u L=0.28u nf=5 m=1}
C {symbols/nfet_03v3.sym} 800 600 0 0 {name=M2 W=50u L=0.28u nf=5 m=1}
C {symbols/nfet_03v3.sym} 400 400 0 0 {name=M3 W=50u L=0.28u nf=5 m=1}
C {symbols/nfet_03v3.sym} 500 400 0 0 {name=M4 W=50u L=0.28u nf=5 m=1}
C {symbols/nfet_03v3.sym} 700 400 0 0 {name=M5 W=50u L=0.28u nf=5 m=1}
C {symbols/nfet_03v3.sym} 800 400 0 0 {name=M6 W=50u L=0.28u nf=5 m=1}
C {devices/res.sym} 450 250 0 0 {name=R1 value=2k}
C {devices/res.sym} 770 250 0 0 {name=R2 value=2k}
C {devices/isource.sym} 600 700 0 0 {name=I1 value=2m}

N 450 220 770 220 {lab=VDD}
N 450 280 450 340 {lab=IF_P}
N 420 370 420 340 {lab=IF_P}
N 420 340 720 340 {lab=IF_P}
N 720 340 720 370 {lab=IF_P}
N 520 370 520 390 {lab=IF_N}
N 520 390 820 390 {lab=IF_N}
N 820 390 820 370 {lab=IF_N}
N 770 280 770 390 {lab=IF_N}
N 420 430 520 430 {lab=M1D}
N 420 430 420 570 {lab=M1D}
N 720 430 820 430 {lab=M2D}
N 820 430 820 570 {lab=M2D}
N 420 630 820 630 {lab=TAIL}
N 600 630 600 670 {lab=TAIL}

C {devices/lab_pin.sym} 420 570 0 0 {name=p1 lab=M1D}
C {devices/lab_pin.sym} 380 600 0 0 {name=p2 lab=RF_P}
C {devices/lab_pin.sym} 420 630 0 0 {name=p3 lab=TAIL}
C {devices/lab_pin.sym} 420 600 0 0 {name=p4 lab=0}
C {devices/lab_pin.sym} 820 570 0 0 {name=p5 lab=M2D}
C {devices/lab_pin.sym} 780 600 0 0 {name=p6 lab=RF_N}
C {devices/lab_pin.sym} 820 630 0 0 {name=p7 lab=TAIL}
C {devices/lab_pin.sym} 820 600 0 0 {name=p8 lab=0}
C {devices/lab_pin.sym} 420 370 0 0 {name=p9 lab=IF_P}
C {devices/lab_pin.sym} 380 400 0 0 {name=p10 lab=LO_P}
C {devices/lab_pin.sym} 420 430 0 0 {name=p11 lab=M1D}
C {devices/lab_pin.sym} 420 400 0 0 {name=p12 lab=0}
C {devices/lab_pin.sym} 520 370 0 0 {name=p13 lab=IF_N}
C {devices/lab_pin.sym} 480 400 0 0 {name=p14 lab=LO_N}
C {devices/lab_pin.sym} 520 430 0 0 {name=p15 lab=M1D}
C {devices/lab_pin.sym} 520 400 0 0 {name=p16 lab=0}
C {devices/lab_pin.sym} 720 370 0 0 {name=p17 lab=IF_P}
C {devices/lab_pin.sym} 680 400 0 0 {name=p18 lab=LO_N}
C {devices/lab_pin.sym} 720 430 0 0 {name=p19 lab=M2D}
C {devices/lab_pin.sym} 720 400 0 0 {name=p20 lab=0}
C {devices/lab_pin.sym} 820 370 0 0 {name=p21 lab=IF_N}
C {devices/lab_pin.sym} 780 400 0 0 {name=p22 lab=LO_P}
C {devices/lab_pin.sym} 820 430 0 0 {name=p23 lab=M2D}
C {devices/lab_pin.sym} 820 400 0 0 {name=p24 lab=0}
C {devices/lab_pin.sym} 450 220 0 0 {name=p25 lab=VDD}
C {devices/lab_pin.sym} 450 280 0 0 {name=p26 lab=IF_P}
C {devices/lab_pin.sym} 770 220 0 0 {name=p27 lab=VDD}
C {devices/lab_pin.sym} 770 280 0 0 {name=p28 lab=IF_N}
C {devices/lab_pin.sym} 600 670 0 0 {name=p29 lab=TAIL}
C {devices/lab_pin.sym} 600 730 0 0 {name=p30 lab=0}

C {devices/ipin.sym} 450 220 0 0 {name=pVDD lab=VDD}
C {devices/ipin.sym} 600 730 0 0 {name=pGND lab=0}
C {devices/ipin.sym} 380 600 0 0 {name=pRFP lab=RF_P}
C {devices/ipin.sym} 780 600 0 0 {name=pRFN lab=RF_N}
C {devices/ipin.sym} 380 400 0 0 {name=pLOP lab=LO_P}
C {devices/ipin.sym} 480 400 0 0 {name=pLON lab=LO_N}
C {devices/opin.sym} 450 280 0 0 {name=pIFP lab=IF_P}
C {devices/opin.sym} 770 280 0 0 {name=pIFN lab=IF_N}
B 2 900 0 1860 220 {flags=graph
rawfile=/home/irman/PandaChip/designs/rf_trans/mixer_verify.raw
sim_type=tran
autoload=1
color="4 12"
y1=0.487
y2=3.56
divy=4
x1=0
x2=5e-07
divx=8
node="vdd
if_p"
}
B 2 900 260 1860 480 {flags=graph
rawfile=/home/irman/PandaChip/designs/rf_trans/mixer_verify.raw
sim_type=tran
autoload=1
color="4 12"
y1=0.571
y2=2.01
divy=4
x1=0
x2=5e-07
divx=8
node="if_n
x1.m1d"
}
B 2 900 520 1860 740 {flags=graph
rawfile=/home/irman/PandaChip/designs/rf_trans/mixer_verify.raw
sim_type=tran
autoload=1
color="4 12"
y1=0.343
y2=1.95
divy=4
x1=0
x2=1.5e-07
divx=8
node="x1.m2d
x1.tail"
}
