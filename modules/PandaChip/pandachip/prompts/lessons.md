# Lessons distilled from previous PandaChip runs
# (append-only; loaded into every agent's prompt)

- [2026-07-21 IRIS_RF_Energy_Harvester] In Dickson charge pumps on GF180MCU, tie each diode-connected NMOS bulk to its drain (dynamic forward body bias) - it recovers most of the body-effect Vth loss and roughly doubled the pumped output.
- [2026-07-21 IRIS_RF_Energy_Harvester] Clamp the rectifier's negative rail with two series diode-connected NMOS to ground to suppress reverse leakage at high input power instead of upsizing the cross-coupled pair.
- [2026-07-21 IRIS_RF_Energy_Harvester] Drive Dickson clock capacitors directly from the differential RF nodes (RF_P/RF_N) - no oscillator block is needed in an RF harvester.
- [2026-07-21 iris-img] A >60% PCE target is not reachable in 180nm at VHF into a fixed 1 Mohm load; report measured PCE honestly and note load matching as the lever, never inflate the number.
- [2026-07-21 platform] For a 0 dBm available-power source in a 50 ohm system use Vpeak = sqrt(8*Rsrc*P) = 0.632 V behind 50 ohm; state the convention once in the toplevel plan and reuse it in every sweep deck.
- [2026-07-21 platform] Transient length for pumped/rectified outputs: simulate at least 20 us at 50 MHz (1000 cycles) or the storage node has not plateaued and the measured mean under-reports VOUT.
