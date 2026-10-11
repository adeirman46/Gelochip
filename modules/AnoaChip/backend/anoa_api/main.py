"""AnoaChip FastAPI backend.

Endpoints the Vite frontend consumes:
  GET    /api/health
  GET    /api/chats                       list chats
  POST   /api/chats                       create a chat
  GET    /api/chats/{id}                  chat + messages + latest run transcript (re-hydrate)
  DELETE /api/chats/{id}                  delete a chat
  POST   /api/chats/{id}/messages         send a prompt (+ optional image/PDF uploads) → starts a run
  GET    /api/runs/{run_id}/stream        Server-Sent-Events live stream of the run
  GET    /api/runs/{run_id}/file?path=…   serve an artifact (e.g. a waveform/plot) from the design dir
  GET    /api/knowledge/stats             knowledge-store stats
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from . import db, runner, ips, sim

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src" / "anoa_chip"))

app = FastAPI(title="AnoaChip API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"], allow_headers=["*"], allow_credentials=True,
)
# IP library + Create-IP + Chip Studio, and the Simulation workspaces
app.include_router(ips.router)
app.include_router(sim.router)


@app.on_event("startup")
def _startup():
    backed = db.init()
    print(f"[anoa-api] persistence: {'Postgres' if backed else 'in-memory'}")
    # Run threads die with the process (uvicorn --reload restarts on every source edit) but
    # their rows kept saying 'running' — eternal spinners, empty transcripts, and a chat
    # switcher pinned to a ghost run. Reap them so the UI recovers the moment we boot.
    try:
        n = db.reap_stale_runs()
        if n:
            print(f"[anoa-api] reaped {n} orphaned run(s) from a previous process")
    except Exception as e:  # noqa: BLE001
        print(f"[anoa-api] stale-run reap failed: {e}")


# --- models -----------------------------------------------------------------
class CreateChat(BaseModel):
    title: str | None = None
    project_id: str | None = None


class CreateProject(BaseModel):
    name: str | None = None


class RenameProject(BaseModel):
    name: str


class MoveChat(BaseModel):
    project_id: str | None = None


class RunOpts(BaseModel):
    use_web: bool = True
    run_harden: bool = False        # run the Glayout layout + DRC/LVS after specs pass
    deep_steps: bool = True
    # analog target spec — BOTH optional; blank means "let the prompt/agent decide"
    gain_db: float | None = None    # minimum DC/mid-band gain in dB
    bw_hz: float | None = None      # minimum -3 dB bandwidth / GBW in Hz
    # which SPICE analyses to run — any subset of dc/ac/tran (default: all three)
    sim_types: list[str] | None = None
    num_ctx: int | None = None      # Ollama context window (tokens); None → model default
    model: str | None = None        # Ollama chat model (picker); None → OLLAMA_MODEL/.env
    # kept for backend/DB compatibility (unused by the analog flow)
    clock_port: str = "clk"
    clock_period: float = 24.0
    die_um: float = 600.0
    core_util: int = 25


# --- health -----------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/system/caps")
def system_caps():
    """Hardware-aware limits for the chat parameters — the context-window slider is sized to the
    user's GPU VRAM (or RAM on CPU) so the chosen num_ctx's KV cache always fits."""
    try:
        from llm import recommended_ctx_limits, provider_label
        caps = recommended_ctx_limits()
        caps["model"] = provider_label()
        return caps
    except Exception:  # noqa: BLE001
        return {"device": "cpu", "total_gb": 0.0, "num_ctx_min": 2048,
                "num_ctx_max": 32768, "num_ctx_step": 2048, "num_ctx_default": 32768}


@app.get("/api/system/models")
def system_models():
    """Installed Ollama chat models, so the UI can offer a model picker (all local — whatever the
    user has pulled). `current` is the model in effect now."""
    try:
        from llm import current_model, list_ollama_models
        return {"models": list_ollama_models(), "current": current_model()}
    except Exception:  # noqa: BLE001
        return {"models": [], "current": ""}


@app.get("/api/knowledge/stats")
def knowledge_stats():
    try:
        from memory_store import get_memory
        return get_memory().stats() or {"total": 0, "by_kind": {}}
    except Exception:  # noqa: BLE001
        return {"total": 0, "by_kind": {}}


# --- knowledge store browser (Postgres rows + MinIO objects: view/search/add/delete) ---
class KnowledgeItem(BaseModel):
    text: str
    kind: str = "note"
    title: str = ""
    design: str = ""
    tags: str = ""


def _mem():
    from memory_store import get_memory
    return get_memory()


@app.get("/api/knowledge/items")
def knowledge_items(kind: str = "", design: str = "", q: str = "", limit: int = 200):
    """List knowledge rows (newest first), optionally filtered by kind/design, OR
    semantically searched when `q` is given (pgvector cosine)."""
    try:
        mem = _mem()
        if q.strip():
            items = mem.recall(q, kind=kind or None, design=design or None, k=min(limit, 50))
        else:
            items = mem.list_items(kind=kind or None, design=design or None, limit=limit)
        # normalize datetimes to strings
        for it in items:
            ca = it.get("created_at")
            if ca is not None and not isinstance(ca, str):
                it["created_at"] = str(ca)
        return {"items": items, "enabled": bool(getattr(mem, "enabled", False))}
    except Exception as e:  # noqa: BLE001
        return {"items": [], "enabled": False, "error": str(e)}


@app.get("/api/knowledge/item/{item_id}")
def knowledge_item(item_id: str):
    row = _mem().get(item_id)
    if not row:
        raise HTTPException(404, "not found")
    ca = row.get("created_at")
    if ca is not None and not isinstance(ca, str):
        row["created_at"] = str(ca)
    return row


@app.post("/api/knowledge/items")
def knowledge_add(body: KnowledgeItem):
    if not body.text.strip():
        raise HTTPException(400, "text is required")
    rid = _mem().remember(body.kind or "note", body.text, design=body.design,
                          source="manual-ui", title=body.title or body.text[:60],
                          tags=body.tags or "manual")
    if not rid:
        raise HTTPException(503, "knowledge store unavailable")
    return {"id": rid, "ok": True}


@app.delete("/api/knowledge/item/{item_id}")
def knowledge_delete(item_id: str):
    return {"ok": _mem().delete(item_id)}


@app.delete("/api/knowledge/items")
def knowledge_delete_where(kind: str = "", design: str = ""):
    if not (kind or design):
        raise HTTPException(400, "pass kind and/or design (refuses to wipe everything)")
    return {"deleted": _mem().delete_where(kind=kind or None, design=design or None)}


@app.get("/api/knowledge/objects")
def knowledge_objects(prefix: str = ""):
    """List MinIO objects (key + size) — the raw blobs behind the rows."""
    try:
        return {"objects": _mem().list_objects(prefix)}
    except Exception as e:  # noqa: BLE001
        return {"objects": [], "error": str(e)}


@app.get("/api/knowledge/object")
def knowledge_object(key: str):
    """Download/serve one MinIO object by key."""
    blob = _mem().get_object(key)
    if blob is None:
        raise HTTPException(404, "object not found")
    from fastapi.responses import Response
    return Response(content=blob, media_type="application/octet-stream",
                    headers={"Content-Disposition": f'inline; filename="{key.split("/")[-1]}"'})


# --- projects (group many chats / IPs) --------------------------------------
@app.get("/api/projects")
def projects():
    return {"projects": db.list_projects()}


@app.post("/api/projects")
def create_project(body: CreateProject):
    return db.create_project(body.name or "New project")


@app.patch("/api/projects/{project_id}")
def rename_project(project_id: str, body: RenameProject):
    db.rename_project(project_id, body.name)
    return {"ok": True}


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str, cascade: bool = False):
    db.delete_project(project_id, cascade=cascade)
    return {"ok": True}


# --- chats ------------------------------------------------------------------
@app.get("/api/chats")
def chats(project_id: str | None = None):
    return db.list_chats(project_id=project_id)


@app.post("/api/chats")
def create_chat(body: CreateChat):
    return db.create_chat(body.title or "New chat", project_id=body.project_id)


@app.post("/api/chats/{chat_id}/move")
def move_chat(chat_id: str, body: MoveChat):
    db.move_chat(chat_id, body.project_id)
    return {"ok": True}


@app.get("/api/chats/{chat_id}")
def get_chat(chat_id: str):
    chat = db.get_chat(chat_id)
    if not chat:
        raise HTTPException(404, "chat not found")
    run = db.latest_run_for_chat(chat_id)
    return {"chat": chat, "messages": db.get_messages(chat_id),
            "run": run, "transcript": (run or {}).get("transcript", []),
            "runs": db.runs_for_chat(chat_id)}


@app.delete("/api/chats/{chat_id}")
def delete_chat(chat_id: str):
    db.delete_chat(chat_id)
    return {"ok": True}


@app.delete("/api/chats/{chat_id}/messages/{message_id}")
def delete_message(chat_id: str, message_id: str):
    """Remove one message + its run(s). Orphaned design folders are cleaned up; a design a prior
    message still owns is kept (so deleting a bad continuation reverts to your real design)."""
    db.delete_message(message_id)
    return {"ok": True}


class _MessageEdit(BaseModel):
    content: str


@app.patch("/api/chats/{chat_id}/messages/{message_id}")
def edit_message(chat_id: str, message_id: str, body: _MessageEdit):
    """Edit a message's text in place (no re-run)."""
    db.update_message(message_id, body.content)
    return {"ok": True}


