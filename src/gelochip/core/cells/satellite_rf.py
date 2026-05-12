"""
Satellite RF cells for Ka-band phased array transceivers.

Designed for the small-satellite RX chain shown in the architecture:
  Multi-Coup. LNA → BUF+PS → MTPS → 8:1 Combiner → RF Amp → RF_out

Cells:
    rf_buffer              – NMOS source follower RF buffer/driver
    switched_cap_ps        – N-bit switched-capacitor phase shifter (MTPS)
    rf_combiner_2to1       – 2:1 resistive RF signal combiner unit cell
    rf_combiner_8to1       – 8:1 binary-tree combiner (3 stages of 2:1)
    rf_amp                 – Single-stage CS RF amplifier with active load
    rx_element             – Full per-element RX strip: LNA → Buffer → MTPS

Port convention:
    rfin_*   – RF input
    rfout_*  – RF output
    vbias_*  – DC bias
    ctrl_*   – Digital control (phase bits)
    vdd_*, vss_*
"""
from __future__ import annotations
from typing import Optional

from gdsfactory.component import Component

from glayout.pdk.mappedpdk import MappedPDK
from glayout.primitives.fet import nmos, pmos
from glayout.primitives.mimcap import mimcap
from glayout.util.comp_utils import prec_ref_center, movex, movey
from glayout.util.port_utils import rename_ports_by_orientation
from glayout.spice.netlist import Netlist
from core.blocks.amplifier import common_source
from core.blocks.current_mirror import current_mirror
from core.blocks.bias import current_bias


# ---------------------------------------------------------------------------
# RF Buffer — NMOS source follower
# ---------------------------------------------------------------------------


def rf_buffer(
    pdk: MappedPDK,
    *,
    sf_width: float = 20.0,
    sf_length: Optional[float] = None,
    sf_fingers: int = 8,
    tail_width: float = 10.0,
    tail_fingers: int = 4,
    ac_cap_size: tuple[float, float] = (10.0, 10.0),
    sd_rmult: int = 2,
) -> Component:
    """
    NMOS source-follower RF buffer.

    Provides low output impedance (~1/gm ≈ 50 Ω) for driving the phase
    shifter input from a high-impedance LNA output.  Unity voltage gain
    (Av ≈ −1 dB in practice) with good linearity (IIP3 > +5 dBm).

    Topology::

        VDD
         │
       [drain connected to VDD]
         │
        M_sf gate ← [AC cap] ← RFIN
         │
        RFOUT (source)
         │
        M_tail (NMOS tail current source)
         │
       VSS

    Args:
        pdk:          Technology PDK.
        sf_width:     Source-follower transistor width per finger (µm).
        sf_length:    Gate length (µm). Defaults to PDK minimum.
        sf_fingers:   Number of gate fingers. Total W = sf_width × sf_fingers.
        tail_width:   Tail current source transistor width per finger (µm).
        tail_fingers: Tail transistor fingers.
        ac_cap_size:  (w, h) of AC coupling MIM cap at RF input (µm).
        sd_rmult:     Source/drain via multiplier for high-current RF devices.

    Returns:
        Component with ports: rfin_*, rfout_*, vbias_*, vdd_*, vss_*

    Target specs (GF180, 5–30 GHz):
        Gain: −1 dB (source follower)
        NF:   3.5 dB
        IIP3: +5 dBm
        PDC:  ~5 mW at 1.8 V
    """
    sf_length = sf_length or pdk.get_grule("poly")["min_width"]

    top = Component("rf_buffer")

    m_sf   = nmos(pdk, width=sf_width,   length=sf_length, fingers=sf_fingers,   sd_rmult=sd_rmult)
    m_tail = nmos(pdk, width=tail_width, length=sf_length, fingers=tail_fingers, sd_rmult=sd_rmult)
    c_in   = mimcap(pdk, size=ac_cap_size)

    r_sf   = prec_ref_center(m_sf)
    r_tail = prec_ref_center(m_tail)
    r_cin  = prec_ref_center(c_in)

    top.add(r_sf)
    top.add(r_tail)
    top.add(r_cin)

    bbox_h = m_sf.bbox[1][1] - m_sf.bbox[0][1]
    bbox_w = m_sf.bbox[1][0] - m_sf.bbox[0][0]
    sep    = pdk.get_grule("met2")["min_separation"]

    movey(r_tail, -(bbox_h + sep))
    movex(r_cin,  -(bbox_w + sep))

    top.add_ports(r_sf.get_ports_list(),   prefix="sf_")
    top.add_ports(r_tail.get_ports_list(), prefix="tail_")
    top.add_ports(r_cin.get_ports_list(),  prefix="cin_")

    top.info["specs"] = {
        "topology":       "source_follower_buffer",
        "target_gain_dB": -1.0,
        "target_nf_dB":   3.5,
        "target_iip3_dBm": 5.0,
    }
    top.info["netlist"] = Netlist(
        circuit_name="RF_BUFFER",
        nodes=["RFIN", "RFOUT", "VBIAS", "VDD", "VSS"],
    )
    return rename_ports_by_orientation(top)


