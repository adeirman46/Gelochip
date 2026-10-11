Design a PROPER narrowband LNA at 40 MHz on the GF180MCU-D PDK (3.3V
devices) in ONE schematic file lna_match_tb.sch. A gain block alone is
not an LNA: input impedance matching is REQUIRED.

Architecture (required):
- 50 ohm source: EMF source VS value="SIN(0 0.001 40MEG) AC 1" with a
  series 50 ohm resistor RS from VS_EMF to node IN.
- Inductively degenerated common-source input stage: series gate inductor
  LG from IN to gate node G1, source degeneration inductor LS from source
  to ground (devices/ind.sym; these model off-chip matching parts).
  At 40 MHz expect LG about 0.5u-3u and LS about 20n-200n; tune so the
  input resonates at 40 MHz. Cascode on the input stage encouraged.
  More gain stages after the core are allowed for the total gain target.
- Verify with analyze_raw on the AC raw:
  * Input match: v(IN) at the 40-50 MHz sample must be 0.4-0.6 of the
    1.0 EMF (about -8 to -4.4 dB) and clearly lower than at 1 MHz —
    that dip IS the match.
  * Gain: v(OUT) >= 50 dB at the 40-50 MHz sample.
  * TRAN: OUT fundamental at 40 MHz >= 0.1 V from the 1 mV EMF.
- Analyses: .tran 0.5n 2u and .ac dec 20 1k 1G
- Nets: VS_EMF, IN, G1, OUT, VDD. Follow the placement and wiring rules:
  real wires, left-to-right stages, VDD rail on top.
