"""Chat + run persistence (Postgres) — so a prompt and its run state survive reloads
('not vanished'). Lives in the same `anoachip` database as the knowledge store, in
its own tables: `chat`, `message`, `run`. Defensive: if Postgres is down, the API still
serves with an in-memory fallback so the UI works for a single session.

The full run transcript is stored as JSONB on the `run` row, so reopening a chat
re-hydrates the entire conversation + agent transcript exactly as it was.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

_DB_URL = os.getenv("ANOA_DATABASE_URL",
                    "postgresql+psycopg://anoa:anoa@localhost:5433/anoachip")

_engine = None
_ready = False


def _now():
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def init() -> bool:
    """Create the engine + tables. Returns True if Postgres-backed, False if it fell
    back to in-memory (DB unavailable)."""
    global _engine, _ready
    if _ready:
        return True
    try:
        from sqlalchemy import (Column, DateTime, MetaData, String, Table, Text,
                                create_engine)
        from sqlalchemy.dialects.postgresql import JSONB
        eng = create_engine(_DB_URL, pool_pre_ping=True, future=True)
        md = MetaData()
        # a PROJECT groups many chats (each chat = an IP / design conversation)
        Table("project", md,
              Column("id", String, primary_key=True),
              Column("name", String),
              Column("created_at", DateTime(timezone=True)),
              Column("updated_at", DateTime(timezone=True)))
        Table("chat", md,
              Column("id", String, primary_key=True),
              Column("title", String),
              Column("project_id", String, index=True),
              Column("created_at", DateTime(timezone=True)),
              Column("updated_at", DateTime(timezone=True)))
        Table("message", md,
              Column("id", String, primary_key=True),
              Column("chat_id", String, index=True),
              Column("role", String),                 # user | assistant | system
              Column("content", Text),
              Column("files", JSONB),                  # [{name, object_key, kind}]
              Column("created_at", DateTime(timezone=True)))
        Table("run", md,
              Column("id", String, primary_key=True),
              Column("chat_id", String, index=True),
              Column("message_id", String),
              Column("status", String),                # running | paused | done | error
              Column("query", Text),
              Column("design_dir", String),
              Column("ctx", JSONB),
              Column("transcript", JSONB),             # full step-by-step transcript
              Column("queue", JSONB),                  # remaining steps (for resume)
              Column("pending", String),               # last-run step (for resume)
              Column("created_at", DateTime(timezone=True)),
              Column("updated_at", DateTime(timezone=True)))
        md.create_all(eng)
        # add resume columns to a pre-existing run table (create_all won't ALTER)
        from sqlalchemy import text as sqltext
        with eng.begin() as conn:
            conn.execute(sqltext("ALTER TABLE run ADD COLUMN IF NOT EXISTS queue JSONB"))
            conn.execute(sqltext("ALTER TABLE run ADD COLUMN IF NOT EXISTS pending VARCHAR"))
            conn.execute(sqltext("ALTER TABLE chat ADD COLUMN IF NOT EXISTS project_id VARCHAR"))
        _engine, _ready = eng, True
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[db] Postgres unavailable ({exc}); using in-memory store.")
        _engine, _ready = None, False
        return False


# --- in-memory fallback (single-process) -----------------------------------
_mem = {"project": {}, "chat": {}, "message": [], "run": {}}


# --- projects (group many chats / IPs) --------------------------------------
def create_project(name: str) -> dict:
    pid = new_id("proj")
    row = {"id": pid, "name": (name or "New project")[:200],
           "created_at": _now(), "updated_at": _now()}
    if _engine:
        _q("INSERT INTO project (id,name,created_at,updated_at) "
           "VALUES (:id,:name,:created_at,:updated_at)", **row)
    else:
        _mem["project"][pid] = row
    return _iso(row)


def list_projects() -> list[dict]:
    if _engine:
        rows = _q("SELECT p.id, p.name, p.created_at, p.updated_at, "
                  "COUNT(c.id) AS chats FROM project p "
                  "LEFT JOIN chat c ON c.project_id = p.id "
                  "GROUP BY p.id ORDER BY p.updated_at DESC NULLS LAST").mappings().all()
        return [_iso(dict(r)) for r in rows]
    out = []
    for p in sorted(_mem["project"].values(), key=lambda x: x["updated_at"], reverse=True):
        chats = sum(1 for c in _mem["chat"].values() if c.get("project_id") == p["id"])
        out.append(_iso({**p, "chats": chats}))
    return out


def rename_project(project_id: str, name: str) -> None:
    if _engine:
        _q("UPDATE project SET name=:n, updated_at=:t WHERE id=:id",
           n=name[:200], t=_now(), id=project_id)
    elif project_id in _mem["project"]:
        _mem["project"][project_id].update(name=name[:200], updated_at=_now())


def delete_project(project_id: str, *, cascade: bool = False) -> None:
    """Delete a project. cascade=True deletes its chats (+designs/knowledge); otherwise the
    chats are just unfiled (project_id cleared) so nothing is lost."""
    if cascade:
        for c in list_chats(project_id=project_id):
            delete_chat(c["id"])
    if _engine:
        _q("UPDATE chat SET project_id=NULL WHERE project_id=:id", id=project_id)
        _q("DELETE FROM project WHERE id=:id", id=project_id)
    else:
        for c in _mem["chat"].values():
            if c.get("project_id") == project_id:
                c["project_id"] = None
        _mem["project"].pop(project_id, None)


def move_chat(chat_id: str, project_id: str | None) -> None:
    if _engine:
        _q("UPDATE chat SET project_id=:p, updated_at=:t WHERE id=:id",
           p=project_id, t=_now(), id=chat_id)
    elif chat_id in _mem["chat"]:
        _mem["chat"][chat_id]["project_id"] = project_id


def _q(sql, **params):
    from sqlalchemy import text as sqltext
    with _engine.begin() as conn:
        return conn.execute(sqltext(sql), params)


# --- chats ------------------------------------------------------------------
def create_chat(title: str, project_id: str | None = None) -> dict:
    cid = new_id("chat")
    row = {"id": cid, "title": title[:200] or "New chat", "project_id": project_id,
           "created_at": _now(), "updated_at": _now()}
    if _engine:
        _q("INSERT INTO chat (id,title,project_id,created_at,updated_at) "
           "VALUES (:id,:title,:project_id,:created_at,:updated_at)", **row)
    else:
        _mem["chat"][cid] = row
    return _iso(row)


def list_chats(project_id: str | None = None) -> list[dict]:
    if _engine:
        if project_id is not None:
            rows = _q("SELECT id,title,project_id,created_at,updated_at FROM chat "
                      "WHERE project_id=:p ORDER BY updated_at DESC NULLS LAST",
                      p=project_id).mappings().all()
        else:
            rows = _q("SELECT id,title,project_id,created_at,updated_at FROM chat "
                      "ORDER BY updated_at DESC NULLS LAST").mappings().all()
        return [_iso(dict(r)) for r in rows]
    chats = [c for c in _mem["chat"].values()
             if project_id is None or c.get("project_id") == project_id]
    return [_iso(c) for c in sorted(chats, key=lambda c: c["updated_at"], reverse=True)]


def get_chat(chat_id: str) -> dict | None:
    if _engine:
        r = _q("SELECT id,title,project_id,created_at,updated_at FROM chat WHERE id=:id",
               id=chat_id).mappings().first()
        return _iso(dict(r)) if r else None
    return _iso(_mem["chat"].get(chat_id)) if chat_id in _mem["chat"] else None


def touch_chat(chat_id: str, title: str | None = None) -> None:
    if _engine:
        if title:
            _q("UPDATE chat SET updated_at=:t, title=:ti WHERE id=:id",
               t=_now(), ti=title[:200], id=chat_id)
        else:
            _q("UPDATE chat SET updated_at=:t WHERE id=:id", t=_now(), id=chat_id)
    elif chat_id in _mem["chat"]:
        _mem["chat"][chat_id]["updated_at"] = _now()
        if title:
            _mem["chat"][chat_id]["title"] = title[:200]


def delete_chat(chat_id: str) -> None:
    """Delete a chat AND most of what it produced: its messages/runs (Postgres), the
    design's knowledge rows + MinIO blobs (object storage), and its on-disk workspace.
    The learned error→fix LESSONS (kind='fix') are PRESERVED in the knowledge store —
    they're cross-design lessons, not chat data, so deleting the chat must not lose them."""
    designs, dirs = _chat_designs(chat_id)
    if _engine:
        _q("DELETE FROM run WHERE chat_id=:id", id=chat_id)
        _q("DELETE FROM message WHERE chat_id=:id", id=chat_id)
        _q("DELETE FROM chat WHERE id=:id", id=chat_id)
    else:
        _mem["chat"].pop(chat_id, None)
        _mem["message"] = [m for m in _mem["message"] if m["chat_id"] != chat_id]
        _mem["run"] = {k: v for k, v in _mem["run"].items() if v["chat_id"] != chat_id}
    # NEVER delete a workspace a SURVIVING chat's run still points at. Legacy chats with the
    # same prompt SHARED output/<slug> (dirs are chat-unique only since the chat_id suffix),
    # so deleting one chat used to vanish the other's artifacts/images (user-hit bug).
    dirs = {d for d in dirs if not _dir_still_referenced(d)}
    designs = {n for n in designs if not _design_still_referenced(n)}
    _cleanup_designs(designs, dirs)


