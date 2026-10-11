Redraw the existing LNA testbench with professional placement and wiring.

Read lna_tb.sch in this workspace. Create lna_neat.sch: the EXACT same
circuit (same devices, sizes, values, net names, control block) but drawn
per the placement-and-wiring-quality rules in your guide: stimulus sources
left, three stages left-to-right on a 280-unit pitch, transistors row-
aligned, REAL N-segment wires for every local connection (drain-to-load,
source-to-ground, coupling caps between stages, bias resistors), one
horizontal VDD rail wire on top, gnd symbols at the bottom, labels only
for VDD/0/VBIAS and the named signal nets (IN, N1, N1G, N2, N2G, OUT).
No overlapping symbols or text.

Verify: netlist lna_neat.sch and confirm the SAME device list and
connectivity as lna_tb.spice (read both netlists and compare), then run
one simulation and confirm AC gain at 40-50 MHz is still >= 50 dB.
Then call done.
