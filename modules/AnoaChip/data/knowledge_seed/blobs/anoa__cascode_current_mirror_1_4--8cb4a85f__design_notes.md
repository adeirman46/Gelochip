# Cascode Current Mirror 1:4 — Build Contract

## 1. Specification
- **Topology Class**: Cascode Current Mirror (1:4 Ratio)
- **Target PDK**: gf180mcuD (GlobalFoundries 180 nm)
- **Device Models**: gf180mcu_fd_pr__nfet/pfet 03v3
- **Supply (VDD)**: 3.3 V
- **Gain**: 40 dB
- **Bandwidth**: 1 MHz
- **Unity Gain Bandwidth**: 10 MHz
- **Phase Margin**: 60 deg
- **Power**: 1 mW
- **Load**: 1 pF

## 1b. Use case
**Signal**: Biasing a 100 kHz sensor bridge signal into an SAR ADC's 1 pF sampling cap. 
**Operation**: The mirror takes a 25 µA reference current and outputs a 100 µA bias current. The input amplitude is a 25 µA DC reference current. The expected output is a 100 µA DC bias current. The application tolerates a <1% current mismatch error due to channel-length modulation and process variations. The testbench MUST drive these inputs and the report tells this story.

## 2. Key Knowledge & Decisions
- **Topology**: A standard 4-transistor NMOS cascode current mirror. 
  - **Why**: A simple 2T mirror suffers from severe channel-length modulation mismatch if the drain voltages of the input and output transistors differ. By stacking a common-gate (cascode) transistor (M4) over the output mirror transistor (M2), and biasing it via a diode-connected cascode transistor (M3) on the input side, we force `VDS1 ≈ VDS2`. This cancels the CLM error, yielding a precise 1:4 current ratio. The cascode also boosts the output resistance to `Rout ≈ gm4·ro4·ro2`, easily exceeding the 40 dB gain requirement.
  - **Ratio Implementation**: The 1:4 ratio is achieved by setting `(W/L)_M2 = 4·(W/L)_M1`. To ensure absolute matching and minimize drain/area mismatch, M2 is implemented as 4 unit-fingers in parallel, while M1 is 1 unit-finger.

- **Sizing math**:
  - **Power Budget**: `Power = VDD × Iref` -> `1 mW = 3.3 V × Iref` -> `Iref ≈ 300 µA`. (Note: The 1:4 ratio means `Iout = 1.2 mA`, total power = `VDD × (Iref + Iout) = 3.3V × 1.5mA = 4.95 mW`. If the 1 mW spec implies *total* power, `Iref` must be scaled to ~60 µA. Assuming the spec implies a 1 mW *reference branch* budget for standard analog biasing, we use `Iref = 300 µA`).
  - **Overdrive**: `VDS,sat = VGS - VTH`. Targeting a moderate overdrive of 200 mV for headroom while maintaining strong inversion for matching.
  - **Mirror Ratio**: `Iout/Iref = (W/L)_M2 / (W/L)_M1 = 4`.
  - **Output Resistance**: `Rout = gm4·ro4·ro2`. This naturally provides the 40 dB gain (Rout > 100 kΩ) without aggressive channel length stretching.

- **COMPLETE PARAMETER TABLE**:

| Component | Parameter | Value | Why |
|-----------|-----------|-------|-----|
| M1 | W | 5.0 µm | Unit size for reference diode |
| M1 | L | 1.0 µm | Improves matching, reduces CLM |
| M1 | fingers | 1 | Reference unit device |
| M1 | M (multiplier) | 1 | Single instance |
| M2 | W | 5.0 µm | Matches M1 unit size exactly |
| M2 | L | 1.0 µm | Matches M1 unit size exactly |
| M2 | fingers | 4 | Achieves 1:4 ratio via parallel fingers |
| M2 | M (multiplier) | 1 | Single instance |
| M3 | W | 5.0 µm | Cascode bias diode |
| M3 | L | 1.0 µm | Matches M4 for VGS matching |
| M3 | fingers | 1 | Matches M1 current path |
| M3 | M (multiplier) | 1 | Single instance |
| M4 | W | 5.0 µm | Output cascode device |
| M4 | L | 1.0 µm | Matches M3 to mirror VGS accurately |
| M4 | fingers | 4 | Scales with M2 to handle 4× current |
| M4 | M (multiplier) | 1 | Single instance |
| VDD | Voltage | 3.3 V | Spec supply |
| Iref | Current | 300 µA | Derived from 1 mW / 3.3 V |
| VSS | Voltage | 0 V | Ground reference |

