v {xschem version=3.4.8 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
C {symbols/nfet_03v3.sym} 200 30 0 0 {name=M1 W=50u L=0.28u nf=5 m=1}
C {symbols/nfet_03v3.sym} 300 30 0 1 {name=M2 W=50u L=0.28u nf=5 m=1}

N 220 -100 220 -60 {lab=VDD}
N 280 -100 280 -60 {lab=VDD}
N 220 0 220 0 {lab=LO_P}
N 280 0 280 0 {lab=LO_N}

N 220 60 220 100 {lab=TAIL}
N 280 60 280 100 {lab=TAIL}
N 220 100 280 100 {lab=TAIL}
N 250 100 250 130 {lab=TAIL}
N 250 190 250 230 {lab=0}

N 120 0 220 0 {lab=LO_P}
N 280 0 380 0 {lab=LO_N}

C {devices/ipin.sym} 250 -100 0 0 {name=pVDD lab=VDD}
C {devices/opin.sym} 120 0 0 0 {name=pLOP lab=LO_P}
C {devices/opin.sym} 380 0 0 0 {name=pLON lab=LO_N}
C {devices/ipin.sym} 250 230 0 0 {name=pGND lab=0}

C {devices/ind.sym} 220 -30 0 0 {name=L1 value=100n}
C {devices/ind.sym} 280 -30 0 0 {name=L2 value=100n}

C {devices/res.sym} 190 -30 0 0 {name=R1 value=2k}
C {devices/res.sym} 310 -30 0 0 {name=R2 value=2k}
N 190 -100 220 -100 {lab=VDD}
N 280 -100 310 -100 {lab=VDD}
N 190 -60 190 -100 {lab=VDD}
N 310 -60 310 -100 {lab=VDD}
N 190 0 190 0 {lab=LO_P}
N 310 0 310 0 {lab=LO_N}
N 190 0 220 0 {lab=LO_P}
N 280 0 310 0 {lab=LO_N}

C {devices/capa.sym} 160 30 0 0 {name=C1 value=31.2p}
C {devices/capa.sym} 340 30 0 0 {name=C2 value=31.2p}

N 160 0 160 0 {lab=LO_P}
N 160 60 160 100 {lab=0}
N 340 0 340 0 {lab=LO_N}
N 340 60 340 100 {lab=0}

C {devices/isource.sym} 250 160 0 0 {name=I1 value=1m}

C {devices/lab_pin.sym} 220 -60 0 0 {name=l1 lab=VDD}
C {devices/lab_pin.sym} 280 -60 0 0 {name=l2 lab=VDD}
C {devices/lab_pin.sym} 220 0 0 0 {name=l3 lab=LO_P}
C {devices/lab_pin.sym} 280 0 0 0 {name=l4 lab=LO_N}
C {devices/lab_pin.sym} 220 60 0 0 {name=l5 lab=TAIL}
C {devices/lab_pin.sym} 280 60 0 0 {name=l6 lab=TAIL}
C {devices/lab_pin.sym} 250 230 0 0 {name=l7 lab=0}

C {devices/lab_pin.sym} 160 0 0 0 {name=l8 lab=LO_P}
C {devices/lab_pin.sym} 160 100 0 0 {name=l9 lab=0}
C {devices/lab_pin.sym} 340 0 0 0 {name=l10 lab=LO_N}
C {devices/lab_pin.sym} 340 100 0 0 {name=l11 lab=0}

C {devices/lab_pin.sym} 180 30 0 0 {name=l12 lab=LO_N}
C {devices/lab_pin.sym} 320 30 0 0 {name=l13 lab=LO_P}

C {devices/lab_pin.sym} 220 30 0 0 {name=l14 lab=0}
C {devices/lab_pin.sym} 280 30 0 0 {name=l15 lab=0}

N 220 -100 250 -100 {lab=VDD}
N 250 -100 280 -100 {lab=VDD}
B 2 460 -100 1420 120 {flags=graph
rawfile=/home/irman/PandaChip/designs/rf_trans/lo_verify.raw
sim_type=tran
autoload=1
color="4 12"
y1=2.09
y2=4.5
divy=4
x1=1e-12
x2=2e-07
divx=8
node="vdd
lo_p"
}
B 2 460 160 1420 380 {flags=graph
rawfile=/home/irman/PandaChip/designs/rf_trans/lo_verify.raw
sim_type=tran
autoload=1
color="4 12"
y1=-0.686
y2=7.17
divy=4
x1=1e-12
x2=1.67e-07
divx=8
node="lo_n
x1.tail"
}