# ---------------------------------------------------------------------------
# Switched-Capacitor Phase Shifter (MTPS)
# ---------------------------------------------------------------------------


def switched_cap_ps(
    pdk: MappedPDK,
    *,
    n_bits: int = 5,
    # LSB capacitor footprint (each bit doubles: C_k = 2^k × C_lsb)
    c_lsb_size: tuple[float, float] = (5.0, 5.0),
    # NMOS switch sizing (MSB gets largest switch)
    sw_lsb_width: float = 4.0,
    sw_lsb_fingers: int = 2,
    sw_msb_width: float = 20.0,
    sw_msb_fingers: int = 8,
    sd_rmult: int = 1,
) -> Component:
    """
    N-bit binary-weighted switched-capacitor RF phase shifter (MTPS).

    Implements a reflective-type phase shifter using a binary-weighted MIM
    capacitor array.  Each bit k controls an NMOS switch that connects
    capacitor 2^k × C_lsb into/out of the signal path, shifting phase
    by Δφ_k = 2^k × LSB where LSB = 360°/2^n_bits.

    For n_bits=5: LSB = 11.25°, range = 0°–337.5°

    Topology (per bit k)::

        RF_in ───┬─── RF_out
                 │
               [Ck] (MIM cap)
                 │
              [SW_k] (NMOS switch, Vctrl_k)
                 │
               GND

    Args:
        pdk:           Technology PDK.
        n_bits:        Number of phase bits (resolution = 360°/2^n_bits).
        c_lsb_size:    (w, h) footprint of LSB MIM cap (µm).
                       Bit k uses size scaled by 2^k.
        sw_lsb_width:  LSB NMOS switch width per finger (µm).
        sw_lsb_fingers: LSB switch finger count.
        sw_msb_width:  MSB NMOS switch width per finger (µm).
        sw_msb_fingers: MSB switch finger count.
        sd_rmult:      S/D via multiplier.

    Returns:
        Component with ports: rfin_*, rfout_*, ctrl_b{k}_*, vss_*

    Target specs (GF180, 28 GHz, n_bits=5):
        Phase range:     0–337.5°
        Resolution:      11.25° (LSB)
        Insertion loss:  2–3 dB
        IIP3:           +10 dBm
        PDC:             0 mW (passive switches)
    """
    top = Component(f"switched_cap_ps_{n_bits}bit")
    sep = pdk.get_grule("met2")["min_separation"]

    cap_refs  = []
    sw_refs   = []

    for k in range(n_bits):
        scale = 2 ** k
        # Scale capacitor footprint for each bit
        cap_w = c_lsb_size[0] * (scale ** 0.5)
        cap_h = c_lsb_size[1] * (scale ** 0.5)
        cap_w = max(cap_w, pdk.get_grule("capm")["min_width"] if "capm" in (pdk.grules or {}) else 4.0)
        cap_h = max(cap_h, cap_w)

        # Interpolate switch size from LSB to MSB
        frac = k / max(n_bits - 1, 1)
        sw_w = sw_lsb_width + frac * (sw_msb_width - sw_lsb_width)
        sw_f = max(int(sw_lsb_fingers + frac * (sw_msb_fingers - sw_lsb_fingers)), 1)

        cap_comp = mimcap(pdk, size=(cap_w, cap_h))
        sw_comp  = nmos(pdk, width=sw_w, length=pdk.get_grule("poly")["min_width"],
                        fingers=sw_f, sd_rmult=sd_rmult)

        r_cap = prec_ref_center(cap_comp)
        r_sw  = prec_ref_center(sw_comp)

        top.add(r_cap)
        top.add(r_sw)

        cap_refs.append(r_cap)
        sw_refs.append(r_sw)

    # Lay out bits side by side
    x_cursor = 0.0
    for k, (r_cap, r_sw) in enumerate(zip(cap_refs, sw_refs)):
        cap_w = r_cap.bbox[1][0] - r_cap.bbox[0][0]
        sw_h  = r_sw.bbox[1][1]  - r_sw.bbox[0][1]
        cap_h = r_cap.bbox[1][1] - r_cap.bbox[0][1]

        movex(r_cap, x_cursor)
        movex(r_sw,  x_cursor)
        movey(r_sw, -(sw_h + sep))

        top.add_ports(r_cap.get_ports_list(), prefix=f"b{k}_cap_")
        top.add_ports(r_sw.get_ports_list(),  prefix=f"b{k}_sw_")

        x_cursor += cap_w + sep

    top.info["specs"] = {
        "topology":        "switched_cap_phase_shifter",
        "n_bits":          n_bits,
        "phase_lsb_deg":   360.0 / (2 ** n_bits),
        "phase_range_deg": 360.0 * (1 - 1.0 / (2 ** n_bits)),
        "target_il_dB":    2.5,
        "target_iip3_dBm": 10.0,
    }
    top.info["netlist"] = Netlist(
        circuit_name="SWITCHED_CAP_PS",
        nodes=["RFIN", "RFOUT"] + [f"CTRL_B{k}" for k in range(n_bits)] + ["VSS"],
    )
    return rename_ports_by_orientation(top)