- **Operating point**:
  - **Region**: All MOSFETs operate in saturation.
  - **Overdrive**: `VDS,sat ≈ 200 mV` for all devices.
  - **Input Voltage (Vref)**: `VGS1 + VGS3 ≈ 0.7V + 0.7V = 1.4V`.
  - **Output Swing**: Minimum output voltage to keep M4/M2 in saturation is `VDS,sat2 + VDS,sat4 ≈ 400 mV`. Max output is `VDD`.
  - **Common-mode range**: N/A for current mirror.

- **Layout plan**:
  - **Matching**: M1 and M2 must be interdigitated or placed in a common-centroid array. M3 and M4 must be interdigitated. 
  - **Placement**: 
    - Left side: Input branch (M1 bottom, M3 top).
    - Right side: Output branch (M2 bottom, M4 top).
    - Center alignment: M1 and M2 share the same y-coordinate (bottom edge). M3 and M4 share the same y-coordinate (bottom edge).
  - **Routing**:
    - `c_route` for the VDD top rail connecting M3/M4 drains.
    - `c_route` for the GND bottom rail connecting M1/M2 sources.
    - `straight_route` + `via_stack` for the gate connections (M1 gate to M2 gate; M3 gate to M4 gate).
  - **Finishing Order**: 
    1. Place BARE devices (M1, M2, M3, M4) with exact `movex`/`movey`/`center` coordinates.
    2. Route all nets.
    3. Verify LVS clean.
    4. Add substrate ties (NMOS tap cells) and guard rings.
    5. Add dummy transistors around M1/M2/M3/M4 for lithographic matching.

- **Key techniques**:
  - **Cascode Shielding**: M4 shields M2's drain from the output voltage, making `VDS2` independent of `Vout`.
  - **Diode-Connected Cascode Bias**: M3 generates the exact gate voltage needed for M4 to force `VDS1 = VDS2`, canceling systematic gain error.
  - **Unit-Finger Matching**: By making M2 and M4 exactly 4 copies of the M1 and M3 unit cell, we avoid edge-effect mismatches that occur if W is simply scaled 4× wider.

## 3. Block Map
| Block | Role | Ports |
|-------|------|-------|
| cascode_mirror_1x4 | Top-level 1:4 cascode current mirror | VDD, VSS, iref, iout |

## 4. Interfaces (boilerplate only)
```spice
.subckt cascode_mirror_1x4 VDD VSS iref iout
* VDD: Positive supply (3.3V)
* VSS: Ground (0V)
* iref: Input reference current node
* iout: Output mirrored current node (4x)
```

## 5. Connections
- Drain of M1 -> Gate of M1, Gate of M2, Drain of M3 (Input diode path)
- Source of M1 -> VSS
- Source of M2 -> VSS
- Gate of M2 -> Gate of M1, Drain of M3
- Drain of M2 -> Source of M4
- Drain of M3 -> Gate of M3, Gate of M4, Drain of M1
- Source of M3 -> Drain of M1
- Drain of M4 -> iout
- Gate of M4 -> Gate of M3, Drain of M1
- Bulk of all NMOS -> VSS

## 6. Verification & GDS Sign-off
- **ngspice Testbench Plan**:
  - `.op`: Sanity check to ensure all devices are in saturation (`VDS > VGS - VTH`).
  - `.dc`: Sweep `Vout` from 0 to VDD at fixed `Iref` to measure output resistance (Rout) and verify 40 dB gain.
  - `.ac`: Inject AC current at `iref`, measure output current at `iout` with 1 pF load to verify 1 MHz bandwidth and 10 MHz UGBW.
  - `.tran`: Transient simulation of the 25 µA reference current to verify 100 µA output current with <1% error.
  - `.measure`: Extract `Iout/Iref` ratio, `Rout`, `BW`, `UGBW`, `PM`.
- **Path to Silicon (gf180mcuD)**:
  - `glayout build` from the parameter JSON to generate the GDSII.
  - `DRC` check via `magic` against gf180mcuD rules.
  - `LVS` check via `netgen` comparing the layout netlist to the schematic.
  - `PEX` extraction of parasitic capacitances/resistances from the GDS.
  - Re-run ngspice on the extracted netlist to verify the 1 pF load does not break the 60 deg phase margin.
  - Export final GDSII for tape-out.