import os, sys, io, contextlib
from pathlib import Path
OUT = Path("/home/irman/gLayout/notebook/rf_harvester_tapeout_out")
PDK_ROOT = os.environ["PDK_ROOT"]
from glayout import gf180

TOP = "D05_Gelochip_FET"
gds = OUT / f"{TOP}.gds"
net = OUT / f"{TOP}_source.spice"
buf = io.StringIO()
try:
    with contextlib.redirect_stdout(buf):
        gf180.lvs_netgen(str(gds), TOP, pdk_root=PDK_ROOT, netlist=str(net))
except Exception as e:
    buf.write(f"\nEXC {type(e).__name__}: {e}")
out = buf.getvalue()
(OUT / f"{TOP}_lvs.log").write_text(out)
ok = "match uniquely" in out
print(f"LVS {TOP}: {'MATCH' if ok else 'CHECK LOG'}")
tail = [l for l in out.splitlines() if l.strip()]
print("\n".join(tail[-40:]))
