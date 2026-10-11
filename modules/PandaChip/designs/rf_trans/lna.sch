v {xschem version=3.4.8 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
C {symbols/nfet_03v3.sym} 200 100 0 0 {name=M1 W=50u L=0.28u nf=5 m=1}
C {symbols/nfet_03v3.sym} 200 40 0 0 {name=M2 W=50u L=0.28u nf=5 m=1}

N 220 -100 220 -60 {lab=VDD}
N 220 0 220 10 {lab=RF_OUT}
N 220 70 220 70 {lab=MID}
N 220 130 220 160 {lab=0}

C {devices/ind.sym} 220 -30 0 0 {name=L1 value=100n}
C {devices/capa.sym} 280 -30 0 0 {name=C1 value=25.3p}
C {devices/res.sym} 340 -30 0 0 {name=R_load value=2k}

N 220 -60 280 -60 {lab=VDD}
N 280 -60 340 -60 {lab=VDD}
N 220 0 280 0 {lab=RF_OUT}
N 280 0 340 0 {lab=RF_OUT}

C {devices/capa.sym} 120 100 1 0 {name=Cin value=10p}
N 40 100 90 100 {lab=RF_IN}
N 150 100 180 100 {lab=VBIAS1}

C {devices/res.sym} 120 -10 0 0 {name=R1 value=15k}
C {devices/res.sym} 120 70 0 0 {name=R2 value=18k}
N 120 -60 120 -40 {lab=VDD}
N 120 20 120 40 {lab=VBIAS2}
N 120 100 120 160 {lab=0}
N 120 40 180 40 {lab=VBIAS2}

C {devices/res.sym} 160 150 0 0 {name=R3 value=25k}
C {devices/res.sym} 160 230 0 0 {name=R4 value=8k}
N 160 -60 160 120 {lab=VDD}
N 160 180 160 200 {lab=VBIAS1}
N 160 260 160 280 {lab=0}
N 160 190 180 190 {lab=VBIAS1}
N 180 100 180 190 {lab=VBIAS1}

C {devices/ipin.sym} 220 -100 0 0 {name=pVDD lab=VDD}
C {devices/ipin.sym} 40 100 0 0 {name=pIN lab=RF_IN}
C {devices/opin.sym} 340 0 0 0 {name=pOUT lab=RF_OUT}
C {devices/ipin.sym} 220 160 0 0 {name=pGND lab=0}

C {devices/lab_pin.sym} 220 -60 0 0 {name=l1 lab=VDD}
C {devices/lab_pin.sym} 220 0 0 0 {name=l2 lab=RF_OUT}
C {devices/lab_pin.sym} 220 70 0 0 {name=l3 lab=MID}
C {devices/lab_pin.sym} 220 160 0 0 {name=l4 lab=0}
C {devices/lab_pin.sym} 180 100 0 0 {name=l5 lab=VBIAS1}
C {devices/lab_pin.sym} 180 40 0 0 {name=l6 lab=VBIAS2}
C {devices/lab_pin.sym} 120 -60 0 0 {name=l7 lab=VDD}
C {devices/lab_pin.sym} 160 -60 0 0 {name=l8 lab=VDD}
C {devices/lab_pin.sym} 120 160 0 0 {name=l9 lab=0}
C {devices/lab_pin.sym} 160 280 0 0 {name=l10 lab=0}
C {devices/lab_pin.sym} 220 100 0 0 {name=l11 lab=0}
C {devices/lab_pin.sym} 220 40 0 0 {name=l12 lab=0}

N 120 -60 160 -60 {lab=VDD}
N 160 -60 220 -60 {lab=VDD}
B 2 420 -100 1380 120 {flags=graph
rawfile=/home/irman/PandaChip/designs/rf_trans/lna_verify.raw
sim_type=tran
autoload=1
color="4 12"
y1=3.22
y2=3.38
divy=4
x1=0
x2=2e-07
divx=8
node="vdd
rf_out"
}
B 2 420 160 1380 380 {flags=graph
rawfile=/home/irman/PandaChip/designs/rf_trans/lna_verify.raw
sim_type=tran
autoload=1
color="4 12"
y1=-0.103
y2=1.01
divy=4
x1=0
x2=1.5e-07
divx=8
node="x1.mid
rf_in"
}
B 2 420 420 1380 640 {flags=graph
rawfile=/home/irman/PandaChip/designs/rf_trans/lna_verify.raw
sim_type=tran
autoload=1
color="4 12"
y1=0.688
y2=1.91
divy=4
x1=0
x2=1.5e-07
divx=8
node="x1.vbias1
x1.vbias2"
}