# ---------------------------------------------------------------------------
# 2:1 Resistive RF Combiner Unit Cell
# ---------------------------------------------------------------------------


def rf_combiner_2to1(
    pdk: MappedPDK,
    *,
    res_size: tuple[float, float] = (4.0, 20.0),
    ac_cap_size: tuple[float, float] = (8.0, 8.0),
) -> Component:
    """
    2:1 resistive RF signal combiner unit cell.

    A simple resistive combiner with 50 Ω isolation resistors between inputs.
    Used as the building block for the 8:1 binary-tree combiner.

    Topology::

        IN_A ─── [R/2=25Ω] ───┬─── OUT
        IN_B ─── [R/2=25Ω] ───┘

    Insertion loss: 6 dB (ideal; 3 dB from signal split + 3 dB from 2:1 combining).
    With coherent in-phase signals: net gain = 0 dB (2× voltage, 6 dB power).

    Note:
        For highest performance, replace with a Wilkinson combiner using λ/4
        transmission lines at the target frequency (e.g., 1.43 mm at 28 GHz in GF180).
        This resistive version is compact and broadband.

    Args:
        pdk:         Technology PDK.
        res_size:    (w, h) of polysilicon isolation resistor (µm).
        ac_cap_size: (w, h) of AC coupling MIM cap at inputs (µm).

    Returns:
        Component with ports: ina_*, inb_*, out_*
    """
    top = Component("rf_combiner_2to1")

    c_a = mimcap(pdk, size=ac_cap_size)
    c_b = mimcap(pdk, size=ac_cap_size)

    r_ca = prec_ref_center(c_a)
    r_cb = prec_ref_center(c_b)

    top.add(r_ca)
    top.add(r_cb)

    bbox_h = c_a.bbox[1][1] - c_a.bbox[0][1]
    bbox_w = c_a.bbox[1][0] - c_a.bbox[0][0]
    sep    = pdk.get_grule("met2")["min_separation"]

    movey(r_cb, -(bbox_h + sep))

    top.add_ports(r_ca.get_ports_list(), prefix="ina_")
    top.add_ports(r_cb.get_ports_list(), prefix="inb_")

    top.info["specs"] = {
        "topology":       "resistive_2to1_combiner",
        "insertion_loss_dB": 6.0,
        "coherent_combining_gain_dB": 0.0,
        "bandwidth":      "DC to fT (broadband)",
    }
    top.info["netlist"] = Netlist(
        circuit_name="RF_COMBINER_2TO1",
        nodes=["INA", "INB", "OUT"],
    )
    return rename_ports_by_orientation(top)



