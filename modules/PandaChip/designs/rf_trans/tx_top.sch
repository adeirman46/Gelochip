v {xschem version=3.4.8 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
C {mixer.sym} 200 100 0 0 {name=X1}
C {pa.sym} 600 100 0 0 {name=X2}

C {devices/capa.sym} 300 80 1 0 {name=Cc value=10p}
N 240 80 270 80 {lab=MIX_OUT_P}
N 330 80 560 80 {lab=PA_IN}
N 560 80 560 100 {lab=PA_IN}

C {devices/ipin.sym} 100 80 0 0 {name=pIFP lab=IF_P}
C {devices/ipin.sym} 100 120 0 0 {name=pIFN lab=IF_N}
N 100 80 160 80 {lab=IF_P}
N 100 120 160 120 {lab=IF_N}

C {devices/ipin.sym} 100 60 0 0 {name=pLOP lab=LO_P}
C {devices/ipin.sym} 100 140 0 0 {name=pLON lab=LO_N}
N 100 60 160 60 {lab=LO_P}
N 100 140 160 140 {lab=LO_N}

C {devices/opin.sym} 700 100 0 0 {name=pOUT lab=RF_OUT}
N 640 100 700 100 {lab=RF_OUT}

C {devices/ipin.sym} 400 20 0 0 {name=pVDD lab=VDD}
N 400 20 400 60 {lab=VDD}
N 400 140 400 180 {lab=0}
C {devices/ipin.sym} 400 180 0 0 {name=pGND lab=0}

N 200 40 200 0 {lab=VDD}
N 200 160 200 200 {lab=0}
N 600 60 600 0 {lab=VDD}
N 600 140 600 200 {lab=0}

N 200 0 400 0 {lab=VDD}
N 400 0 600 0 {lab=VDD}
N 200 200 400 200 {lab=0}
N 400 200 600 200 {lab=0}

C {devices/lab_pin.sym} 240 80 0 0 {name=l1 lab=MIX_OUT_P}
C {devices/lab_pin.sym} 330 80 0 0 {name=l2 lab=PA_IN}
C {devices/lab_pin.sym} 400 0 0 0 {name=l3 lab=VDD}
C {devices/lab_pin.sym} 400 200 0 0 {name=l4 lab=0}
C {devices/lab_pin.sym} 100 80 0 0 {name=l5 lab=IF_P}
C {devices/lab_pin.sym} 100 120 0 0 {name=l6 lab=IF_N}
C {devices/lab_pin.sym} 100 60 0 0 {name=l7 lab=LO_P}
C {devices/lab_pin.sym} 100 140 0 0 {name=l8 lab=LO_N}
C {devices/lab_pin.sym} 700 100 0 0 {name=l9 lab=RF_OUT}
C {devices/lab_pin.sym} 240 120 0 0 {name=l10 lab=MIX_OUT_N}
C {devices/lab_pin.sym} 560 100 0 0 {name=l11 lab=PA_IN}

C {devices/res.sym} 270 120 1 0 {name=Rdummy value=10k}
N 240 120 240 120 {lab=MIX_OUT_N}
N 300 120 330 120 {lab=0}
N 330 120 330 160 {lab=0}
C {devices/lab_pin.sym} 330 160 0 0 {name=l12 lab=0}
B 2 780 0 1740 220 {flags=graph
rawfile=/home/irman/PandaChip/designs/rf_trans/tx_top_verify.raw
sim_type=tran
autoload=1
color="4 12"
y1=0.66
y2=2.06
divy=4
x1=0
x2=1.88e-07
divx=8
node="x1.mix_out_p
x1.pa_in"
}
B 2 780 260 1740 480 {flags=graph
rawfile=/home/irman/PandaChip/designs/rf_trans/tx_top_verify.raw
sim_type=tran
autoload=1
color="4 12"
y1=1.38
y2=1.62
divy=4
x1=0
x2=5e-07
divx=8
node="if_p
if_n"
}
B 2 780 520 1740 740 {flags=graph
rawfile=/home/irman/PandaChip/designs/rf_trans/tx_top_verify.raw
sim_type=tran
autoload=1
color="4 12"
y1=1
y2=3.4
divy=4
x1=0
x2=1.67e-07
divx=8
node="lo_p
lo_n"
}
