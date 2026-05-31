# ═══════════════════════════════════════════════════════════════════════════
#  Gelochip Studio — self-contained Ubuntu image for the Kaizen RAG agent.
#
#  Bundles EVERYTHING needed to go from prompt → DRC-clean gf180 GDS:
#    • EDA tools:  magic 8.3.644, netgen 1.5.272, ngspice, klayout (pip)
#    • gf180 PDK:  open_pdks 0fe599b2… installed via volare into /pdks
#    • Python app: FastAPI + LangGraph RAG agent + ChromaDB (collections prebuilt)
#    • Models:     embedding model (all-MiniLM-L6-v2) + PixelatedRF inference
#                  weights + layoutRL PPO, all baked in (no runtime download)
#    • Frontend:   compiled React SPA (stage 1) served by FastAPI at "/"
#
#  A second compose service (pixelrf) reuses this image to serve the PixelatedRF
#  Designer on port 8001. The *_resume.pt training checkpoints are NOT bundled.
#
#  The LLM (qwen3.5:9b) is served by a separate `ollama` container — see
#  docker-compose.yml. Build + run with a single `docker compose up`.
# ═══════════════════════════════════════════════════════════════════════════

# ── Stage 1: build the React SPA ───────────────────────────────────────────────
FROM node:20-slim AS frontend
WORKDIR /fe
COPY app/frontend/package.json ./
RUN npm install
COPY app/frontend/ ./
# Build into /out; copied into the runtime image's app/static/web below.
RUN mkdir -p /out && npm run build -- --outDir /out --emptyOutDir


# ── Stage 2: EDA tools + Python runtime ────────────────────────────────────────
FROM ubuntu:22.04 AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PDK_ROOT=/pdks \
    HF_HOME=/opt/hf \
    HF_HUB_DISABLE_TELEMETRY=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/opt/eda/bin:/usr/local/bin:$PATH

# --- system deps: python, ngspice, build toolchain for magic/netgen -----------
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv python3-dev \
        ngspice ngspice-dev \
        git curl ca-certificates \
        build-essential m4 csh \
        tcl-dev tk-dev \
        libcairo2-dev mesa-common-dev libglu1-mesa-dev libx11-dev libncurses-dev \
        libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# --- magic 8.3.644 (DRC engine; APT's 8.3.105 is too old for gf180) -----------
# --retry/--retry-all-errors makes the GitHub download resilient to the transient
# "connection reset by peer" resets that codeload occasionally throws.
RUN curl -fL --retry 6 --retry-delay 4 --retry-all-errors -o /tmp/magic.tar.gz \
        https://github.com/RTimothyEdwards/magic/archive/refs/tags/8.3.644.tar.gz \
    && tar xzf /tmp/magic.tar.gz -C /tmp \
    && cd /tmp/magic-8.3.644 \
    && ./configure --prefix=/opt/eda \
    && make -j"$(nproc)" && make install \
    && rm -rf /tmp/magic*

# --- netgen 1.5.272 (LVS engine; kept for parity with the local toolchain) ----
RUN curl -fL --retry 6 --retry-delay 4 --retry-all-errors -o /tmp/netgen.tar.gz \
        https://github.com/RTimothyEdwards/netgen/archive/refs/tags/1.5.272.tar.gz \
    && tar xzf /tmp/netgen.tar.gz -C /tmp \
    && cd /tmp/netgen-1.5.272 \
    && ./configure --prefix=/opt/eda \
    && make -j"$(nproc)" && make install \
    && rm -rf /tmp/netgen*

# --- Python deps (CUDA torch: runs PixelatedRF + embeddings on GPU when present,
#     and falls back to CPU automatically on machines without a GPU) ------------
COPY requirements-app.txt /tmp/requirements-app.txt
RUN python3 -m pip install --no-cache-dir --upgrade pip \
    && python3 -m pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cu121 torch \
    && python3 -m pip install --no-cache-dir -r /tmp/requirements-app.txt \
    && python3 -m pip install --no-cache-dir volare

# --- gf180 PDK (minimal: magic/ngspice/netgen tech only, ~3 MB) ---------------
# The full open_pdks gf180mcu is 7.5 GB, dominated by digital standard cells
# (libs.ref) and klayout DRC decks the analog Magic flow never touches. We bundle
# just the Magic tech + SPICE models the agent's DRC/testbench needs (staged into
# pdk/ from a local volare install — see scripts/stage_pdk.sh). PDK_ROOT=/pdks.
COPY pdk/ /pdks/

# --- the application ----------------------------------------------------------
WORKDIR /app
COPY src/ ./src/
COPY app/ ./app/
COPY data/ ./data/
COPY scripts/ ./scripts/
# models/ ships the runnable weights (embedding · PixelatedRF inference ·
# layoutRL); the *_resume.pt training checkpoints are excluded via .dockerignore.
COPY models/ ./models/
COPY pyproject.toml README.md ./
# compiled React SPA from stage 1 → served by FastAPI at "/"
COPY --from=frontend /out ./app/static/web

ENV PYTHONPATH=/app/src

# Embedding model ships in models/embeddings/ (copied above) → fully offline.
# Re-fetch only if it's somehow missing.
RUN [ -f models/embeddings/all-MiniLM-L6-v2/config.json ] \
    || python3 -m gelochip.kaizen.embeddings

# --- prebuild the 3 ChromaDB collections from data/ (instant, offline start) --
RUN python3 -c "import sys; sys.path.insert(0,'src'); \
from gelochip.kaizen import collections; print('prebuilt:', collections.build_all())" \
    || echo "collections will build on first request"

EXPOSE 8090
# Robust serving: no --reload (never restarts mid-run), graceful shutdown.
CMD ["python3", "-m", "uvicorn", "app.kaizen_app:app", \
     "--host", "0.0.0.0", "--port", "8090", "--timeout-graceful-shutdown", "2"]
