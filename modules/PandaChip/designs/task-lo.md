Design a local oscillator on the GF180MCU-D PDK using 3.3V devices
(nfet_03v3 / pfet_03v3) in ONE schematic file named lo_tb.sch, and verify
sustained oscillation with a transient simulation.

Requirements:
- A CMOS ring oscillator (odd number of inverter stages, e.g. 5) running
  from VDD = 3.3V is a good choice. Size the inverters deliberately
  (e.g. pfet W about 2-3x nfet W).
- Target oscillation frequency in the 20-200 MHz range; report the value.
- Remember an ideal ring never starts by itself in simulation: kick it
  with .ic V(OSC1)=0 in the control block.
- Analysis: .tran 0.05n 1u (adjust if needed for enough cycles).
- Verify with analyze_raw on an oscillator node: sustained rail-to-rail
  swing (vpp > 2.5 V) and a clear dominant FFT peak; report frequency and
  amplitude.
- Net names: OSC1..OSCn for ring nodes, VDD.