def _dir_still_referenced(design_dir: str) -> bool:
    """True if any surviving run (whatever chat) still points at this design_dir."""
    try:
        if _engine:
            row = _q("SELECT COUNT(*) AS n FROM run WHERE design_dir=:dd",
                     dd=str(design_dir)).mappings().first()
            return bool(row and row["n"])
        return any(r.get("design_dir") == str(design_dir) for r in _mem["run"].values())
    except Exception:  # noqa: BLE001
        return True                   # unsure → keep the files; never destroy on doubt


def _design_still_referenced(design_name: str) -> bool:
    """True if a surviving run's design_dir basename equals this design name (knowledge
    rows/blobs are keyed by that name, so they must outlive the other chat too)."""
    try:
        if _engine:
            row = _q("SELECT COUNT(*) AS n FROM run WHERE design_dir LIKE :pat",
                     pat=f"%/{design_name}").mappings().first()
            return bool(row and row["n"])
        return any(str(r.get("design_dir", "")).endswith("/" + design_name)
                   for r in _mem["run"].values())
    except Exception:  # noqa: BLE001
        return True


def _chat_designs(chat_id: str):
    """Collect the (design-name, design-dir) of every run in this chat."""
    from pathlib import Path
    designs, dirs = set(), set()
    if _engine:
        rows = _q("SELECT design_dir FROM run WHERE chat_id=:id", id=chat_id).mappings().all()
    else:
        rows = [r for r in _mem["run"].values() if r["chat_id"] == chat_id]
    for r in rows:
        dd = r.get("design_dir")
        if dd:
            dirs.add(dd)
            designs.add(Path(dd).name)
    return designs, dirs


