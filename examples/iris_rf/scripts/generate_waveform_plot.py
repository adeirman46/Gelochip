from pathlib import Path
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
wave_path = ROOT / 'results' / 'prelayout' / 'f060mhz_pp00dbm_wave.csv'
xs = []
ys = []
with wave_path.open() as handle:
    for idx, line in enumerate(handle):
        parts = [part for part in line.strip().split() if part]
        if len(parts) >= 4 and idx % 20 == 0:
            t = float(parts[0])
            v = float(parts[3])
            if t >= 75e-6:
                xs.append(t * 1e6)
                ys.append(v)
fig, ax = plt.subplots(figsize=(8, 4), dpi=150)
ax.plot(xs, ys, color='tab:blue')
ax.set_xlabel('Time (us)')
ax.set_ylabel('Vout (V)')
ax.set_title('IRIS pre-layout output waveform at 60 MHz, 0 dBm')
ax.grid(True, alpha=0.3)
fig.tight_layout()
fig.savefig(ROOT / 'results' / 'prelayout_waveform.png')
