"""Tail a live backend run's SSE stream as readable one-line events (for monitoring).

    python scripts/watch_run.py <run_id>
"""
import json
import sys
import time
import urllib.request

run_id = sys.argv[1]
url = f"http://localhost:8011/api/runs/{run_id}/stream"
t0 = time.time()
KINDS = ("error", "warning", "success")
while True:
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            for raw in r:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                try:
                    ev = json.loads(line[5:].strip())
                except Exception:
                    continue
                t = int(time.time() - t0)
                ty = ev.get("type")
                if ty == "step":
                    print(f"[{t:5d}s] STEP: {ev.get('node')}", flush=True)
                elif ty == "block" and ev.get("kind") in KINDS:
                    pay = str((ev.get("payload") or [""])[0])[:240].replace("\n", " | ")
                    print(f"[{t:5d}s]   {ev.get('kind')}: {pay}", flush=True)
                elif ty == "end":
                    print(f"[{t:5d}s] END: {ev.get('status')}", flush=True)
                    return_code = 0
                    sys.exit(0)
    except SystemExit:
        raise
    except Exception as e:
        print(f"[{int(time.time()-t0):5d}s] (stream dropped: {e}; reconnecting)", flush=True)
        time.sleep(3)
