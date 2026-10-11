# Research Digest — Cascode Current Mirror (Iout = 4 × Iref)

## Target Spec
A cascode current mirror with a current gain of 4: **Iout = 4 × Iref**.
The mirror must replicate (and scale) a reference current while presenting
high output resistance and good current-gain accuracy.

---

## Reference Design Architecture

The reference design is a **wide-swing cascode current mirror** built from
NMOS transistors (the same topology applies to PMOS by mirroring to VDD).
It is the standard "improved current mirror" covered in the anchor lecture
material and used as the bias block in a single-stage cascode amplifier.

### Topology — 4 transistors (diode-connected input pair + cascode output pair)

```
        VDD (or top rail)
         |
    Iref |              Iout (= 4×Iref)
         |                  |
        --- M3 (diode)     --- M4 (cascode)
         | (gate=M3)        | (gate=M3, shared)
         |                  |
        --- M1 (diode)     --- M2 (output)
         | (gate=M1)        | (gate=M1, shared)
         |                  |
        GND (or bottom rail)
```

**Transistor roles:**

| Device | Role | Notes |
|--------|------|-------|
| **M1** | Diode-connected input transistor | Gate tied to its own drain; sets Vgs reference. Vds1 = Vgs1. |
| **M3** | Diode-connected cascode input | Gate tied to its own drain; sits on top of M1. Generates the cascode bias voltage. |
| **M2** | Output (bottom) transistor | Gate shares M1's gate node. Sized 4× M1 for the 4:1 current ratio. |
| **M4** | Output cascode transistor | Gate shares M3's gate node. Sized 4× M3. Provides high output resistance. |

### Key operating principles

1. **Current scaling by W/L ratio.** With matched devices and equal L,
   `Iout / Iref = (W2/L2) / (W1/L1)`. For a 4:1 mirror, the output pair
   (M2, M4) is sized **4× the input pair (M1, M3)** in width (or 4×
   multiplier/finger count). The lecture's Example 16-2 shows the
   preferred layout: use **4 unit-sized fingers** for the output device
   so that edge-tolerance errors cancel (ratio error ≈ 0.75% vs. much
   worse for a single wide device).

2. **Cascode benefit — high output resistance.**
   `Rout ≈ gm4 · rds4 · rds2` — roughly gm·rds times higher than a simple
   mirror. This keeps Iout nearly independent of the output node voltage.

3. **Cascode benefit — accurate current matching.** Because M3 is
   diode-connected, `Vds1 = Vgs1` is forced on the input side. The cascode
   bias (M3's gate) is applied to M4 so that `Vds2 ≈ Vds1`, eliminating the
   channel-length-modulation mismatch that plagues the simple mirror.
   Current gain is listed as **"excellent"** in the reference summary table.

4. **Voltage headroom.**
   - `Vmin(out) = 2·Von` (two overdrive drops stacked).
   - `Vmin(in)  = Vt + Von`.
   This is the trade-off vs. the simple mirror (Vmin(out) = Von): higher
   output resistance costs one extra overdrive of headroom.

### Sizing strategy for Iout = 4 × Iref

- Choose a unit device: `W_unit, L_unit` (e.g. L = 1 µm for good matching
  and high rds; W chosen for the desired gm and bias point).
- **Input pair (M1, M3):** 1× unit each → `W = W_unit, fingers = 1, M = 1`.
- **Output pair (M2, M4):** 4× unit each → `W = W_unit, fingers = 4, M = 1`
  (or `M = 4` with fingers = 1). Using 4 fingers of the unit width is the
  layout-friendly form recommended by the reference.
- All four devices share the same **L** so that λ (channel-length
  modulation) matches and the cascode biasing works correctly.

### Bias / reference current

- `Iref` is injected into the diode-connected input stack (M3→M1).
- The gate voltages generated (M1 gate = Vgs, M3 gate = Vgs + Vgs_cascode)
  are shared with the output stack (M2, M4).
- No explicit bias voltage generator is needed — the diode connections
  self-bias the cascode gates. (A "self-biased cascode" variant adds a
  resistor R for even better matching but is not required here.)

---

## Variants noted in the reference (for context, not used here)

| Variant | Rout | Matching | Vmin(out) |
|---------|------|----------|-----------|
| Simple mirror | rds | poor | Von |
| **Wide-swing cascode** (chosen) | gm·rds² | excellent | 2·Von |
| Self-biased cascode | gm·rds² | excellent | 2·Von |
| Regulated cascode | gm²·rds³ | good-excellent | Vt+2·Von |

---

## Modules to implement

1. **Input branch** — diode-connected M1 (bottom) + diode-connected M3
   (top, cascode). Iref flows through this stack and sets both gate bias
   voltages.
2. **Output branch** — M2 (bottom, 4× M1) + M4 (top cascode, 4× M3).
   Gates tied to the corresponding input-branch gate nodes. Delivers
   Iout = 4·Iref.
3. **Ports:** `Iref` (input current injection node), `Iout` (output
   current node), `VDD`, `VSS` (supply rails for the NMOS stack).

## Key takeaways for sizing/layout
- Use **4 fingers** (or M=4) on the output devices to realize the 4:1
  ratio with good matching.
- Keep **L identical** across all four transistors.
- The cascode gate bias is **self-generated** by the diode-connected M3 —
  no external bias voltage needed.
- High Rout (gm·rds²) is the main performance advantage; verify it in AC
  simulation by measuring the output conductance at the Iout node.