def _cleanup_designs(designs: set, dirs: set) -> None:
    """Remove each design's knowledge rows + MinIO blobs, and its output/ workspace."""
    if designs:
        try:
            import sys
            from pathlib import Path
            src = str(Path(__file__).resolve().parents[2] / "src" / "anoa_chip")
            if src not in sys.path:
                sys.path.insert(0, src)
            from memory_store import get_memory
            mem = get_memory()
            for d in designs:
                # delete this design's rows + blobs, but KEEP kind='fix' lessons — those are
                # durable, cross-design knowledge that must survive the chat being deleted.
                mem.delete_where(design=d, exclude_kinds=["fix"])
        except Exception as exc:  # noqa: BLE001
            print(f"[db] knowledge cleanup skipped: {exc}")
    import shutil
    from pathlib import Path
    for dd in dirs:
        try:
            p = Path(dd).resolve()
            if "output" in p.parts and p.exists():    # only ever under output/
                shutil.rmtree(p)
        except Exception:  # noqa: BLE001
            pass


# --- messages ---------------------------------------------------------------
def add_message(chat_id: str, role: str, content: str, files: list | None = None) -> dict:
    mid = new_id("msg")
    row = {"id": mid, "chat_id": chat_id, "role": role, "content": content or "",
           "files": files or [], "created_at": _now()}
    if _engine:
        import json
        _q("INSERT INTO message (id,chat_id,role,content,files,created_at) "
           "VALUES (:id,:chat_id,:role,:content,CAST(:files AS JSONB),:created_at)",
           **{**row, "files": json.dumps(row["files"])})
    else:
        _mem["message"].append(row)
    touch_chat(chat_id)
    return _iso(row)


def get_messages(chat_id: str) -> list[dict]:
    if _engine:
        rows = _q("SELECT id,chat_id,role,content,files,created_at FROM message "
                  "WHERE chat_id=:id ORDER BY created_at", id=chat_id).mappings().all()
        return [_iso(dict(r)) for r in rows]
    return [_iso(m) for m in _mem["message"] if m["chat_id"] == chat_id]


def update_message(message_id: str, content: str) -> None:
    """Edit a message's text in place (e.g. fix a typo'd prompt)."""
    if _engine:
        _q("UPDATE message SET content=:c WHERE id=:id", id=message_id, c=content or "")
    else:
        for m in _mem["message"]:
            if m["id"] == message_id:
                m["content"] = content or ""


