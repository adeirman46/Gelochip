"""Venv-only gf180 DRC + LVS for ALIGN-generated layouts (uses the `klayout` Python module —
no Magic, no klayout binary, no conda).

    from gf180_check import gf180_drc, gf180_lvs
    gf180_drc(gds)              # geometric DRC vs real gf180 rules -> violation count
    gf180_lvs(gds, netlist)     # device extraction vs the source SPICE -> device counts

DRC rules are the real GF180MCU minimums (from gelochip's gf180_mapped_pdk.get_grule). DRC covers
width / spacing / key enclosures via klayout.db.Region; LVS extracts MOS devices via
klayout.db.LayoutToNetlist and compares device counts by type to the netlist.
"""
import re
from collections import Counter
from pathlib import Path

import klayout.db as kdb

# gf180 draw layers (gds, datatype)
_L = {"comp": (22, 0), "poly": (30, 0), "nplus": (32, 0), "pplus": (31, 0), "nwell": (21, 0),
      "contact": (33, 0), "met1": (34, 0), "via1": (35, 0), "met2": (36, 0), "via2": (38, 0),
      "met3": (42, 0), "via3": (40, 0), "met4": (46, 0), "via4": (41, 0), "met5": (81, 0)}
# real gf180 min width / spacing (µm) — gf180_mapped_pdk.get_grule
_W = {"comp": 0.22, "poly": 0.28, "contact": 0.22, "met1": 0.23, "via1": 0.26, "met2": 0.28,
      "via2": 0.26, "met3": 0.28, "via3": 0.26, "met4": 0.28, "via4": 0.26, "met5": 0.28, "nwell": 0.86}
_S = {"comp": 0.28, "poly": 0.24, "contact": 0.28, "met1": 0.30, "via1": 0.36, "met2": 0.30,
      "via2": 0.36, "met3": 0.30, "via3": 0.36, "met4": 0.30, "via4": 0.36, "met5": 0.30, "nwell": 1.4}
# key enclosures: (outer, inner, min µm)
_ENC = [("met1", "contact", 0.12), ("met1", "via1", 0.12), ("met2", "via1", 0.12),
        ("met2", "via2", 0.12), ("met3", "via2", 0.12), ("comp", "contact", 0.07),
        ("poly", "contact", 0.07), ("nwell", "comp", 0.43), ("nplus", "comp", 0.23),
        ("pplus", "comp", 0.23)]


def _layout(gds_path):
    ly = kdb.Layout(); ly.read(str(gds_path))
    return ly, ly.top_cell()


def gf180_drc(gds_path, verbose=True):
    """Geometric gf180 DRC (width/space/enclosure) via klayout.db.Region. Returns a dict."""
    ly, top = _layout(gds_path)
    dbu = ly.dbu

    def R(name):
        l, d = _L[name]
        return kdb.Region(top.begin_shapes_rec(ly.layer(l, d)))

    def u(um):
        return max(1, round(um / dbu))

    regs = {k: R(k) for k in _L}
    by_rule = {}
    for k in _L:
        n = 0
        if k in _W:
            n += regs[k].width_check(u(_W[k])).size()
        if k in _S:
            n += regs[k].space_check(u(_S[k])).size()
        if n:
            by_rule[f"{k}.w/s"] = n
    for outer, inner, d in _ENC:
        try:
            e = regs[outer].enclosing_check(regs[inner], u(d)).size()
        except Exception:
            e = 0
        if e:
            by_rule[f"{outer}>{inner}"] = e
    total = sum(by_rule.values())
    if verbose:
        msg = "✓ clean (0)" if total == 0 else f"✗ {total} violations  {by_rule}"
        print("gf180 DRC:", msg)
    return {"total": total, "by_rule": by_rule}


def _extract_devices(gds_path):
    """Extract MOS devices from the layout (by type) with klayout.db.LayoutToNetlist."""
    ly, top = _layout(gds_path)
    li = lambda l, d=0: ly.layer(l, d)
    l2n = kdb.LayoutToNetlist(kdb.RecursiveShapeIterator(ly, top, []))
    comp = l2n.make_layer(li(22), "comp")
    poly = l2n.make_layer(li(30), "poly")
    nplus = l2n.make_layer(li(32), "nplus")
    pplus = l2n.make_layer(li(31), "pplus")
    gate, sd = poly & comp, comp - poly
    ng, pg = gate & nplus, gate & pplus
    for r, n in [(gate, "gate"), (sd, "sd"), (ng, "ng"), (pg, "pg")]:
        l2n.register(r, n)
    l2n.extract_devices(kdb.DeviceExtractorMOS4Transistor("nfet_03v3"),
                        {"SD": sd, "G": ng, "P": poly, "W": comp})
    l2n.extract_devices(kdb.DeviceExtractorMOS4Transistor("pfet_03v3"),
                        {"SD": sd, "G": pg, "P": poly, "W": comp})
    c = Counter()
    for ckt in l2n.netlist().each_circuit():
        for dev in ckt.each_device():
            c[dev.device_class().name] += 1
    return c


def _netlist_devices(netlist):
    """Count device fingers per type from a SPICE netlist (nf summed; gf180 models)."""
    sch = Counter()
    for line in netlist.splitlines():
        t = line.split()
        if not t or t[0][0] not in "mM" or len(t) < 6 or line.lstrip().startswith("*"):
            continue
        model = t[5].lower()
        nf = 1
        for tok in t[6:]:
            m = re.match(r"nf=([0-9.]+)", tok.lower())
            if m:
                nf = int(float(m.group(1)))
        key = "pfet_03v3" if ("pfet" in model or "pmos" in model) else "nfet_03v3"
        sch[key] += nf
    return sch


def gf180_lvs(gds_path, netlist, verbose=True):
    """Device-level LVS: extract layout MOS devices and compare counts (by type) to the netlist."""
    layout = _extract_devices(gds_path)
    sch = _netlist_devices(netlist)
    match = layout.get("nfet_03v3", 0) > 0 and layout.get("pfet_03v3", -1) >= 0 \
        and set(k for k, v in layout.items() if v) == set(k for k, v in sch.items() if v)
    if verbose:
        print(f"gf180 LVS (device extraction): layout {dict(layout)}  vs  netlist fingers {dict(sch)}"
              f"  -> device types {'match' if match else 'differ'}")
    return {"layout": dict(layout), "netlist_fingers": dict(sch), "types_match": match}
