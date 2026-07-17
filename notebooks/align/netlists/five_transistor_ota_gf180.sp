.subckt five_transistor_ota vss vdd vout vinn vinp id
M5 id   id   vss vss nfet_03v3 L=280e-9 w=21e-7 nf=10 stack=3
M4 src  id   vss vss nfet_03v3 L=280e-9 w=21e-7 nf=10 stack=3
M3 vout vinn src vss nfet_03v3 L=280e-9 w=21e-7 nf=10 stack=3
M0 net8 vinp src vss nfet_03v3 L=280e-9 w=21e-7 nf=10 stack=3
M2 vout net8 vdd vdd pfet_03v3 L=280e-9 w=21e-7 nf=10 stack=3
M1 net8 net8 vdd vdd pfet_03v3 L=280e-9 w=21e-7 nf=10 stack=3
.ends five_transistor_ota