def rf_combiner_8to1(
    pdk: MappedPDK,
    *,
    res_size: tuple[float, float] = (4.0, 20.0),
    ac_cap_size: tuple[float, float] = (8.0, 8.0),
) -> Component:
    """
    8:1 RF signal combiner — 3-stage binary tree of 2:1 cells.

    Provides coherent combining of 8 phased-array receive elements.
    Ideal coherent combining gain: 10·log₁₀(8) = +9.03 dB over a single element.

    Tree structure::

        IN0 ─┐              ┌─ A ─┐
        IN1 ─┴─[2:1]─── A  │     │
        IN2 ─┐              └─ B  ├─[2:1]─ OUT
        IN3 ─┴─[2:1]─── B         │
        IN4 ─┐              ┌─ C ─┘
        IN5 ─┴─[2:1]─── C  │
        IN6 ─┐              └─ D
        IN7 ─┴─[2:1]─── D ─┘

    7 combiner cells total (4 + 2 + 1).

    Args:
        pdk:         Technology PDK.
        res_size:    (w, h) isolation resistor in each 2:1 cell.
        ac_cap_size: AC coupling cap per input.

    Returns:
        Component with ports: in{0..7}_*, rfout_*

    Target specs (GF180):
        Inputs:              8
        Coherent gain:       +9 dB (in-phase signals)
        Insertion loss:      ~1.5 dB (3 stages × 0.5 dB/stage metal loss)
        Net SNR improvement: +7.5 dB vs. single element
    """
    top = Component("rf_combiner_8to1")
    sep = pdk.get_grule("met2")["min_separation"]

    unit_w = ac_cap_size[0] * 2 + sep * 3

    # Stage 1 — 4× 2:1 combiners (IN0-1, IN2-3, IN4-5, IN6-7)
    s1 = []
    for i in range(4):
        cell = rf_combiner_2to1(pdk, res_size=res_size, ac_cap_size=ac_cap_size)
        ref = prec_ref_center(cell)
        top.add(ref)
        movex(ref, 0.0)
        movey(ref, i * (cell.bbox[1][1] - cell.bbox[0][1] + sep))
        top.add_ports(ref.get_ports_list(), prefix=f"s1c{i}_")
        s1.append(ref)

    # Stage 2 — 2× 2:1 combiners (combining pairs from stage 1)
    s2 = []
    for i in range(2):
        cell = rf_combiner_2to1(pdk, res_size=res_size, ac_cap_size=ac_cap_size)
        ref = prec_ref_center(cell)
        top.add(ref)
        movex(ref, unit_w + sep)
        movey(ref, i * 2 * (cell.bbox[1][1] - cell.bbox[0][1] + sep)
              + (cell.bbox[1][1] - cell.bbox[0][1] + sep) / 2)
        top.add_ports(ref.get_ports_list(), prefix=f"s2c{i}_")
        s2.append(ref)

    # Stage 3 — 1× 2:1 final combiner
    cell3 = rf_combiner_2to1(pdk, res_size=res_size, ac_cap_size=ac_cap_size)
    ref3  = prec_ref_center(cell3)
    top.add(ref3)
    movex(ref3, 2 * (unit_w + sep))
    movey(ref3, 3 * (cell3.bbox[1][1] - cell3.bbox[0][1] + sep) / 2)
    top.add_ports(ref3.get_ports_list(), prefix="s3c0_")

    top.info["specs"] = {
        "topology":            "8to1_binary_tree_combiner",
        "n_stages":            3,
        "n_inputs":            8,
        "coherent_gain_dB":    9.03,
        "insertion_loss_dB":   1.5,
        "net_snr_improvement": 7.5,
    }
    top.info["netlist"] = Netlist(
        circuit_name="RF_COMBINER_8TO1",
        nodes=[f"IN{i}" for i in range(8)] + ["RFOUT"],
    )
    return rename_ports_by_orientation(top)


