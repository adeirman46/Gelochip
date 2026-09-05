# D05 "Gelochip" RF Energy Harvester — chip I/O and power connectivity

Slot: **D05**, variant **EH**, 550 × 550 µm, slot origin on the chip at (350, 1475) µm.
Everything below is parsed from the organiser's `D05.def.tgz`
(`D05_EH_interface.yaml`, `D05_EH_pad_map.yaml`, `D05_EH_padring.v`) — not hand-copied.

## 1. The five chip pins

The project slot gives exactly **five** pins. All five arrive on the **west** edge of the
550 × 550 µm slot as **Metal2** rectangles occupying x = 0 … 1 µm (the padring's metal
overhangs 1 µm into the project area; the project must land on it).

| # | Pin | Direction | Pad slot | Pad cell | Type | Metal2 landing (slot frame, µm) | Net inside the harvester |
|---|------|-----------|----------|----------|------|--------------------------------|--------------------------|
| 0 | `VSS`  | INOUT | W12 | `gf180mcu_fd_io__dvss`     | GROUND | x 0–1, y  6.36 … 78.64  | VSS — global ground / substrate / guard rings |
| 1 | `RFP`  | INOUT | W13 | `gf180mcu_fd_io__asig_5p0` | SIGNAL | x 0–1, y 120.34 … 164.66 | RF input, positive half of the differential pair |
| 2 | `RFN`  | INOUT | W14 | `gf180mcu_fd_io__asig_5p0` | SIGNAL | x 0–1, y 220.34 … 264.66 | RF input, negative half |
| 3 | `VOUT` | INOUT | W15 | `gf180mcu_fd_io__asig_5p0` | SIGNAL | x 0–1, y 320.34 … 364.66 | Charge-pump output / load |
| 4 | `VCC`  | INOUT | W16 | `gf180mcu_fd_io__dvdd`     | POWER  | x 0–1, y 406.36 … 478.64 | **VRECT** — the rectified rail |

`secondary_esd: false` is set on the three `asig_5p0` pads (RFP, RFN, VOUT).

### Signal descriptions

* **RFP / RFN** — differential RF input, driven from an off-chip matching network
  (shunt ≈ 10.6 pF + series ≈ 1.25 µH per side to 100 Ω). Nominal 30 MHz, characterised
  20–120 MHz. These two nets feed the cross-coupled rectifier gates and sources.
* **VRECT → VCC** — the rectifier output rail. It supplies the startup-bias leg and the
  Dickson pump input, and it is brought out on the `dvdd` pad so the rail is observable
  during bring-up.
* **VOUT** — the pump output after the diode-connected NMOS load and the storage
  capacitor. This is the harvested DC output.
* **VSS** — the single ground: rectifier sources, pump ground, load source, every guard
  ring, the substrate taps, and the met5 west trunk.

## 2. Where VDD and VSS actually go — read this before wiring the bench

This is the part that is easy to get wrong, because your two power pins are not ordinary
signal pins: they are the supply rails of your pad-ring segment.

In `D05_EH_padring.v`, our own five pads are instantiated like this:

```verilog
gf180mcu_fd_io__dvss     W12 (.DVSS(W12), .VDD(W16), .DVDD(W16));
gf180mcu_fd_io__asig_5p0 W13 (.ASIG5V(W13), .VSS(W12), .DVSS(W12), .VDD(W16), .DVDD(W16));
gf180mcu_fd_io__asig_5p0 W14 (.ASIG5V(W14), .VSS(W12), .DVSS(W12), .VDD(W16), .DVDD(W16));
gf180mcu_fd_io__asig_5p0 W15 (.ASIG5V(W15), .VSS(W12), .DVSS(W12), .VDD(W16), .DVDD(W16));
gf180mcu_fd_io__dvdd     W16 (.DVDD(W16), .VSS(W12), .DVSS(W12));
```

The supply census over the whole generated ring is asymmetric, and the two rails behave
differently:

| Rail | Reach |
|---|---|
| `.DVDD(W16)` | **25 cells** — our five pads plus their twenty fillers, and nothing else |
| `.DVDD(FLOAT_VDD_1)` | 517 cells — the entire rest of the ring |
| `.DVSS(W12)` | 542 cells — every cell in the file |

So:

* **`VCC` (pad W16, `dvdd`) supplies exactly the D05 segment.** The `.cfg` places `BREAK ;`
  immediately before W12 and immediately after W16 (`BRK_BEFORE_EH` / `BRK_AFTER_EH`,
  `reason: project_boundary`), and the census confirms the cut is real: W11 and W17, the pads
  just outside those breaks, are on `FLOAT_VDD_1`, not on W16. Your DVDD is not shared with
  the neighbouring projects.
* **`VSS` (pad W12, `dvss`) appears on every cell** in this file. That is an artefact of the
  per-project view — W12 is the only ground pad instantiated in it. In the assembled chip each
  project contributes its own `dvss` pad.

The part that matters for the bench: **W13, W14 and W15 — the RFP, RFN and VOUT pads — do take
`.VDD(W16)/.DVDD(W16)`.** Their ESD network therefore references `VCC`, and `VCC` is `VRECT`.

**Consequence of mapping VCC ← VRECT:** the harvester powers its own I/O segment — a genuinely
self-powered chip — and VRECT stays observable for bring-up. The trade-off is that those three
pads' ESD networks reference a rail that is ≈ 0 V at cold start. While VRECT is charging, an RF
excursion on RFP/RFN above roughly one diode drop over VRECT can be clamped into the VRECT rail
through the pad. That path is not destructive — it charges VRECT and acts as a parasitic
parallel rectifier — but it perturbs the measured input impedance and the sensitivity figure at
very low input power. If bench measurements need a clean, undisturbed Zin, force VCC from an
external supply instead and treat VRECT as unobservable.

## 3. Internal nets that are *not* brought out

`VMID1`, `VMID2` (startup-bias mid-nodes) and `N1`, `N2` (Dickson pump inter-stage nodes)
stay internal. They are labelled in the layout for debug but have no pad — there are only
five pins in the slot.

## 4. Top-level metal discipline

| Layer | Use |
|-------|-----|
| met1 | inside PCells; vertical straps of the guard rings |
| met2 | PCell rails, guard-ring horizontals, **and the five Metal2 boundary landings** |
| met3 | block lanes / stubs, and the vertical lanes of the boundary router |
| met4 | chip rails (2 µm), boundary-router horizontals, rail landing pads |
| met5 | VSS trunk on the west edge |

The boundary router takes each core met4 rail pad, runs met4 west to a dedicated met3 lane
(x = 24, 40, 56, 72, 88 µm), jogs vertically on met3 to the pin's y, runs met4 west again to
x = 4 µm, and drops to the Metal2 landing through a met2→met4 via stack (a multi-cut
`via_array` on VSS and VCC). Horizontal runs are met4 and vertical runs are met3, so the one
unavoidable crossing — RFP and VOUT swap order between the core and the pad ring — never
puts two nets on the same layer.
