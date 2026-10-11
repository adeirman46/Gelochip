"""Tiny background-job + SSE bus for the slow tabs (Create-IP hardening, batch builds).

Same replay-friendly append-only log as the chat RunBus, but generic: a job is just a
function ``fn(bus)`` run on a daemon thread; viewers stream its log lines (and a final
status) over SSE, reconnect-safe (the whole backlog replays from index 0).
"""
from __future__ import annotations

import json
import threading
import uuid


class JobBus:
    def __init__(self) -> None:
        self.log: list[dict] = []
        self._lock = threading.Lock()
        self.done = False
        self.status = "running"
        self.result: dict = {}

    def emit(self, kind: str, **data) -> None:
        with self._lock:
            self.log.append({"type": kind, **data})

    def line(self, text: str) -> None:
        self.emit("log", text=text)

    def finish(self, status: str, **result) -> None:
        self.status = status
        self.result = result
        self.done = True
        self.emit("end", status=status, **result)

    def since(self, idx: int):
        with self._lock:
            return self.log[idx:], len(self.log)


_JOBS: dict[str, JobBus] = {}


def start_job(fn) -> str:
    """Run ``fn(bus)`` on a daemon thread; return the job id. On exception the job ends
    with status='error' and the message — a failure never crashes the server."""
    jid = "job_" + uuid.uuid4().hex[:12]
    bus = JobBus()
    _JOBS[jid] = bus

    def _run():
        try:
            fn(bus)
            if not bus.done:
                bus.finish("done")
        except Exception as exc:  # noqa: BLE001
            bus.line(f"job crashed: {exc}")
            bus.finish("error", error=str(exc))

    threading.Thread(target=_run, daemon=True).start()
    return jid


def get_job(jid: str) -> JobBus | None:
    return _JOBS.get(jid)


def sse(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"
