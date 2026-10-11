"""Poll a chat's latest run from Postgres (NO SSE — never pauses the run) and print a
line whenever the stage/status changes or a new RTL file appears.

    python scripts/poll_run.py <chat_id> [design_dir]
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from anoa_api import db  # noqa: E402

db.init()
chat_id = sys.argv[1]
design_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else None
t0 = time.time()
last_pending = last_status = None
last_files: set = set()
last_err_count = 0

while True:
    t = int(time.time() - t0)
    r = db.latest_run_for_chat(chat_id)
    if not r:
        if last_status != "_norun":
            print(f"[{t:5d}s] (no run for this chat yet)", flush=True)
            last_status = "_norun"
        time.sleep(8)
        continue
    status = r.get("status")
    pending = r.get("pending")
    ctx = r.get("ctx") or {}
    dd = design_dir or (Path(ctx["design_dir"]) if ctx.get("design_dir") else None)

    step_changed = pending != last_pending
    files = {p.name for p in (dd / "rtl").glob("*.v")} if dd and (dd / "rtl").exists() else set()
    if step_changed:
        # report the rtl count at each stage boundary (not per file — too noisy)
        cnt = f" — rtl files: {len(files)}" if files else ""
        print(f"[{t:5d}s] STEP: {pending}  (status={status}){cnt}", flush=True)
        last_pending = pending
        last_files = files
    if status != last_status:
        print(f"[{t:5d}s] STATUS: {status}", flush=True)
        last_status = status
    ec = ctx.get("error_count", 0)
    if ec != last_err_count:
        print(f"[{t:5d}s]   sim/correct cycle: error_count={ec}", flush=True)
        last_err_count = ec
    gds = (ctx.get("harden") or {}).get("gds")
    if gds:
        print(f"[{t:5d}s] GDS: {gds}", flush=True)

    if status in ("done", "error"):
        print(f"[{t:5d}s] END: {status} | sim_passed={not ctx.get('simulation_output')} | gds={gds}", flush=True)
        break
    # (status changes are already reported above; don't spam while paused)
    time.sleep(8)
