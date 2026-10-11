v {xschem version=3.4.8 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
N 50 -400 1500 -400 {lab=VDD}
N 0 300 1500 300 {lab=0}
N 100 -30 170 -30 {lab=VS_EMF}
N 230 -30 270 -30 {lab=RS_OUT}
N 330 -30 420 -30 {lab=IN}
N 480 -30 680 -30 {lab=G1}
N 680 -30 680 0 {lab=G1}
N 720 -90 970 -90 {lab=D1}
N 1030 -90 1140 -90 {lab=G2}
N 1140 -90 1140 0 {lab=G2}
N 1140 0 1180 0 {lab=G2}
N 1220 -90 1420 -90 {lab=OUT}
N 800 -170 800 -90 {lab=D1}
N 860 -170 860 -90 {lab=D1}
N 920 -170 920 -90 {lab=D1}
N 800 -230 920 -230 {lab=VDD}
N 860 -230 860 -400 {lab=VDD}
N 1300 -170 1300 -90 {lab=OUT}
N 1360 -170 1360 -90 {lab=OUT}
N 1420 -170 1420 -90 {lab=OUT}
N 1300 -230 1420 -230 {lab=VDD}
N 1360 -230 1360 -400 {lab=VDD}
N 720 30 720 70 {lab=S1}
N 720 130 720 300 {lab=0}
N 550 30 720 30 {lab=S1}
N 1220 30 1220 300 {lab=0}
N 500 -30 500 20 {lab=G1}
N 500 80 500 120 {lab=VB1}
N 500 180 500 300 {lab=0}
N 1100 -90 1100 20 {lab=G2}
N 1100 80 1100 120 {lab=VB2}
N 1100 180 1100 300 {lab=0}
N 50 -230 50 -400 {lab=VDD}
N 50 -170 50 300 {lab=0}
N 100 30 100 300 {lab=0}
N 600 280 600 300 {lab=0}
N 1150 280 1150 300 {lab=0}
C {devices/vsource.sym} 100 0 0 0 {name=VS value="SIN(0 0.001 40MEG) AC 1"}
C {devices/lab_pin.sym} 100 -30 0 0 {name=p1 lab=VS_EMF}
C {devices/lab_pin.sym} 100 30 0 0 {name=p2 lab=0}
C {devices/res.sym} 200 -30 1 0 {name=RS value=50}
C {devices/lab_pin.sym} 230 -30 0 0 {name=p3 lab=RS_OUT}
C {devices/lab_pin.sym} 170 -30 0 0 {name=p4 lab=VS_EMF}
C {devices/capa.sym} 300 -30 1 0 {name=Cdc value=100n}
C {devices/lab_pin.sym} 330 -30 0 0 {name=p5 lab=IN}
C {devices/lab_pin.sym} 270 -30 0 0 {name=p6 lab=RS_OUT}
C {devices/ind.sym} 450 -30 1 0 {name=LG value=1u}
C {devices/lab_pin.sym} 480 -30 0 0 {name=p7 lab=G1}
C {devices/lab_pin.sym} 420 -30 0 0 {name=p8 lab=IN}
C {devices/capa.sym} 550 0 0 0 {name=Cext value=15p}
C {devices/lab_pin.sym} 550 -30 0 0 {name=p9 lab=G1}
C {devices/lab_pin.sym} 550 30 0 0 {name=p10 lab=S1}
C {symbols/nfet_03v3.sym} 700 0 0 0 {name=M1 W=100u L=0.28u nf=5 m=1}
C {devices/lab_pin.sym} 680 0 0 0 {name=p11 lab=G1}
C {devices/lab_pin.sym} 720 -30 0 0 {name=p12 lab=MID1}
C {devices/lab_pin.sym} 720 30 0 0 {name=p13 lab=S1}
C {devices/lab_pin.sym} 720 0 0 0 {name=p14 lab=0}
C {devices/ind.sym} 720 100 0 0 {name=LS value=60n}
C {devices/lab_pin.sym} 720 70 0 0 {name=p15 lab=S1}
C {devices/lab_pin.sym} 720 130 0 0 {name=p16 lab=0}
C {symbols/nfet_03v3.sym} 700 -60 0 0 {name=M2 W=100u L=0.28u nf=5 m=1}
C {devices/lab_pin.sym} 680 -60 0 0 {name=p17 lab=VCAS1}
C {devices/lab_pin.sym} 720 -90 0 0 {name=p18 lab=D1}
C {devices/lab_pin.sym} 720 -60 0 0 {name=p20 lab=0}
C {devices/ind.sym} 800 -200 0 0 {name=Lt1 value=1u}
C {devices/lab_pin.sym} 800 -230 0 0 {name=p21 lab=VDD}
C {devices/lab_pin.sym} 800 -170 0 0 {name=p22 lab=D1}
C {devices/capa.sym} 860 -200 0 0 {name=Ct1 value=15p}
C {devices/lab_pin.sym} 860 -230 0 0 {name=p23 lab=VDD}
C {devices/lab_pin.sym} 860 -170 0 0 {name=p24 lab=D1}
C {devices/res.sym} 920 -200 0 0 {name=Rt1 value=1.5k}
C {devices/lab_pin.sym} 920 -230 0 0 {name=p25 lab=VDD}
C {devices/lab_pin.sym} 920 -170 0 0 {name=p26 lab=D1}
C {devices/capa.sym} 1000 -90 1 0 {name=Ccoup value=1n}
C {devices/lab_pin.sym} 1030 -90 0 0 {name=p27 lab=G2}
C {devices/lab_pin.sym} 970 -90 0 0 {name=p28 lab=D1}
C {devices/res.sym} 500 50 0 0 {name=Rb1 value=1Meg}
C {devices/lab_pin.sym} 500 20 0 0 {name=p29 lab=G1}
C {devices/lab_pin.sym} 500 80 0 0 {name=p30 lab=VB1}
C {devices/vsource.sym} 500 150 0 0 {name=VBS1 value=0.9}
C {devices/lab_pin.sym} 500 120 0 0 {name=p31 lab=VB1}
C {devices/lab_pin.sym} 500 180 0 0 {name=p32 lab=0}
C {devices/res.sym} 1100 50 0 0 {name=Rb2 value=1Meg}
C {devices/lab_pin.sym} 1100 20 0 0 {name=p33 lab=G2}
C {devices/lab_pin.sym} 1100 80 0 0 {name=p34 lab=VB2}
C {devices/vsource.sym} 1100 150 0 0 {name=VBS2 value=0.9}
C {devices/lab_pin.sym} 1100 120 0 0 {name=p35 lab=VB2}
C {devices/lab_pin.sym} 1100 180 0 0 {name=p36 lab=0}
C {symbols/nfet_03v3.sym} 1200 0 0 0 {name=M3 W=100u L=0.28u nf=5 m=1}
C {devices/lab_pin.sym} 1180 0 0 0 {name=p37 lab=G2}
C {devices/lab_pin.sym} 1220 -30 0 0 {name=p38 lab=MID2}
C {devices/lab_pin.sym} 1220 30 0 0 {name=p39 lab=0}
C {devices/lab_pin.sym} 1220 0 0 0 {name=p40 lab=0}
C {symbols/nfet_03v3.sym} 1200 -60 0 0 {name=M4 W=100u L=0.28u nf=5 m=1}
C {devices/lab_pin.sym} 1180 -60 0 0 {name=p41 lab=VCAS2}
C {devices/lab_pin.sym} 1220 -90 0 0 {name=p42 lab=OUT}
C {devices/lab_pin.sym} 1220 -60 0 0 {name=p44 lab=0}
C {devices/ind.sym} 1300 -200 0 0 {name=Lt2 value=1u}
C {devices/lab_pin.sym} 1300 -230 0 0 {name=p45 lab=VDD}
C {devices/lab_pin.sym} 1300 -170 0 0 {name=p46 lab=OUT}
C {devices/capa.sym} 1360 -200 0 0 {name=Ct2 value=15p}
C {devices/lab_pin.sym} 1360 -230 0 0 {name=p47 lab=VDD}
C {devices/lab_pin.sym} 1360 -170 0 0 {name=p48 lab=OUT}
C {devices/res.sym} 1420 -200 0 0 {name=Rt2 value=1.5k}
C {devices/lab_pin.sym} 1420 -230 0 0 {name=p49 lab=VDD}
C {devices/lab_pin.sym} 1420 -170 0 0 {name=p50 lab=OUT}
C {devices/vsource.sym} 50 -200 0 0 {name=VDDSRC value=3.3}
C {devices/lab_pin.sym} 50 -230 0 0 {name=p51 lab=VDD}
C {devices/lab_pin.sym} 50 -170 0 0 {name=p52 lab=0}
C {devices/vsource.sym} 600 250 0 0 {name=VCAS1SRC value=2.0}
C {devices/lab_pin.sym} 600 220 0 0 {name=p53 lab=VCAS1}
C {devices/lab_pin.sym} 600 280 0 0 {name=p54 lab=0}
C {devices/vsource.sym} 1150 250 0 0 {name=VCAS2SRC value=2.0}
C {devices/lab_pin.sym} 1150 220 0 0 {name=p55 lab=VCAS2}
C {devices/lab_pin.sym} 1150 280 0 0 {name=p56 lab=0}
C {devices/gnd.sym} 100 300 0 0 {name=l1 lab=0}
C {devices/gnd.sym} 720 300 0 0 {name=l2 lab=0}
C {devices/gnd.sym} 1220 300 0 0 {name=l3 lab=0}
C {devices/code_shown.sym} 700 -600 0 0 {name=CONTROL only_toplevel=true value=".include /foss/pdks/gf180mcuD/libs.tech/ngspice/design.ngspice
.lib /foss/pdks/gf180mcuD/libs.tech/ngspice/sm141064.ngspice typical
.tran 0.5n 2u
.ac dec 20 1k 1G
.save all"}
B 2 1580 -600 2540 -380 {flags=graph
rawfile=/home/irman/PandaChip/designs/lna-match/lna_match_view.raw
sim_type=tran
autoload=1
color="4"
y1=1.46
y2=5.11
divy=4
x1=0
x2=3.75e-07
divx=8
node="out"
}
B 2 1580 -340 2540 -120 {flags=graph
rawfile=/home/irman/PandaChip/designs/lna-match/lna_match_view.raw
sim_type=tran
autoload=1
color="4"
y1=0.896
y2=0.907
divy=4
x1=0
x2=3.75e-07
divx=8
node="in"
}
B 2 1580 -80 2540 140 {flags=graph
rawfile=/home/irman/PandaChip/designs/lna-match/lna_match_view.raw
sim_type=ac
autoload=1
color="4"
y1=-80
y2=70
divy=6
x1=3
x2=9
divx=6
logx=1
unitx=1
node="gain_dB;out db20()"
}
B 2 1580 180 2540 400 {flags=graph
rawfile=/home/irman/PandaChip/designs/lna-match/lna_match_view.raw
sim_type=ac
autoload=1
color="12"
y1=-10
y2=4
divy=7
x1=3
x2=9
divx=6
logx=1
unitx=1
node="match_dB;in db20()"
}
T {AC gain (dB) and input match: v(IN) dips to -6.6 dB at 40 MHz = matched to 50 ohm} 1580 -100 0 0 0.25 0.25 {layer=8}
