from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
GLAYOUT_SRC = SRC / "gelochip"
if str(GLAYOUT_SRC) not in sys.path:
    sys.path.insert(0, str(GLAYOUT_SRC))

extra_paths = os.environ.get("EXTRA_PYTHONPATH", "")
if extra_paths:
    for path in extra_paths.split(os.pathsep):
        if path and path not in sys.path:
            sys.path.insert(0, path)

from gdsfactory.component import Component
from gelochip.glayout import gf180 as pdk

RF_BLOCKS_PATH = ROOT / "src" / "gelochip" / "glayout" / "cells" / "composite" / "rf_blocks.py"
VERIFICATION_PATH = ROOT / "src" / "gelochip" / "glayout" / "verification" / "verification.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load module spec for {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rf_blocks = _load_module("rf_blocks", RF_BLOCKS_PATH)
verification = _load_module("verification", VERIFICATION_PATH)

lna_block = rf_blocks.lna_block
rf_amp_block = rf_blocks.rf_amp_block
buffer_block = rf_blocks.buffer_block
combiner_8to1 = rf_blocks.combiner_8to1
rx_frontend = rf_blocks.rx_frontend
mtp_memory_wrapper = rf_blocks.mtp_memory_wrapper

parse_drc_report = verification.parse_drc_report
parse_lvs_report = verification.parse_lvs_report


def _require_pdk() -> None:
    if pdk is None:
        raise RuntimeError("gf180 PDK not available. Set PDK_ROOT and retry.")


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _read_text(path: Path) -> str:
    try:
        return path.read_text()
    except Exception:
        return ""


def _relax_info_validation() -> None:
    """Allow dict payloads in gdsfactory Info for legacy netlist_data fields."""
    try:
        import gdsfactory.component_layout as component_layout
    except Exception:
        return

    def _setitem(self, key, value):
        self.__dict__[key] = value
        fields_set = getattr(self, "__pydantic_fields_set__", None)
        if fields_set is not None:
            fields_set.add(key)

    component_layout.Info.__setitem__ = _setitem


def _make_stub_netlist(name: str, nodes: list[str]) -> str:
    pins = " ".join(nodes)
    return f".subckt {name} {pins}\n.ends {name}"


def _get_netlist_text(component: Component, design_name: str, nodes: list[str]) -> str:
    netlist_info = component.info.get("netlist") if hasattr(component, "info") else None
    if isinstance(netlist_info, str) and netlist_info.strip():
        return netlist_info
    if hasattr(netlist_info, "generate_netlist"):
        try:
            return netlist_info.generate_netlist()
        except Exception:
            pass
    return _make_stub_netlist(design_name, nodes)


def main() -> int:
    _require_pdk()

    # Ensure gdsfactory sees an active PDK before any @cell wrappers run.
    pdk.activate()
    _relax_info_validation()

    pdk_root = os.environ.get("PDK_ROOT")
    if not pdk_root:
        raise RuntimeError("PDK_ROOT is not set. Export PDK_ROOT and retry.")

    gds_dir = ROOT / "outputs" / "rf_blocks_gds" / "blocks"
    out_dir = ROOT / "outputs" / "rf_blocks_verification"
    _ensure_dir(gds_dir)
    _ensure_dir(out_dir)

    blocks = [
        ("lna_block", lna_block(pdk)),
        ("rf_amp_block", rf_amp_block(pdk)),
        ("buffer_block", buffer_block(pdk)),
        ("combiner_8to1", combiner_8to1(pdk)),
        ("rx_frontend", rx_frontend(pdk)),
        ("mtp_memory_wrapper", mtp_memory_wrapper(pdk)),
    ]

    results: dict[str, dict[str, object]] = {}

    for name, comp in blocks:
        try:
            from gdsfactory.component import name_counters
            name_counters.pop(name, None)
        except Exception:
            pass

        wrapper = Component(name)
        wrapper << comp
        wrapper.name = name
        design_name = name

        nodes = []
        netlist_obj = comp.info.get("netlist") if hasattr(comp, "info") else None
        if netlist_obj is not None and hasattr(netlist_obj, "nodes"):
            nodes = list(netlist_obj.nodes)
        elif hasattr(wrapper, "ports"):
            nodes = list(wrapper.ports.keys())

        netlist_text = _get_netlist_text(comp, design_name, nodes)

        gds_path = gds_dir / f"{name}.gds"
        wrapper.write_gds(str(gds_path))

        pdk.drc_magic(wrapper, design_name, pdk_root=pdk_root, output_file=out_dir)
        lvs_error = None
        try:
            pdk.lvs_netgen(
                wrapper,
                design_name,
                pdk_root=pdk_root,
                netlist=netlist_text,
                output_file_path=out_dir,
            )
        except Exception as exc:
            lvs_error = str(exc)

        drc_report = out_dir / "drc" / design_name / f"{design_name}.rpt"
        lvs_report = out_dir / "lvs" / design_name / f"{design_name}_lvs.rpt"

        drc_summary = parse_drc_report(_read_text(drc_report))
        lvs_summary = parse_lvs_report(_read_text(lvs_report))
        if lvs_error:
            lvs_summary["conclusion"] = f"LVS error: {lvs_error}"

        results[name] = {
            "gds_path": str(gds_path),
            "drc_report": str(drc_report),
            "lvs_report": str(lvs_report),
            "drc": drc_summary,
            "lvs": lvs_summary,
            "design_name": design_name,
        }

        drc_status = "PASS" if drc_summary.get("is_pass") else "FAIL"
        lvs_status = "PASS" if lvs_summary.get("is_pass") else "FAIL"
        print(f"{name}: DRC {drc_status}, LVS {lvs_status}")

    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(results, indent=2))
    print(f"\nSummary saved to: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
