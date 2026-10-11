v {xschem version=3.4.8 file_version=1.2}
G {}
K {}
V {}
S {}
E {}

// ======== Power and bias sources ========
C {devices/vsource.sym} 100 -400 0 0 {name=VDD value=3.3}
C {devices/lab_pin.sym} 100 -430 0 0 {name=p1 lab=VDD}
C {devices/gnd.sym} 100 -370 0 0 {name=l1 lab=0}

C {devices/vsource.sym} 200 -400 0 0 {name=VCBS value=1.3}
C {devices/lab_pin.sym} 200 -430 0 0 {name=p2 lab=VCB}
C {devices/gnd.sym} 200 -370 0 0 {name=l2 lab=0}

C {devices/vsource.sym} 300 -400 0 0 {name=VPBS value=2.0}
C {devices/lab_pin.sym} 300 -430 0 0 {name=p3 lab=VPB}
C {devices/gnd.sym} 300 -370 0 0 {name=l3 lab=0}

// Input source: 1 mV sine at 100 MHz, DC=0.9V, AC magnitude=1
C {devices/vsource.sym} 100 100 0 0 {name=VIN value="SIN(0.9 0.001 100MEG) AC 1"}
C {devices/lab_pin.sym} 100 70 0 0 {name=p4 lab=IN}
C {devices/gnd.sym} 100 130 0 0 {name=l4 lab=0}

// Input AC coupling: IN -> IN_G
C {devices/capa.sym} 370 0 0 0 {name=CIN value=1p}
C {devices/lab_pin.sym} 370 -30 0 0 {name=p5 lab=IN_G}
C {devices/lab_pin.sym} 370 30 0 0 {name=p6 lab=IN}

// ======== Stage 1: Cascode NMOS + PMOS active load, self-biased ========
C {symbols/nfet_03v3.sym} 500 0 0 0 {name=M1 W=80u L=0.28u nf=2 m=1}
C {devices/lab_pin.sym} 480 0 0 0 {name=p7 lab=IN_G}
C {devices/lab_pin.sym} 520 -30 0 0 {name=p8 lab=NC1}
C {devices/gnd.sym} 520 30 0 0 {name=l5 lab=0}
C {devices/lab_pin.sym} 520 0 0 0 {name=p9 lab=0}

C {symbols/nfet_03v3.sym} 500 -60 0 0 {name=M2 W=80u L=0.28u nf=2 m=1}
C {devices/lab_pin.sym} 480 -60 0 0 {name=p10 lab=VCB}
C {devices/lab_pin.sym} 520 -90 0 0 {name=p11 lab=N1}
C {devices/lab_pin.sym} 520 -60 0 0 {name=p12 lab=0}

C {symbols/pfet_03v3.sym} 500 -120 0 0 {name=M3 W=80u L=0.28u nf=2 m=1}
C {devices/lab_pin.sym} 480 -120 0 0 {name=p13 lab=VPB}
C {devices/lab_pin.sym} 520 -150 0 0 {name=p14 lab=VDD}
C {devices/lab_pin.sym} 520 -120 0 0 {name=p15 lab=VDD}

// Feedback resistor R_f1: N1 -> IN_G
C {devices/res.sym} 600 -45 1 0 {name=RF1 value=1M}
C {devices/lab_pin.sym} 630 -45 0 0 {name=p16 lab=N1}
C {devices/lab_pin.sym} 570 -45 0 0 {name=p17 lab=IN_G}

// ======== Stage 2: Cascode NMOS + PMOS active load, self-biased ========
C {symbols/nfet_03v3.sym} 850 0 0 0 {name=M4 W=80u L=0.28u nf=2 m=1}
C {devices/lab_pin.sym} 830 0 0 0 {name=p18 lab=N1}
C {devices/lab_pin.sym} 870 -30 0 0 {name=p19 lab=NC2}
C {devices/gnd.sym} 870 30 0 0 {name=l6 lab=0}
C {devices/lab_pin.sym} 870 0 0 0 {name=p20 lab=0}

C {symbols/nfet_03v3.sym} 850 -60 0 0 {name=M5 W=80u L=0.28u nf=2 m=1}
C {devices/lab_pin.sym} 830 -60 0 0 {name=p21 lab=VCB}
C {devices/lab_pin.sym} 870 -90 0 0 {name=p22 lab=N2}
C {devices/lab_pin.sym} 870 -60 0 0 {name=p23 lab=0}

C {symbols/pfet_03v3.sym} 850 -120 0 0 {name=M6 W=80u L=0.28u nf=2 m=1}
C {devices/lab_pin.sym} 830 -120 0 0 {name=p24 lab=VPB}
C {devices/lab_pin.sym} 870 -150 0 0 {name=p25 lab=VDD}
C {devices/lab_pin.sym} 870 -120 0 0 {name=p26 lab=VDD}

// Feedback resistor R_f2: N2 -> N1
C {devices/res.sym} 950 -45 1 0 {name=RF2 value=1M}
C {devices/lab_pin.sym} 980 -45 0 0 {name=p27 lab=N2}
C {devices/lab_pin.sym} 920 -45 0 0 {name=p28 lab=N1}

// ======== Stage 3: Cascode NMOS + PMOS active load, self-biased ========
C {symbols/nfet_03v3.sym} 1200 0 0 0 {name=M7 W=80u L=0.28u nf=2 m=1}
C {devices/lab_pin.sym} 1180 0 0 0 {name=p29 lab=N2}
C {devices/lab_pin.sym} 1220 -30 0 0 {name=p30 lab=NC3}
C {devices/gnd.sym} 1220 30 0 0 {name=l7 lab=0}
C {devices/lab_pin.sym} 1220 0 0 0 {name=p31 lab=0}

C {symbols/nfet_03v3.sym} 1200 -60 0 0 {name=M8 W=80u L=0.28u nf=2 m=1}
C {devices/lab_pin.sym} 1180 -60 0 0 {name=p32 lab=VCB}
C {devices/lab_pin.sym} 1220 -90 0 0 {name=p33 lab=OUT}
C {devices/lab_pin.sym} 1220 -60 0 0 {name=p34 lab=0}

C {symbols/pfet_03v3.sym} 1200 -120 0 0 {name=M9 W=80u L=0.28u nf=2 m=1}
C {devices/lab_pin.sym} 1180 -120 0 0 {name=p35 lab=VPB}
C {devices/lab_pin.sym} 1220 -150 0 0 {name=p36 lab=VDD}
C {devices/lab_pin.sym} 1220 -120 0 0 {name=p37 lab=VDD}

// Feedback resistor R_f3: OUT -> N2
C {devices/res.sym} 1300 -45 1 0 {name=RF3 value=1M}
C {devices/lab_pin.sym} 1330 -45 0 0 {name=p38 lab=OUT}
C {devices/lab_pin.sym} 1270 -45 0 0 {name=p39 lab=N2}

// ======== SPICE control block ========
C {devices/code_shown.sym} 1500 -400 0 0 {name=CONTROL only_toplevel=true value=".include /foss/pdks/gf180mcuD/libs.tech/ngspice/design.ngspice
.lib /foss/pdks/gf180mcuD/libs.tech/ngspice/sm141064.ngspice typical
.tran 0.2n 2u
.ac dec 20 1k 1G
.save all"}