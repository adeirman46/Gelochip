"""Layer-aware whole-chip wiring check on the EXACT tapeout GDS.

magic cannot extract the gf180 M2-M3 MIM (it reads the plate via as a short),
which is why LVS runs on the FET view.  KLayout's LayoutToNetlist can do better:
drop the via2 cuts that sit inside CAP_MK and the MIM becomes the open circuit a
capacitor actually is -- so the *whole* chip, caps included, can be checked for
net continuity and for shorts between the five slot pins.
"""
import sys, json
from pathlib import Path
import klayout.db as kdb
sys.path.insert(0, "/home/irman/gLayout/notebook/tapeout")
from slot_adapter import SlotSpec, core_pad_positions

OUT  = Path("/home/irman/gLayout/notebook/rf_harvester_tapeout_out")
GDS  = OUT / "D05_Gelochip.gds"
TGZ  = "/home/irman/gLayout/notebook/D05.def.tgz"
spec = SlotSpec(TGZ, "EH")
NETMAP = {"VSS": "VSS", "RFP": "RFP", "RFN": "RFN", "VOUT": "VOUT", "VCC": "VRECT"}

L = dict(met1=(34,0), via1=(35,0), met2=(36,0), via2=(38,0), met3=(42,0),
         via3=(40,0), met4=(46,0), via4=(41,0), met5=(81,0), capmk=(117,5))

ly = kdb.Layout(); ly.read(str(GDS)); top = ly.top_cell(); dbu = ly.dbu
print("file:", GDS.name, "| top:", top.name, "| cells:", len(list(ly.each_cell())))

l2n = kdb.LayoutToNetlist(kdb.RecursiveShapeIterator(ly, top, []))
l2n.threads = 4
# every layer stays inside the l2n deep-shape store so boolean results can be
# fed straight back into connect()
R = {k: l2n.make_polygon_layer(ly.layer(*v), k)
     for k, v in L.items() if k not in ("capmk", "via2")}
capmk  = l2n.make_polygon_layer(ly.layer(*L["capmk"]), "capmk")
v2_all = l2n.make_polygon_layer(ly.layer(*L["via2"]),  "via2_all")
# Drop WHOLE via2 cuts that belong to a MIM.  A boolean subtraction is wrong
# here: it leaves a sliver wherever a cut straddles the CAP_MK edge, and a
# sliver still touches both plates -- so the cap would still read as a short.
v2_real = v2_all.not_interacting(capmk)
l2n.register(v2_real, "via2_real")
print("CAP_MK regions: %d covering %.1f um^2" % (capmk.count(), capmk.area()*dbu*dbu))
print("via2 cuts: %d total, %d inside CAP_MK (MIM plates), %d real routing vias"
      % (v2_all.count(), v2_all.count()-v2_real.count(), v2_real.count()))

for n in ("met1","met2","met3","met4","met5"):
    l2n.connect(R[n])
l2n.connect(R["met1"], R["via1"]); l2n.connect(R["via1"], R["met2"])
l2n.connect(R["met2"], v2_real);   l2n.connect(v2_real,   R["met3"])
l2n.connect(R["met3"], R["via3"]); l2n.connect(R["via3"], R["met4"])
l2n.connect(R["met4"], R["via4"]); l2n.connect(R["via4"], R["met5"])
l2n.extract_netlist()
nl = l2n.netlist()
circ = nl.circuit_by_name(top.name) or list(nl.each_circuit())[0]
print("extracted nets (wiring only, MIM open):", sum(1 for _ in circ.each_net()))

pads = {k: v[0] for k, v in core_pad_positions(GDS).items()}   # already slot frame
print("\ncore met4 rail pads (slot frame):",
      {k: (round(x,2), round(y,2)) for k,(x,y) in pads.items()})

def probe(layer, x, y):
    n = l2n.probe_net(layer, kdb.DPoint(x, y))
    return n

print("\n%-6s %-24s %-26s %s" % ("PIN", "Metal2 boundary net", "core met4 rail net", "verdict"))
print("-"*90)
seen, ok_all = {}, True
for pin, core_net in NETMAP.items():
    info = spec.pins[pin]
    nb = probe(R["met2"], info["cx"] if info["edge"] in "NS" else 4.0, info["cy"])
    px, py = pads[core_net]
    nc = probe(R["met4"], px, py)
    same = (nb is not None and nc is not None
            and nb.cluster_id == nc.cluster_id)
    dup  = seen.get(nb.cluster_id if nb else None)
    seen[nb.cluster_id if nb else None] = pin
    verdict = ("OK" if same else "NOT CONNECTED")
    if dup: verdict = f"SHORTED to {dup}"
    ok_all &= (same and not dup)
    print("%-6s %-24s %-26s %s" % (
        pin, (nb.expanded_name() if nb else "none"),
        (nc.expanded_name() if nc else "none"), verdict))

print("-"*90)
print("5 slot pins on 5 distinct, correctly-connected nets:", ok_all)

# ---- if anything merged, say exactly which cap plates are involved --------
if not ok_all:
    for pin, core_net in NETMAP.items():
        info = spec.pins[pin]
        n = probe(R["met2"], 4.0, info["cy"])
        print(f"   {pin}: net {n.expanded_name() if n else None}")

# also confirm none of the five pins is shorted to any other pin's net
ids = [n for n in seen if n is not None]
print("distinct boundary net cluster ids:", len(set(ids)), "of", len(NETMAP))
json.dump({"pins_ok": bool(ok_all), "distinct": len(set(ids))},
          open(OUT/"connectivity_report.json","w"), indent=1)
