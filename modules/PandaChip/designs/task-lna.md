Finalize a low-noise amplifier (LNA) on the GF180MCU-D PDK using 3.3V
devices (nfet_03v3 / pfet_03v3) in ONE schematic file named lna_tb.sch,
verified with BOTH an AC and a transient simulation from that single file.

Relaxed target spec:
- Small-signal voltage gain of at least 50 dB at 40 MHz.
- Supply VDD = 3.3V.

IMPORTANT: this workspace already contains previous iterations from an
earlier session (lna_v4.sch: 3-stage AC-coupled cascade measuring ~54 dB
peak / 53.3 dB at 100 MHz; lna_v5.sch: ~104 dB peak / 95 dB at 100 MHz;
plus their netlists and raws). Do not start from scratch: read the best
previous schematic, adapt it (rename final testbench to lna_tb.sch),
change the transient input to 40 MHz, and verify the relaxed spec.

Verification requirements:
- Input source: value="SIN(<bias> 0.001 40MEG) AC 1"
- Analyses in the same deck: .tran 0.5n 2u  and  .ac dec 20 1k 1G
- AC raw: gain_db at 40 MHz >= 50 (check gain_db_samples near 50 MHz and
  the peak; report the exact value at the closest sample).
- TRAN raw: output fundamental at 40 MHz with amplitude >= 0.25 V
  (1 mV input x 316 for 50 dB; some compression is acceptable).
- Net names: IN, OUT, VDD (stage nodes as needed).