class _MessageRerun(BaseModel):
    content: str
    opts: dict | None = None


@app.post("/api/chats/{chat_id}/messages/{message_id}/rerun")
def rerun_message(chat_id: str, message_id: str, body: _MessageRerun):
    """Edit a message AND re-run it (like ChatGPT) — the new run REPLACES the old one. Routes the
    same way a fresh send does: a continuation prompt resumes the existing design, else a new run."""
    db.update_message(message_id, body.content)
    db.delete_runs_for_message(message_id)          # the new run replaces the old; design is kept
    try:
        run_opts = RunOpts(**(body.opts or {})).model_dump()
    except Exception:  # noqa: BLE001
        run_opts = RunOpts().model_dump()
    prompt = body.content
    if runner.is_continue(prompt):
        rec = runner.resume_run(chat_id=chat_id, message_id=message_id)
        if rec is not None:
            return {"run": rec, "resumed": True}
    rec = runner.start_run(chat_id=chat_id, message_id=message_id,
                           prompt=prompt, files=[], opts=run_opts)
    return {"run": rec}


# --- artifacts: the design's papers / code / GDS / images, for the "shelf" UI ---
_ART_KIND = {".sp": "code", ".spice": "code", ".cir": "code", ".cdl": "code",
             ".py": "code", ".json": "data",
             ".pdf": "pdf", ".png": "image", ".jpg": "image", ".jpeg": "image",
             ".svg": "image", ".webp": "image", ".gds": "gds",
             ".md": "doc", ".log": "log", ".txt": "doc"}


