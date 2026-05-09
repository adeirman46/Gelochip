"""
SPICE testbench generator for each analog/RF circuit type.

For each circuit type, generates a complete ngspice-compatible testbench that:
  - Includes the post-layout PEX netlist (with parasitics)
  - Sets up DC bias, AC/RF sources, and load conditions
  - Defines the .meas statements to extract target performance metrics

Usage::

    from gelochip.verification.testbench import generate_testbench
    tb = generate_testbench(
        circuit_type="lna",
        spice_path="/tmp/gelochip_output/lna_cascode_pex.spice",
        circuit_name="lna_cascode",
        spec={"vdd_V": 1.8, "freq_GHz": 5.0, "nf_dB": 2.0, "gain_dB": 15.0},
        pdk="gf180",
    )
    # tb is a string — write to file and run with ngspice
"""
from __future__ import annotations
from typing import Optional


# ── PDK model includes ─────────────────────────────────────────────────────────

_PDK_MODELS = {
    "gf180": [
        "${PDK_ROOT}/gf180mcuD/libs.tech/ngspice/design.ngspice",
        "${PDK_ROOT}/gf180mcuD/libs.ref/gf180mcu_fd_pr/spice/gf180mcu_fd_pr__nfet_03v3.spice",
        "${PDK_ROOT}/gf180mcuD/libs.ref/gf180mcu_fd_pr/spice/gf180mcu_fd_pr__pfet_03v3.spice",
    ],
    "sky130": [
        "${PDK_ROOT}/sky130A/libs.tech/ngspice/sky130.lib.spice tt",
    ],
    "ihp130": [
        "${PDK_ROOT}/sg13g2/libs.tech/ngspice/models/cornerMOSlv.lib tt",
    ],
}


def _model_includes(pdk: str) -> str:
    lines = [f".lib {path}" for path in _PDK_MODELS.get(pdk, _PDK_MODELS["gf180"])]
    return "\n".join(lines)


# ── LNA testbench ──────────────────────────────────────────────────────────────

def _lna_testbench(
    spice_path: str,
    circuit_name: str,
    spec: dict,
    pdk: str,
) -> str:
    vdd   = spec.get("vdd_V", 1.8)
    freq  = spec.get("freq_GHz", 5.0)
    vbias = vdd * 0.5

    return f"""\
* ── LNA Testbench ──────────────────────────────────────────────────────────
* Circuit: {circuit_name}
* PDK:     {pdk}
* Target:  gain > {spec.get('gain_dB', 15)} dB, NF < {spec.get('nf_dB', 2)} dB @ {freq} GHz

{_model_includes(pdk)}
.include "{spice_path}"

* ── Bias and supply ──────────────────────────────────────────────────────────
Vdd  vdd  0  dc {vdd}
Vss  vss  0  dc 0
Vbias_gm  vbias_gm  0  dc {vbias:.3f}
Vbias_cas vbias_cas 0  dc {vdd * 0.7:.3f}

* ── RF source (50-ohm port) ──────────────────────────────────────────────────
Vin  rfin  0  dc 0 ac 1
Rs   rfin_s rfin  0  50

* ── DUT instantiation ───────────────────────────────────────────────────────
* Adjust port order to match your actual SPICE subckt pin order
X_dut rfin rfout vbias_gm vbias_cas vdd vss {circuit_name}

* ── Output load ─────────────────────────────────────────────────────────────
Rl  rfout 0  50

* ── Simulations ─────────────────────────────────────────────────────────────
.op

* AC: sweep 100 MHz to 20 GHz
.ac dec 100 100Meg 20G

* Noise: referred to Vin
.noise V(rfout) Vin dec 100 100Meg 20G

* ── Measurements ────────────────────────────────────────────────────────────
* Voltage gain at target frequency
.meas ac gain_dB find vdb(rfout) at={freq}G
* Input match (S11 proxy via input impedance)
.meas ac s11_proxy find vdb(rfin) at={freq}G
* -3 dB bandwidth
.meas ac bw_low  when vdb(rfout)=gain_dB-3 rise=1
.meas ac bw_high when vdb(rfout)=gain_dB-3 fall=1
* Noise figure at target frequency (inoise_spectrum / 4kT*Rs)
.meas noise nf_dB find onoise_spectrum at={freq}G

.end
"""


# ── Op-Amp testbench ──────────────────────────────────────────────────────────

def _opamp_testbench(
    spice_path: str,
    circuit_name: str,
    spec: dict,
    pdk: str,
) -> str:
    vdd = spec.get("vdd_V", 1.8)
    vcm = vdd / 2

    return f"""\
* ── Op-Amp Testbench (AC gain + phase margin) ────────────────────────────────
* Circuit: {circuit_name}
* PDK:     {pdk}
* Target:  DC gain > {spec.get('gain_dB', 60)} dB

{_model_includes(pdk)}
.include "{spice_path}"

* ── Supply ───────────────────────────────────────────────────────────────────
Vdd   vdd 0 dc {vdd}
Vss   vss 0 dc 0
Vbias vbias 0 dc {vcm * 0.5:.3f}

* ── Common-mode input ────────────────────────────────────────────────────────
Vcm  inn 0  dc {vcm:.3f}
Vin  inp inn dc 0  ac 1

* ── DUT ──────────────────────────────────────────────────────────────────────
X_dut inp inn out vbias vdd vss {circuit_name}

* ── Load (10 pF cap, 100 kΩ resistor typical) ────────────────────────────────
Rl   out 0  100k
Cl   out 0  10p

* ── Open-loop AC sweep ───────────────────────────────────────────────────────
.op
.ac dec 100 1 1G

* ── Measurements ────────────────────────────────────────────────────────────
.meas ac dc_gain_dB  find vdb(out) at=1
.meas ac gbw_hz      when vdb(out)=0 fall=1
.meas ac phase_margin find vp(out) when vdb(out)=0 fall=1
.meas ac unity_gain_freq when vdb(out)=0

* DC operating point output swing
.meas dc vout_high when v(out)=vdd*0.9
.meas dc vout_low  when v(out)=vdd*0.1

.end
"""


