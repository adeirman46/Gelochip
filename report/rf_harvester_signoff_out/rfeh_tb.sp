* RF energy harvester - post-layout (PEX) transient
.temp 27
.include /foss/pdks/gf180mcuD/libs.tech/ngspice/design.ngspice
.lib /foss/pdks/gf180mcuD/libs.tech/ngspice/sm141064.ngspice typical
.include /home/irman/gLayout/notebook/rf_harvester_signoff_out/RFEH_pex.spice

XDUT VRECT RFP RFN VSS VOUT N1 N2 VMID1 VMID2 RFEH
Cinj1 RFP VMID1 0.400p
Cinj2 RFN VMID2 0.400p
Cst1 RFN N1 1.200p
Cst2 RFP N2 1.200p
Csto VSS VOUT 21.952p

VVSS VSS 0 0
VSUB VSUBS 0 0
VRFP RFP 0 SIN(0 0.9 30MEG 0 0 0)
VRFN RFN 0 SIN(0 0.9 30MEG 0 0 180)
.GLOBAL VSUBS

.control
tran 1n 10u
meas tran vrect_final find v(VRECT) at=9.99u
meas tran vout_final  find v(VOUT)  at=9.99u
wrdata /home/irman/gLayout/notebook/rf_harvester_signoff_out/rfeh_tran.csv v(VOUT) v(VRECT) v(N2) v(VMID1)
.endc
.end