def _design_base(chat_id: str) -> Path | None:
    """The most-recent run whose design actually HAS files — NOT just the latest run (a
    follow-up that re-planned into an empty dir would otherwise hide the real artifacts)."""
    for r in db.designs_for_chat(chat_id):
        dd = r.get("design_dir")
        if dd and (Path(dd) / "netlist").is_dir() and any((Path(dd) / "netlist").iterdir()):
            return Path(dd)
    run = db.latest_run_for_chat(chat_id)
    return Path(run["design_dir"]) if run and run.get("design_dir") else None


def _git(base: Path, *args: str) -> str:
    import subprocess
    proc = subprocess.run(["git", *args], cwd=base, capture_output=True, text=True,
                          timeout=30)
    return proc.stdout if proc.returncode == 0 else ""


@app.get("/api/chats/{chat_id}/versions")
def chat_versions(chat_id: str):
    """GitHub-style design history: every pipeline step that changed files is a version
    v1..vN, with per-version +added/−removed line counts (the runner commits each step)."""
    base = _design_base(chat_id)
    if not base or not (base / ".git").exists():
        return {"versions": []}
    raw = _git(base, "log", "--reverse", "--pretty=%H|%ct|%s")
    versions = []
    for i, ln in enumerate([l for l in raw.splitlines() if "|" in l], 1):
        sha, ts, label = ln.split("|", 2)
        stat = _git(base, "show", "--numstat", "--pretty=format:", sha)
        files, adds, dels = 0, 0, 0
        for row in stat.splitlines():
            parts = row.split("\t")
            if len(parts) == 3:
                files += 1
                adds += int(parts[0]) if parts[0].isdigit() else 0
                dels += int(parts[1]) if parts[1].isdigit() else 0
        versions.append({"v": i, "id": sha, "label": label, "when": int(ts),
                         "files": files, "adds": adds, "dels": dels})
    return {"versions": list(reversed(versions))}      # newest first for the panel


