v {xschem version=3.4.8 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
C {lna.sym} 200 100 0 0 {name=X1}
C {mixer.sym} 600 100 0 0 {name=X2}

C {devices/capa.sym} 300 100 1 0 {name=Cc value=10p}
N 240 100 270 100 {lab=LNA_OUT}
N 330 100 560 100 {lab=MIX_RF_P}
N 560 100 560 80 {lab=MIX_RF_P}

C {devices/res.sym} 400 40 0 0 {name=Rb1 value=10k}
C {devices/res.sym} 400 160 0 0 {name=Rb2 value=10k}
N 400 -20 400 10 {lab=VDD}
N 400 70 400 130 {lab=VBIAS_MIX}
N 400 190 400 220 {lab=0}

C {devices/res.sym} 460 80 1 0 {name=Rb3 value=10k}
N 400 80 430 80 {lab=VBIAS_MIX}
N 490 80 560 80 {lab=MIX_RF_P}

C {devices/res.sym} 460 120 1 0 {name=Rb4 value=10k}
N 400 120 430 120 {lab=VBIAS_MIX}
N 490 120 560 120 {lab=MIX_RF_N}

C {devices/capa.sym} 520 160 0 0 {name=Cbypass value=100p}
N 520 120 520 130 {lab=MIX_RF_N}
N 520 190 520 210 {lab=0}

C {devices/ipin.sym} 100 100 0 0 {name=pIN lab=RF_IN}
N 100 100 160 100 {lab=RF_IN}

C {devices/ipin.sym} 500 60 0 0 {name=pLOP lab=LO_P}
C {devices/ipin.sym} 500 140 0 0 {name=pLON lab=LO_N}
N 500 60 560 60 {lab=LO_P}
N 500 140 560 140 {lab=LO_N}

C {devices/opin.sym} 700 80 0 0 {name=pIFP lab=IF_P}
C {devices/opin.sym} 700 120 0 0 {name=pIFN lab=IF_N}
N 640 80 700 80 {lab=IF_P}
N 640 120 700 120 {lab=IF_N}

C {devices/ipin.sym} 200 20 0 0 {name=pVDD lab=VDD}
N 200 20 200 60 {lab=VDD}
N 200 140 200 180 {lab=0}
C {devices/ipin.sym} 200 180 0 0 {name=pGND lab=0}

N 600 40 600 0 {lab=VDD}
N 600 160 600 200 {lab=0}

C {devices/lab_pin.sym} 240 100 0 0 {name=l1 lab=LNA_OUT}
C {devices/lab_pin.sym} 330 100 0 0 {name=l2 lab=MIX_RF_P}
C {devices/lab_pin.sym} 400 -20 0 0 {name=l3 lab=VDD}
C {devices/lab_pin.sym} 400 220 0 0 {name=l4 lab=0}
C {devices/lab_pin.sym} 520 210 0 0 {name=l5 lab=0}
C {devices/lab_pin.sym} 600 0 0 0 {name=l6 lab=VDD}
C {devices/lab_pin.sym} 600 200 0 0 {name=l7 lab=0}
C {devices/lab_pin.sym} 100 100 0 0 {name=l8 lab=RF_IN}
C {devices/lab_pin.sym} 500 60 0 0 {name=l9 lab=LO_P}
C {devices/lab_pin.sym} 500 140 0 0 {name=l10 lab=LO_N}
C {devices/lab_pin.sym} 700 80 0 0 {name=l11 lab=IF_P}
C {devices/lab_pin.sym} 700 120 0 0 {name=l12 lab=IF_N}
C {devices/lab_pin.sym} 200 20 0 0 {name=l13 lab=VDD}
C {devices/lab_pin.sym} 200 180 0 0 {name=l14 lab=0}
B 2 780 -20 1740 200 {flags=graph
rawfile=/home/irman/PandaChip/designs/rf_trans/rx_top_verify.raw
sim_type=tran
autoload=1
color="4 12"
y1=1.44
y2=3.51
divy=4
x1=0
x2=1.5e-07
divx=8
node="x1.lna_out
x1.mix_rf_p"
}
B 2 780 240 1740 460 {flags=graph
rawfile=/home/irman/PandaChip/designs/rf_trans/rx_top_verify.raw
sim_type=tran
autoload=1
color="4 12"
y1=1.48
y2=3.47
divy=4
x1=0
x2=5e-07
divx=8
node="vdd
x1.mix_rf_n"
}
B 2 780 500 1740 720 {flags=graph
rawfile=/home/irman/PandaChip/designs/rf_trans/rx_top_verify.raw
sim_type=tran
autoload=1
color="4 12"
y1=-0.331
y2=3.52
divy=4
x1=0
x2=1.5e-07
divx=8
node="rf_in
lo_p"
}
