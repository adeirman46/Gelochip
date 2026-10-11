"""Headless validation run: drive the real runner end-to-end and log every step.

Usage:  .venv/bin/python scripts/validate_run.py "riscv 32 bit pipelined cpu"

Prints one line per pipeline event (step starts, warnings, errors) and a final
verdict, so a long run can be tailed from a log file.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from anoa_api import db, runner  # noqa: E402

# Persist to the SAME Postgres the web UI reads, so a headless validation run shows up
# as a real chat in the sidebar (without this, db falls back to an in-memory store and
# the chat/run never reach the DB).
db.init()

import os
prompt = sys.argv[1] if len(sys.argv) > 1 else "riscv 32 bit pipelined cpu like picorv32"
harden = os.getenv("HARDEN", "0") in ("1", "true", "yes")
use_web = os.getenv("USE_WEB", "0") in ("1", "true", "yes")
deadline = int(os.getenv("DEADLINE", "21600"))   # default 6h
chat = db.create_chat(f"validation: {prompt[:40]}")
msg = db.add_message(chat["id"], "user", prompt)
rec = runner.start_run(chat_id=chat["id"], message_id=msg["id"], prompt=prompt,
                       opts={"use_web": use_web, "run_harden": harden, "deep_steps": True,
                             "clock_period": float(os.getenv("CLOCK_PERIOD", "24.0")),
                             "die_um": float(os.getenv("DIE_UM", "600.0")),
                             "core_util": int(os.getenv("CORE_UTIL", "25"))})
print(f"harden={harden} use_web={use_web} deadline={deadline}s", flush=True)
rid = rec["id"]
print(f"run id: {rid}  design_dir: {rec.get('design_dir')}", flush=True)

bus = runner.get_bus(rid)
idx = 0
t0 = time.time()
while True:
    events, idx = bus.since(idx)
    for ev in events:
        t = int(time.time() - t0)
        kind = ev.get("type")
        if kind == "step":
            print(f"[{t:5d}s] ── STEP: {ev['node']}", flush=True)
        elif kind == "block":
            k = ev.get("kind")
            if k in ("error", "warning", "success", "info"):
                pay = str(ev.get("payload", [""])[0])[:300].replace("\n", " | ")
                print(f"[{t:5d}s]    {k}: {pay}", flush=True)
        elif kind == "end":
            print(f"[{t:5d}s] ══ END: {ev.get('status')}", flush=True)
    if bus.done:
        break
    if time.time() - t0 > deadline:
        print("timeout — requesting pause", flush=True)
        runner.request_pause(rid)
        break
    time.sleep(5)

run = db.get_run(rid)
ctx = run.get("ctx") or {}
harden_info = ctx.get("harden") or {}
print("\n=== VERDICT ===", flush=True)
print("status:", run.get("status"))
print("top:", ctx.get("top_module_name"))
print("sim error count:", ctx.get("error_count"))
print("sim output empty (=passed):", not ctx.get("simulation_output"))
print("GDS:", harden_info.get("gds"))
print("harden rc:", harden_info.get("rc"))
