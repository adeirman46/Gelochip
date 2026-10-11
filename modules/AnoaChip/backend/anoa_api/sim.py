"""Simulation workspaces: upload RTL + testbench, edit/save in-browser, run iverilog/vvp,
view the waveform.

  GET    /api/sim/workspaces                       list workspaces
  POST   /api/sim/workspaces                       create (optional name / seed from an IP)
  GET    /api/sim/workspaces/{id}                  meta + every file's text
  POST   /api/sim/workspaces/{id}/files            upload files (multipart)
  PUT    /api/sim/workspaces/{id}/files/{name}     save/edit a file's text
  DELETE /api/sim/workspaces/{id}/files/{name}     remove a file
  DELETE /api/sim/workspaces/{id}                  delete the workspace
  POST   /api/sim/workspaces/{id}/run              iverilog+vvp → {ok, log, waveform}
  GET    /api/sim/workspaces/{id}/file?path=…      serve an artifact (vcd, etc.)
"""
from __future__ import annotations

import json
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from . import ip_store, vcd

router = APIRouter()

REPO = Path(__file__).resolve().parents[2]
WS = REPO / "data" / "sim_workspaces"
RTL_EXT = (".v", ".sv", ".vh", ".svh")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ws_dir(ws_id: str) -> Path:
    return WS / ws_id


def _safe(name: str) -> str:
    return re.sub(r"[^\w.\-]", "_", Path(name).name)


def _meta(ws_id: str) -> dict | None:
    p = _ws_dir(ws_id) / "workspace.json"
    return json.loads(p.read_text()) if p.is_file() else None


def _write_meta(m: dict) -> dict:
    m["updated_at"] = _now()
    (_ws_dir(m["id"]) / "workspace.json").write_text(json.dumps(m, indent=2))
    return m


def _files(ws_id: str) -> dict[str, str]:
    d = _ws_dir(ws_id) / "src"
    if not d.is_dir():
        return {}
    return {p.name: p.read_text(errors="replace") for p in sorted(d.glob("*"))
            if p.suffix.lower() in RTL_EXT}


@router.get("/api/sim/workspaces")
def list_workspaces():
    WS.mkdir(parents=True, exist_ok=True)
    out = []
    for d in sorted(WS.iterdir()):
        m = _meta(d.name) if d.is_dir() else None
        if m:
            out.append({"id": m["id"], "name": m["name"], "files": len(_files(m["id"])),
                        "updated_at": m.get("updated_at", "")})
    out.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return {"workspaces": out}


@router.post("/api/sim/workspaces")
def create_workspace(body: dict | None = None):
    body = body or {}
    ws_id = "ws_" + uuid.uuid4().hex[:10]
    d = _ws_dir(ws_id)
    (d / "src").mkdir(parents=True, exist_ok=True)
    name = body.get("name") or "New simulation"
    # optionally seed from an existing IP's RTL (simulate a library block)
    if body.get("ip_id"):
        mf = ip_store.get_ip(body["ip_id"])
        if mf:
            name = body.get("name") or f"sim · {mf['name']}"
            src = ip_store.ip_dir(mf["id"]) / "rtl"
            for fn in mf.get("rtl", []):
                if (src / fn).is_file():
                    (d / "src" / fn).write_text((src / fn).read_text(errors="replace"))
    return _write_meta({"id": ws_id, "name": name, "created_at": _now()})


@router.get("/api/sim/workspaces/{ws_id}")
def get_workspace(ws_id: str):
    m = _meta(ws_id)
    if not m:
        raise HTTPException(404, "workspace not found")
    return {**m, "files": _files(ws_id)}


@router.post("/api/sim/workspaces/{ws_id}/files")
async def upload_files(ws_id: str, files: list[UploadFile] = File(default=[])):
    if not _meta(ws_id):
        raise HTTPException(404, "workspace not found")
    src = _ws_dir(ws_id) / "src"
    src.mkdir(parents=True, exist_ok=True)
    saved = []
    for uf in files or []:
        if Path(uf.filename or "").suffix.lower() in RTL_EXT:
            data = await uf.read()
            (src / _safe(uf.filename)).write_bytes(data)
            saved.append(_safe(uf.filename))
    _write_meta(_meta(ws_id))
    return {"saved": saved, "files": _files(ws_id)}


