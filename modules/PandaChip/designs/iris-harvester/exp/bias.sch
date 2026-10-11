v {xschem version=3.4.8 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
N 200 -100 200 -60 {lab=VDD}
N 200 -60 260 -60 {lab=VDD}
N 200 0 200 40 {lab=VBIAS}
N 200 40 260 40 {lab=VBIAS}
N 200 100 200 140 {lab=0}
N 200 140 260 140 {lab=0}
N 160 40 200 40 {lab=VBIAS}
N 160 40 160 70 {lab=VBIAS}
N 160 70 180 70 {lab=VBIAS}
N 200 40 220 40 {lab=VBIAS}
N 200 100 220 100 {lab=0}
C {devices/iopin.sym} 200 -100 0 0 {name=p1 lab=VDD}
C {devices/iopin.sym} 260 40 0 0 {name=p2 lab=VBIAS}
C {devices/isource.sym} 200 -30 0 0 {name=I1 value=1u}
C {symbols/nfet_03v3.sym} 200 70 0 0 {name=M1 W=10u L=0.28u nf=2 m=1}
C {devices/gnd.sym} 200 140 0 0 {name=g1 lab=0}
C {devices/lab_pin.sym} 200 -60 0 0 {name=l1 lab=VDD}
C {devices/lab_pin.sym} 200 40 0 0 {name=l2 lab=VBIAS}
C {devices/lab_pin.sym} 200 100 0 0 {name=l3 lab=0}
C {devices/lab_pin.sym} 220 70 0 0 {name=l4 lab=0}
C {devices/lab_pin.sym} 160 70 0 0 {name=l5 lab=VBIAS}
C {devices/lab_pin.sym} 220 40 0 0 {name=l6 lab=VBIAS}
C {devices/lab_pin.sym} 220 100 0 0 {name=l7 lab=0}
