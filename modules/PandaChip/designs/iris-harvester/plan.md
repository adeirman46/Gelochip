# IRIS RF Energy Harvester Plan

## 1. System Overview
The IRIS (Injection-assisted RF Integrated Scavenger) is an ultra-compact RF energy harvester designed for 50 MHz operation. It uses an L-type matching network for passive voltage boost, an injection-assisted bias network to lower the effective threshold voltage of the rectifier, a differential cross-coupled CMOS rectifier, and a 3-stage Dickson charge pump to boost the voltage for an IoT load.

## 2. Block Breakdown and Sizing

### Block 1: `matching.sch`
*   **Topology:** L-type matching network (Series L, Shunt C) to boost 50 $\Omega$ to a higher impedance.
*   **Components:**
    *   `L1`: 694 nH (between `RF_IN` and `RF_BOOST`)
    *   `C1`: 14 pF (between `RF_BOOST` and `0`)
*   **Connectivity:** `RF_IN` (port), `RF_BOOST` (port), `0` (ground).

### Block 2: `bias.sch`
*   **Topology:** Diode-connected NMOS with an ideal parallel current source.
*   **Components:**
    *   `I1`: 1 $\mu$A ideal current source from `VDD` to `VBIAS`.
    *   `M1`: `nfet_03v3`, W=10$\mu$m, L=0.28$\mu$m, D=G=`VBIAS`, S=B=`0`.
*   **Connectivity:** `VDD` (port), `VBIAS` (port), `0` (ground).

### Block 3: `splitter.sch`
*   **Topology:** Ideal balun (using VCVS) with AC coupling and DC bias injection.
*   **Components:**
    *   `E1`: VCVS, gain +1, from `RF_BOOST` to `RF_P`.
    *   `E2`: VCVS, gain -1, from `RF_BOOST` to `RF_N`.
    *   `C1`, `C2`: 10 pF AC coupling capacitors (`RF_P` to `IN+`, `RF_N` to `IN-`).
    *   `R1`, `R2`: 100 k$\Omega$ bias resistors (`VBIAS` to `IN+`, `VBIAS` to `IN-`).
*   **Connectivity:** `RF_BOOST`, `VBIAS`, `IN+`, `IN-` (ports).

### Block 4: `rectifier.sch`
*   **Topology:** Differential Cross-Coupled CMOS Rectifier with a bottom diode.
*   **Components:**
    *   `M_P1`, `M_P2`: `pfet_03v3`, W=20$\mu$m, L=0.28$\mu$m. Cross-coupled gates. Sources tied to `VRECT+`.
    *   `M_N1`, `M_N2`: `nfet_03v3`, W=20$\mu$m, L=0.28$\mu$m. Cross-coupled gates. Sources tied to `VRECT-`.
    *   `M_D1`: `nfet_03v3`, W=10$\mu$m, L=0.28$\mu$m. Diode-connected (D=G=`VRECT-`, S=B=`0`).
*   **Connectivity:** `IN+`, `IN-`, `VRECT+`, `VRECT-` (ports).

### Block 5: `charge_pump.sch`
*   **Topology:** 3-Stage Dickson Charge Pump.
*   **Components:**
    *   `M_D1` to `M_D4`: `nfet_03v3`, W=10$\mu$m, L=0.28$\mu$m. Diode-connected in series from `VRECT+` to `VCP`.
    *   `C1`, `C2`, `C3`: 10 pF pumping capacitors. `C1` connects `N1` to `IN-`, `C2` connects `N2` to `IN+`, `C3` connects `N3` to `IN-`.
*   **Connectivity:** `VRECT+`, `IN+`, `IN-`, `VCP` (ports).

### Block 6: Top-Level `tb_iris.sch`
*   **Topology:** Integration of all blocks.
*   **Components:**
    *   `V_RF`: 50 MHz sine wave, 0.632 V amplitude (0 dBm at 50 $\Omega$).
    *   `R_S`: 50 $\Omega$ source resistance.
    *   `C_STORE`: 100 pF storage capacitor at `VCP`.
    *   `R_LOAD`: 1 M$\Omega$ load resistor at `VCP`.
    *   `VDD`: 3.3 V DC source.

## 3. Expected Values Table

| Block | Node | Expected waveform | Freq | Ampl/Vpp | DC level |
|---|---|---|---|---|---|
| matching | RF_BOOST | sine | 50 MHz | > 2.0 V ampl | 0 V |
| bias | VBIAS | DC | 0 Hz | 0 V | ~0.5 V to 0.7 V |
| splitter | IN+, IN- | sine (diff) | 50 MHz | > 2.0 V ampl | ~0.6 V (VBIAS) |
| rectifier | VRECT+ | rectified ripple | 100 MHz | < 0.5 Vpp | > 1.5 V |
| rectifier | VRECT- | rectified ripple | 100 MHz | < 0.5 Vpp | ~0.5 V |
| charge_pump | N1, N2, N3 | stair-step charge-up | 50 MHz | > 1.0 Vpp | rising per stage |
| top | VOUT (VCP) | RC charge-up to plateau | - | < 0.1 Vpp | $\ge$ 1.2 V |

## 4. Verification Plan
1.  Build and verify `matching.sch` with a 50 $\Omega$ source.
2.  Build and verify `bias.sch` to confirm the DC bias voltage.
3.  Build and verify `splitter.sch` to confirm AC coupling and DC bias injection.
4.  Build and verify `rectifier.sch` with the splitter and matching network.
5.  Build and verify `charge_pump.sch` with ideal clocks, then integrate.
6.  Assemble `tb_iris.sch`, run a 10 $\mu$s transient simulation, and verify `VOUT` $\ge$ 1.2 V.
