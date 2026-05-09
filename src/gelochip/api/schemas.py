"""Pydantic schemas for the Gelochip FastAPI backend."""
from __future__ import annotations
from typing import Optional, Any
from pydantic import BaseModel, Field


class DesignRequest(BaseModel):
    request: str = Field(..., description="Natural language circuit design request")
    pdk: Optional[str] = Field("gf180", description="Target PDK: gf180 (default), sky130, ihp130")
    max_corrections: int = Field(3, ge=0, le=10)


class DesignResponse(BaseModel):
    job_id: str
    status: str                    # queued | running | done | failed
    final_answer: Optional[str] = None
    gds_path: Optional[str] = None
    circuit_spec: Optional[dict[str, Any]] = None
    component_params: Optional[dict[str, Any]] = None
    errors: list[str] = []


class JobStatus(BaseModel):
    job_id: str
    status: str
    progress_messages: list[str] = []
    result: Optional[DesignResponse] = None


class BlocksResponse(BaseModel):
    primitives: list[str]
    blocks: list[str]
    cells: list[str]