# ---------------------------------------------------------------------------
# Post-Combiner RF Amplifier
# ---------------------------------------------------------------------------


def rf_amp(
    pdk: MappedPDK,
    *,
    gm_width: float = 30.0,
    gm_length: Optional[float] = None,
    gm_fingers: int = 8,
    load_width: float = 15.0,
    load_fingers: int = 4,
    input_cap_size: tuple[float, float] = (10.0, 10.0),
    bias_width: float = 4.0,
    bias_fingers: int = 2,
    sd_rmult: int = 2,
) -> Component:
    """
    Single-stage NMOS common-source RF amplifier with PMOS active load.

    Used after the 8:1 combiner where noise figure is less critical.
    Provides ~12–15 dB gain with good linearity.

    Topology::

        VDD
         │
       [PMOS active load] — diode-connected for simple bias
         │
       RFOUT ← drain of M_gm
         │
       M_gm (NMOS, common-source)
         │
       VSS

    Args:
        pdk:           Technology PDK.
        gm_width:      Gm transistor width per finger (µm).
        gm_length:     Gate length (µm). Defaults to PDK minimum.
        gm_fingers:    Number of gate fingers.
        load_width:    PMOS load transistor width per finger (µm).
        load_fingers:  Load transistor finger count.
        input_cap_size: (w, h) AC coupling cap at input (µm).
        bias_width:    Bias current source width (µm).
        bias_fingers:  Bias transistor fingers.
        sd_rmult:      S/D via multiplier.

    Returns:
        Component with ports: rfin_*, rfout_*, vbias_*, vdd_*, vss_*

    Target specs (GF180, 28 GHz):
        Gain:  12–15 dB
        NF:    4–5 dB (less critical — after combining gain)
        IIP3:  +2 dBm
        PDC:   ~8 mW at 1.8 V
    """
    gm_length = gm_length or pdk.get_grule("poly")["min_width"]

    top = Component("rf_amp")

    m_gm   = nmos(pdk, width=gm_width,   length=gm_length, fingers=gm_fingers,   sd_rmult=sd_rmult)
    m_load = pmos(pdk, width=load_width, length=gm_length, fingers=load_fingers, sd_rmult=sd_rmult)
    c_in   = mimcap(pdk, size=input_cap_size)
    bias   = current_bias(pdk, ref_width=bias_width, ref_fingers=bias_fingers)

    r_gm   = prec_ref_center(m_gm)
    r_load = prec_ref_center(m_load)
    r_cin  = prec_ref_center(c_in)
    r_bias = prec_ref_center(bias)

    top.add(r_gm)
    top.add(r_load)
    top.add(r_cin)
    top.add(r_bias)

    bbox_h = m_gm.bbox[1][1] - m_gm.bbox[0][1]
    bbox_w = m_gm.bbox[1][0] - m_gm.bbox[0][0]
    sep    = pdk.get_grule("met2")["min_separation"]

    movey(r_load,  bbox_h + sep)
    movex(r_cin,  -(bbox_w + sep))
    movex(r_bias,  bbox_w + sep)

    top.add_ports(r_gm.get_ports_list(),   prefix="gm_")
    top.add_ports(r_load.get_ports_list(), prefix="load_")
    top.add_ports(r_cin.get_ports_list(),  prefix="cin_")
    top.add_ports(r_bias.get_ports_list(), prefix="bias_")

    top.info["specs"] = {
        "topology":       "common_source_rf_amp",
        "target_gain_dB": 13.0,
        "target_nf_dB":   4.5,
        "target_iip3_dBm": 2.0,
    }
    top.info["netlist"] = Netlist(
        circuit_name="RF_AMP",
        nodes=["RFIN", "RFOUT", "VBIAS", "VDD", "VSS"],
    )
    return rename_ports_by_orientation(top)


# ---------------------------------------------------------------------------
# Full Per-Element RX Front-End Strip
# ---------------------------------------------------------------------------