def delete_runs_for_message(message_id: str) -> None:
    """Delete a message's run ROWS only (no design cleanup) — used when re-running an edited
    message so the new run replaces the old, while the design folder is kept for the re-run."""
    if _engine:
        _q("DELETE FROM run WHERE message_id=:id", id=message_id)
    else:
        _mem["run"] = {k: v for k, v in _mem["run"].items() if v.get("message_id") != message_id}


def delete_message(message_id: str) -> None:
    """Delete ONE message and its run(s). A run's design_dir is cleaned up ONLY if no OTHER run
    still references it (so deleting a continuation message never wipes the original design a prior
    message still owns). kind='fix' knowledge lessons are preserved (see _cleanup_designs)."""
    if _engine:
        gone = _q("SELECT DISTINCT design_dir FROM run WHERE message_id=:id",
                  id=message_id).mappings().all()
        gone_dirs = {r["design_dir"] for r in gone if r.get("design_dir")}
        _q("DELETE FROM run WHERE message_id=:id", id=message_id)
        _q("DELETE FROM message WHERE id=:id", id=message_id)
        still = {r[0] for r in _q("SELECT DISTINCT design_dir FROM run WHERE design_dir IS NOT NULL")
                 .all()}
        orphan = gone_dirs - still
    else:
        gone_dirs = {v["design_dir"] for v in _mem["run"].values()
                     if v.get("message_id") == message_id and v.get("design_dir")}
        _mem["run"] = {k: v for k, v in _mem["run"].items() if v.get("message_id") != message_id}
        _mem["message"] = [m for m in _mem["message"] if m["id"] != message_id]
        still = {v.get("design_dir") for v in _mem["run"].values() if v.get("design_dir")}
        orphan = gone_dirs - still
    if orphan:
        from pathlib import Path
        _cleanup_designs({Path(d).name for d in orphan}, orphan)


def clear_control_messages(chat_id: str) -> None:
    """Drop stale run-control prompts (the '⏸ Paused…' / '⚠️ A step crashed…' assistant
    bubbles) from a chat. Called when a NEW run starts: the user has clearly acted on the
    prompt, so the old 'Say continue' bubble is obsolete and must not linger in the thread."""
    if _engine:
        _q("DELETE FROM message WHERE chat_id=:id AND role='assistant' "
           "AND (content LIKE '⏸ Paused%' OR content LIKE '⚠️ A step crashed%')", id=chat_id)
    else:
        _mem["message"] = [
            m for m in _mem["message"]
            if not (m["chat_id"] == chat_id and m["role"] == "assistant"
                    and m["content"].startswith(("⏸ Paused", "⚠️ A step crashed")))]


# --- runs (persist live ctx + transcript) -----------------------------------
def reap_stale_runs() -> int:
    """Mark every run still 'running'/'paused' as 'error' at BACKEND STARTUP. Run threads die
    with the process (uvicorn --reload restarts on every source edit), but their DB rows kept
    saying 'running' forever — so the UI showed an eternal spinner with an empty transcript and
    pinned the chat switcher to a ghost run. A run that is alive right now cannot predate this
    process, so at import time every 'running' row is by definition an orphan. Returns count."""
    if _engine:
        n = _q("SELECT COUNT(*) FROM run WHERE status IN ('running','paused')").scalar() or 0
        if n:
            _q("UPDATE run SET status='error', updated_at=:t "
               "WHERE status IN ('running','paused')", t=_now())
        return int(n)
    n = 0
    for r in _mem["run"].values():
        if r.get("status") in ("running", "paused"):
            r["status"] = "error"
            n += 1
    return n


def create_run(chat_id: str, message_id: str, query: str, design_dir: str) -> dict:
    rid = new_id("run")
    row = {"id": rid, "chat_id": chat_id, "message_id": message_id, "status": "running",
           "query": query, "design_dir": design_dir, "ctx": {}, "transcript": [],
           "created_at": _now(), "updated_at": _now()}
    if _engine:
        import json
        _q("INSERT INTO run (id,chat_id,message_id,status,query,design_dir,ctx,transcript,"
           "created_at,updated_at) VALUES (:id,:chat_id,:message_id,:status,:query,"
           ":design_dir,CAST(:ctx AS JSONB),CAST(:transcript AS JSONB),:created_at,:updated_at)",
           **{**row, "ctx": json.dumps({}), "transcript": json.dumps([])})
    else:
        _mem["run"][rid] = row
    return _iso(row)