@app.get("/api/chats/{chat_id}/versions/{rev}/files")
def version_files(chat_id: str, rev: str):
    """Files changed in one version, each with +/− line counts."""
    base = _design_base(chat_id)
    if not base or not (base / ".git").exists() or not re.fullmatch(r"[0-9a-f]{7,40}", rev):
        raise HTTPException(404, "no versions")
    out = []
    for row in _git(base, "show", "--numstat", "--pretty=format:", rev).splitlines():
        parts = row.split("\t")
        if len(parts) == 3:
            out.append({"path": parts[2],
                        "adds": int(parts[0]) if parts[0].isdigit() else 0,
                        "dels": int(parts[1]) if parts[1].isdigit() else 0})
    return {"files": out}


@app.get("/api/chats/{chat_id}/versions/{rev}/tree")
def version_tree(chat_id: str, rev: str):
    """The FULL file tree of the design AT that version (v1 opens its rtl/, tb/, notes,
    report sources… as they were then) — browse any version like a folder."""
    base = _design_base(chat_id)
    if not base or not (base / ".git").exists() or not re.fullmatch(r"[0-9a-f]{7,40}", rev):
        raise HTTPException(404, "no versions")
    changed = {f["path"] for f in version_files(chat_id, rev)["files"]}
    out = []
    for row in _git(base, "ls-tree", "-r", "--name-only", rev).splitlines():
        p = row.strip()
        if p and not p.startswith(".git"):
            out.append({"path": p, "changed": p in changed})
    return {"tree": out}


@app.get("/api/chats/{chat_id}/versions/{rev}/file")
def version_file(chat_id: str, rev: str, path: str):
    """One file's CONTENT at that version (git show rev:path)."""
    base = _design_base(chat_id)
    if not base or not (base / ".git").exists() or not re.fullmatch(r"[0-9a-f]{7,40}", rev):
        raise HTTPException(404, "no versions")
    if ".." in path or path.startswith("/"):
        raise HTTPException(400, "invalid path")
    return {"content": _git(base, "show", f"{rev}:{path}")[:300_000]}


@app.get("/api/chats/{chat_id}/versions/{rev}/diff")
def version_diff(chat_id: str, rev: str, path: str = ""):
    """Unified diff of one version (optionally one file) — the UI colors +green/−red."""
    base = _design_base(chat_id)
    if not base or not (base / ".git").exists() or not re.fullmatch(r"[0-9a-f]{7,40}", rev):
        raise HTTPException(404, "no versions")
    args = ["show", "--unified=3", "--pretty=format:%s%n", rev]
    if path:
        if ".." in path or path.startswith("/"):
            raise HTTPException(400, "invalid path")
        args += ["--", path]
    return {"diff": _git(base, *args)[:200_000]}


@app.get("/api/chats/{chat_id}/artifacts")
def chat_artifacts(chat_id: str):
    base = _design_base(chat_id)
    if not base or not base.exists():
        return {"artifacts": []}
    out, seen = [], set()
    # LaTeX compile litter + the report/report.pdf working copy (the user-facing copy is
    # <top>_report.pdf at the design root) would otherwise show up as duplicate artifacts.
    _skip_ext = {".aux", ".toc", ".out", ".fls", ".fdb_latexmk", ".synctex"}

    # 1) GENERATED artifacts — the pipeline's OWN output: the config JSON, the glayout layout
    #    script, any netlist WE wrote, the GDS, the sim results and the report. These are kept
    #    SEPARATE from the researched reference material (user: 'bedain mana anchor mana
    #    generated code … jangan disatuin' — the internet-sourced .cir/.spice belong to anchor).
    for sub in ("netlist", "rtl", "config", "layout", "tb", "sim",
                "report", "report/fig", "report/archive", "."):
        d = base / sub
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*")):
            if not p.is_file() or p in seen or "runs" in p.parts:
                continue
            if p.suffix.lower() in _skip_ext or (sub == "report" and p.name == "report.pdf"):
                continue
            seen.add(p)
            out.append({"name": p.name, "path": str(p.relative_to(base)),
                        "kind": _ART_KIND.get(p.suffix.lower(), "file"),
                        "size": p.stat().st_size, "origin": "generated"})
    # 2) DESIGN docs the pipeline reasoned out (understanding / research / design_notes / state)
    #    — flat context/ only (NOT its refs|anchor|uploads subdirs, handled below).
    cdir = base / "context"
    if cdir.is_dir():
        for p in sorted(cdir.glob("*")):
            if not p.is_file() or p in seen:
                continue
            seen.add(p)
            out.append({"name": p.name, "path": str(p.relative_to(base)),
                        "kind": _ART_KIND.get(p.suffix.lower(), "doc"),
                        "size": p.stat().st_size, "origin": "generated"})
    # 3) ANCHOR / REFERENCE material the researcher gathered FROM THE INTERNET — the reference
    #    netlists/spice under context/refs/, the cloned repos + papers under context/anchor/,
    #    and any user uploads. ALWAYS tagged origin=anchor + kind=reference (except pdf/image
    #    which keep their preview kind) so the UI never files them under generated code.
    for adir_name in ("context/refs", "context/anchor", "context/uploads"):
        adir = base / adir_name
        if not adir.is_dir():
            continue
        n_ref = 0
        for p in sorted(adir.rglob("*")):
            if not p.is_file() or p in seen:
                continue
            seen.add(p)
            k = _ART_KIND.get(p.suffix.lower(), "file")
            out.append({"name": p.name, "path": str(p.relative_to(base)),
                        "kind": k if k in ("pdf", "image") else "reference",
                        "size": p.stat().st_size, "origin": "anchor"})
            n_ref += 1
            if n_ref >= 80:                      # a big cloned repo shouldn't flood the shelf
                break
    return {"artifacts": out}


