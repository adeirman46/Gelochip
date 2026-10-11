v {xschem version=3.4.8 file_version=1.2}
G {}
K {}
V {}
S {}
E {}

C {devices/vsource.sym} 100 -400 0 0 {name=VDD value=3.3}
C {devices/lab_pin.sym} 100 -430 0 0 {name=p1 lab=VDD}
C {devices/gnd.sym} 100 -370 0 0 {name=l1 lab=0}

C {devices/vsource.sym} 200 -400 0 0 {name=VBS value=0.9}
C {devices/lab_pin.sym} 200 -430 0 0 {name=p2 lab=VBIAS}
C {devices/gnd.sym} 200 -370 0 0 {name=l2 lab=0}

C {devices/vsource.sym} 300 -400 0 0 {name=VCBS value=1.5}
C {devices/lab_pin.sym} 300 -430 0 0 {name=p3 lab=VCB}
C {devices/gnd.sym} 300 -370 0 0 {name=l3 lab=0}

C {devices/vsource.sym} 400 -400 0 0 {name=VPBS value=2.1}
C {devices/lab_pin.sym} 400 -430 0 0 {name=p4 lab=VPB}
C {devices/gnd.sym} 400 -370 0 0 {name=l4 lab=0}

C {devices/vsource.sym} 100 100 0 0 {name=VIN value="SIN(0.9 0.001 100MEG) AC 1"}
C {devices/lab_pin.sym} 100 70 0 0 {name=p5 lab=IN}
C {devices/gnd.sym} 100 130 0 0 {name=l5 lab=0}

C {symbols/nfet_03v3.sym} 500 0 0 0 {name=M1 W=80u L=0.28u nf=2 m=1}
C {devices/lab_pin.sym} 480 0 0 0 {name=p6 lab=IN}
C {devices/lab_pin.sym} 520 -30 0 0 {name=p7 lab=NC1}
C {devices/gnd.sym} 520 30 0 0 {name=l6 lab=0}
C {devices/lab_pin.sym} 520 0 0 0 {name=p8 lab=0}

C {symbols/nfet_03v3.sym} 500 -60 0 0 {name=M2 W=80u L=0.28u nf=2 m=1}
C {devices/lab_pin.sym} 480 -60 0 0 {name=p9 lab=VCB}
C {devices/lab_pin.sym} 520 -90 0 0 {name=p10 lab=N1}
C {devices/lab_pin.sym} 520 -60 0 0 {name=p11 lab=0}

C {symbols/pfet_03v3.sym} 500 -120 0 0 {name=M3 W=80u L=0.28u nf=2 m=1}
C {devices/lab_pin.sym} 480 -120 0 0 {name=p12 lab=VPB}
C {devices/lab_pin.sym} 520 -150 0 0 {name=p13 lab=VDD}
C {devices/lab_pin.sym} 520 -120 0 0 {name=p14 lab=VDD}

C {devices/capa.sym} 650 -90 0 0 {name=C1 value=1n}
C {devices/lab_pin.sym} 650 -120 0 0 {name=p15 lab=N1}
C {devices/lab_pin.sym} 650 -60 0 0 {name=p16 lab=N1G}
C {devices/res.sym} 720 -60 0 0 {name=RB1 value=100k}
C {devices/lab_pin.sym} 720 -90 0 0 {name=p17 lab=N1G}
C {devices/lab_pin.sym} 720 -30 0 0 {name=p18 lab=VBIAS}

C {symbols/nfet_03v3.sym} 850 0 0 0 {name=M4 W=80u L=0.28u nf=2 m=1}
C {devices/lab_pin.sym} 830 0 0 0 {name=p19 lab=N1G}
C {devices/lab_pin.sym} 870 -30 0 0 {name=p20 lab=NC2}
C {devices/gnd.sym} 870 30 0 0 {name=l7 lab=0}
C {devices/lab_pin.sym} 870 0 0 0 {name=p21 lab=0}

C {symbols/nfet_03v3.sym} 850 -60 0 0 {name=M5 W=80u L=0.28u nf=2 m=1}
C {devices/lab_pin.sym} 830 -60 0 0 {name=p22 lab=VCB}
C {devices/lab_pin.sym} 870 -90 0 0 {name=p23 lab=N2}
C {devices/lab_pin.sym} 870 -60 0 0 {name=p24 lab=0}

C {symbols/pfet_03v3.sym} 850 -120 0 0 {name=M6 W=80u L=0.28u nf=2 m=1}
C {devices/lab_pin.sym} 830 -120 0 0 {name=p25 lab=VPB}
C {devices/lab_pin.sym} 870 -150 0 0 {name=p26 lab=VDD}
C {devices/lab_pin.sym} 870 -120 0 0 {name=p27 lab=VDD}

C {devices/capa.sym} 1000 -90 0 0 {name=C2 value=1n}
C {devices/lab_pin.sym} 1000 -120 0 0 {name=p28 lab=N2}
C {devices/lab_pin.sym} 1000 -60 0 0 {name=p29 lab=N2G}
C {devices/res.sym} 1070 -60 0 0 {name=RB2 value=100k}
C {devices/lab_pin.sym} 1070 -90 0 0 {name=p30 lab=N2G}
C {devices/lab_pin.sym} 1070 -30 0 0 {name=p31 lab=VBIAS}

C {symbols/nfet_03v3.sym} 1200 0 0 0 {name=M7 W=80u L=0.28u nf=2 m=1}
C {devices/lab_pin.sym} 1180 0 0 0 {name=p32 lab=N2G}
C {devices/lab_pin.sym} 1220 -30 0 0 {name=p33 lab=NC3}
C {devices/gnd.sym} 1220 30 0 0 {name=l8 lab=0}
C {devices/lab_pin.sym} 1220 0 0 0 {name=p34 lab=0}

C {symbols/nfet_03v3.sym} 1200 -60 0 0 {name=M8 W=80u L=0.28u nf=2 m=1}
C {devices/lab_pin.sym} 1180 -60 0 0 {name=p35 lab=VCB}
C {devices/lab_pin.sym} 1220 -90 0 0 {name=p36 lab=OUT}
C {devices/lab_pin.sym} 1220 -60 0 0 {name=p37 lab=0}

C {symbols/pfet_03v3.sym} 1200 -120 0 0 {name=M9 W=80u L=0.28u nf=2 m=1}
C {devices/lab_pin.sym} 1180 -120 0 0 {name=p38 lab=VPB}
C {devices/lab_pin.sym} 1220 -150 0 0 {name=p39 lab=VDD}
C {devices/lab_pin.sym} 1220 -120 0 0 {name=p40 lab=VDD}

C {devices/code_shown.sym} 1500 -400 0 0 {name=CONTROL only_toplevel=true value=".include /foss/pdks/gf180mcuD/libs.tech/ngspice/design.ngspice
.lib /foss/pdks/gf180mcuD/libs.tech/ngspice/sm141064.ngspice typical
.tran 0.2n 2u
.ac dec 20 1k 1G
.save all"}