def update_run(run_id: str, *, status=None, ctx=None, transcript=None,
               queue=None, pending=None) -> None:
    if _engine:
        import json
        sets, params = ["updated_at=:t"], {"t": _now(), "id": run_id}
        if status is not None:
            sets.append("status=:s")
            params["s"] = status
        if ctx is not None:
            sets.append("ctx=CAST(:c AS JSONB)")
            params["c"] = json.dumps(_jsonable(ctx), allow_nan=False)
        if transcript is not None:
            sets.append("transcript=CAST(:tr AS JSONB)")
            params["tr"] = json.dumps(_jsonable(transcript), allow_nan=False)
        if queue is not None:
            sets.append("queue=CAST(:q AS JSONB)")
            params["q"] = json.dumps(list(queue))
        if pending is not None:
            sets.append("pending=:p")
            params["p"] = pending
        _q(f"UPDATE run SET {', '.join(sets)} WHERE id=:id", **params)
    elif run_id in _mem["run"]:
        r = _mem["run"][run_id]
        if status is not None:
            r["status"] = status
        if ctx is not None:
            r["ctx"] = _jsonable(ctx)
        if transcript is not None:
            r["transcript"] = _jsonable(transcript)
        if queue is not None:
            r["queue"] = list(queue)
        if pending is not None:
            r["pending"] = pending
        r["updated_at"] = _now()


def get_run(run_id: str) -> dict | None:
    if _engine:
        r = _q("SELECT * FROM run WHERE id=:id", id=run_id).mappings().first()
        return _iso(dict(r)) if r else None
    return _iso(_mem["run"].get(run_id)) if run_id in _mem["run"] else None


def runs_for_chat(chat_id: str) -> list[dict]:
    """All runs of a chat (id, message_id, status, transcript) in order — so the UI can
    show each user turn's own assistant response (proper chat alternation)."""
    if _engine:
        rows = _q("SELECT id, message_id, status, transcript FROM run WHERE chat_id=:id "
                  "ORDER BY created_at", id=chat_id).mappings().all()
        return [_iso(dict(r)) for r in rows]
    return [_iso(r) for r in sorted((x for x in _mem["run"].values() if x["chat_id"] == chat_id),
                                    key=lambda r: r["created_at"])]


def latest_run_for_chat(chat_id: str) -> dict | None:
    if _engine:
        r = _q("SELECT * FROM run WHERE chat_id=:id ORDER BY created_at DESC LIMIT 1",
               id=chat_id).mappings().first()
        return _iso(dict(r)) if r else None
    runs = [r for r in _mem["run"].values() if r["chat_id"] == chat_id]
    return _iso(sorted(runs, key=lambda r: r["created_at"])[-1]) if runs else None


def designs_for_chat(chat_id: str) -> list[dict]:
    """Newest-first runs of a chat that have a design_dir, with their query + FULL saved ctx — so a
    follow-up can pick the most recent BUILT design and resume its exact state (not the latest run,
    which might be an empty re-plan)."""
    if _engine:
        rows = _q("SELECT id, query, design_dir, ctx FROM run WHERE chat_id=:id "
                  "AND design_dir IS NOT NULL ORDER BY created_at DESC", id=chat_id).mappings().all()
        return [dict(r) for r in rows]
    return [dict(r) for r in sorted((x for x in _mem["run"].values() if x["chat_id"] == chat_id),
                                    key=lambda r: r["created_at"], reverse=True)]


# --- helpers ----------------------------------------------------------------
def _iso(row: dict) -> dict:
    out = dict(row)
    for k in ("created_at", "updated_at"):
        v = out.get(k)
        if isinstance(v, datetime):
            out[k] = v.isoformat()
    return out


def _jsonable(obj):
    """Make a value safe for Postgres JSONB. Recurse FIRST so non-finite floats are caught:
    LibreLane signoff metrics contain Infinity/NaN (e.g. hold worst-slack with no violation),
    and Python's `json.dumps` happily emits the literal `Infinity` — which Postgres JSONB rejects
    ('Token "Infinity" is invalid'), crashing the run AFTER the GDS was produced. Replace every
    non-finite float with null; drop non-serializable values (e.g. langchain Documents)."""
    import math
    import json
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items() if _safe(v)}
    if isinstance(obj, list):
        return [_jsonable(v) for v in obj if _safe(v)]
    try:
        json.dumps(obj, allow_nan=False)          # allow_nan=False → inf/nan RAISE, not emit
        return obj
    except (TypeError, ValueError):
        return str(obj)[:2000]


def _safe(v) -> bool:
    import json
    if isinstance(v, (dict, list, float, int, str, bool)) or v is None:
        return True
    try:
        json.dumps(v, allow_nan=False)
        return True
    except (TypeError, ValueError):
        return False
