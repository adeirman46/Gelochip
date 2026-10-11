# Research Digest — Cascode Current Mirror

## Target Design
A **cascode current mirror**: a current mirror that stacks a cascode (common-gate)
transistor on top of the diode-connected / mirror transistor pair to boost the
output resistance and reduce channel-length modulation (lambda) effects. The
result is a much higher output impedance than a simple two-transistor mirror,
giving a closer-to-ideal constant-current sink/source over a wide output-voltage
compliance range.

## Reference Design Architecture

The reference design is an analog IP block (bandgap-style bias core) built in a
CMOS process (gpdk045 / sky130-class). Its core biasing relies on **cascoded
PMOS and NMOS current mirrors** — the same topology we will build standalone.

### Key modules observed in the reference

1. **PMOS cascode mirror (upper rail)**
   - Diode-connected PMOS at the input branch sets the gate voltage of the
     bottom mirror devices.
   - A second PMOS stack (cascode) sits between the mirror devices and VDD,
     with its gate biased by a separate diode reference, raising the output
     impedance seen at the mirror output node.
   - Devices: `M13/M14`-style diode + cascode pairs, `w≈28µm l=1µm m=1`.

2. **NMOS cascode mirror (lower rail / sink)**
   - NMOS diode-connected input device sets the reference gate voltage.
   - Cascode NMOS on top of the mirror device, gate held at a fixed bias
     (~Vth + Vdsat above the mirror source), to shield the mirror node from
     output swing.
   - Devices: `n18` model, `w≈14µm l=1µm m=1` for the mirror; cascode sized
     similarly for matching.

3. **Bias / reference generation**
   - A beta-multiplier / self-biased reference core generates the seed current
     that feeds the diode-connected input of the mirror.
   - Startup circuit (enable / enable-bar devices) ensures the reference
     escapes the zero-current metastable point.

4. **Output branch**
   - The mirrored current is delivered at a high-impedance node (the cascode
     drain). Output compliance is limited by the need to keep both the cascode
     and the mirror device in saturation: `Vout_min ≈ 2·Vdsat`.

### Topology summary (NMOS cascode mirror, standalone)

```
VDD ──┬──────────────────────────┬──────────────┐
      │                          │              │
  Iref │                       Iout              │
      ▼                          ▼              ▼
   ┌──┴──┐                   ┌──┴──┐        ┌──┴──┐
   │ M3  │ (diode, gate=M4g) │ M4  │        │ M_c │  ← cascode out
   │     │                   │     │        │     │
   └──┬──┘                   └──┬──┘        └──┬──┘
      │                          │              │
   ┌──┴──┐                   ┌──┴──┐        ┌──┴──┐
   │ M1  │ (diode)           │ M2  │ mirror │ M_c │  ← cascode in (diode)
   └──┬──┘                   └──┬──┘        └──┬──┘
      │                          │              │
     GND                        GND            GND
```

- **M1, M2**: bottom mirror pair (M1 diode-connected, defines Vgs).
- **M3, M4**: cascode pair (M3 diode-connected defines the cascode gate bias
  Vb = Vgs_M1 + Vgs_M3).
- Output current `Iout` is taken at M4's drain; output resistance
  `Rout ≈ gm4·ro4·ro2` (boosted by the cascode gm·ro product).

### Key sizing principles (from reference)
- Mirror devices (M1=M2) use **long L** (1 µm) for high `ro` and good matching.
- Cascode devices (M3=M4) sized equal to mirror devices for matched Vdsat.
- Multiplier `m=1` on the reference; output branches may use `m>1` to scale
  the mirrored current ratio.
- Vdsat budget: keep `Vdsat ≈ 150–250 mV` per device so the two-stack needs
  ~0.4–0.5 V minimum output headroom.

## What we will build
A standalone **NMOS cascode current mirror** subcircuit in sky130, with:
- Input port `Iref` (current input / diode node), output port `Iout`,
  supply `VDD`, ground `VSS`.
- Four matched NMOS devices (M1–M4), sizes from the config file.
- A testbench that sweeps Vout and measures output resistance, mirror ratio
  accuracy, and minimum compliance voltage.

## Notes
- The reference design's exact repo/owner/URL is intentionally omitted here.
- Sizing seeds (W, L, m) are taken from the reference's mirror devices and
  scaled to sky130 minimum rules (L ≥ 0.15 µm, W ≥ 0.42 µm).