@app.get("/api/chats/{chat_id}/export-knowledge")
def export_status(chat_id: str):
    """Has this chat's design already been exported to the knowledge store?"""
    run = db.latest_run_for_chat(chat_id)
    base = Path(run["design_dir"]) if run and run.get("design_dir") else None
    if not base:
        return {"exported": False, "count": 0}
    try:
        rows = _mem().list_items(design=base.name, limit=500)
        return {"exported": len(rows) > 0, "count": len(rows)}
    except Exception:  # noqa: BLE001
        return {"exported": False, "count": 0}


@app.post("/api/chats/{chat_id}/export-knowledge")
def export_knowledge(chat_id: str):
    """Persist this chat's design (RTL/TB/notes/refs/GDS) into the durable knowledge store
    (Postgres rows + MinIO blobs) ON DEMAND — so deleting the chat/message NEVER loses the
    knowledge; it stays recallable and browsable in the Knowledge tab."""
    run = db.latest_run_for_chat(chat_id)
    base = Path(run["design_dir"]) if run and run.get("design_dir") else None
    if not base or not base.exists():
        raise HTTPException(404, "no design to export")
    ctx = run.get("ctx") or {}
    try:
        n = _mem().ingest_run(base, design=base.name, query=ctx.get("query", ""))
        return {"ok": True, "count": int(n or 0), "design": base.name}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, f"export failed: {e}")


@app.get("/api/chats/{chat_id}/file")
def chat_file(chat_id: str, path: str):
    run = db.latest_run_for_chat(chat_id)
    if not run or not run.get("design_dir"):
        raise HTTPException(404, "no design")
    base = Path(run["design_dir"]).resolve()
    target = (base / path).resolve()
    if base != target and base not in target.parents:
        raise HTTPException(400, "invalid path")
    if not target.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(str(target))


