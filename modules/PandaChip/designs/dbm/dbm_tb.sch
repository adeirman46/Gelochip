v {xschem version=3.4.8 file_version=1.2}
G {}
K {}
V {}
S {}
E {}

C {symbols/nfet_03v3.sym} 400 600 0 0 {name=M1 W=20u L=0.28u nf=2 m=1}
C {symbols/nfet_03v3.sym} 800 600 0 0 {name=M2 W=20u L=0.28u nf=2 m=1}
C {symbols/nfet_03v3.sym} 400 400 0 0 {name=M3 W=20u L=0.28u nf=2 m=1}
C {symbols/nfet_03v3.sym} 500 400 0 0 {name=M4 W=20u L=0.28u nf=2 m=1}
C {symbols/nfet_03v3.sym} 700 400 0 0 {name=M5 W=20u L=0.28u nf=2 m=1}
C {symbols/nfet_03v3.sym} 800 400 0 0 {name=M6 W=20u L=0.28u nf=2 m=1}
C {devices/res.sym} 450 250 0 0 {name=R1 value=5k}
C {devices/res.sym} 770 250 0 0 {name=R2 value=5k}
C {devices/isource.sym} 600 700 0 0 {name=I1 value=200u}
C {devices/vsource.sym} 100 100 0 0 {name=V1 value=3.3}
C {devices/vsource.sym} 100 600 0 0 {name=V2 value="SIN(1.5 0.05 5MEG)"}
C {devices/vsource.sym} 1100 600 0 0 {name=V3 value="SIN(1.5 0.05 5MEG 0 0 180)"}
C {devices/vsource.sym} 100 400 0 0 {name=V4 value="SIN(2.2 0.4 4MEG)"}
C {devices/vsource.sym} 1100 400 0 0 {name=V5 value="SIN(2.2 0.4 4MEG 0 0 180)"}
C {devices/code_shown.sym} 700 -600 0 0 {name=CONTROL only_toplevel=true value=".include /foss/pdks/gf180mcuD/libs.tech/ngspice/design.ngspice
.lib /foss/pdks/gf180mcuD/libs.tech/ngspice/sm141064.ngspice typical
E1 IF_DIFF 0 IF_P IF_N 1
.tran 1n 10u
.save all
.option savecurrents"}

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
C {devices/lab_pin.sym} 100 70 0 0 {name=p31 lab=VDD}
C {devices/lab_pin.sym} 100 130 0 0 {name=p32 lab=0}
C {devices/lab_pin.sym} 100 570 0 0 {name=p33 lab=RF_P}
C {devices/lab_pin.sym} 100 630 0 0 {name=p34 lab=0}
C {devices/lab_pin.sym} 1100 570 0 0 {name=p35 lab=RF_N}
C {devices/lab_pin.sym} 1100 630 0 0 {name=p36 lab=0}
C {devices/lab_pin.sym} 100 370 0 0 {name=p37 lab=LO_P}
C {devices/lab_pin.sym} 100 430 0 0 {name=p38 lab=0}
C {devices/lab_pin.sym} 1100 370 0 0 {name=p39 lab=LO_N}
C {devices/lab_pin.sym} 1100 430 0 0 {name=p40 lab=0}
B 2 1180 -600 2140 -380 {flags=graph
rawfile=/home/irman/PandaChip/designs/dbm/dbm_tb_tran.raw
sim_type=tran
autoload=1
y1=1.34
y2=2.71
divy=4
x1=0
x2=1e-05
divx=8
node="rf_p
lo_p"
}
B 2 1180 -340 2140 -120 {flags=graph
rawfile=/home/irman/PandaChip/designs/dbm/dbm_tb_tran.raw
sim_type=tran
autoload=1
y1=2.49
y2=3.11
divy=4
x1=0
x2=1e-05
divx=8
node="if_p
if_n"
}
B 2 1180 -80 2140 140 {flags=graph
rawfile=/home/irman/PandaChip/designs/dbm/dbm_tb_tran.raw
sim_type=tran
autoload=1
y1=-0.609
y2=0.609
divy=4
x1=0
x2=1e-05
divx=8
node="IF_diff;if_p if_n -"
}
