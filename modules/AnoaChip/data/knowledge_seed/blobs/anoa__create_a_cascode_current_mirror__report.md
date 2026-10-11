# cascode_current_mirror — AnoaChip design report

**Prompt:** create a cascode current mirror

**PDK:** gf180mcuD  ·  **Circuits:** —

## Objective
Design a single-output NMOS cascode current mirror in gf180mcuD to sink a precise 10 µA (1:1) from a 10 µA reference, targeting ≥10 MΩ output resistance, ≥1.0 V compliance on a 3.3 V supply, and ≤1% mismatch for a bandgap-referenced temperature-sensor SoC.

## Topology & sizing
- **Supply**: VDD = 3.3 V, VSS = 0 V
- **Reference current**: I_ref = 10 µA
- **Cascode bias**: V_bias_cascode = 1.1 V
- **Load**: C_L = 1 pF
- **Devices** (all `gf180mcu_fd_pr__nfet_03v3`, W=5 µm, L=1 µm, fingers=1, m=1):
  - M1/M2: diode/mirror pair
  - M3/M4: common-gate cascode NMOS
  - M5/M6: self-bias branch for cascode gate
- **Target power**: 33 µW (I_ref × VDD)

## Verification (measured vs spec)
| Metric | Spec | Measured |
|---|---|---|
| Output current | 10 µA | — |
| Output resistance | ≥10 MΩ | — |
| Compliance voltage | ≥1.0 V | — |
| DC gain | ≥140 dB | — |
| Bandwidth | ≥1 MHz | — |
| Unity-gain bandwidth | ≥10 MHz | — |
| Phase margin | ≥60° | — |
| Current mismatch | ≤1% | — |
| Settling time | ≤1 µs | — |

No measured metrics were reported; all entries are pending post-silicon or simulation extraction.

## Layout sign-off (DRC/LVS)
- **GDS**: `cascode_current_mirror.gds`
- **Ports**: 3522
- **Bounding box**: [-9.995, -6.835] µm to [9.995, 6.795] µm (~20 × 13.63 µm)
- **DRC**: pass
- **LVS**: pass

## Spec verdict (target vs measured)

```
spec              target            measured        verdict
topology          cascode_current_mirror —               FAIL ✗
device_class      NMOS sink, single output —               FAIL ✗
supply_v          3.3               —               FAIL ✗
input_current_a   1e-05             —               FAIL ✗
output_current_a  1e-05             —               FAIL ✗
mirror_ratio      1                 —               FAIL ✗
output_resistance_ohm 10000000.0        —               FAIL ✗
compliance_v      1.0               —               FAIL ✗
dc_gain_db        140               —               FAIL ✗
bandwidth_hz      1000000.0         —               FAIL ✗
unity_gain_bandwidth_hz 10000000.0        —               FAIL ✗
phase_margin_deg  60                —               FAIL ✗
power_w           3.3e-05           —               FAIL ✗
load_f            1e-12             —               FAIL ✗
current_mismatch_pct 1                 —               FAIL ✗
settling_time_s   1e-06             —               FAIL ✗
```

## Layout sign-off

- GDS: `/home/irman/AnoaChip/output/create_a_cascode_current_mirror/layout/cascode_current_mirror.gds`
- Ports: 3522
- Bounding box: [-9.995, -6.835, 9.995, 6.795] µm
- DRC (magic): **pass**
- LVS (netgen): **pass**

### Layout

![Layout](layout/cascode_current_mirror.svg)
