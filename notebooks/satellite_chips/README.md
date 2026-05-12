# Satellite chip notebooks — Ka-band phased-array RX

Step-by-step PySpice + gLayout walk-throughs for every block in the
Ka-band radiation-hardened RX chip:

```
Antenna ──► LNA ──► BUF+PS ──► MTPS ──► 8:1 Comb ──► RFAMP ──► RFout
                                       (8 elements per chip, 32 chips → 256-element 4.1 × 4.1 cm tile)
```

| # | Notebook | Block | Topology |
|---|----------|-------|----------|
| 01 | [01_LNA.ipynb](01_LNA.ipynb)                       | Low-Noise Amplifier      | NMOS cascode + inductive degeneration |
| 02 | [02_Buffer.ipynb](02_Buffer.ipynb)                 | RF Buffer                | NMOS source follower |
| 03 | [03_MTPS.ipynb](03_MTPS.ipynb)                     | Multi-Tap Phase Shifter  | 5-bit switched-cap binary-weighted |
| 04 | [04_8to1_Combiner.ipynb](04_8to1_Combiner.ipynb)   | 8:1 RF combiner          | 3-stage binary tree of 2:1 Wilkinson-like cells |
| 05 | [05_RF_Amp.ipynb](05_RF_Amp.ipynb)                 | Post-combiner RF Amp     | CS + PMOS active load |
| 06 | [06_RX_Element.ipynb](06_RX_Element.ipynb)         | Per-element RX strip     | LNA → Buffer → MTPS (cascade) |
| 07 | [07_MTP_Flash_Memory.ipynb](07_MTP_Flash_Memory.ipynb) | Calibration NVM      | MTP bit cell + sense amp |

Each notebook follows the same teaching template:

1. **Position in the chain** + target specs.
2. **Theory & design equations.**
3. **PySpice** netlist + AC / OP simulation with plots.
4. **gLayout** cell call → GDS export → preview.
5. **Summary.**

## Prerequisites
* `ngspice` (system package) — `sudo apt install ngspice`
* `PySpice`, `gdsfactory`, `klayout`, `numpy`, `matplotlib` (already in `requirements.txt`)
* SKY130 PDK installed via volare to `~/pdks`

Run any notebook with the `glayout_env` kernel:

```bash
jupyter lab notebooks/satellite_chips/
```
