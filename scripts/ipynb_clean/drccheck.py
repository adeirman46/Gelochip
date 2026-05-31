"""DRC-check one or more circuits from their ipynb (with patches). Usage:
  .venv/bin/python scripts/ipynb_clean/drccheck.py <name> [<name> ...]
"""
import sys, os
os.environ.setdefault('PDK_ROOT', os.path.expanduser('~/pdks'))
sys.path.insert(0, 'src'); sys.path.insert(0, os.path.abspath('src/gelochip'))
sys.path.insert(0, os.path.dirname(__file__))
import mkclean, patches
from gelochip.kaizen import executor
from collections import Counter

def rep(s):
    return dict(Counter(str(e.get('rule', e)).split('<')[0][:24] for e in s))

for n in sys.argv[1:]:
    try:
        src = mkclean.build_source(f'data/circuits/{n}/{n}.ipynb', 2)
        if n in patches.PATCHES:
            src = patches.apply(n, src)
        r = executor.run_layout_code(src, f'/home/irman/Gelochip/.drcwork/job_chk_{n}', name=n.upper()[:18], run_drc=True)
        if not r['ok']:
            print(f"RESULT {n}: BUILD_FAIL {(r['error'] or '').strip().splitlines()[-1][:70]}", flush=True)
            continue
        print(f"RESULT {n}: err={r['drc'].get('total_errors')} :: {rep(r['drc'].get('error_details') or [])}", flush=True)
    except Exception as e:
        print(f"RESULT {n}: EXC {str(e)[:80]}", flush=True)
