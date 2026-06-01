"""
gelochip.kaizen.studio  —  backend for the three Gelochip Studio canvas tools.

    list_ips()              IP Library     — built blocks from data/circuits/*
    padframe()              Padframe       — gf180 pad ring (chipathon / caravel)
    propose_connections()   Pin-Connect AI — LLM proposes pin↔pin nets + names

These power the drag-n-drop chip floorplan: drag IP cards (each with a bbox and
named pins) onto the padframe, then let the agent wire the pins together.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from gelochip.kaizen import config

DATASETS_DIR = config.CIRCUITS_DIR
# Registry of corrected / agent-generated IPs that passed DRC and were promoted
# into the library (written by the IP-correction notebook and the agent).
IP_REGISTRY = config.KAIZEN_DIR / "ip_registry.json"

# ── Pin maps per circuit family ───────────────────────────────────────────────
# side ∈ {left=input, right=output, top=supply/bias, bottom=ground/tail}
_P = lambda name, side: {"name": name, "side": side}  # noqa: E731

_PIN_MAP: dict[str, list[dict]] = {
    "current_mirror": [_P("VB", "left"), _P("VCOPY", "right"), _P("VSS", "bottom")],
    "stacked_current_mirror": [_P("VB", "left"), _P("VCOPY", "right"), _P("VSS", "bottom")],
    "low_voltage_cmirror": [_P("VB", "left"), _P("VCOPY", "right"), _P("VSS", "bottom")],
    "diff_pair": [_P("VIP", "left"), _P("VIM", "left"), _P("VOP", "right"),
                  _P("VOM", "right"), _P("VTAIL", "bottom"), _P("VSS", "bottom")],
    "diff_pair_cmirrorbias": [_P("VIP", "left"), _P("VIM", "left"), _P("VOUT", "right"),
                              _P("VBIAS", "top"), _P("VSS", "bottom")],
    "diff_pair_stackedcmirror": [_P("VIP", "left"), _P("VIM", "left"), _P("VOUT", "right"),
                                 _P("VBIAS", "top"), _P("VSS", "bottom")],
    "ota": [_P("VIP", "left"), _P("VIM", "left"), _P("VOUT", "right"),
            _P("VBIAS", "top"), _P("VDD", "top"), _P("VSS", "bottom")],
    "opamp": [_P("VIP", "left"), _P("VIM", "left"), _P("VOUT", "right"),
              _P("VBIAS", "top"), _P("VDD", "top"), _P("VSS", "bottom")],
    "opamp_twostage": [_P("VIP", "left"), _P("VIM", "left"), _P("VOUT", "right"),
                       _P("VBIAS", "top"), _P("VDD", "top"), _P("VSS", "bottom")],
    "fvf": [_P("VIN", "left"), _P("VOUT", "right"), _P("VBIAS", "top"), _P("VSS", "bottom")],
    "transmission_gate": [_P("IN", "left"), _P("OUT", "right"), _P("EN", "top"),
                          _P("ENB", "top")],
    "differential_to_single_ended_converter": [_P("VIP", "left"), _P("VIM", "left"),
                                                _P("VOUT", "right"), _P("VDD", "top"),
                                                _P("VSS", "bottom")],
    "row_csamplifier_diff_to_single_ended_converter": [_P("VIP", "left"), _P("VIM", "left"),
                                                        _P("VOUT", "right"), _P("VDD", "top"),
                                                        _P("VSS", "bottom")],
    "n_block": [_P("INP", "left"), _P("INN", "left"), _P("OUT", "right"), _P("VSS", "bottom")],
    "p_block": [_P("INP", "left"), _P("INN", "left"), _P("OUT", "right"), _P("VDD", "top")],
}
_DEFAULT_PINS = [_P("IN", "left"), _P("OUT", "right"), _P("VDD", "top"), _P("VSS", "bottom")]


def _pins_for(key: str) -> list[dict]:
    return _PIN_MAP.get(key, _DEFAULT_PINS)


# ── IP Library ────────────────────────────────────────────────────────────────
def list_ips(only_drc_clean: bool = True) -> list[dict[str, Any]]:
    """Scan data/circuits/* and return one descriptor per built IP block.

    Only **DRC-clean** blocks (``drc.is_pass == True``, 0 errors) are admitted to
    the library by default — a chip must be built from DRC-free IP. Set
    ``only_drc_clean=False`` to list every block regardless of DRC status.
    """
    ips: list[dict] = []
    if not DATASETS_DIR.exists():
        return ips
    seen: set[str] = set()
    # (1) corrected / agent-promoted IPs from the registry (already DRC-vetted).
    for ip in _load_registry():
        if only_drc_clean and not ip.get("drc_pass"):
            continue
        ip.setdefault("pins", _pins_for(ip.get("id", "")))
        ips.append(ip)
        seen.add(ip["id"])

    # (2) DRC-clean blocks scanned from data/circuits/*.
    for d in sorted(DATASETS_DIR.iterdir()):
        if not d.is_dir() or d.name in seen:
            continue
        # Prefer the current canonical, DRC-clean eval; fall back to the legacy one.
        evalf = d / "eval_result_clean.json"
        if not evalf.exists():
            evalf = d / "eval_result.json"
        meta = json.loads(evalf.read_text()) if evalf.exists() else {}
        preview = next(iter(d.glob("*preview*.png")), None)
        thumb = next(iter(d.glob("*_thumb.png")), None)   # tight-cropped GDS layout
        area = meta.get("area_um2") or (meta.get("geometric", {}) or {}).get("raw_area_um2")
        side = round(math.sqrt(area)) if area else 60
        drc_summary = (meta.get("drc", {}) or {}).get("summary", {}) or {}
        drc = (meta.get("drc", {}) or {}).get("is_pass")
        errors = drc_summary.get("total_errors")
        lvs = ((meta.get("lvs", {}) or {}).get("is_pass"))
        # Gate on DRC: skip anything not verified clean.
        if only_drc_clean and not (drc is True and (errors in (0, None))):
            continue
        ips.append({
            "id": d.name,
            "name": _pretty(d.name),
            "component_name": meta.get("component_name", d.name),
            "preview_url": f"/datasets/{d.name}/{preview.name}" if preview else None,
            "thumb_url": f"/datasets/{d.name}/{thumb.name}" if thumb else (
                f"/datasets/{d.name}/{preview.name}" if preview else None),
            "pins": _pins_for(d.name),
            "width_um": side,
            "height_um": side,
            "area_um2": round(area, 1) if area else None,
            "drc_pass": drc,
            "drc_errors": errors,
            "lvs_pass": lvs,
            "pdk": config.PDK,
        })
    return ips


def _pretty(slug: str) -> str:
    return slug.replace("_", " ").title()


def _load_registry() -> list[dict]:
    if IP_REGISTRY.exists():
        try:
            return json.loads(IP_REGISTRY.read_text())
        except json.JSONDecodeError:
            return []
    return []


def register_ip(ip_id: str, name: str, preview_url: str | None, pins: list[dict] | None,
                area_um2: float | None, drc_pass: bool, source: str = "corrected") -> dict:
    """Promote a DRC-clean corrected/generated block into the IP library registry."""
    reg = [x for x in _load_registry() if x.get("id") != ip_id]
    side = round(math.sqrt(area_um2)) if area_um2 else 60
    entry = {
        "id": ip_id, "name": name, "component_name": ip_id,
        "preview_url": preview_url, "pins": pins or _pins_for(ip_id),
        "width_um": side, "height_um": side, "area_um2": area_um2,
        "drc_pass": drc_pass, "drc_errors": 0 if drc_pass else None,
        "lvs_pass": None, "pdk": config.PDK, "source": source,
    }
    reg.append(entry)
    IP_REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    IP_REGISTRY.write_text(json.dumps(reg, indent=2))
    return entry


# ── Padframe ──────────────────────────────────────────────────────────────────
def padframe(pads_per_side: int = 6) -> dict[str, Any]:
    """A gf180 pad ring used as the chip boundary on the canvas.

    Default is a generated ring (works offline). Drop a real chipathon /
    caravel-gf180mcu padframe GDS into notebooks/kaizen_architecture/padframe/
    to replace it. Sources:
      github.com/sscs-ose/sscs-chipathon-2025  (Blocks & Bots, gf180mcuD)
      github.com/efabless/caravel-gf180mcu       (GF180MCU Caravel pad ring)
    """
    outline = {"w": 1200, "h": 1200, "core_margin": 180}
    # A sensible default power/IO assignment for a small analog test chip.
    labels = {
        "top":    ["VDDA", "IO_N1", "IO_N2", "IO_N3", "IO_N4", "VSSA"],
        "bottom": ["VDD", "IO_S1", "IO_S2", "IO_S3", "IO_S4", "VSS"],
        "left":   ["IO_W1", "VINP", "VINM", "VBIAS", "IO_W5", "IO_W6"],
        "right":  ["IO_E1", "VOUT", "IO_E3", "IO_E4", "IO_E5", "IO_E6"],
    }
    pads: list[dict] = []
    w, h = outline["w"], outline["h"]
    n = pads_per_side
    for side in ("top", "bottom", "left", "right"):
        names = (labels.get(side) or [])[:n]
        for i, name in enumerate(names):
            frac = (i + 1) / (n + 1)
            if side == "top":
                x, y = frac * w, 0
            elif side == "bottom":
                x, y = frac * w, h
            elif side == "left":
                x, y = 0, frac * h
            else:
                x, y = w, frac * h
            pads.append({"name": name, "side": side, "x": round(x), "y": round(y)})
    return {"source": "generated gf180 pad ring (chipathon/caravel compatible)",
            "outline": outline, "pads": pads}


# ── Pin-Connect agentic AI ────────────────────────────────────────────────────
def propose_connections(blocks: list[dict], use_llm: bool = True) -> dict[str, Any]:
    """Propose a netlist (pin↔pin wiring + net names) for placed blocks.

    `blocks` = [{"id": "U1", "ip": "ota", "pins": [{"name","side"}...]}, ...]
    Returns {"nets": [{"name": "VSS", "pins": ["U1.VSS","U2.VSS"]}], "source": ...}
    Tries the LLM first (qwen3.5:9b), falls back to name-matching rules.
    """
    if use_llm:
        try:
            return _llm_connections(blocks)
        except Exception:
            pass
    return _rule_connections(blocks)


def _rule_connections(blocks: list[dict]) -> dict[str, Any]:
    """Connect identically-named power/bias pins; chain output→next input."""
    nets: dict[str, list[str]] = {}
    inputs, outputs = [], []
    for b in blocks:
        for p in b.get("pins", []):
            ref = f"{b['id']}.{p['name']}"
            up = p["name"].upper()
            if up in ("VDD", "VSS", "VDDA", "VSSA", "VBIAS", "VB", "VTAIL"):
                nets.setdefault(up, []).append(ref)
            elif up.startswith(("VIN", "VIP", "VIM", "IN")):
                inputs.append(ref)
            elif up.startswith(("VOUT", "VCOPY", "OUT", "VOP", "VOM")):
                outputs.append(ref)
    # Chain each output to the next block's input (simple series hookup).
    for i, out in enumerate(outputs):
        if i < len(inputs):
            nets[f"SIG_{i+1}"] = [out, inputs[i]]
    out = [{"name": k, "pins": v} for k, v in nets.items() if len(v) >= 2]
    return {"nets": out, "source": "rule-based name matching"}


def _llm_connections(blocks: list[dict]) -> dict[str, Any]:
    from gelochip.kaizen.agent import get_llm, _text

    spec = [{"id": b["id"], "ip": b.get("ip", b["id"]),
             "pins": [p["name"] for p in b.get("pins", [])]} for b in blocks]
    prompt = (
        "You are an analog IC integration assistant. Given these placed blocks and "
        "their pins, propose how to wire them on a gf180 chip. Connect shared power "
        "(VDD/VSS), bias (VBIAS), and chain signal output→input sensibly.\n"
        "Return ONLY JSON: {\"nets\":[{\"name\":\"VSS\",\"pins\":[\"U1.VSS\",\"U2.VSS\"]}]}\n\n"
        f"Blocks: {json.dumps(spec)}"
    )
    raw = _text(get_llm(temperature=0).invoke(prompt))
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    data = json.loads(m.group(0)) if m else {"nets": []}
    data.setdefault("nets", [])
    data["source"] = f"{config.LLM_MODEL} (agentic)"
    return data
