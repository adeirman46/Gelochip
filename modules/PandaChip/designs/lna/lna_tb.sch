v {xschem version=3.4.8 file_version=1.2}
G {}
K {}
V {}
S {}
E {}

C {devices/vsource.sym} 100 -300 0 0 {name=VDD value=3.3}
C {devices/lab_pin.sym} 100 -330 0 0 {name=p1 lab=VDD}
C {devices/gnd.sym} 100 -270 0 0 {name=l1 lab=0}

C {devices/vsource.sym} 200 -300 0 0 {name=VBS value=0.9}
C {devices/lab_pin.sym} 200 -330 0 0 {name=p2 lab=VBIAS}
C {devices/gnd.sym} 200 -270 0 0 {name=l2 lab=0}

C {devices/vsource.sym} 100 100 0 0 {name=VIN value="SIN(0.9 0.001 40MEG) AC 1"}
C {devices/lab_pin.sym} 100 70 0 0 {name=p3 lab=IN}
C {devices/gnd.sym} 100 130 0 0 {name=l3 lab=0}

C {symbols/nfet_03v3.sym} 400 0 0 0 {name=M1 W=80u L=0.28u nf=2 m=1}
C {devices/lab_pin.sym} 380 0 0 0 {name=p4 lab=IN}
C {devices/lab_pin.sym} 420 -30 0 0 {name=p5 lab=N1}
C {devices/gnd.sym} 420 30 0 0 {name=l4 lab=0}
C {devices/lab_pin.sym} 420 0 0 0 {name=p6 lab=0}
C {devices/res.sym} 420 -60 0 0 {name=RL1 value=2k}
C {devices/lab_pin.sym} 420 -90 0 0 {name=p7 lab=VDD}

C {devices/capa.sym} 550 -30 0 0 {name=C1 value=1n}
C {devices/lab_pin.sym} 550 -60 0 0 {name=p8 lab=N1}
C {devices/lab_pin.sym} 550 0 0 0 {name=p9 lab=N1G}
C {devices/res.sym} 620 0 0 0 {name=RB1 value=10k}
C {devices/lab_pin.sym} 620 -30 0 0 {name=p10 lab=N1G}
C {devices/lab_pin.sym} 620 30 0 0 {name=p11 lab=VBIAS}

C {symbols/nfet_03v3.sym} 700 0 0 0 {name=M3 W=80u L=0.28u nf=2 m=1}
C {devices/lab_pin.sym} 680 0 0 0 {name=p12 lab=N1G}
C {devices/lab_pin.sym} 720 -30 0 0 {name=p13 lab=N2}
C {devices/gnd.sym} 720 30 0 0 {name=l5 lab=0}
C {devices/lab_pin.sym} 720 0 0 0 {name=p14 lab=0}
C {devices/res.sym} 720 -60 0 0 {name=RL2 value=2k}
C {devices/lab_pin.sym} 720 -90 0 0 {name=p15 lab=VDD}

C {devices/capa.sym} 850 -30 0 0 {name=C2 value=1n}
C {devices/lab_pin.sym} 850 -60 0 0 {name=p16 lab=N2}
C {devices/lab_pin.sym} 850 0 0 0 {name=p17 lab=N2G}
C {devices/res.sym} 920 0 0 0 {name=RB2 value=10k}
C {devices/lab_pin.sym} 920 -30 0 0 {name=p18 lab=N2G}
C {devices/lab_pin.sym} 920 30 0 0 {name=p19 lab=VBIAS}

C {symbols/nfet_03v3.sym} 1000 0 0 0 {name=M5 W=80u L=0.28u nf=2 m=1}
C {devices/lab_pin.sym} 980 0 0 0 {name=p20 lab=N2G}
C {devices/lab_pin.sym} 1020 -30 0 0 {name=p21 lab=OUT}
C {devices/gnd.sym} 1020 30 0 0 {name=l6 lab=0}
C {devices/lab_pin.sym} 1020 0 0 0 {name=p22 lab=0}
C {devices/res.sym} 1020 -60 0 0 {name=RL3 value=2k}
C {devices/lab_pin.sym} 1020 -90 0 0 {name=p23 lab=VDD}

C {devices/code_shown.sym} 1300 -300 0 0 {name=CONTROL only_toplevel=true value=".include /foss/pdks/gf180mcuD/libs.tech/ngspice/design.ngspice
.lib /foss/pdks/gf180mcuD/libs.tech/ngspice/sm141064.ngspice typical
.tran 0.5n 2u
.ac dec 20 1k 1G
.save all"}
B 2 1380 -330 2340 -110 {flags=graph
rawfile=/home/irman/PandaChip/designs/lna/lna_view.raw
sim_type=tran
autoload=1
color="4"
y1=0.12
y2=1.07
divy=4
x1=0
x2=3.75e-07
divx=8
node="out"
}
B 2 1380 -70 2340 150 {flags=graph
rawfile=/home/irman/PandaChip/designs/lna/lna_view.raw
sim_type=tran
autoload=1
color="4"
y1=0.899
y2=0.901
divy=4
x1=0
x2=3.75e-07
divx=8
node="in"
}

T {AC verified (lna_final_ac.raw): peak 54.0 dB @ 2.24 MHz, 53.8 dB @ 40-50 MHz, -3dB BW 22.4 kHz - 251 MHz} 1380 210 0 0 0.25 0.25 {layer=8}
B 2 1380 190 2340 410 {flags=graph
rawfile=/home/irman/PandaChip/designs/lna/lna_view.raw
sim_type=ac
autoload=1
color="4"
y1=0
y2=60
divy=4
x1=3
x2=9
divx=8
logx=1
unitx=1
node="gain_dB;out db20()"
}
