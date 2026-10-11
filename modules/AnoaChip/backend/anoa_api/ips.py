"""IP library, Create-IP (upload → LibreLane → IP), and Chip Studio endpoints.

  GET    /api/ips                         list IPs (manifests)
  GET    /api/ips/{id}                     one IP manifest
  GET    /api/ips/{id}/file?path=…         serve a file from the IP folder (rtl/gds/png)
  POST   /api/ips                          create an IP from uploaded RTL (multipart)
  DELETE /api/ips/{id}                      delete an IP (folder + knowledge rows)
  POST   /api/ips/{id}/harden               start a LibreLane harden job → {job_id}
  GET    /api/jobs/{job_id}/stream          SSE log of a background job (harden/build)

  GET    /api/chipstudio/padframe           padframe backdrop info (image url + size)
  GET    /api/chipstudio/padframe.png       the rendered padring backdrop
  GET    /api/chipstudio/floorplans          list saved chip floorplans
  POST   /api/chipstudio/floorplans          create a floorplan
  GET    /api/chipstudio/floorplans/{id}     load one
  PUT    /api/chipstudio/floorplans/{id}     save placed macros + nets
  DELETE /api/chipstudio/floorplans/{id}     delete one
"""
from __future__ import annotations

import asyncio
import json
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from PIL import Image

from . import harden, ip_store, jobs

router = APIRouter()

REPO = Path(__file__).resolve().parents[2]
STUDIO = REPO / "data" / "chip_studio"
PADFRAME = STUDIO / "padframe.png"
FLOORPLANS = STUDIO / "floorplans"


# --- IP library --------------------------------------------------------------
@router.get("/api/ips")
def list_ips():
    ips = ip_store.list_ips()
    return {"ips": ips, "categories": ip_store.CATEGORIES,
            "labels": ip_store.CATEGORY_LABELS, "icons": ip_store.CATEGORY_ICONS,
            "counts": {c: sum(1 for m in ips if m["category"] == c) for c in ip_store.CATEGORIES}}


@router.get("/api/ips/{ip_id}")
def get_ip(ip_id: str):
    mf = ip_store.get_ip(ip_id)
    if not mf:
        raise HTTPException(404, "ip not found")
    # include the RTL text so the IP detail view can show/edit the source
    d = ip_store.ip_dir(ip_id) / "rtl"
    mf = {**mf, "files": {fn: (d / fn).read_text(errors="replace")
                          for fn in mf.get("rtl", []) if (d / fn).is_file()}}
    return mf


@router.get("/api/ips/{ip_id}/file")
def ip_file(ip_id: str, path: str):
    base = ip_store.ip_dir(ip_id).resolve()
    target = (base / path).resolve()
    if base != target and base not in target.parents:
        raise HTTPException(400, "invalid path")
    if not target.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(str(target))


@router.post("/api/ips")
async def create_ip(name: str = Form(...), category: str = Form(""), top: str = Form(""),
                    subtitle: str = Form(""), files: list[UploadFile] = File(default=[])):
    rtl: dict[str, str] = {}
    for uf in files or []:
        data = await uf.read()
        if data and Path(uf.filename or "").suffix.lower() in (".v", ".sv", ".vh", ".svh"):
            rtl[uf.filename] = data.decode("utf-8", errors="replace")
    if not rtl:
        raise HTTPException(400, "upload at least one .v/.sv file")
    # a custom category typed by the user is slugified to a stable key (e.g. "Sensor IF" → "sensor_if")
    cat = ip_store.slug(category) if category and category not in ip_store.CATEGORIES else category
    mf = ip_store.create_ip(name, rtl, category=cat, top=top, source="upload", subtitle=subtitle)
    ip_store.ingest_ip(mf["id"])
    return mf


@router.delete("/api/ips/{ip_id}")
def delete_ip(ip_id: str):
    return {"ok": ip_store.delete_ip(ip_id)}


@router.post("/api/ips/{ip_id}/simulate")
def simulate_ip(ip_id: str):
    """Compile RTL + testbench and run it — proves the IP works (pass/fail + log)."""
    if not ip_store.get_ip(ip_id):
        raise HTTPException(404, "ip not found")
    return ip_store.simulate_ip(ip_id)