# --- send a message (starts a run) ------------------------------------------
@app.post("/api/chats/{chat_id}/messages")
async def send_message(
    chat_id: str,
    prompt: str = Form(...),
    opts: str = Form("{}"),
    files: list[UploadFile] = File(default=[]),
):
    chat = db.get_chat(chat_id)
    if not chat:
        raise HTTPException(404, "chat not found")

    # read uploads (image/PDF/text) into memory for the pipeline + knowledge store
    uploads = []
    for uf in files or []:
        data = await uf.read()
        if data:
            uploads.append({"name": uf.filename or "file", "data": data})

    user_files = [{"name": u["name"], "kind": _kind(u["name"])} for u in uploads]
    msg = db.add_message(chat_id, "user", prompt, files=user_files)
    # name the chat from the first prompt
    if chat["title"] in ("New chat", "", None):
        db.touch_chat(chat_id, title=prompt[:60])

    try:
        run_opts = RunOpts(**json.loads(opts or "{}")).model_dump()
    except Exception:  # noqa: BLE001
        run_opts = RunOpts().model_dump()

    # "continue" / "resume" → pick up the chat's last run from its SAVED state
    if runner.is_continue(prompt) and not uploads:
        rec = runner.resume_run(chat_id=chat_id, message_id=msg["id"])
        if rec is not None:
            return {"message": msg, "run": rec, "resumed": True}
        # Nothing resumable AND no prior design in this chat → do NOT start a fresh build on
        # the literal word ("continue" became a design named 'continue' that web-researched
        # the word). Tell the user instead of burning a run.
        if not runner.has_design(chat_id):
            note = db.add_message(
                chat_id, "assistant",
                "⚠️ Nothing to continue in this chat — the previous run left no design/state "
                "(it may have been interrupted). Describe the hardware you want to build, or "
                "open the chat that has the design and say `continue` there.")
            return {"message": msg, "assistant": note, "run": None}

    # UNDERSTAND the intent (not string matching): when no deterministic route matched
    # but this chat already HAS a design, ask the model what the user MEANS — a typo'd
    # "cocntinue" or any phrasing must never wipe into a fresh from-scratch build.
    if runner.has_design(chat_id) and not uploads and not runner.looks_like_followup(prompt):
        intent = runner.classify_intent(prompt)
        if intent == "continue":
            rec = runner.resume_run(chat_id=chat_id, message_id=msg["id"])
            if rec is not None:
                return {"message": msg, "run": rec, "resumed": True}
            intent = "followup"                       # nothing resumable → treat as follow-up
        if intent == "followup":
            rec = runner.start_run(chat_id=chat_id, message_id=msg["id"], prompt=prompt,
                                   files=uploads, opts=run_opts, force_continue=True)
            return {"message": msg, "run": rec}
        # intent == "new" → a genuinely different design: fresh build below

    rec = runner.start_run(chat_id=chat_id, message_id=msg["id"],
                           prompt=prompt, files=uploads, opts=run_opts)
    return {"message": msg, "run": rec}


# --- pause a running run (state is saved; 'continue' resumes) ---------------
@app.post("/api/runs/{run_id}/pause")
def pause_run(run_id: str):
    ok = runner.request_pause(run_id)
    return {"ok": ok, "paused": ok}


class SteerBody(BaseModel):
    message: str


@app.post("/api/runs/{run_id}/steer")
def steer_run(run_id: str, body: SteerBody):
    """Steer a LIVE run: the message is applied as feedback to the next step."""
    return {"ok": runner.request_steer(run_id, body.message)}


# --- SSE live stream of a run ----------------------------------------------
@app.get("/api/runs/{run_id}/stream")
async def stream_run(run_id: str, request: Request):
    bus = runner.get_bus(run_id)
    if bus is None:
        # run already finished (or server restarted) → replay persisted transcript
        run = db.get_run(run_id)
        if not run:
            raise HTTPException(404, "run not found")

        async def replay():
            for r in run.get("transcript", []):
                for b in r.get("blocks", []):
                    yield _sse({"type": "block", "node": r["node"], **b})
            yield _sse({"type": "end", "status": run.get("status", "done")})
        return StreamingResponse(replay(), media_type="text/event-stream")

    async def gen():
        # Replay the ENTIRE backlog from index 0 (so a reload mid-run restores the whole
        # transcript), then continue live. The bus keeps every event, so this is safe.
        idx = 0
        while True:
            # Client closed the tab / reloaded / switched chat → just STOP STREAMING to
            # this viewer. The RUN KEEPS GOING server-side (a multi-hour RTL→GDS build must
            # survive a page reload, like watching CI — closing the tab doesn't cancel CI).
            # To intentionally stop a run, use the Stop button (POST /api/runs/{id}/pause).
            if await request.is_disconnected():
                break
            batch, idx = bus.since(idx)
            for event in batch:
                yield _sse(event)
            if batch and batch[-1].get("type") == "end":
                break
            if not batch:                           # nothing new → heartbeat + brief poll
                yield ": keep-alive\n\n"
                await asyncio.sleep(0.25)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


# --- serve an artifact from a run's design dir ------------------------------
@app.get("/api/runs/{run_id}/file")
def run_file(run_id: str, path: str):
    run = db.get_run(run_id)
    if not run or not run.get("design_dir"):
        raise HTTPException(404, "run not found")
    base = Path(run["design_dir"]).resolve()
    target = (base / path).resolve()
    if base != target and base not in target.parents:
        raise HTTPException(400, "invalid path")
    if not target.is_file():
        raise HTTPException(404, "file not found")
    return FileResponse(str(target))


# --- helpers ----------------------------------------------------------------
def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"


def _kind(name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext == ".pdf":
        return "pdf"
    if ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        return "image"
    return "file"
