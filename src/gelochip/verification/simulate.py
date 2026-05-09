"""
ngspice simulation runner and result parser.

Flow:
    1. Write testbench to a temp file
    2. Run ngspice in batch mode (-b flag)
    3. Parse stdout for .meas results
    4. Return structured SimResult dict

Requires ngspice to be installed:
    sudo apt install ngspice        # Ubuntu/Debian
    brew install ngspice            # macOS

Usage::

    from gelochip.verification.simulate import run_simulation
    result = run_simulation(testbench_str, circuit_type="lna")
    print(result)
    # {'gain_dB': 16.3, 'nf_dB': 1.8, 'bw_GHz': 3.2, 'passed': True}
"""
from __future__ import annotations
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional


# ── ngspice output parser ──────────────────────────────────────────────────────

def _parse_measure(ngspice_output: str) -> dict[str, float]:
    """
    Parse .meas results from ngspice stdout.

    ngspice prints lines like:
        gain_dB = 1.632000e+01
        nf_db   = 1.823000e+00
        gbw_hz  = 4.512000e+08   (failed) means not measured
    """
    results: dict[str, float] = {}
    # Match:  name = value  (scientific or decimal)
    pattern = re.compile(
        r"^(\w+)\s*=\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)",
        re.MULTILINE | re.IGNORECASE,
    )
    for m in pattern.finditer(ngspice_output):
        name  = m.group(1).lower()
        value = float(m.group(2))
        results[name] = value

    # Also capture "failed" measurements as NaN
    fail_pat = re.compile(r"^(\w+)\s*=\s*.*failed", re.MULTILINE | re.IGNORECASE)
    for m in fail_pat.finditer(ngspice_output):
        results[m.group(1).lower()] = float("nan")

    return results


def _map_to_sim_result(raw: dict[str, float], circuit_type: str) -> dict[str, Any]:
    """Map raw .meas names → standardised SimResult fields."""
    r: dict[str, Any] = {"raw_measurements": raw}

    if circuit_type == "lna":
        r["gain_dB"]    = raw.get("gain_db")
        r["nf_dB"]      = raw.get("nf_db")
        r["bw_GHz"]     = (raw["bw_high"] - raw["bw_low"]) / 1e9 if "bw_high" in raw and "bw_low" in raw else None
        r["s11_dB"]     = raw.get("s11_proxy")

    elif circuit_type == "opamp":
        r["gain_dB"]         = raw.get("dc_gain_db")
        r["gbw_MHz"]         = raw.get("gbw_hz", 0) / 1e6 if raw.get("gbw_hz") else None
        r["phase_margin_deg"]= raw.get("phase_margin")
        r["unity_gain_MHz"]  = raw.get("unity_gain_freq", 0) / 1e6 if raw.get("unity_gain_freq") else None

    elif circuit_type == "mixer":
        r["conversion_gain_dB"] = raw.get("conv_gain_db")
        r["iip3_dBm"]           = raw.get("iip3_dbm")
        r["nf_dB"]              = raw.get("nf_db")

    elif circuit_type == "vco":
        r["freq_GHz"]        = 1.0 / raw["freq_osc"] / 1e9 if raw.get("freq_osc") and raw["freq_osc"] > 0 else None
        r["tuning_range_pct"]= None  # needs post-processing across Vtune sweep

    return r


# ── Main runner ───────────────────────────────────────────────────────────────

def run_simulation(
    testbench: str,
    circuit_type: str,
    timeout: int = 300,
    ngspice_bin: str = "ngspice",
) -> dict[str, Any]:
    """
    Run ngspice on the given testbench string, return parsed SimResult.

    Args:
        testbench:    Complete SPICE testbench as a string.
        circuit_type: "lna" | "opamp" | "mixer" | "vco"
        timeout:      Max seconds to wait for ngspice (default 300).
        ngspice_bin:  Path to ngspice executable.

    Returns:
        Dict with performance metrics + "passed" bool + "error" if any.

    Example::

        from gelochip.verification.testbench import generate_testbench
        from gelochip.verification.simulate import run_simulation

        tb = generate_testbench("lna", "lna_pex.spice", "lna_cascode", spec, "gf180")
        result = run_simulation(tb, "lna")
        print(result["gain_dB"], result["nf_dB"])
    """
    # Check ngspice is available
    if not _ngspice_available(ngspice_bin):
        return {
            "error": (
                f"ngspice not found ({ngspice_bin}). "
                "Install with: sudo apt install ngspice"
            ),
            "passed": False,
        }

    # Write testbench to temp file
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".sp", delete=False, prefix="gelochip_tb_"
    ) as f:
        f.write(testbench)
        tb_path = f.name

    try:
        proc = subprocess.run(
            [ngspice_bin, "-b", "-o", tb_path.replace(".sp", ".out"), tb_path],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        stdout = proc.stdout + "\n" + proc.stderr

        # Also read .out file if it exists
        out_file = tb_path.replace(".sp", ".out")
        if Path(out_file).exists():
            with open(out_file) as f:
                stdout += "\n" + f.read()

        raw_meas = _parse_measure(stdout)
        result   = _map_to_sim_result(raw_meas, circuit_type)

        result["sim_stdout"]  = stdout[:3000]
        result["returncode"]  = proc.returncode
        result["passed"]      = proc.returncode == 0 and bool(raw_meas)
        result["error"]       = None if proc.returncode == 0 else proc.stderr[:500]

        return result

    except subprocess.TimeoutExpired:
        return {"error": f"ngspice timed out after {timeout}s", "passed": False}
    except Exception as e:
        return {"error": str(e), "passed": False}
    finally:
        Path(tb_path).unlink(missing_ok=True)


def check_specs(sim_result: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    """
    Compare simulation results against target specifications.

    Returns a dict with:
        all_passed: bool
        checks: list of {metric, target, measured, passed}
    """
    checks = []

    def _chk(metric: str, measured: Optional[float], target: Optional[float], higher_is_better: bool):
        if target is None or measured is None:
            return
        if higher_is_better:
            passed = measured >= target
        else:
            passed = measured <= target
        checks.append({
            "metric":   metric,
            "target":   target,
            "measured": round(measured, 2) if measured is not None else None,
            "passed":   passed,
        })

    _chk("gain_dB",       sim_result.get("gain_dB"),       spec.get("gain_dB"),  higher_is_better=True)
    _chk("nf_dB",         sim_result.get("nf_dB"),         spec.get("nf_dB"),    higher_is_better=False)
    _chk("iip3_dBm",      sim_result.get("iip3_dBm"),      spec.get("iip3_dBm"), higher_is_better=True)
    _chk("s11_dB",        sim_result.get("s11_dB"),        spec.get("s11_dB"),   higher_is_better=False)
    _chk("phase_margin",  sim_result.get("phase_margin_deg"), 45.0,              higher_is_better=True)

    return {
        "all_passed": all(c["passed"] for c in checks),
        "checks": checks,
    }


def _ngspice_available(binary: str = "ngspice") -> bool:
    try:
        subprocess.run([binary, "--version"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