# ── Mixer testbench ───────────────────────────────────────────────────────────

def _mixer_testbench(
    spice_path: str,
    circuit_name: str,
    spec: dict,
    pdk: str,
) -> str:
    vdd      = spec.get("vdd_V", 1.8)
    rf_freq  = spec.get("freq_GHz", 5.0)
    lo_freq  = rf_freq - 0.1        # IF = 100 MHz
    if_freq  = rf_freq - lo_freq

    return f"""\
* ── Mixer Testbench (conversion gain, IIP3) ─────────────────────────────────
* Circuit: {circuit_name}
* PDK:     {pdk}
* RF={rf_freq}GHz, LO={lo_freq:.2f}GHz → IF={if_freq*1000:.0f}MHz

{_model_includes(pdk)}
.include "{spice_path}"

* ── Supply ───────────────────────────────────────────────────────────────────
Vdd   vdd  0  dc {vdd}
Vss   vss  0  dc 0
Vbias vbias 0 dc {vdd*0.5:.3f}

* ── RF input (differential, -30 dBm = 7.07 mV peak into 50Ω) ───────────────
Vrf_p  rfp  0  dc 0  sin(0 7.07m {rf_freq}G)
Vrf_n  rfn  0  dc 0  sin(0 -7.07m {rf_freq}G)

* ── LO drive (differential, 0 dBm = 223 mV peak) ───────────────────────────
Vlo_p  lop  0  dc {vdd*0.5:.3f}  sin(0 0.223 {lo_freq:.4f}G)
Vlo_n  lon  0  dc {vdd*0.5:.3f}  sin(0 -0.223 {lo_freq:.4f}G)

* ── DUT ──────────────────────────────────────────────────────────────────────
X_dut rfp rfn lop lon ifp ifn vbias vdd vss {circuit_name}

* ── IF load ─────────────────────────────────────────────────────────────────
Rl_p  ifp  0  1k
Rl_n  ifn  0  1k

* ── Transient sim (enough cycles for FFT) ───────────────────────────────────
.tran 10p 100n

* ── IIP3: two-tone test (RF + RF+1MHz) ──────────────────────────────────────
* (Add .measure FFT for full IIP3 analysis — needs post-processing)

.end
"""


# ── VCO testbench ─────────────────────────────────────────────────────────────

def _vco_testbench(
    spice_path: str,
    circuit_name: str,
    spec: dict,
    pdk: str,
) -> str:
    vdd   = spec.get("vdd_V", 1.8)
    vbias = vdd * 0.8

    return f"""\
* ── VCO Testbench (oscillation frequency, tuning range) ─────────────────────
* Circuit: {circuit_name}
* PDK:     {pdk}
* Target freq: {spec.get('freq_GHz', 5.0)} GHz

{_model_includes(pdk)}
.include "{spice_path}"

* ── Supply and bias ──────────────────────────────────────────────────────────
Vdd   vdd   0  dc {vdd}
Vss   vss   0  dc 0
Vbias vbias 0  dc {vbias:.3f}

* ── Tuning voltage sweep (0 → VDD) ─────────────────────────────────────────
Vtune vtune 0  dc 0.9   * centre tune

* ── DUT ──────────────────────────────────────────────────────────────────────
X_dut outp outn vtune vbias vdd vss {circuit_name}

* ── Differential output probe ───────────────────────────────────────────────
Ediff vdiff 0  outp outn 1

* ── Transient: run for 20 ns to capture oscillation ─────────────────────────
.tran 1p 20n

* ── DC sweep of Vtune to measure tuning range ───────────────────────────────
.dc Vtune 0 {vdd} 0.1

* ── Measure oscillation frequency via zero-crossing ─────────────────────────
.meas tran freq_osc trig v(outp)=0.9 rise=5 targ v(outp)=0.9 rise=6

.end
"""


# ── Public API ────────────────────────────────────────────────────────────────

_GENERATORS = {
    "lna": _lna_testbench,
    "opamp": _opamp_testbench,
    "mixer": _mixer_testbench,
    "vco": _vco_testbench,
}


def generate_testbench(
    circuit_type: str,
    spice_path: str,
    circuit_name: str,
    spec: dict,
    pdk: str = "gf180",
) -> str:
    """
    Generate a complete ngspice testbench for the given circuit type.

    Args:
        circuit_type: "lna" | "opamp" | "mixer" | "vco"
        spice_path:   Path to the post-layout PEX SPICE netlist.
        circuit_name: Subcircuit name inside the netlist (used in X_dut line).
        spec:         Circuit spec dict (vdd_V, freq_GHz, gain_dB, nf_dB, …).
        pdk:          "gf180" | "sky130" | "ihp130"

    Returns:
        SPICE testbench as a string.

    Raises:
        ValueError: if circuit_type is not supported.
    """
    gen = _GENERATORS.get(circuit_type.lower())
    if gen is None:
        raise ValueError(
            f"No testbench template for '{circuit_type}'. "
            f"Supported: {list(_GENERATORS.keys())}"
        )
    return gen(spice_path, circuit_name, spec, pdk)