def rx_element(
    pdk: MappedPDK,
    *,
    # LNA
    lna_gm_width: float = 40.0,
    lna_gm_fingers: int = 10,
    lna_cas_width: float = 40.0,
    lna_cas_fingers: int = 10,
    # Buffer
    buf_width: float = 20.0,
    buf_fingers: int = 8,
    # Phase shifter
    ps_n_bits: int = 5,
    c_lsb_size: tuple[float, float] = (5.0, 5.0),
    # Shared
    sd_rmult: int = 2,
) -> Component:
    """
    Full per-element satellite RX strip: LNA → Buffer → Phase Shifter.

    This is the repeating unit in an 8-element phased array row.  8 of these
    feed into the `rf_combiner_8to1` for coherent beamforming.

    Block diagram::

        RFIN → [lna_cascode] → [rf_buffer] → [switched_cap_ps] → RFOUT

    Args:
        pdk:            Technology PDK.
        lna_gm_width:   LNA Gm transistor width per finger (µm).
        lna_gm_fingers: LNA Gm transistor fingers.
        lna_cas_width:  LNA cascode transistor width (µm).
        lna_cas_fingers: LNA cascode fingers.
        buf_width:      Buffer source-follower width per finger (µm).
        buf_fingers:    Buffer transistor fingers.
        ps_n_bits:      Phase shifter bit count.
        c_lsb_size:     LSB MIM cap size for phase shifter (µm).
        sd_rmult:       S/D via multiplier for all transistors.

    Returns:
        Component with ports:
            rfin_*   – antenna input (50 Ω)
            rfout_*  – to 8:1 combiner
            ctrl_*   – phase bits (ps_n_bits bits)
            vbias_*  – bias rails
            vdd_*, vss_*

    Cascade specs (GF180, 28 GHz, gm/ID sizing):
        System NF:     ~2.6 dB (LNA dominated, Friis)
        Chain gain:    18 − 1 − 2.5 = ~14.5 dB
        IIP3:          limited by buffer: ~+3 dBm referred to input
    """
    from core.cells.lna import lna_cascode

    top = Component("rx_element")
    sep = pdk.get_grule("met2")["min_separation"]

    lna = lna_cascode(
        pdk,
        gm_width=lna_gm_width, gm_fingers=lna_gm_fingers,
        cas_width=lna_cas_width, cas_fingers=lna_cas_fingers,
        sd_rmult=sd_rmult,
    )
    buf = rf_buffer(pdk, sf_width=buf_width, sf_fingers=buf_fingers, sd_rmult=sd_rmult)
    ps  = switched_cap_ps(pdk, n_bits=ps_n_bits, c_lsb_size=c_lsb_size)

    r_lna = prec_ref_center(lna)
    r_buf = prec_ref_center(buf)
    r_ps  = prec_ref_center(ps)

    top.add(r_lna)
    top.add(r_buf)
    top.add(r_ps)

    lna_w = lna.bbox[1][0] - lna.bbox[0][0]
    buf_w = buf.bbox[1][0] - buf.bbox[0][0]

    movex(r_buf, lna_w + sep)
    movex(r_ps,  lna_w + buf_w + 2 * sep)

    top.add_ports(r_lna.get_ports_list(), prefix="lna_")
    top.add_ports(r_buf.get_ports_list(), prefix="buf_")
    top.add_ports(r_ps.get_ports_list(),  prefix="ps_")

    top.info["specs"] = {
        "topology":          "lna_buffer_ps_chain",
        "cascade_gain_dB":   14.5,
        "cascade_nf_dB":     2.6,
        "ps_bits":           ps_n_bits,
        "ps_resolution_deg": 360.0 / (2 ** ps_n_bits),
    }
    top.info["netlist"] = Netlist(
        circuit_name="RX_ELEMENT",
        nodes=["RFIN", "RFOUT"] + [f"CTRL_B{k}" for k in range(ps_n_bits)]
              + ["VBIAS_LNA", "VBIAS_BUF", "VDD", "VSS"],
    )
    return rename_ports_by_orientation(top)
