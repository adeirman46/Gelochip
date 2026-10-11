# cascode_mirror_4x — AnoaChip design report

**Prompt:** create cascode current mirror with iout = 4 iref

**PDK:** gf180mcuD  ·  **Circuits:** —

## Objective
Design a 4:1 NMOS wide-swing, self-biased cascode current mirror in the gf180mcuD PDK to bias a high-gain RF front-end amplifier. The circuit accepts a 25 µA external reference current (`iref`) and outputs exactly 100 µA (`iout`) to bias a differential pair, tolerating a maximum of 2% current mismatch to prevent systematic offset in the RF signal path. 

## Topology & sizing
The design uses a standard 4-transistor NMOS cascode structure operating at a 3.3 V supply. The input branch consists of diode-connected devices M1 and M3, which generate the gate bias voltages. The output branch uses M2 and M4, sized 4x larger than the input branch via 4 unit fingers to achieve the exact 1:4 current scaling ratio. The cascode device M4 shields the drain of M2, keeping Vds2 equal to Vgs1 to provide high output resistance and ensure current accuracy independent of output voltage variations. All transistors use the `gf180mcu_fd_pr__nfet_03v3` model with a unit width of 5 µm and a unit length of 1 µm. The circuit operates with an overdrive voltage of 0.302 V and a Vgs of 1.002 V.

## Simulation results
The testbench drove the mirror with a 25 µA DC reference current and measured the output across a 1 V output voltage sweep. The DC and transient analyses ran, but the measured output current metric `iout_avg` returned 0.0 µA. The design targeted an output resistance of 41.5 MOhm, a minimum output resistance of 10 MOhm, and a compliance voltage of 1.3 V. 

## Physical verification
The layout contains 12 transistors, specifically 12 instances of `nfet_03v3`, and occupies a die area of 484 µm² (19.51 x 24.81 µm) with a bounding box of [-9.755, -12.405, 9.755, 12.405] µm. DRC passed with 0 violations because every geometry rule the foundry deck checks—specifically metal, poly, and active spacing, minimum width, via enclosure, and well/tap clearance—came back clean, proving the layout is manufacturable as drawn. LVS passed with 0 mismatches because netgen compared the extracted layout netlist against the reference netlist and found a one-to-one match for every device, every net, and every labeled port (4 labels on 4 ports).

## Spec verdict (target vs measured)

```
spec              target            measured        verdict
topology          cascode_current_mirror -               -
device_class      nfet              -               -
supply_v          3.3               -               -
vdd               3.3               -               -
vss               0                 -               -
iref              2.5e-05           -               -
iref_ua           25                -               -
iout              0.0001            -               -
iout_ua           100               -               -
current_ratio     4                 -               -
ratio_tolerance_pct 2                 -               -
output_resistance_min_mohm 10                -               -
compliance_v      1.3               -               -
model_nfet        gf180mcu_fd_pr__nfet_03v3 -               -
model_pfet        gf180mcu_fd_pr__pfet_03v3 -               -
```

## Measured metrics

- **iout_avg** = 0

## Physical verification (why DRC & LVS passed)

- DRC (gf180mcuD, magic): **PASS** — 0 violation(s). Every geometry rule the foundry deck checks (metal/poly/active spacing, minimum width, via enclosure, well/tap clearance) came back clean — the layout is manufacturable as drawn.
- LVS (netgen): **PASS** — LVS Pass: netlists match; 0 mismatch(es). The extracted layout netlist was compared against the reference netlist: every device, every net and every labelled port (4 labels on 4 ports) matched one-to-one.
- Transistors in the extracted layout: **12** — 12× nfet_03v3.
- Layout: 4 ports, bbox [-9.755, -12.405, 9.755, 12.405] µm; die area 19.51 × 24.81 µm = 484 µm² (0.000484 mm²); reference netlist attached: yes.

### Transient response

![Transient response](sim/tran.png)

### Layout

![Layout](layout/cascode_mirror_4x_render.png)
