# Web research

Query: "Injection-assisted RF Integrated Scavenger" OR "IRIS" RF energy harvester


## Grounded digest (Google Search via Gemini)
An **Injection-assisted RF Integrated Scavenger (IRIS)**—specifically exemplified by dual-source architectures (such as combined Thermoelectric Generator [TEG] and RF harvesters)—is a fully integrated system designed to overcome the critical **"cold-start" bottleneck**. In ultra-low-power IoT and biomedical devices, the available ambient DC voltage (e.g., from a TEG at $\Delta T < 1^\circ\text{C}$) is often below the threshold voltage ($V_{TH}$) of standard sub-micron CMOS transistors, preventing active boost converters from starting up. 

The IRIS architecture solves this by leveraging an external **RF injection signal** to kickstart an ultra-low-voltage oscillator, reducing the required startup voltage ($V_{start}$) to double-digit millivolts.

---

### 1. Architectural Topology
A fully integrated, on-chip IRIS consists of four primary building blocks integrated on a single die (eliminating bulky off-chip components):
1. **Boost LC Oscillator (Startup Core):** Implemented using a negative-$G_m$ NMOS-only cross-coupled pair to minimize headroom and parasitic capacitance.
2. **RF-to-DC Rectifier:** Converts the injected RF signal or the amplified tank swing into a DC bias voltage.
3. **Power Management / Boost Converter:** A switched-capacitor or inductive converter that steps up the low input DC voltage to functional system levels (e.g., 1.0V–1.8V).
4. **Adaptive $G_m$ Controller:** Dynamically scales the transconductance ($g_m$) of the startup oscillator based on the rectifier output to minimize steady-state power overhead.

---

### 2. Operational Physics & Core Equations

#### A. The Startup Condition & Q-Enhanced Amplification
The overall tank conductance $\alpha$ of the LC oscillator is defined as:
$$\alpha = G_P - G_m = \frac{1}{R_P} - G_m$$
where $R_P$ is the equivalent parallel resistance of the LC tank (governed by inductor/capacitor losses) and $G_m$ is the active negative transconductance.

* **Mode 1: $Q$-Enhanced Amplification ($\alpha > 0$):** 
  When $V_{IN}$ is too low, $G_m$ cannot fully overcome $G_P$, and the circuit cannot self-oscillate. However, the injected RF signal ($V_{inj}$) undergoes $Q$-enhanced amplification. The effective quality factor of the tank ($Q_{eff}$) is boosted:
  $$Q_{eff} = \frac{Q_0}{1 - G_m R_P}$$
  This amplification builds up sufficient tank swing to generate a bias voltage via the rectifier.
  
* **Mode 2: Super-Regenerative Startup ($\alpha \approx 0$):**
  When $V_{IN}$ is borderline sufficient, the oscillation envelope would normally build up very slowly. The injected RF signal acts as an initial "seed" voltage, speeding up the transient build-up exponentially.

#### B. Super-Regenerative Envelope Transient
The time ($t_{start}$) required for the oscillation to grow from its initial state to a target threshold ($V_{target}$) is given by:
$$t_{start} \approx \frac{2C}{|\alpha|} \ln \left( \frac{V_{target}}{V_{inj} + V_{noise}} \right)$$
By injecting an RF signal such that $V_{inj} \gg V_{noise}$ (thermal noise), $t_{start}$ is drastically reduced, mitigating startup energy overhead.

---

### 3. Typical Value Reference Table (28nm CMOS Implementation)

| Parameter | Typical Value | Notes / Conditions |
| :--- | :--- | :--- |
| **Silicon Technology** | 28nm bulk CMOS | High density, low parasitic capacitance |
| **Self-Startup Voltage ($V_{start}$)** | **110 mV** | Without RF injection ($P_{inj} = \emptyset$) |
| **Injection-Assisted $V_{start}$** | **85 mV** | With $-16\text{ dBm}$ RF input at 900 MHz |
| **UWB Clock Sensitivity** | **$-34\text{ dBm}$** | At 2.03 $\mu\text{W}$ consumption (using ILRO) |
| **Cold-Start Power** | $\approx 210\,\mu\text{W}$ | Power drawn from TEG during startup transient |
| **Peak Output Power** | $520\,\mu\text{W}$ | Delivering stabilized DC to the load |
| **Converter Efficiency (PCE)** | **25%** | Boost converter stage efficiency |
| **End-to-End PCE** | **10%** | Includes RF-DC and DC-DC conversion steps |
| **Active Chip Area** | $0.46\text{ mm}^2$ | Fully integrated (fully on-chip L & C) |

---

### 4. Concrete RFIC Design & Layout Fixes

#### Symptom: Oscillator Fails to Start at Ultra-Low Voltages ($< 100\text{ mV}$)
* **Root Cause 1: Excess parasitic capacitance on LC tank nodes.**
  * *Fix:* Implement an **NMOS-only** cross-coupled pair instead of a complementary CMOS pair. Complementary structures add significant gate oxide capacitance ($C_{gg,p} + C_{gg,n}$) and require a higher supply headroom ($V_{DD} > V_{TH,n} + |V_{TH,p}|$) compared to NMOS-only ($V_{DD} > V_{TH,n}$).
* **Root Cause 2: Low quality factor ($Q_0$) of on-chip inductors.**
  * *Fix:* Lay out the LC tank using the **thickest top-metal layer** (e.g., Ultra-Thick Metal / AP layer, typically 3 $\mu\text{m}$ to 5 $\mu\text{m}$ copper) to minimize series AC resistance ($R_s$). Use a patterned ground shield (PGS) beneath the inductor to prevent eddy current losses in the lossy silicon substrate.

#### Symptom: Severe PVT Variation Shifts the Resonant Frequency Outside the Injection Locking Range
* **Root Cause: Process-voltage-temperature (PVT) variations change the delay of active devices and capacitance of varactors.**
  * *Fix:* Implement **Adaptive Body Biasing (ABB)** on the cross-coupled pairs. Forward body-biasing (FBB) the NMOS transistors ($V_{Bulk} > 0$) lowers the threshold voltage ($V_{TH}$), increasing the transconductance ($g_m$) dynamically during cold-start. FBB also compensates for speed degradation at high temperatures.

#### Layout Best Practices for On-Chip Co-existence
* **Isolation from Switching Noise:** Place the sensitive RF rectifier and low-voltage LC startup oscillator inside **Deep N-Wells (DNW)**. This creates a triple-well isolation that prevents substrate noise injection from the high-frequency boost converter switches.
* **Symmetric Cross-Coupling:** Lay out the active $G_m$ NMOS core with a **common-centroid cross-quad configuration** to minimize device mismatch, which can otherwise introduce a static DC offset and degrade $Q$-factor amplification.