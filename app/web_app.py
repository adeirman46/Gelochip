"""
Gelochip Web Application  —  FastAPI + SSE backend.

Stage-by-stage execution: each pipeline node pauses after completion
and waits for the user to click "Continue" before the next node runs.

Run:
    uv run uvicorn app.web_app:app --port 8080 --reload
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from datetime import date as _date
from pathlib import Path
from typing import Any, AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

# ── Paths ──────────────────────────────────────────────────────────────────────
_STATIC_DIR = Path(__file__).parent / "static"
_STATIC_DIR.mkdir(exist_ok=True)

# Persistent outputs directory: <project_root>/outputs/ (or GELOCHIP_OUTPUT_DIR)
_env_output = os.getenv("GELOCHIP_OUTPUT_DIR")
if _env_output:
    OUTPUT_DIR = Path(_env_output)
else:
    # Walk up to project root (contains pyproject.toml)
    _here = Path(__file__).resolve()
    OUTPUT_DIR = _here.parent.parent / "outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(title="Gelochip", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Silence socket.io 404 noise from browser extensions
@app.api_route("/ws/{path:path}", methods=["GET", "POST", "OPTIONS"])
async def _ignore_socketio():
    from fastapi.responses import Response
    return Response(status_code=204)

app.mount("/static",  StaticFiles(directory=str(_STATIC_DIR)), name="static")
app.mount("/output",  StaticFiles(directory=str(OUTPUT_DIR)),  name="output")

# ── Node metadata ──────────────────────────────────────────────────────────────
_NODE_META: dict[str, dict[str, str]] = {
    "spec_parser":      {"label": "SpecParser",      "icon": "📋", "color": "#6366f1"},
    "researcher":       {"label": "Researcher",      "icon": "🔍", "color": "#0ea5e9"},
    "circuit_designer": {"label": "CircuitDesigner", "icon": "⚡", "color": "#f59e0b"},
    "layout_generator": {"label": "LayoutGenerator", "icon": "🏗️", "color": "#10b981"},
    "corrector":        {"label": "Corrector",       "icon": "🔧", "color": "#ef4444"},
    "verifier":         {"label": "Verifier",        "icon": "🔬", "color": "#ec4899"},
    "summarizer":       {"label": "Summarizer",      "icon": "✍️",  "color": "#8b5cf6"},
}

_STAGE_ORDER = ["spec_parser", "researcher", "circuit_designer",
                "layout_generator", "corrector", "verifier", "summarizer"]

# ── Output folder naming ───────────────────────────────────────────────────────

def _make_output_slug(design: str, job_id: str) -> str:
    """
    Build a human-readable output folder name.
    Example: "5 GHz cascode LNA — gf180, NF < 2 dB" + id →
             "5_ghz_cascode_lna_gf180_nf_2_db_2026-05-09_dd938b"
    """
    clean = re.sub(r'[^a-zA-Z0-9\s]', ' ', design)   # strip special chars
    clean = re.sub(r'\s+', '_', clean.strip()).lower() # collapse spaces
    clean = re.sub(r'_+', '_', clean).strip('_')[:45]  # dedupe underscores
    today = _date.today().strftime('%Y-%m-%d')
    return f"{clean}_{today}_{job_id[:6]}"


# ── In-memory store ────────────────────────────────────────────────────────────
_JOBS: dict[str, dict[str, Any]] = {}

# Shared LangGraph checkpointer (survives across /continue calls)
try:
    from langgraph.checkpoint.memory import MemorySaver
    _MEMORY = MemorySaver()
except ImportError:
    _MEMORY = None


# ── Models ─────────────────────────────────────────────────────────────────────
class DesignRequest(BaseModel):
    design: str
    pdk: str = "gf180"
    mode: str = "auto"   # "auto" | "manual"


# ── LLM factory ───────────────────────────────────────────────────────────────
def _build_llm():
    if os.getenv("OLLAMA_MODEL"):
        from langchain_ollama import ChatOllama
        return ChatOllama(
            model=os.getenv("OLLAMA_MODEL", "qwen3.5:9b"),
            base_url=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
            temperature=0.1,
            num_ctx=8192,
        )
    if os.getenv("ANTHROPIC_API_KEY"):
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model="claude-sonnet-4-6", temperature=0.1, max_tokens=8192)
    if os.getenv("GOOGLE_API_KEY"):
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model="gemini-2.5-pro", temperature=0.1)
    if os.getenv("OPENAI_API_KEY"):
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model="gpt-4o", temperature=0.1)
    raise EnvironmentError(
        "No LLM configured. Set OLLAMA_MODEL, ANTHROPIC_API_KEY, "
        "GOOGLE_API_KEY, or OPENAI_API_KEY in .env"
    )


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse(str(_STATIC_DIR / "favicon.ico"), media_type="image/x-icon")


@app.get("/")
async def index():
    return FileResponse(str(_STATIC_DIR / "index.html"))


@app.post("/api/design")
async def start_design(req: DesignRequest):
    """Start a new design job. Returns job_id for SSE subscription."""
    job_id = str(uuid.uuid4())
    queue: asyncio.Queue = asyncio.Queue()

    try:
        llm = _build_llm()
    except EnvironmentError as e:
        raise HTTPException(500, str(e))

    from gelochip.agent.graph import build_graph, create_initial_state
    from gelochip.agent.output_manager import OutputManager

    # Create per-job output directory: outputs/{slug}_{date}_{short_id}/
    slug = _make_output_slug(req.design, job_id)
    om = OutputManager(slug, root=OUTPUT_DIR)

    interrupt_nodes = ["spec_parser", "researcher", "circuit_designer",
                       "layout_generator", "corrector", "verifier"]
    use_interrupts = (req.mode == "manual") and (_MEMORY is not None)
    graph = build_graph(
        llm=llm,
        checkpointer=_MEMORY,
        interrupt_after=interrupt_nodes if use_interrupts else None,
    )
    initial_state = create_initial_state(
        user_request=req.design,
        max_corrections=3,
        output_dir=str(om.root),
    )
    thread_cfg = {"configurable": {"thread_id": job_id}}

    _JOBS[job_id] = {
        "id":             job_id,
        "slug":           slug,
        "design":         req.design,
        "pdk":            req.pdk,
        "mode":           req.mode,
        "status":         "running",
        "graph":          graph,
        "config":         thread_cfg,
        "queue":          queue,
        "events":         [],          # replay buffer
        "first_run":      True,
        "initial_state":  initial_state,
        "output_dir":     str(om.root),
        "output_manager": om,
    }
    asyncio.create_task(_run_stage(job_id))
    return {"job_id": job_id}


@app.post("/api/jobs/{job_id}/continue")
async def continue_job(job_id: str):
    """Resume a paused job (user approved the last stage)."""
    job = _JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job["status"] not in ("paused", "awaiting_approval"):
        raise HTTPException(400, f"Job not paused (status={job['status']})")
    job["status"] = "running"
    asyncio.create_task(_run_stage(job_id))
    return {"ok": True}


@app.get("/api/stream/{job_id}")
async def stream(job_id: str):
    """SSE stream — single persistent connection covering all stages."""
    job = _JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    async def generate() -> AsyncGenerator[str, None]:
        # Replay buffered events first (reconnect support)
        for ev in list(job["events"]):
            yield f"data: {json.dumps(ev)}\n\n"
        if job["status"] == "done":
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

        q: asyncio.Queue = job["queue"]
        while True:
            try:
                ev = await asyncio.wait_for(q.get(), timeout=30.0)
            except asyncio.TimeoutError:
                yield ": ping\n\n"
                continue
            if ev is None:   # pipeline fully done
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                break
            job["events"].append(ev)
            yield f"data: {json.dumps(ev)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/jobs")
async def list_jobs():
    _skip = {"queue", "graph", "initial_state", "output_manager"}
    return [
        {k: v for k, v in job.items() if k not in _skip}
        for job in sorted(_JOBS.values(), key=lambda j: j.get("created_at", ""), reverse=True)
    ]


@app.get("/api/jobs/{job_id}/files")
async def job_files(job_id: str):
    """Return a manifest of all output files saved for a job."""
    job = _JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    om = job.get("output_manager")
    if not om:
        return {"job_id": job_id, "files": {}}
    return om.manifest()


@app.get("/api/gds-preview/{filename:path}")
async def gds_preview(filename: str):
    # Search in any job output dir first, then root
    candidates = list(OUTPUT_DIR.rglob(filename))
    if not candidates:
        raise HTTPException(404, "GDS not found")
    gds_path = candidates[0]
    png_path = gds_path.parent / (gds_path.stem + "_preview.png")
    if not png_path.exists():
        try:
            _gds_to_png(str(gds_path), str(png_path))
        except Exception as e:
            raise HTTPException(500, f"Preview failed: {e}")
    return FileResponse(str(png_path), media_type="image/png")


# ── GDS → PNG ──────────────────────────────────────────────────────────────────
def _gds_to_png(gds_path: str, out_path: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    try:
        import gdsfactory as gf
        comp = gf.import_gds(gds_path)
        fig = comp.plot(show=False, return_fig=True)
        if fig:
            fig.savefig(out_path, dpi=150, bbox_inches="tight", facecolor="#0a0a0b")
            return
    except Exception:
        pass
    # Fallback: klayout
    import klayout.db as db
    import klayout.lay as lay
    lv = lay.LayoutView()
    lv.load_layout(gds_path)
    lv.max_hier()
    lv.zoom_fit()
    lv.get_pixels(1200, 900).write_png(out_path)


# ── Agent stage runner ─────────────────────────────────────────────────────────

async def _run_stage(job_id: str) -> None:
    """
    Run the graph until the next interrupt_after point, streaming events
    to the job's queue.  The queue is kept open between stages so the
    SSE connection stays alive.
    """
    job   = _JOBS[job_id]
    queue = job["queue"]
    graph = job["graph"]
    config = job["config"]

    first = job.pop("first_run", False)
    initial_state = job.pop("initial_state", None) if first else None

    in_think:    set[str] = set()
    in_response: set[str] = set()   # run_ids whose response stream has started
    current_node: str | None = None

    try:
        async for event in graph.astream_events(
            initial_state, config=config, version="v2"
        ):
            kind   = event["event"]
            name   = event.get("name", "")
            run_id = event.get("run_id", "")

            # ── Node started ──────────────────────────────────────────────
            if kind == "on_chain_start" and name in _NODE_META:
                current_node = name
                meta = _NODE_META[name]
                await queue.put({
                    "type":  "node_start",
                    "node":  name,
                    "label": meta["label"],
                    "icon":  meta["icon"],
                    "color": meta["color"],
                })

            # ── Node finished ─────────────────────────────────────────────
            elif kind == "on_chain_end" and name in _NODE_META:
                output = event["data"].get("output") or {}
                if not isinstance(output, dict):
                    output = {}
                detail = _node_detail(name, output)
                await queue.put({
                    "type":    "node_end",
                    "node":    name,
                    "summary": _node_summary(name, output),
                    "detail":  detail,
                })

            # ── Tool started ──────────────────────────────────────────────
            elif kind == "on_tool_start":
                tool_input = event["data"].get("input") or {}
                await queue.put({
                    "type":   "tool_start",
                    "run_id": run_id,
                    "tool":   name,
                    "input":  json.dumps(tool_input, default=str)[:600],
                    "node":   current_node,
                })

            # ── Tool finished ─────────────────────────────────────────────
            elif kind == "on_tool_end":
                out = event["data"].get("output") or ""
                await queue.put({
                    "type":   "tool_end",
                    "run_id": run_id,
                    "output": str(out)[:1200],
                })

            # ── LLM token stream — thinking + response streaming ─────────
            elif kind == "on_chat_model_stream":
                chunk = event["data"].get("chunk")
                if not (chunk and hasattr(chunk, "content") and chunk.content):
                    continue
                token: str = chunk.content if isinstance(chunk.content, str) else ""
                if not token:
                    continue

                if "<think>" in token and run_id not in in_think:
                    in_think.add(run_id)
                    after = token.split("<think>", 1)[1]
                    await queue.put({"type": "think_start", "run_id": run_id, "node": current_node})
                    if after.strip():
                        await queue.put({"type": "think_token", "run_id": run_id, "token": after})

                elif "</think>" in token and run_id in in_think:
                    in_think.discard(run_id)
                    before = token.split("</think>", 1)[0]
                    if before.strip():
                        await queue.put({"type": "think_token", "run_id": run_id, "token": before})
                    await queue.put({"type": "think_end", "run_id": run_id})
                    # Any text after </think> starts the response stream
                    rest = token.split("</think>", 1)[1]
                    if rest:
                        in_response.add(run_id)
                        await queue.put({"type": "response_start", "run_id": run_id, "node": current_node})
                        await queue.put({"type": "response_token", "run_id": run_id, "token": rest})

                elif run_id in in_think:
                    await queue.put({"type": "think_token", "run_id": run_id, "token": token})

                else:
                    # Normal response token (Claude, Gemini, GPT — no think tags)
                    if run_id not in in_response:
                        in_response.add(run_id)
                        await queue.put({"type": "response_start", "run_id": run_id, "node": current_node})
                    await queue.put({"type": "response_token", "run_id": run_id, "token": token})

        # ── After stream ends: check graph state ──────────────────────────
        if _MEMORY:
            graph_state = graph.get_state(config)
            if graph_state.next:
                next_node = graph_state.next[0]
                meta = _NODE_META.get(next_node, {})
                job["status"] = "paused"
                await queue.put({
                    "type":       "awaiting_approval",
                    "next_node":  next_node,
                    "next_label": meta.get("label", next_node),
                    "next_icon":  meta.get("icon", ""),
                    "next_color": meta.get("color", "#888"),
                })
                return   # keep queue open — don't send None
        # No more nodes → pipeline complete
        job["status"] = "done"
        await queue.put(None)

    except Exception as e:
        job["status"] = "error"
        await queue.put({"type": "error", "message": str(e)})
        await queue.put(None)


# ── Path → URL helper ─────────────────────────────────────────────────────────

def _path_to_url(abs_path: str | None) -> str | None:
    """Convert an absolute output-dir path to a /output/... web URL."""
    if not abs_path:
        return None
    try:
        rel = Path(abs_path).relative_to(OUTPUT_DIR)
        return f"/output/{rel.as_posix()}"
    except ValueError:
        return None  # not under OUTPUT_DIR — can't serve it


# ── Node detail / summary helpers ──────────────────────────────────────────────

def _node_summary(node: str, output: dict) -> str:
    if node == "spec_parser":
        spec = output.get("circuit_spec") or {}
        if spec:
            return (f"{spec.get('circuit_type','?').upper()} "
                    f"@ {spec.get('freq_GHz','?')} GHz · {spec.get('pdk','?')}")
        return "Spec parsed."
    if node == "researcher":
        n = len(output.get("retrieved_papers") or [])
        return f"Found {n} paper{'s' if n != 1 else ''}."
    if node == "circuit_designer":
        params = {k: v for k, v in (output.get("component_params") or {}).items()
                  if not k.startswith("_")}
        pyspice_ok = (output.get("pyspice_result") or {}).get("success")
        spice_tag = " · PySpice ✅" if pyspice_ok else (" · PySpice ❌" if pyspice_ok is False else "")
        return f"Sized {len(params)} parameters{spice_tag}."
    if node == "corrector":
        next_n = output.get("next_node") or "?"
        count  = output.get("correction_count", 0)
        failed = output.get("failed_node") or "unknown"
        action = "fixed ✅" if next_n in ("verifier", "layout_generator") and not failed else f"retrying → {next_n}"
        return f"Attempt {count} — {action}."
    if node == "layout_generator":
        lr = output.get("layout_result") or {}
        gds = lr.get("gds_path", "")
        return f"GDS: {Path(gds).name}" if gds else "Layout generated."
    if node == "verifier":
        lr = output.get("layout_result") or {}
        return lr.get("drc_summary") or "Verification complete."
    if node == "summarizer":
        ans = output.get("final_answer", "")
        return (ans[:100] + "…") if len(ans) > 100 else ans
    return "Done."


def _node_detail(node: str, output: dict) -> dict:
    d: dict[str, Any] = {}

    if node == "spec_parser":
        d["spec"] = output.get("circuit_spec")

    elif node == "researcher":
        raw = output.get("retrieved_papers") or []
        d["papers"] = [
            {
                "title":     p.get("title", ""),
                "authors":   p.get("authors", []),
                "abstract":  (p.get("summary") or p.get("abstract", ""))[:400],
                "pdf_url":   p.get("pdf_url", ""),
                "pdf_local": _path_to_url(p.get("pdf_local")),
                "published": p.get("published", ""),
                "images":    [u for u in (_path_to_url(img) for img in p.get("images", [])) if u],
            }
            for p in raw[:6]
        ]

    elif node == "circuit_designer":
        params = dict(output.get("component_params") or {})
        params.pop("_performance_estimate", None)
        d["params"] = params
        pyspice_result = output.get("pyspice_result") or {}
        d["pyspice_passed"] = pyspice_result.get("success")
        d["pyspice_output"] = pyspice_result.get("stdout", "")[:500] if pyspice_result else None

    elif node == "corrector":
        d["failed_node"]  = output.get("failed_node")
        d["next_node"]    = output.get("next_node")
        d["attempt"]      = output.get("correction_count", 0)
        d["feedback"]     = (output.get("corrector_feedback") or "")[:600]
        lr = output.get("layout_result") or {}
        d["error"]        = lr.get("error")

    elif node == "layout_generator":
        lr = output.get("layout_result") or {}
        d["gds_path"]     = lr.get("gds_path")
        d["gds_filename"] = Path(lr["gds_path"]).name if lr.get("gds_path") else None
        d["python_code"]  = lr.get("python_code", "")
        d["error"]        = lr.get("error")

    elif node == "verifier":
        lr  = output.get("layout_result") or {}
        sim = output.get("sim_result") or {}
        d["drc_summary"] = lr.get("drc_summary")
        # Only show real sim results (skip analytical estimates, skip error keys)
        d["sim"] = {
            k: v for k, v in sim.items()
            if k not in ("raw_measurements", "sim_stdout", "returncode", "error", "passed")
            and v is not None
        } if sim and not sim.get("skipped") and not sim.get("error") else None
        d["sim_error"] = sim.get("error") if sim else None

    elif node == "summarizer":
        d["final_answer"] = output.get("final_answer")
        d["errors"]       = output.get("errors") or []

    return d
