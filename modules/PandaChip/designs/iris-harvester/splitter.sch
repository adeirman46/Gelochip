v {xschem version=3.4.8 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
N 100 0 160 0 {lab=RF_BOOST}
N 100 100 160 100 {lab=VBIAS}
N 260 -40 320 -40 {lab=RF_P}
N 380 -40 440 -40 {lab=IN_P}
N 260 40 320 40 {lab=RF_N}
N 380 40 440 40 {lab=IN_N}
N 300 100 400 100 {lab=VBIAS}
N 300 -100 400 -100 {lab=VBIAS}
N 300 -100 300 100 {lab=VBIAS}

C {devices/iopin.sym} 100 0 0 0 {name=p1 lab=RF_BOOST}
C {devices/iopin.sym} 100 100 0 0 {name=p2 lab=VBIAS}
C {devices/iopin.sym} 440 -40 0 0 {name=p3 lab=IN_P}
C {devices/iopin.sym} 440 40 0 0 {name=p4 lab=IN_N}
C {devices/capa.sym} 350 -40 1 0 {name=C1 value=10p}
C {devices/capa.sym} 350 40 1 0 {name=C2 value=10p}
C {devices/res.sym} 400 -70 0 0 {name=R1 value=100k}
C {devices/res.sym} 400 70 0 0 {name=R2 value=100k}
C {devices/code_shown.sym} 200 -100 0 0 {name=BALUN only_toplevel=false value="E1 RF_P 0 RF_BOOST 0 1
E2 RF_N 0 RF_BOOST 0 -1"}
C {devices/lab_pin.sym} 160 0 0 0 {name=l1 lab=RF_BOOST}
C {devices/lab_pin.sym} 160 100 0 0 {name=l2 lab=VBIAS}
C {devices/lab_pin.sym} 260 -40 0 0 {name=l3 lab=RF_P}
C {devices/lab_pin.sym} 260 40 0 0 {name=l4 lab=RF_N}
C {devices/lab_pin.sym} 440 -40 0 0 {name=l5 lab=IN_P}
C {devices/lab_pin.sym} 440 40 0 0 {name=l6 lab=IN_N}
C {devices/lab_pin.sym} 300 100 0 0 {name=l7 lab=VBIAS}
C {devices/lab_pin.sym} 400 -100 0 0 {name=l8 lab=VBIAS}
C {devices/lab_pin.sym} 400 -40 0 0 {name=l9 lab=IN_P}
C {devices/lab_pin.sym} 400 40 0 0 {name=l10 lab=IN_N}
C {devices/lab_pin.sym} 400 100 0 0 {name=l11 lab=VBIAS}
B 2 520 -100 1480 120 {flags=graph
rawfile=/home/irman/PandaChip/designs/iris-harvester/splitter_verify.raw
sim_type=tran
autoload=1
color="4 12"
y1=-2.39
y2=2.39
divy=4
x1=0
x2=3e-07
divx=8
node="rf_boost
vbias"
}
B 2 520 160 1480 380 {flags=graph
rawfile=/home/irman/PandaChip/designs/iris-harvester/splitter_verify.raw
sim_type=tran
autoload=1
color="4 12"
y1=-2.45
y2=3.05
divy=4
x1=0
x2=3e-07
divx=8
node="x1.rf_p
in_p"
}
B 2 520 420 1480 640 {flags=graph
rawfile=/home/irman/PandaChip/designs/iris-harvester/splitter_verify.raw
sim_type=tran
autoload=1
color="4 12"
y1=-2.45
y2=3.06
divy=4
x1=0
x2=3e-07
divx=8
node="x1.rf_n
in_n"
}
