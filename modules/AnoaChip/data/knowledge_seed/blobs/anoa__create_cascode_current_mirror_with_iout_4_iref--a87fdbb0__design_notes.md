# Cascode Current Mirror (4:1) — Build Contract

## 1. Specification
- **Topology class**: Cascode current mirror (NMOS, wide-swing)
- **Current gain**: Iout = 4 × Iref
- **Target PDK**: gf180mcuD (GlobalFoundries 180 nm)
- **Device models**: gf180mcu_fd_pr__nfet_03v3 / pfet_03v3
- **Supply**: VDD = 3.3 V

## 1b. Use case
Biasing the tail current source of a high-gain RF front-end amplifier. A 25 µA external bandgap reference current (`Iref`) is fed into the mirror, which outputs exactly 100 µA (`Iout`) to bias the differential pair. The application tolerates ≤ 2% current mismatch to prevent systematic offset in the RF signal path. The testbench drives a 25 µA DC reference current and measures the 100 µA output across a 1 V output voltage sweep.

## 2. Key Knowledge & Decisions
- **Topology**: A standard 4-transistor NMOS cascode current mirror. M1 and M3 are diode-connected input devices that establish the gate bias voltages. M2 and M4 form the output branch, sized 4× larger to scale the current. The cascode structure (M4) shields the drain of M2, keeping Vds2 constant and providing high output resistance, which ensures current accuracy independent of output voltage variations.
- **Sizing math**: 
  - Current scaling: `Iout / Iref = (W2/L2) / (W1/L1)`. With identical lengths, W2 = 4 × W1.
  - To ensure strong inversion and good matching, we select a unit width of 5 µm and a length of 1 µm.
  - Input pair (M1, M3): 1 finger, W=5µm, L=1µm.
  - Output pair (M2, M4): 4 fingers, W=5µm, L=1µm (total effective width = 20µm).
  - Overdrive: `Vdsat = sqrt(2 * Iref / (k' * (W/L)))`. For 25 µA and W/L = 5, Vdsat ≈ 150 mV.
- **COMPLETE PARAMETER TABLE**:

| Component | Parameter | Value | Why |
|-----------|-----------|-------|-----|
| M1 | W | 5 µm | Unit input width |
| M1 | L | 1 µm | Standard matching length |
| M1 | Fingers | 1 | Unit device |
| M3 | W | 5 µm | Matches M1 for cascode bias generation |
| M3 | L | 1 µm | Matches M1 |
| M3 | Fingers | 1 | Unit device |
| M2 | W | 5 µm | Unit width, multiplied by fingers |
| M2 | L | 1 µm | Matches M1 to ensure accurate 4:1 ratio |
| M2 | Fingers | 4 | 4× multiplier to achieve Iout = 4 × Iref |
| M4 | W | 5 µm | Unit width, multiplied by fingers |
| M4 | L | 1 µm | Matches M3 |
| M4 | Fingers | 4 | 4× multiplier to match M2 and maintain cascode matching |
| VDD | Voltage | 3.3 V | Specified supply constraint |
| Iref | Current | 25 µA | Application use-case reference current |

- **Operating point**: All devices in saturation. Vds(M1) = Vgs(M1) ≈ 0.8 V. Vds(M2) is clamped to Vgs(M1) by the cascode, ensuring it remains ≥ Vdsat for high output resistance. Output compliance voltage is approximately Vgs(M1) + Vdsat(M4) ≈ 0.95 V.
- **Layout plan**: 
  - **Matching**: M1/M2 and M3/M4 are matching-critical pairs. M2 and M4 will be laid out as 4 unit fingers to interdigitate with dummy fingers if needed for edge-effect matching.
  - **Placement**: M1 and M3 stacked vertically on the left (input branch). M2 and M4 stacked vertically on the right (output branch). 
  - **Routing**: The shared gate nodes (net M1-gate and net M3-gate) will use `straight_route` horizontally between the left and right branches. VDD/VSS rails will use `c_route` or `straight_route` at the top and bottom. 
  - **Finishing order**: 1) Place bare devices (M1-M4) -> 2) Route all nets -> 3) LVS clean -> 4) Add substrate ties, guard rings, and dummy fingers.
- **Key techniques**: Wide-swing cascode biasing. By diode-connecting M3 on top of M1, the gate voltage of M4 is naturally generated to keep M2 at the exact edge of saturation (Vds2 = Vgs1), maximizing output swing while preserving the high output resistance of the cascode.

## 3. Block Map
| Block | Role | Ports |
|-------|------|-------|
| cascode_mirror_4x | Top-level 4:1 cascode current mirror | VDD, VSS, iref, iout |

## 4. Interfaces
```spice
.subckt cascode_mirror_4x VDD VSS iref iout
* VDD: Positive supply (3.3V)
* VSS: Ground / negative supply
* iref: Reference current input node
* iout: Scaled output current node (4x Iref)
```

## 5. Connections
- Drain of M3 → Gate of M3, Gate of M4, Drain of M4 (cascode bias net)
- Source of M3 → Drain of M1 (input branch mid-net)
- Drain of M1 → Gate of M1, Gate of M2, Drain of M2 (bottom bias net)
- Source of M1 → VSS
- Source of M2 → VSS
- Drain of M3 → iref (top of input branch)
- Drain of M4 → iout (top of output branch)

## 6. Verification & GDS Sign-off
- **ngspice Testbench Plan**:
  - `.op`: Verify all devices are in saturation (Vds > Vgs - Vth) and check the exact DC operating point currents.
  - `.dc`: Sweep Vout from 0 to 3.3V at the `iout` node while forcing 25µA into `iref`. Measure the output current to confirm Iout = 100µA and evaluate output resistance.
  - `.measure`: DC current gain (`Iout / Iref`) and output resistance (`dVout / dIout`).
- **Silicon Path (gf180mcuD)**:
  - glayout build (JSON config → automated placement and routing)
  - DRC check via magic (target PDK: gf180mcuD)
  - LVS check via netgen (target PDK: gf180mcuD)
  - PEX extraction and final GDSII export