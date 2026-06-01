#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Gelochip launcher.   Usage:  ./scripts/run.sh [port]
#
#   ./scripts/run.sh   [8090]   Gelochip Studio — ONE app:
#       Prompt → GDSII (RAG agent) · Chip Studio (IP library + padframe + wiring)
#       · PixelatedRF (S₁₁ → GDS inverse EM design)
#
# Handles the venv, deps, the local model + ChromaDB build.
# ─────────────────────────────────────────────────────────────────────────────
set -e
cd "$(dirname "$0")/.."                       # repo root (scripts/ is one level down)
export PDK_ROOT="${PDK_ROOT:-$HOME/pdks}"
export PYTHONPATH="$PWD/src:${PYTHONPATH:-}"
export HF_HUB_DISABLE_TELEMETRY=1

# Single unified app. (PixelatedRF + legacy web UI are merged into Studio.)
APP="kaizen"
TARGET="app.kaizen_app:app"; DEFPORT=8090
PORT="${2:-${1:-$DEFPORT}}"
case "${1:-}" in ''|[0-9]*) ;; *) echo "note: only one app now (Studio). ignoring '$1'." ;; esac

# 1. Python env + deps ---------------------------------------------------------
if [ ! -x .venv/bin/python ]; then
  echo "[run] creating .venv + installing dependencies…"
  if command -v uv >/dev/null 2>&1; then uv sync
  else python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt; fi
fi

# 2. Kaizen needs the local agent model (no-op if already pulled) --------------
if [ "$APP" = "kaizen" ]; then
  if command -v ollama >/dev/null 2>&1; then
    ollama list 2>/dev/null | grep -q "qwen3.5:9b" || ollama pull qwen3.5:9b
  else
    echo "[run] WARNING: ollama not found — install it, then: ollama pull qwen3.5:9b"
  fi
fi

# 3. Launch (kaizen auto-builds its 3 ChromaDB collections on first run) -------
# NO --reload by default → stable, never restarts mid-run (live SSE stays open).
# Set RELOAD=1 for dev auto-reload (will interrupt running designs on file edits).
RELOAD_FLAG=""
[ "${RELOAD:-0}" = "1" ] && RELOAD_FLAG="--reload"
echo "[run] $APP  →  http://localhost:${PORT}   (RELOAD=${RELOAD:-0})"
exec .venv/bin/python -m uvicorn "$TARGET" --port "${PORT}" --timeout-graceful-shutdown 2 $RELOAD_FLAG
