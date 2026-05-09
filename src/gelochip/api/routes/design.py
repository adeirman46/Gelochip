"""Design API routes – submit jobs and poll results."""
from __future__ import annotations
import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException

from gelochip.api.schemas import DesignRequest, DesignResponse, JobStatus
from gelochip.agent.graph import build_graph, create_initial_state

router = APIRouter(prefix="/design", tags=["design"])

# In-memory job store (replace with Redis/DB for production)
_jobs: dict[str, dict[str, Any]] = {}


def _run_agent(job_id: str, request: DesignRequest) -> None:
    """Background task: run the LangGraph agent and store the result."""
    _jobs[job_id]["status"] = "running"
    try:
        graph = build_graph()
        state = create_initial_state(
            user_request=request.request,
            max_corrections=request.max_corrections,
        )
        result = graph.invoke(state)
        _jobs[job_id].update({
            "status": "done",
            "result": DesignResponse(
                job_id=job_id,
                status="done",
                final_answer=result.get("final_answer"),
                gds_path=result.get("layout_result", {}).get("gds_path"),
                circuit_spec=result.get("circuit_spec"),
                component_params=result.get("component_params"),
                errors=result.get("errors", []),
            ),
            "progress": [m.content for m in result.get("messages", []) if hasattr(m, "content")],
        })
    except Exception as e:
        _jobs[job_id]["status"] = "failed"
        _jobs[job_id]["error"] = str(e)


@router.post("/submit", response_model=DesignResponse)
async def submit_design(request: DesignRequest, background_tasks: BackgroundTasks):
    """Submit a circuit design job. Returns immediately with a job_id."""
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "queued", "result": None, "progress": []}
    background_tasks.add_task(_run_agent, job_id, request)
    return DesignResponse(job_id=job_id, status="queued")


@router.get("/status/{job_id}", response_model=JobStatus)
async def get_job_status(job_id: str):
    """Poll the status of a design job."""
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    job = _jobs[job_id]
    return JobStatus(
        job_id=job_id,
        status=job["status"],
        progress_messages=job.get("progress", []),
        result=job.get("result"),
    )


@router.post("/run_sync", response_model=DesignResponse)
async def run_design_sync(request: DesignRequest):
    """Run a design job synchronously (waits for completion). Use for small circuits."""
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "queued", "result": None, "progress": []}
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _run_agent, job_id, request)
    job = _jobs[job_id]
    if job["status"] == "failed":
        raise HTTPException(status_code=500, detail=job.get("error", "Agent failed"))
    return job["result"]