# --- Create-IP: harden → GDS (background job) --------------------------------
@router.post("/api/ips/{ip_id}/harden")
def harden_ip(ip_id: str, body: dict | None = None):
    mf = ip_store.get_ip(ip_id)
    if not mf:
        raise HTTPException(404, "ip not found")
    if not harden.available():
        raise HTTPException(503, "librelane not available on PATH")
    opts = body or {}
    util = int(opts.get("core_util", 40))
    period = float(opts.get("clock_period", 20.0))
    clock = opts.get("clock_port", "clk")

    def _job(bus: jobs.JobBus):
        bus.line(f"⚙️  hardening {ip_id} (top={mf['top']}) — LibreLane gf180 …")
        ip_store.update_ip(ip_id, status="hardening")
        rtl = ip_store.ip_dir(ip_id) / "rtl"
        work = Path(tempfile.mkdtemp(prefix=f"harden_{ip_id}_"))
        res = harden.harden_rtl(rtl, work, ip_id, top=mf["top"], clock_port=clock,
                                clock_period=period, core_util=util, on_log=bus.line)
        if res["ok"]:
            ip_store.attach_harden(ip_id, gds_src=res["gds"], png_src=res["png"],
                                   metrics=res["metrics"], signoff=res.get("signoff"),
                                   tapeout_ready=res.get("tapeout_ready", False), status="hardened")
            ip_store.ingest_ip(ip_id)
            if res.get("tapeout_ready"):
                bus.line(f"✅ TAPE-OUT READY — GDS sign-off clean; metrics={res['metrics']}")
            else:
                fails = (res.get("signoff") or {}).get("failed", [])
                bus.line(f"⚠️ GDS produced but NOT sign-off clean — violations: {', '.join(fails)}")
            bus.finish("done", ok=True, tapeout_ready=res.get("tapeout_ready", False),
                       signoff=res.get("signoff"))
        else:
            ip_store.update_ip(ip_id, status="harden_failed")
            bus.line(f"❌ harden failed (rc={res['rc']})")
            bus.finish("error", ok=False, rc=res["rc"])
        import shutil
        shutil.rmtree(work, ignore_errors=True)

    return {"job_id": jobs.start_job(_job)}


@router.get("/api/jobs/{job_id}/stream")
async def job_stream(job_id: str, request: Request):
    bus = jobs.get_job(job_id)
    if bus is None:
        raise HTTPException(404, "job not found")

    async def gen():
        idx = 0
        while True:
            if await request.is_disconnected():
                break
            batch, idx = bus.since(idx)
            for ev in batch:
                yield jobs.sse(ev)
            if batch and batch[-1].get("type") == "end":
                break
            if not batch:
                yield ": keep-alive\n\n"
                await asyncio.sleep(0.3)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --- Chip Studio -------------------------------------------------------------
@router.get("/api/chipstudio/padframe")
def padframe():
    if not PADFRAME.is_file():
        return {"image_url": None, "width": 0, "height": 0, "source": ""}
    try:
        w, h = Image.open(PADFRAME).size
    except Exception:  # noqa: BLE001
        w = h = 2000
    return {"image_url": "/api/chipstudio/padframe.png", "width": w, "height": h,
            "source": "SSCS Chipathon-2025 gf180 padring"}


@router.get("/api/chipstudio/padframe.png")
def padframe_png():
    if not PADFRAME.is_file():
        raise HTTPException(404, "no padframe — copy a padring GDS into data/chip_studio/")
    return FileResponse(str(PADFRAME))


def _fp_path(fp_id: str) -> Path:
    return FLOORPLANS / f"{fp_id}.json"


@router.get("/api/chipstudio/floorplans")
def list_floorplans():
    FLOORPLANS.mkdir(parents=True, exist_ok=True)
    out = []
    for p in sorted(FLOORPLANS.glob("*.json")):
        try:
            d = json.loads(p.read_text())
            out.append({"id": d.get("id", p.stem), "name": d.get("name", p.stem),
                        "blocks": len(d.get("placed", [])), "updated_at": d.get("updated_at", "")})
        except Exception:  # noqa: BLE001
            pass
    return {"floorplans": out}


@router.post("/api/chipstudio/floorplans")
def create_floorplan(body: dict | None = None):
    FLOORPLANS.mkdir(parents=True, exist_ok=True)
    fp_id = "fp_" + uuid.uuid4().hex[:10]
    doc = {"id": fp_id, "name": (body or {}).get("name", "New chip"),
           "placed": [], "nets": [], "updated_at": ""}
    _fp_path(fp_id).write_text(json.dumps(doc, indent=2))
    return doc


@router.get("/api/chipstudio/floorplans/{fp_id}")
def get_floorplan(fp_id: str):
    p = _fp_path(fp_id)
    if not p.is_file():
        raise HTTPException(404, "floorplan not found")
    return json.loads(p.read_text())


@router.put("/api/chipstudio/floorplans/{fp_id}")
def save_floorplan(fp_id: str, body: dict):
    from datetime import datetime, timezone
    p = _fp_path(fp_id)
    doc = {"id": fp_id, "name": body.get("name", "chip"),
           "placed": body.get("placed", []), "nets": body.get("nets", []),
           "updated_at": datetime.now(timezone.utc).isoformat()}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=2))
    return doc


@router.delete("/api/chipstudio/floorplans/{fp_id}")
def delete_floorplan(fp_id: str):
    p = _fp_path(fp_id)
    if p.is_file():
        p.unlink()
        return {"ok": True}
    return {"ok": False}
