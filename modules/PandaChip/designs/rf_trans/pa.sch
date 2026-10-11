v {xschem version=3.4.8 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
C {symbols/nfet_03v3.sym} 200 100 0 0 {name=M1 W=400u L=0.28u nf=40 m=1}

N 220 -100 220 -60 {lab=VDD}
N 220 0 220 70 {lab=PA_D}
N 220 100 220 160 {lab=0}

C {devices/ind.sym} 220 -30 0 0 {name=L1 value=1u}
C {devices/capa.sym} 280 0 1 0 {name=Cout value=1n}

N 220 0 250 0 {lab=PA_D}
N 310 0 340 0 {lab=RF_OUT}

C {devices/capa.sym} 120 100 1 0 {name=Cin value=100p}
N 40 100 90 100 {lab=RF_IN}
N 150 100 180 100 {lab=VBIAS}

C {devices/res.sym} 160 10 0 0 {name=R1 value=10k}
C {devices/res.sym} 160 190 0 0 {name=R2 value=10k}
N 160 -60 160 -20 {lab=VDD}
N 160 40 160 160 {lab=VBIAS}
N 160 220 160 260 {lab=0}
N 160 100 180 100 {lab=VBIAS}

C {devices/ipin.sym} 220 -100 0 0 {name=pVDD lab=VDD}
C {devices/ipin.sym} 40 100 0 0 {name=pIN lab=RF_IN}
C {devices/opin.sym} 340 0 0 0 {name=pOUT lab=RF_OUT}
C {devices/ipin.sym} 220 160 0 0 {name=pGND lab=0}

C {devices/lab_pin.sym} 220 -60 0 0 {name=l1 lab=VDD}
C {devices/lab_pin.sym} 220 0 0 0 {name=l2 lab=PA_D}
C {devices/lab_pin.sym} 220 160 0 0 {name=l4 lab=0}
C {devices/lab_pin.sym} 180 100 0 0 {name=l5 lab=VBIAS}
C {devices/lab_pin.sym} 160 -60 0 0 {name=l8 lab=VDD}
C {devices/lab_pin.sym} 160 260 0 0 {name=l10 lab=0}
C {devices/lab_pin.sym} 40 100 0 0 {name=l11 lab=RF_IN}
C {devices/lab_pin.sym} 340 0 0 0 {name=l12 lab=RF_OUT}
C {devices/lab_pin.sym} 220 100 0 0 {name=l13 lab=0}
C {devices/lab_pin.sym} 220 130 0 0 {name=l14 lab=0}

N 160 -60 220 -60 {lab=VDD}
B 2 420 -100 1380 120 {flags=graph
rawfile=/home/irman/PandaChip/designs/rf_trans/pa_verify.raw
sim_type=tran
autoload=1
color="4 12"
y1=2.91
y2=3.69
divy=4
x1=0
x2=2e-07
divx=8
node="vdd
x1.pa_d"
}
B 2 420 160 1380 380 {flags=graph
rawfile=/home/irman/PandaChip/designs/rf_trans/pa_verify.raw
sim_type=tran
autoload=1
color="4 12"
y1=-0.39
y2=0.395
divy=4
x1=0
x2=1.5e-07
divx=8
node="rf_out
rf_in"
}
B 2 420 420 1380 640 {flags=graph
rawfile=/home/irman/PandaChip/designs/rf_trans/pa_verify.raw
sim_type=tran
autoload=1
color="4"
y1=1.53
y2=1.77
divy=4
x1=0
x2=1.5e-07
divx=8
node="x1.vbias"
}
