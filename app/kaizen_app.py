"""
Gelochip Kaizen Web App  —  FastAPI + SSE backend for the RAG agent.

Prompt → plan → retrieve (3 ChromaDB collections) → generate glayout code →
test (build GDS + gf180 DRC) → critic → Kaizen-memory loop → GDS preview.

Run (from repo root, in the venv):
    .venv/bin/python -m uvicorn app.kaizen_app:app --port 8090 --reload
then open  http://localhost:8090/

Each pipeline event is streamed live to the browser over Server-Sent Events.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

os.environ.setdefault("PDK_ROOT", os.path.expanduser("~/pdks"))
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from fastapi import FastAPI, HTTPException, Request                # noqa: E402
from fastapi.middleware.cors import CORSMiddleware                 # noqa: E402
from fastapi.middleware.gzip import GZipMiddleware                 # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles                        # noqa: E402
from pydantic import BaseModel, field_validator                    # noqa: E402

from gelochip.kaizen import collections, config, studio            # noqa: E402

logging.basicConfig(level=getattr(logging, config.LOG_LEVEL, logging.INFO),
                    format="%(asctime)s [%(levelname)s] kaizen: %(message)s")
log = logging.getLogger("kaizen")

_STATIC = Path(__file__).parent / "static" / "kaizen"     # legacy vanilla UI (fallback)
_WEB = Path(__file__).parent / "static" / "web"           # compiled React SPA (frontend/)
_STATIC.mkdir(parents=True, exist_ok=True)
config.ensure_dirs()


# ── Job manager (concurrency-limited, cancellable, self-reaping) ──────────────
@dataclass
class Job:
    id: str
    prompt: str
    queue: "asyncio.Queue"
    cancel: threading.Event = field(default_factory=threading.Event)
    status: str = "queued"          # queued | running | done | error | cancelled
    created: float = field(default_factory=time.time)


_JOBS: dict[str, Job] = {}
_RUN_SEM = threading.BoundedSemaphore(config.MAX_CONCURRENT_RUNS)


def _reap_jobs() -> None:
    now = time.time()
    for jid in [j for j, job in list(_JOBS.items())
                if job.status in ("done", "error", "cancelled")
                and now - job.created > config.JOB_TTL_SECONDS]:
        _JOBS.pop(jid, None)


@asynccontextmanager
async def _lifespan(app: "FastAPI"):
    log.info("starting Gelochip Studio (max_concurrent=%d, origins=%s)",
             config.MAX_CONCURRENT_RUNS, config.ALLOWED_ORIGINS)
    try:
        counts = collections.collection_counts()
        if counts.get(config.COLL_TEMPLATES, 0) == 0 or counts.get(config.COLL_THEORY, 0) == 0:
            log.info("knowledge collections empty — building from data/ (one-time)…")
            log.info("built: %s", collections.build_all())
        else:
            log.info("collections ready (skipping rebuild): %s", counts)
    except Exception as e:
        log.warning("startup collection check failed: %s", e)
    yield
    # graceful shutdown: signal all running jobs to stop
    active = [j for j in _JOBS.values() if j.status in ("running", "queued")]
    if active:
        log.info("shutdown — cancelling %d active job(s)", len(active))
    for j in active:
        j.cancel.set()


app = FastAPI(title="Gelochip Studio", version="1.0.0", lifespan=_lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.ALLOWED_ORIGINS,
                   allow_methods=["*"], allow_headers=["*"])
app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    return resp


@app.exception_handler(Exception)
async def _on_error(request: Request, exc: Exception):
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"error": f"{type(exc).__name__}: {exc}"})


app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")
# Compiled React SPA (Vite emits hashed assets under /assets). Mounted only
# when the frontend has been built (frontend/ → npm run build).
if (_WEB / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(_WEB / "assets")), name="assets")
app.mount("/output", StaticFiles(directory=str(config.OUTPUT_DIR)), name="output")
# IP-block preview images live next to the circuit datasets.
_DATASETS = config.CIRCUITS_DIR
if _DATASETS.exists():
    app.mount("/datasets", StaticFiles(directory=str(_DATASETS)), name="datasets")


# ── Health / readiness ────────────────────────────────────────────────────────
@app.get("/health")
@app.get("/api/health")
async def health():
    """Liveness + readiness: ollama reachable, collections present, DB writable."""
    import httpx
    out = {"status": "ok", "version": app.version}
    try:
        out["collections"] = collections.collection_counts()
    except Exception as e:
        out["status"] = "degraded"; out["collections_error"] = str(e)[:120]
    try:
        r = httpx.get(f"{config.OLLAMA_BASE_URL}/api/tags", timeout=3)
        models = [m.get("name") for m in r.json().get("models", [])]
        out["ollama"] = {"up": True, "has_agent_model": any(config.LLM_MODEL in m for m in models)}
        if not out["ollama"]["has_agent_model"]:
            out["status"] = "degraded"
    except Exception as e:
        out["status"] = "degraded"; out["ollama"] = {"up": False, "error": str(e)[:80]}
    out["active_jobs"] = sum(1 for j in _JOBS.values() if j.status == "running")
    out["queued_jobs"] = sum(1 for j in _JOBS.values() if j.status == "queued")
    return out


class RunRequest(BaseModel):
    prompt: str

    @field_validator("prompt")
    @classmethod
    def _check(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("empty prompt")
        if len(v) > config.MAX_PROMPT_CHARS:
            raise ValueError(f"prompt too long (max {config.MAX_PROMPT_CHARS} chars)")
        return v


@app.get("/")
async def index():
    """Serve the React SPA if it has been built, else the vanilla fallback UI."""
    spa = _WEB / "index.html"
    return FileResponse(str(spa if spa.exists() else _STATIC / "index.html"))


# Static assets that Vite emits at the SPA root (favicon, vite.svg, …).
@app.get("/{fname}")
async def web_root_file(fname: str):
    if "/" in fname or fname.startswith("."):
        raise HTTPException(404, "not found")
    f = _WEB / fname
    if f.is_file():
        return FileResponse(str(f))
    raise HTTPException(404, "not found")


@app.get("/api/kaizen/collections")
async def collection_counts():
    """Live chunk counts for the three knowledge collections."""
    return collections.collection_counts()


# ── Studio tool 2: IP library ─────────────────────────────────────────────────
@app.get("/api/ip/library")
async def ip_library(all: bool = False):
    """Built IP blocks. Only DRC-clean blocks unless ?all=true."""
    return {"ips": studio.list_ips(only_drc_clean=not all)}


# ── Studio tool 3: padframe ───────────────────────────────────────────────────
@app.get("/api/padframe")
async def get_padframe():
    """gf180 pad ring (outline + named pads) for the chip floorplan."""
    return studio.padframe()


# ── Studio tool 4: pin-connect agent ──────────────────────────────────────────
class ConnectRequest(BaseModel):
    blocks: list[dict]
    use_llm: bool = True


@app.post("/api/connect")
async def connect(req: ConnectRequest):
    """Agent proposes pin↔pin nets + names for the placed blocks."""
    return studio.propose_connections(req.blocks, use_llm=req.use_llm)


@app.post("/api/kaizen/run")
async def run(req: RunRequest):
    _reap_jobs()
    job_id = uuid.uuid4().hex[:12]
    job = Job(id=job_id, prompt=req.prompt, queue=asyncio.Queue())
    _JOBS[job_id] = job
    loop = asyncio.get_event_loop()
    # Readable per-project dir (outputs/kaizen/<slug>_<date>/) instead of a UUID.
    from gelochip.kaizen.project_dir import make_project_dir
    job_dir = str(make_project_dir(req.prompt, job_id=job_id))

    from gelochip.kaizen import history
    try:                                   # show in history immediately
        history.save_session(job_id, req.prompt, [], {})
    except Exception:
        pass

    collected: list[dict] = []

    def emit(ev: dict):
        s = _serialise(ev, job_id)
        collected.append(s)
        loop.call_soon_threadsafe(job.queue.put_nowait, s)
        if not s.get("streaming"):         # persist on milestones (restore-safe)
            try:
                history.save_session(job_id, req.prompt, collected, {})
            except Exception:
                pass

    def worker():
        # Concurrency cap: heavy LLM+DRC jobs queue until a slot is free.
        if not _RUN_SEM.acquire(timeout=900):
            job.status = "error"
            emit({"node": "error", "msg": "server busy — try again shortly"})
            loop.call_soon_threadsafe(job.queue.put_nowait, {"node": "_end"})
            return
        job.status = "running"
        final: dict = {}
        try:
            from gelochip.kaizen import agent
            final = agent.run(req.prompt, job_dir=job_dir, on_event=emit,
                              cancel=job.cancel.is_set)
            if job.cancel.is_set():
                job.status = "cancelled"
                emit({"node": "summarize", "msg": "⏹ cancelled by user"})
            else:
                job.status = "done"
                emit({"node": "done", "msg": final.get("answer", ""),
                      "answer": final.get("answer", "")})
        except Exception as e:
            job.status = "error"
            log.exception("run %s failed", job_id)
            emit({"node": "error", "msg": f"{type(e).__name__}: {e}"})
        finally:
            _RUN_SEM.release()
            try:
                history.save_session(job_id, req.prompt, collected, final)
            except Exception:
                pass
            loop.call_soon_threadsafe(job.queue.put_nowait, {"node": "_end"})

    threading.Thread(target=worker, daemon=True, name=f"kaizen-{job_id}").start()
    return {"job_id": job_id, "status": "started"}


@app.post("/api/kaizen/cancel/{job_id}")
async def cancel(job_id: str):
    """Cooperatively stop a running job (aborts at the next agent step)."""
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "unknown job")
    job.cancel.set()
    return {"ok": True, "status": "cancelling"}


# ── Chat / build history (SQLite — click to restore last state) ───────────────
@app.get("/api/kaizen/history")
async def list_history():
    from gelochip.kaizen import history
    return {"sessions": history.list_sessions()}


@app.get("/api/kaizen/history/{job_id}")
async def get_history(job_id: str):
    from gelochip.kaizen import history
    s = history.get_session(job_id)
    if s is None:
        raise HTTPException(404, "unknown session")
    return s


@app.delete("/api/kaizen/history/{job_id}")
async def del_history(job_id: str):
    from gelochip.kaizen import history
    history.delete_session(job_id)
    return {"ok": True}


@app.get("/api/kaizen/stream/{job_id}")
async def stream(job_id: str):
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "unknown job")

    async def gen():
        try:
            while True:
                try:
                    ev = await asyncio.wait_for(job.queue.get(), timeout=30)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"     # SSE comment → keeps proxies open
                    continue
                if ev.get("node") == "_end":
                    yield "event: end\ndata: {}\n\n"
                    break
                yield f"data: {json.dumps(ev)}\n\n"
        finally:
            _reap_jobs()                          # don't pop immediately (allow reconnect)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no",
                                      "Connection": "keep-alive"})


def _serialise(ev: dict, job_id: str) -> dict:
    """Turn absolute artifact paths into /output URLs the browser can fetch."""
    out = dict(ev)
    for key in ("png_path", "gds_path", "spice_path", "ac_plot", "tran_plot"):
        p = ev.get(key)
        if p and Path(p).exists():
            try:
                rel = Path(p).relative_to(config.OUTPUT_DIR)
                url_key = key.replace("_path", "_url") if key.endswith("_path") else key + "_url"
                out[url_key] = f"/output/{rel}"
            except ValueError:
                pass
    return out
