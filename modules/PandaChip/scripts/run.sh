#!/bin/sh
# PandaChip — build (when needed) and run the web platform.
#
#   scripts/run.sh            → http://localhost:8317
#   scripts/run.sh :9000      → custom port
#
# Serves the React frontend (frontend/dist) through the Go server (web/),
# which spawns the agent (Ollama GLM 5.2 or Google Gemini via ADC) +
# OpenADA for every submitted prompt.
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
ADDR="${1:-:8317}"

# 0. Environment (.env: Google Cloud project for Gemini-via-ADC, etc.)
if [ -f "$ROOT/.env" ]; then
  set -a
  . "$ROOT/.env"
  set +a
fi

# 1. EDA container (xschem 3.4.8 / ngspice 46 / gf180mcuD live inside)
docker inspect -f '{{.State.Running}}' pandachip-eda 2>/dev/null | grep -q true \
  || "$ROOT/scripts/start_eda_container.sh"

# 2. React frontend (only rebuilds when sources changed)
if [ ! -f "$ROOT/frontend/dist/index.html" ] || \
   [ -n "$(find "$ROOT/frontend/src" "$ROOT/frontend/index.html" -newer "$ROOT/frontend/dist/index.html" 2>/dev/null | head -1)" ]; then
  echo "building frontend..."
  (cd "$ROOT/frontend" && npm run build)
fi

# 3. Go server (only rebuilds when sources changed)
if [ ! -x "$ROOT/web/pandachip-web" ] || \
   [ -n "$(find "$ROOT/web" -name '*.go' -newer "$ROOT/web/pandachip-web" 2>/dev/null | head -1)" ]; then
  echo "building web server..."
  (cd "$ROOT/web" && go build -o pandachip-web ./cmd/server)
fi

# 4. Run (replaces any previous instance)
pkill -x pandachip-web 2>/dev/null || true
sleep 0.5
echo "PandaChip -> http://localhost:${ADDR#:}   (sign in with any username/password)"
exec "$ROOT/web/pandachip-web" -root "$ROOT" -addr "$ADDR"
