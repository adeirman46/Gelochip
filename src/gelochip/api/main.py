"""
Gelochip FastAPI backend.

Start with:
    uvicorn gelochip.api.main:app --reload --port 8000

Or via the CLI:
    gelochip serve
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from gelochip.api.routes.design import router as design_router
from gelochip.agent.tools.circuit_tools import list_available_blocks, get_pdk_info
from gelochip.api.schemas import BlocksResponse

app = FastAPI(
    title="Gelochip API",
    description="AI-Assisted Analog/RF IC Layout Automation",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(design_router)


@app.get("/")
async def root():
    return {"message": "Gelochip API is running", "docs": "/docs"}


@app.get("/blocks", response_model=BlocksResponse)
async def get_blocks():
    """List all available building blocks."""
    blocks = list_available_blocks.invoke({})
    return BlocksResponse(**blocks)


@app.get("/pdks")
async def get_pdks():
    """Get info for all supported PDKs."""
    return {
        pdk: get_pdk_info.invoke({"pdk_name": pdk})
        for pdk in ["gf180", "sky130", "ihp130"]
    }


@app.get("/health")
async def health():
    return {"status": "ok"}
