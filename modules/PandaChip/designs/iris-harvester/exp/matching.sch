v {xschem version=3.4.8 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
N 100 0 160 0 {lab=RF_IN}
N 220 0 280 0 {lab=RF_BOOST}
N 280 0 340 0 {lab=RF_BOOST}
N 280 0 280 30 {lab=RF_BOOST}
N 280 90 280 120 {lab=0}
C {devices/iopin.sym} 100 0 0 0 {name=p1 lab=RF_IN}
C {devices/iopin.sym} 340 0 0 0 {name=p2 lab=RF_BOOST}
C {devices/ind.sym} 190 0 1 0 {name=L1 value=694n}
C {devices/capa.sym} 280 60 0 0 {name=C1 value=14p}
C {devices/gnd.sym} 280 120 0 0 {name=g1 lab=0}
C {devices/lab_pin.sym} 160 0 0 0 {name=l1 lab=RF_IN}
C {devices/lab_pin.sym} 220 0 0 0 {name=l2 lab=RF_BOOST}
C {devices/lab_pin.sym} 280 30 0 0 {name=l3 lab=RF_BOOST}
C {devices/lab_pin.sym} 280 90 0 0 {name=l4 lab=0}
C {devices/lab_pin.sym} 280 120 0 0 {name=l5 lab=0}
