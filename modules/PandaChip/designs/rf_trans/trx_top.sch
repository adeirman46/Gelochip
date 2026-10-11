v {xschem version=3.4.8 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
C {rx_top.sym} 200 100 0 0 {name=X1}
C {tx_top.sym} 600 100 0 0 {name=X2}

C {devices/ipin.sym} 100 80 0 0 {name=pRX_RF_IN lab=RX_RF_IN}
N 100 80 160 80 {lab=RX_RF_IN}

C {devices/opin.sym} 300 80 0 0 {name=pRX_IF_P lab=RX_IF_P}
C {devices/opin.sym} 300 120 0 0 {name=pRX_IF_N lab=RX_IF_N}
N 240 80 300 80 {lab=RX_IF_P}
N 240 120 300 120 {lab=RX_IF_N}

C {devices/ipin.sym} 500 80 0 0 {name=pTX_IF_P lab=TX_IF_P}
C {devices/ipin.sym} 500 120 0 0 {name=pTX_IF_N lab=TX_IF_N}
N 500 80 560 80 {lab=TX_IF_P}
N 500 120 560 120 {lab=TX_IF_N}

C {devices/opin.sym} 700 100 0 0 {name=pTX_RF_OUT lab=TX_RF_OUT}
N 640 100 700 100 {lab=TX_RF_OUT}

C {devices/ipin.sym} 100 -20 0 0 {name=pLOP lab=LO_P}
C {devices/ipin.sym} 100 240 0 0 {name=pLON lab=LO_N}

N 100 -20 560 -20 {lab=LO_P}
N 560 -20 560 60 {lab=LO_P}
N 160 120 140 120 {lab=LO_P}
N 140 120 140 -20 {lab=LO_P}

N 100 240 560 240 {lab=LO_N}
N 560 240 560 140 {lab=LO_N}
N 160 140 140 140 {lab=LO_N}
N 140 140 140 240 {lab=LO_N}

C {devices/ipin.sym} 400 20 0 0 {name=pVDD lab=VDD}
N 200 40 400 40 {lab=VDD}
N 400 40 400 20 {lab=VDD}
N 400 40 600 40 {lab=VDD}

C {devices/ipin.sym} 400 180 0 0 {name=pGND lab=0}
N 200 160 400 160 {lab=0}
N 400 160 400 180 {lab=0}
N 400 160 600 160 {lab=0}

C {devices/lab_pin.sym} 100 80 0 0 {name=l1 lab=RX_RF_IN}
C {devices/lab_pin.sym} 300 80 0 0 {name=l2 lab=RX_IF_P}
C {devices/lab_pin.sym} 300 120 0 0 {name=l3 lab=RX_IF_N}
C {devices/lab_pin.sym} 500 80 0 0 {name=l4 lab=TX_IF_P}
C {devices/lab_pin.sym} 500 120 0 0 {name=l5 lab=TX_IF_N}
C {devices/lab_pin.sym} 700 100 0 0 {name=l6 lab=TX_RF_OUT}
C {devices/lab_pin.sym} 100 -20 0 0 {name=l7 lab=LO_P}
C {devices/lab_pin.sym} 100 240 0 0 {name=l8 lab=LO_N}
C {devices/lab_pin.sym} 400 20 0 0 {name=l9 lab=VDD}
C {devices/lab_pin.sym} 400 180 0 0 {name=l10 lab=0}
B 2 780 -20 1740 200 {flags=graph
rawfile=/home/irman/PandaChip/designs/rf_trans/trx_top_verify.raw
sim_type=tran
autoload=1
color="4 12"
y1=-0.161
y2=1.65
divy=4
x1=0
x2=1.5e-07
divx=8
node="rx_rf_in
rx_if_p"
}
B 2 780 240 1740 460 {flags=graph
rawfile=/home/irman/PandaChip/designs/rf_trans/trx_top_verify.raw
sim_type=tran
autoload=1
color="4 12"
y1=1.05
y2=1.65
divy=4
x1=0
x2=5e-07
divx=8
node="rx_if_n
tx_if_p"
}
B 2 780 500 1740 720 {flags=graph
rawfile=/home/irman/PandaChip/designs/rf_trans/trx_top_verify.raw
sim_type=tran
autoload=1
color="4 12"
y1=-1.34
y2=1.87
divy=4
x1=0
x2=5e-07
divx=8
node="tx_if_n
tx_rf_out"
}
