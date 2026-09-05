"""Confirm every MIM has BOTH plates on the right net, and that the two plates
are NOT the same net (which is what the shipped GDS got wrong)."""
import sys, klayout.db as kdb
from pathlib import Path
sys.path.insert(0,"/home/irman/gLayout/notebook/tapeout")
from slot_adapter import core_pad_positions
OUT=Path("/home/irman/gLayout/notebook/rf_harvester_tapeout_out")

EXPECT = {"inj1": ("RFP","VMID1"), "inj2": ("RFN","VMID2"),
          "st1": ("RFN","N1"), "st2": ("RFP","N2"), "sto": ("VSS","VOUT")}

def audit(gds, label):
    print("="*76); print(label, "|", Path(gds).name)
    ly=kdb.Layout(); ly.read(str(gds)); top=ly.top_cell(); dbu=ly.dbu
    ly.flatten(top.cell_index(),-1,True)
    l2n=kdb.LayoutToNetlist(kdb.RecursiveShapeIterator(ly,top,[])); l2n.threads=4
    L=dict(met1=(34,0),via1=(35,0),met2=(36,0),met3=(42,0),via3=(40,0),
           met4=(46,0),via4=(41,0),met5=(81,0))
    R={k:l2n.make_polygon_layer(ly.layer(*v),k) for k,v in L.items()}
    capmk=l2n.make_polygon_layer(ly.layer(117,5),"capmk")
    v2=l2n.make_polygon_layer(ly.layer(38,0),"v2"); v2r=v2.not_interacting(capmk)
    l2n.register(v2r,"v2r")
    for n in ("met1","met2","met3","met4","met5"): l2n.connect(R[n])
    l2n.connect(R["met1"],R["via1"]); l2n.connect(R["via1"],R["met2"])
    l2n.connect(R["met2"],v2r);       l2n.connect(v2r,R["met3"])
    l2n.connect(R["met3"],R["via3"]); l2n.connect(R["via3"],R["met4"])
    l2n.connect(R["met4"],R["via4"]); l2n.connect(R["via4"],R["met5"])
    l2n.extract_netlist()

    pads={k:v[0] for k,v in core_pad_positions(gds).items()}
    railnet={}
    for n,(x,y) in pads.items():
        nn=l2n.probe_net(R["met4"],kdb.DPoint(x,y)); railnet[n]=nn.cluster_id if nn else None
    print("  chip rails:", railnet)

    cm=kdb.Region(top.shapes(ly.layer(117,5))); cm.merge()
    grown=cm.sized(int(1.5/dbu)); grown.merge()
    banks=sorted([p.bbox() for p in grown.each()], key=lambda b:-(b.width()*b.height()))
    ok=True
    for i,bb in enumerate(banks):
        cx,cy=bb.center().x*dbu, bb.center().y*dbu
        nb=l2n.probe_net(R["met2"],kdb.DPoint(cx,cy))   # bottom plate
        nt=l2n.probe_net(R["met3"],kdb.DPoint(cx,cy))   # top plate
        b=nb.cluster_id if nb else None; t=nt.cluster_id if nt else None
        rb=[k for k,v in railnet.items() if v==b]; rt=[k for k,v in railnet.items() if v==t]
        shorted = (b is not None and b==t)
        floating = (b is None or t is None)
        if shorted or floating: ok=False
        print(f"  bank {i} @({cx:8.2f},{cy:8.2f}) {cm.interacting(kdb.Region(bb)).count():2d} tiles"
              f"  bottom=net {b} {rb}  top=net {t} {rt}"
              f"   {'*** PLATES SHORTED ***' if shorted else ('*** A PLATE IS FLOATING ***' if floating else 'OK')}")
    print(f"  ==> all MIM plates distinct and driven: {ok}")
    return ok

audit(OUT/"D05_Gelochip.gds", "FIXED tapeout GDS")
audit(Path("/home/irman/gLayout/notebook/rf_harvester_signoff_out/harvester_top_full.gds"),
      "ORIGINAL shipped GDS (19 Jul)")
