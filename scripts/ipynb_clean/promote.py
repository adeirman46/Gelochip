import sys, os, json, shutil
from pathlib import Path
os.environ.setdefault('PDK_ROOT', os.path.expanduser('~/pdks'))
sys.path.insert(0, 'src'); sys.path.insert(0, '/home/irman/Gelochip/src/gelochip'); sys.path.insert(0, '/tmp')
import mkclean, patches
from gelochip.kaizen import executor

name = sys.argv[1]
ncells = int(sys.argv[2]) if len(sys.argv) > 2 else 2
write = '--write' in sys.argv
ddir = Path(f"data/circuits/{name}")
nb = ddir / f"{name}.ipynb"
src = patches.apply(name, mkclean.build_source(str(nb), ncells))
clean_path_tmp = f"/tmp/clean_{name}.py"
open(clean_path_tmp, "w").write(src)

r = executor.run_layout_code(src, f"/home/irman/Gelochip/.drcwork/job_{name}", name=name, run_drc=True)
drc = r.get('drc', {})
errs = drc.get('total_errors')
comp_name = None
print(f"[{name}] build_ok={r['ok']} stage={r['stage']} drc_pass={drc.get('is_pass')} errors={errs} skipped={drc.get('skipped')}")
if r['error']:
    print("  build_err:", r['error'].strip().splitlines()[-1][:160])
from collections import Counter
c = Counter(str(e.get('rule', e))[:70] for e in (drc.get('error_details') or []))
for k, v in c.most_common(20):
    print(f"    [{v}] {k}")

clean = r['ok'] and drc.get('is_pass') and errs in (0, None) and not drc.get('skipped')
if clean and write:
    # 1. clean.py
    (ddir / f"{name}_clean.py").write_text(src)
    # 2. preview png
    png = r.get('png_path')
    if png and Path(png).exists():
        shutil.copy(png, ddir / f"{name}_preview.png")
    # 3. eval_result_clean.json (preserve prior structure where possible)
    prev = {}
    p = ddir / "eval_result_clean.json"
    if p.exists():
        try: prev = json.loads(p.read_text())
        except Exception: pass
    out = {
        "component_name": prev.get("component_name", name),
        "source": "kaizen_canonical_from_ipynb",
        "drc": {"is_pass": True, "summary": {"total_errors": 0}},
        "pex": prev.get("pex", {"status": "skipped"}),
        "testbench": prev.get("testbench", {}),
        "area_um2": prev.get("area_um2"),
    }
    p.write_text(json.dumps(out, indent=2))
    print(f"  ✓ PROMOTED {name}: clean.py + preview + eval_result_clean.json")
elif clean:
    print(f"  (clean, not written — pass --write)")
else:
    print(f"  ✗ not clean")
