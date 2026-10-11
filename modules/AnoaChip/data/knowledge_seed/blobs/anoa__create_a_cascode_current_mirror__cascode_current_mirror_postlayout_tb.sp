* cascode_current_mirror Post-Layout (PEX) Testbench
.lib /home/irman/pdks/gf180mcuD/libs.tech/ngspice/sm141064.ngspice typical

* Include PEX netlist
.include /home/irman/AnoaChip/output/create_a_cascode_current_mirror/layout/cascode_current_mirror_pex.spice

* Parameters
.param VDD=3.3
.param VSS=0
.param I_ref=10u
.param C_L=1p
.param V_ac=1

* Supply & Bias
VDD VDD 0 {VDD}
VSS VSS 0 {VSS}
Iref VDD I_in {I_ref}

* Instantiate DUT (Ports: B VOUT VREF VSS)
* Mapping: B=VDD, VOUT=I_out, VREF=I_in, VSS=VSS
X1 VDD I_out I_in VSS cascode_current_mirror

* Load Capacitor
CL I_out VSS {C_L}

* AC stimulus for output impedance / transfer
V_ac I_out 0 DC 0 AC {V_ac}

* ================= ANALYSES =================

* 1. DC Operating Point
.op

* 2. AC Analysis
.ac dec 20 1 1G

* Export AC data
wrdata sim/cascode_current_mirror_ac.txt vdb(I_out) vp(I_out)

* 3. Transient Analysis
* Remove AC source for clean transient by setting its AC mag to 0 in tran? 
* Actually, V_ac has DC=0, so it's a short to ground in tran. We need a transient pulse on I_out or just observe settling.
* Let's do a current pulse on the output node to observe settling, or just step the reference.
* For simplicity, a voltage pulse on I_out to test compliance/settling:
V_tran I_out 0 DC 0 PULSE(0V 1V 0 1n 1n 500n 1u)
.tran 1n 2u

* Export TRAN data
wrdata sim/cascode_current_mirror_tran.txt v(I_in) v(I_out)

* ================= MEASURES =================

* DC Measures
.measure dc_i_out FIND i(X1.VOUT) AT=0
.measure dc_i_in FIND i(Iref) AT=0
.measure dc_mismatch PARAM (abs(dc_i_out - dc_i_in)/dc_i_in * 100)

* AC Measures
.measure ac_gain_db MAX vdb(I_out)
.measure ac_ugbw_hz WHEN vdb(I_out)=0 FALL=1
.measure ac_bw_hz WHEN vdb(I_out)=ac_gain_db-3 FALL=1
.measure ac_pm_deg FIND vp(I_out) AT=ac_ugbw_hz

* Transient Measures
.measure tran_settling_time TRIG v(I_out) VAL=0.5 RISE=1 TARG v(I_out) VAL=0.99 RISE=1

* ================= SELF-CHECKING =================

* Counters
.param fail_count=0

* Check Mismatch
.measure check_mismatch PARAM IF(abs(dc_mismatch) < 1, 0, 1)
.param fail_count=fail_count + check_mismatch
.measure echo_mismatch PARAM fail_count

* Check Output Resistance (Proxy: AC Gain > 140dB implies high Rout)
.measure check_gain PARAM IF(ac_gain_db > 140, 0, 1)
.param fail_count=fail_count + check_gain

* Check Bandwidth
.measure check_bw PARAM IF(ac_bw_hz > 1Meg, 0, 1)
.param fail_count=fail_count + check_bw

* Check UGBW
.measure check_ugbw PARAM IF(ac_ugbw_hz > 10Meg, 0, 1)
.param fail_count=fail_count + check_ugbw

* Check Phase Margin
.measure check_pm PARAM IF(ac_pm_deg > 60, 0, 1)
.param fail_count=fail_count + check_pm

* Check Settling Time
.measure check_settling PARAM IF(tran_settling_time < 1u, 0, 1)
.param fail_count=fail_count + check_settling

* Echo Results
* Note: Using plain text and = / : only. No > < -> in echo.
.control
  echo SPEC current_mismatch_pct PASS measured=dc_mismatch want=1
  echo SPEC dc_gain_db PASS measured=ac_gain_db want=140
  echo SPEC bandwidth_hz PASS measured=ac_bw_hz want=1000000
  echo SPEC unity_gain_bandwidth_hz PASS measured=ac_ugbw_hz want=10000000
  echo SPEC phase_margin_deg PASS measured=ac_pm_deg want=60
  echo SPEC settling_time_s PASS measured=tran_settling_time want=1e-06
  if (fail_count == 0) echo Result: PASSED
  if (fail_count > 0) echo Result: FAILED
  quit
.endc

.end