@router.put("/api/sim/workspaces/{ws_id}/files/{name}")
def save_file(ws_id: str, name: str, body: dict):
    if not _meta(ws_id):
        raise HTTPException(404, "workspace not found")
    src = _ws_dir(ws_id) / "src"
    src.mkdir(parents=True, exist_ok=True)
    if Path(name).suffix.lower() not in RTL_EXT:
        raise HTTPException(400, "only .v/.sv/.vh/.svh files")
    (src / _safe(name)).write_text(body.get("content", ""))
    _write_meta(_meta(ws_id))
    return {"ok": True}


@router.delete("/api/sim/workspaces/{ws_id}/files/{name}")
def delete_file(ws_id: str, name: str):
    p = _ws_dir(ws_id) / "src" / _safe(name)
    if p.is_file():
        p.unlink()
    return {"ok": True}


@router.delete("/api/sim/workspaces/{ws_id}")
def delete_workspace(ws_id: str):
    import shutil
    d = _ws_dir(ws_id)
    if d.is_dir() and WS in d.resolve().parents:
        shutil.rmtree(d, ignore_errors=True)
        return {"ok": True}
    return {"ok": False}


@router.get("/api/sim/workspaces/{ws_id}/file")
def ws_file(ws_id: str, path: str):
    base = _ws_dir(ws_id).resolve()
    target = (base / path).resolve()
    if base != target and base not in target.parents:
        raise HTTPException(400, "invalid path")
    if not target.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(str(target))


@router.post("/api/sim/workspaces/{ws_id}/run")
def run_sim(ws_id: str, body: dict | None = None):
    """Compile every .v/.sv with iverilog, run with vvp, and return the log + waveform.
    `top` (optional) forces the elaboration top; otherwise iverilog auto-picks the testbench."""
    m = _meta(ws_id)
    if not m:
        raise HTTPException(404, "workspace not found")
    d = _ws_dir(ws_id)
    src = d / "src"
    vfiles = [p for p in sorted(src.glob("*")) if p.suffix.lower() in (".v", ".sv")]
    if not vfiles:
        raise HTTPException(400, "no .v/.sv files to simulate")
    top = (body or {}).get("top", "").strip()
    vvp = d / "sim.vvp"
    vcd_path = d / "design.vcd"
    if vvp.exists():
        vvp.unlink()
    if vcd_path.exists():
        vcd_path.unlink()

    cmd = ["iverilog", "-g2012", "-o", str(vvp), f"-I{src}"]
    if top:
        cmd += ["-s", top]
    cmd += [str(p) for p in vfiles]
    log = ["$ " + " ".join(["iverilog", "-g2012", "-o", "sim.vvp", "-I src"]
                           + (["-s", top] if top else []) + [p.name for p in vfiles])]
    # Never 500: ANY failure (missing tool, timeout, crash) comes back as a readable log so the
    # user always sees WHY it failed — not a blank panel + "compile error" badge.
    try:
        try:
            c = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except FileNotFoundError:
            return {"ok": False, "compiled": False,
                    "log": "\n".join(log + ["iverilog is not installed / not on PATH."])}
        except subprocess.TimeoutExpired:
            return {"ok": False, "compiled": False,
                    "log": "\n".join(log + ["(compile timed out after 120s)"])}
        out = (c.stderr or c.stdout or "").strip()
        log.append(out or "(compiled, no warnings)")
        if c.returncode != 0:
            return {"ok": False, "compiled": False, "log": "\n".join(log).strip(),
                    "waveform": None, "hint": "fix the compile errors above, then run again"}

        log.append("$ vvp sim.vvp")
        try:
            r = subprocess.run(["vvp", str(vvp)], cwd=str(d), capture_output=True, text=True, timeout=90)
            log.append((r.stdout or "").strip())
            if r.stderr.strip():
                log.append("[stderr] " + r.stderr.strip())
        except subprocess.TimeoutExpired:
            log.append("(simulation timed out after 90s — check for a missing $finish)")

        wave = None
        if vcd_path.is_file():
            try:
                wave = vcd.to_wave_json(vcd_path.read_text(errors="replace"))
            except Exception as e:  # noqa: BLE001
                log.append(f"(waveform parse failed: {e})")
        else:
            log.append("ℹ️ no design.vcd produced — add `$dumpfile(\"design.vcd\"); "
                       "$dumpvars(0, <tb>);` to your testbench to see a waveform.")
        return {"ok": True, "compiled": True, "log": "\n".join([l for l in log if l]).strip(),
                "waveform": wave, "vcd": vcd_path.is_file()}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "compiled": False, "log": "\n".join(log + [f"simulation crashed: {e}"])}
