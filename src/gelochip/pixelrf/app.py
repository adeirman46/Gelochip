"""
PixelatedRF Designer — standalone FastAPI app.

Start with:
    uv run uvicorn gelochip.pixelrf.app:app --host 0.0.0.0 --port 8001 --reload

Or add to CLI:
    gelochip pixelrf-serve
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from gelochip.pixelrf import inference as inf
from gelochip.pixelrf import gds_builder as gds

# ── App setup ──────────────────────────────────────────────────────────────────

app = FastAPI(
    title="PixelatedRF Designer",
    description="Draw an S11 target → get the inverse-designed pixel layout + GDS + DRC",
    version="0.1.0",
    docs_url="/api/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve the frontend
_STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")

# Temp GDS store  {uuid: path}
_gds_store: dict[str, Path] = {}


# ── Models are loaded once at startup ─────────────────────────────────────────

@app.on_event("startup")
async def _startup():
    try:
        inf.load_models()
    except FileNotFoundError as e:
        print(f"[pixelrf] WARNING: {e}")
        print("[pixelrf] Run 02_train.ipynb first to generate model checkpoints.")


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    return (_STATIC / "index.html").read_text()


class PredictRequest(BaseModel):
    s11_db: list[float] = Field(
        ...,
        min_length=81, max_length=81,
        description="81 S11 values (dB) at 1–10 GHz, uniformly spaced",
    )
    k_samples: int = Field(8, ge=1, le=32, description="Best-of-K candidates")


class DRCOut(BaseModel):
    density_pct: float
    density_ok: bool
    min_width_violations: int
    min_space_violations: int
    corner_touch_violations: int
    min_area_violations: int
    chip_w_um: float
    chip_h_um: float
    metal_area_um2: float
    fill_pct: float
    status: str


class PredictResponse(BaseModel):
    layout: list[list[int]]
    surrogate_s11: list[float]
    freqs_ghz: list[float]
    rmse_db: float
    fill_pct: float
    drc: DRCOut
    gds_id: str          # use with GET /gds/{gds_id}


@app.post("/predict", response_model=PredictResponse)
async def predict(req: PredictRequest):
    # Lazy-load: when this app is MOUNTED as a sub-app (inside Gelochip Studio),
    # Starlette does NOT run its startup event, so load the models on first use.
    if inf._inv_model is None:
        try:
            inf.load_models()
        except Exception as e:  # noqa: BLE001
            raise HTTPException(503, f"Models not loaded ({e}) — run 02_train.ipynb first")
    if inf._inv_model is None:
        raise HTTPException(503, "Models not loaded — run 02_train.ipynb first")

    result = inf.predict(req.s11_db, k=req.k_samples)

    gds_id = uuid.uuid4().hex[:12]
    gds_path, _ = gds.build_gds(result.layout, name=f"pixelrf_{gds_id}")
    drc_result   = gds.run_drc(gds_path, result.layout)
    _gds_store[gds_id] = gds_path

    return PredictResponse(
        layout=result.layout,
        surrogate_s11=result.surrogate_s11,
        freqs_ghz=result.freqs_ghz,
        rmse_db=round(result.rmse_db, 3),
        fill_pct=round(result.fill * 100, 1),
        drc=DRCOut(**drc_result),
        gds_id=gds_id,
    )


@app.get("/gds/{gds_id}")
async def download_gds(gds_id: str):
    path = _gds_store.get(gds_id)
    if not path or not path.exists():
        raise HTTPException(404, "GDS not found or expired")
    return FileResponse(
        str(path),
        media_type="application/octet-stream",
        filename=f"pixelrf_{gds_id}.gds",
    )


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "models_loaded": inf._inv_model is not None,
        "device": inf.DEVICE,
    }
