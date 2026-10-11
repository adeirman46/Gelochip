#!/usr/bin/env bash
# =====================================================================
# AnoaChip — launch the web app: FastAPI backend + Vite frontend.
#
# Ensures the analog EDA tools (ngspice/magic/netgen) are on PATH, that
# Ollama + the Postgres/MinIO knowledge stack are up, starts the FastAPI
# backend (uvicorn, :8012) and, if the frontend is installed, the Vite
# dev server (:5175). AnoaChip uses :8012 / :5175 so it can run side-by-side
# with a GarudaChip instance on :8011 / :5173.
#
# Usage:
#   ./scripts/run.sh                 # backend + frontend
#   ./scripts/run.sh --backend-only  # just the API
# =====================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# --- Load .env so the backend gets ANOA_DATABASE_URL (Postgres :5434), the model,
#     PDK, etc. Without this the store falls back and can hit the wrong DB port. ---
if [ -f "$REPO_ROOT/.env" ]; then
  set -a; . "$REPO_ROOT/.env"; set +a
fi

# --- Analog EDA tools (AnoaChip's OWN env) + PDK_ROOT ---
export PDK_ROOT="${PDK_ROOT:-$HOME/pdks}"
export ANOA_ALLOW_GLAYOUT_TOOLS="${ANOA_ALLOW_GLAYOUT_TOOLS:-0}"
# AnoaChip builds magic/netgen/ngspice under .tools/eda (scripts/install.sh) so the
# app never depends on a system install. Put them FIRST on PATH.
if [ -d "$REPO_ROOT/.tools/eda/bin" ]; then
  export PATH="$REPO_ROOT/.tools/eda/bin:$PATH"
fi
# HEADLESS: magic/netgen are Tk-linked; clear DISPLAY so DRC/LVS never pop a window.
export DISPLAY=""
for b in ngspice magic netgen; do
  command -v "$b" >/dev/null 2>&1 \
    && echo "✓ $b: $(command -v $b)" \
    || echo "! $b not found — run ./scripts/install.sh to build the .tools/eda env"
done

# --- Ollama (local model) ---
if ! curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
  echo "! Ollama not on :11434 — starting it"
  nohup ollama serve >/tmp/ollama.log 2>&1 &
  sleep 3
fi

# --- Knowledge stack (Postgres pgvector + MinIO + SearXNG) ---
if command -v docker >/dev/null 2>&1; then
  docker compose up -d >/dev/null 2>&1 \
    && echo "✓ Knowledge stack up (Postgres :5434 · MinIO :9102 · SearXNG :8890)" \
    || echo "! Could not start docker compose — recall will be disabled."
fi

# --- Use the cached embeddings model offline (avoids HuggingFace name-resolution
#     hangs that silently skip knowledge ingest). Only if a HF cache already exists. ---
if [ -d "$HOME/.cache/huggingface" ]; then
  export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
fi

# --- Backend (FastAPI) ---
# --reload + --reload-dir so edits to the API (backend/) AND the pipeline engine
# (src/anoa_chip/app.py, runner imports) take effect WITHOUT a manual restart.
# --timeout-graceful-shutdown: a reload during a LIVE run used to WEDGE the server —
# the old worker stopped accepting new HTTP connections but waited forever for the
# open SSE run-stream to drain, so the whole UI "lagged" (every API call timed out)
# until the process was killed by hand. Cap the drain at 5 s: the run row is reaped
# on startup and `continue` resumes it.
echo "→ Starting FastAPI backend on http://localhost:8012 (auto-reload on code changes)"
( cd "$REPO_ROOT/backend" && exec uv run uvicorn anoa_api.main:app --port 8012 \
    --reload --reload-dir "$REPO_ROOT/backend" --reload-dir "$REPO_ROOT/src" \
    --timeout-graceful-shutdown 5 ) &
BACKEND_PID=$!
trap 'kill $BACKEND_PID 2>/dev/null || true' EXIT

if [ "${1:-}" = "--backend-only" ]; then
  wait $BACKEND_PID
  exit 0
fi

# --- Frontend (Vite) — port 5175, proxies /api to the backend on :8012 ---
if [ -d "$REPO_ROOT/frontend/node_modules" ]; then
  echo "→ Starting Vite frontend on http://localhost:5175"
  cd "$REPO_ROOT/frontend" && exec npm run dev
else
  echo "! Frontend deps not installed. In another terminal:"
  echo "    cd frontend && npm install && npm run dev"
  echo "  Backend is running; press Ctrl-C to stop."
  wait $BACKEND_PID
fi
