Design a double balanced mixer (Gilbert cell) on the GF180MCU-D PDK using
3.3 V devices (nfet_03v3 / pfet_03v3) and verify it with a transient
simulation.

Requirements:
- Proper Gilbert cell: RF differential transconductance pair, LO switching
  quad (4 transistors), differential resistive loads to VDD=3.3V, and a tail
  current sink. Bias every node deliberately (state your bias choices).
- Differential RF input: small signal (~50mV amplitude) at 5 MHz around a
  suitable common-mode bias.
- Differential LO input: large signal (~300-600mV amplitude) at 4 MHz around
  a suitable common-mode bias.
- Simulate at least 10 microseconds of transient with adequate time
  resolution for FFT analysis.
- Verify with analyze_raw on the differential IF output nodes: the mixing
  products at 1 MHz (fRF-fLO) and 9 MHz (fRF+fLO) must be clearly present, using the real PDK models,
  and they must dominate over RF (5 MHz) and LO (4 MHz) feedthrough in the
  differential output spectrum. Report the amplitudes.
- Name the testbench schematic dbm_tb.sch. Use net names RF_P, RF_N, LO_P,
  LO_N, IF_P, IF_N, VDD, TAIL.
