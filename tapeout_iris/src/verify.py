import json, os, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, "/home/irman/gLayout/notebook/tapeout")
OUT = Path("/home/irman/gLayout/notebook/rf_harvester_tapeout_out")
PDK_ROOT = os.environ["PDK_ROOT"]
MAGICRC = Path(PDK_ROOT)/"gf180mcuD"/"libs.tech"/"magic"/"gf180mcuD.magicrc"

def magic_drc(gds, top, tag):
    tcl = (f"crashbackups stop\ndrc euclidean on\ndrc style drc(full)\n"
           f"gds read {gds}\nload {top} -dereference\nselect top cell\nexpand\n"
           f"drc check\ndrc catchup\n"
           f'puts "COUNT_BEGIN"\nputs [drc list count total]\nputs "COUNT_END"\n'
           f'puts "WHY_BEGIN"\nforeach v [drc listall why] {{ puts $v }}\nputs "WHY_END"\n'
           f"quit -noprompt\n")
    with tempfile.NamedTemporaryFile("w", suffix=".tcl", delete=False) as f:
        f.write(tcl); sp=f.name
    r = subprocess.run(f"magic -rcfile {MAGICRC} -noconsole -dnull < {sp}",
                       shell=True, capture_output=True, text=True, cwd=str(OUT))
    (OUT/f"{tag}_drc.log").write_text(r.stdout+"\n--STDERR--\n"+r.stderr)
    o = r.stdout
    cnt = o.split("COUNT_BEGIN")[1].split("COUNT_END")[0].strip().splitlines()[-1].strip() if "COUNT_BEGIN" in o else "?"
    why = o.split("WHY_BEGIN")[1].split("WHY_END")[0].strip() if "WHY_BEGIN" in o else ""
    return cnt, why

for tag, top in (("D05_Gelochip", "D05_Gelochip"), ("D05_Gelochip_FET", "D05_Gelochip_FET")):
    gds = OUT/f"{top}.gds"
    cnt, why = magic_drc(gds, top, tag)
    print(f"\n=== DRC {top} ({os.path.getsize(gds)/1e6:.2f} MB) ===")
    print("  total violations:", cnt)
    if why: print("  why:\n   " + "\n   ".join(why.splitlines()[:25]))
