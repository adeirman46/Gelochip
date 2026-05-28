"""
gelochip.kaizen.history  —  persistent chat/build history (SQLite).

Every Studio run is saved: the prompt, the streamed pipeline events, the final
answer, and the artifact URLs (code, GDS/PNG, SPICE, AC/transient plots). The UI
lists past sessions and, on click, restores the full last state of that run.

DB lives at ``OUTPUT_DIR/sessions.db`` (git-ignored).
"""
from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

from gelochip.kaizen import config


def _db_path():
    # Chat/build history is a MAIN, persistent database → lives under data/
    # (alongside chroma_db), not under the ephemeral outputs/ tree.
    config.ensure_dirs()
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    return str(config.DATA_DIR / "sessions.db")


def _conn():
    con = sqlite3.connect(_db_path())
    con.row_factory = sqlite3.Row
    return con


def init() -> None:
    with _conn() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id          TEXT PRIMARY KEY,
                created_at  REAL,
                prompt      TEXT,
                answer      TEXT,
                passed      INTEGER,
                circuit     TEXT,
                events_json TEXT,
                state_json  TEXT
            )""")


def _derive_state(events: list[dict], final: dict) -> dict:
    """Reconstruct the restorable UI state from the streamed events (+ final).

    Works for in-progress runs too (called incrementally), so switching chats
    and coming back always shows the latest progress.
    """
    final = final or {}
    test = final.get("test", {}) if isinstance(final, dict) else {}
    state = {"answer": final.get("answer", ""), "code": final.get("code", ""),
             "circuit": final.get("circuit", ""), "passed": bool(test.get("passed")),
             "drc": test.get("drc", {})}
    for ev in events:
        n = ev.get("node")
        if n == "plan" and ev.get("circuit"):
            state["circuit"] = ev["circuit"]
        if n == "generate" and ev.get("code"):
            state["code"] = ev["code"]            # last (= newest) wins
        if n == "test":
            for k in ("png_url", "gds_url", "spice_url", "ac_plot_url", "tran_plot_url"):
                if ev.get(k):
                    state[k] = ev[k]
            if "passed" in ev:
                state["passed"] = bool(ev["passed"])
        if n in ("summarize", "done") and ev.get("msg"):
            state["answer"] = ev["msg"]
    return state


def _compact(events: list[dict]) -> list[dict]:
    """Drop streaming partials (keep the final of each) so the record stays small
    but still restores log / thinking / knowledge / code."""
    out, last_stream = [], {}
    for ev in events:
        if ev.get("streaming"):
            last_stream[ev.get("node")] = ev      # keep only the latest per node
        else:
            out.append(ev)
    out.extend(last_stream.values())
    return out


def save_session(job_id: str, prompt: str, events: list[dict], final: dict) -> None:
    """Upsert a run (id=job_id). Safe to call repeatedly during a run."""
    init()
    state = _derive_state(events, final)
    compact = _compact(events)
    with _conn() as con:
        con.execute(
            "INSERT OR REPLACE INTO sessions "
            "(id, created_at, prompt, answer, passed, circuit, events_json, state_json) "
            "VALUES (?, COALESCE((SELECT created_at FROM sessions WHERE id=?), ?), ?,?,?,?,?,?)",
            (job_id, job_id, time.time(), prompt, state["answer"], int(state["passed"]),
             state["circuit"], json.dumps(compact), json.dumps(state)),
        )


def list_sessions(limit: int = 50) -> list[dict[str, Any]]:
    init()
    with _conn() as con:
        rows = con.execute(
            "SELECT id, created_at, prompt, passed, circuit FROM sessions "
            "ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [{"id": r["id"], "created_at": r["created_at"], "prompt": r["prompt"],
             "passed": bool(r["passed"]), "circuit": r["circuit"]} for r in rows]


def get_session(job_id: str) -> dict[str, Any] | None:
    init()
    with _conn() as con:
        r = con.execute("SELECT * FROM sessions WHERE id=?", (job_id,)).fetchone()
    if not r:
        return None
    return {"id": r["id"], "created_at": r["created_at"], "prompt": r["prompt"],
            "answer": r["answer"], "passed": bool(r["passed"]), "circuit": r["circuit"],
            "events": json.loads(r["events_json"] or "[]"),
            "state": json.loads(r["state_json"] or "{}")}


def delete_session(job_id: str) -> None:
    init()
    with _conn() as con:
        con.execute("DELETE FROM sessions WHERE id=?", (job_id,))
