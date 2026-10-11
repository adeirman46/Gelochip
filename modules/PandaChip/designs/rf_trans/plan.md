# RF Transceiver 100MHz Plan

## Architecture
The system is a 100MHz transceiver in GF180MCU 3.3V.
- **LO**: 90 MHz cross-coupled LC oscillator.
- **LNA**: 100 MHz cascode amplifier with LC tank load.
- **Mixer**: Gilbert cell used for both downconversion (RX) and upconversion (TX).
- **PA**: Class A common-source amplifier with RF choke and 50-ohm load.
- **RX**: LNA -> Mixer (Downconvert 100MHz RF to 10MHz IF).
- **TX**: Mixer -> PA (Upconvert 10MHz IF to 100MHz RF).
- **TRX**: Combined top level.

## Expected Values

| Block | Node | Expected waveform | Freq | Ampl/Vpp | DC level |
|---|---|---|---|---|---|
| LO | LO_P, LO_N | Sine wave | ~90 MHz | > 1 Vpp | ~3.3V |
| LNA | RF_OUT | Amplified sine | 100 MHz | > 100 mVpp | ~3.3V |
| Mixer (RX) | IF_P, IF_N | Mixed sine | 10 MHz | > 100 mVpp | ~2.5V |
| PA | PA_OUT | Amplified sine | 100 MHz | > 1 Vpp | 0V (AC coupled) |
| RX Top | IF_OUT | Mixed sine | 10 MHz | > 100 mVpp | ~2.5V |
| TX Top | RF_OUT | Amplified sine | 100 MHz | > 1 Vpp | 0V (AC coupled) |
| TRX Top | RX_IF, TX_RF | Mixed/Amplified | 10/100 MHz | > 100mV / > 1V | ~2.5V / 0V |

## Implementation Steps
1. Design and verify LO.
2. Design and verify LNA.
3. Design and verify Mixer.
4. Design and verify PA.
5. Design and verify RX Top.
6. Design and verify TX Top.
7. Design and verify TRX Top.
