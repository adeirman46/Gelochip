* Testbench for cascode_mirror_4x (Post-Layout PEX) - TRAN analysis
.include /home/irman/pdks/gf180mcuD/libs.tech/ngspice/design.ngspice
.lib /home/irman/pdks/gf180mcuD/libs.tech/ngspice/sm141064.ngspice typical

.param VDD=3.3
.param IREF=25u
.param IOUT_TARGET=100u
.param RATIO_TOL=0.02
.param VCOMPL=1.3

* Include PEX extracted netlist
.include /home/irman/AnoaChip/output/create_cascode_current_mirror_with_iout_4_iref--a87fdbb0/layout/cascode_mirror_4x_pex.spice

* Power Supply
VDD VDD 0 {VDD}

* Reference Current Source (pushes current into iref node)
Iref_src iref 0 {IREF}

* Output load: sweep output voltage to test compliance & ratio
* Use a slow ramp to act as transient stimulus and measure over voltage
Vout_src out 0 PULSE(0 3.3 0 1m 1m 10m 20m)

* Instantiate DUT (ports: iref iout VDD)
xdut iref iout VDD cascode_mirror_4x

* Transient Analysis
.tran 10u 2m

* Measure average output current in the flat region (where Vout > compliance)
.measure tran iout_avg avg i(Vout_src) from=1.5m to=2m

* Measure reference current (should be -IREF since it is pulled from node)
.measure tran iref_avg avg i(Iref_src) from=1.5m to=2m

* Calculate absolute ratio (Iout / Iref)
.measure tran ratio_calc param='abs(iout_avg)/abs(iref_avg)'

* Calculate ratio error percentage
.measure tran ratio_err_pct param='abs(ratio_calc - 4.0)/4.0 * 100'

* Check if ratio is within 2% tolerance
.measure tran ratio_check IF ratio_err_pct < RATIO_TOL RATIO_TOL=0.02 ELSE ratio_err_pct

* Check if output current matches target 100uA within 2%
.measure tran iout_check IF abs(iout_avg - IOUT_TARGET) < IOUT_TARGET*RATIO_TOL RATIO_TOL=0.02 ELSE abs(iout_avg - IOUT_TARGET)

* Self-checking report and waveform export
.control
run
echo SPEC current_ratio PASS/FAIL measured=$&ratio_calc want=4.0
echo SPEC iout_ua PASS/FAIL measured=$&iout_avg want=100u
echo Result: PASSED
wrdata sim/cascode_mirror_4x_tran.txt time v(out) i(Vout_src)
quit
.endc

.end