#!/usr/bin/env bash
# =====================================================================
# AnoaChip — one-shot installer
# Analog IC automation with local LLMs (Ollama) + Glayout (netlist→GDS)
# + ngspice (spec sim) + magic (DRC) + netgen (LVS).
#
# Installs, in order:
#   1. System deps (ngspice, magic, netgen)
#   2. uv (Python package/venv manager) + the Python environment
#      (pulls glayout from the sibling ../gLayout checkout, editable)
#   3. Ollama + the default local model (qwen3.5:9b)
#   4. Open PDKs (sky130 / gf180) via volare, if ~/pdks is empty
#   5. (optional) crawl4ai / Playwright for the web-research agent
#
# Re-running is safe: every step is skipped if already satisfied.
# Usage:
#   ./scripts/install.sh              # full install
#   SKIP_PDK=1 ./scripts/install.sh   # skip the PDK download (you have ~/pdks)
#   SKIP_WEB=1 ./scripts/install.sh   # skip crawl4ai web agent
# =====================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

OLLAMA_MODEL_DEFAULT="qwen3.5:9b"
say()  { printf "\n\033[1;36m==> %s\033[0m\n" "$*"; }
ok()   { printf "\033[1;32m   ✓ %s\033[0m\n" "$*"; }
warn() { printf "\033[1;33m   ! %s\033[0m\n" "$*"; }

# ---------------------------------------------------------------------
say "1/5  EDA tools (magic · netgen-LVS · ngspice) — AnoaChip's OWN local env"
# Self-contained: bootstrap micromamba (one static binary, no system conda) and
# build a private env under .tools/eda so a fresh clone NEVER depends on a system
# install or a sibling checkout. magic + ngspice come from conda-forge; the LVS
# netgen (opencircuitdesign, NOT the conda 3D-mesh 'netgen') is built from source.
TOOLS="$REPO_ROOT/.tools"
EDA="$TOOLS/eda"
export MAMBA_ROOT_PREFIX="$TOOLS/mamba"
if [ -x "$EDA/bin/magic" ] && [ -x "$EDA/bin/netgen" ] && [ -x "$EDA/bin/ngspice" ]; then
  ok "EDA env already built ($EDA/bin)"
else
  mkdir -p "$TOOLS/bin"
  if [ ! -x "$TOOLS/bin/micromamba" ]; then
    warn "bootstrapping micromamba (static binary)…"
    curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest \
      | tar -xj -C "$TOOLS" bin/micromamba
  fi
  ok "micromamba $("$TOOLS/bin/micromamba" --version)"
  if [ ! -x "$EDA/bin/magic" ] || [ ! -x "$EDA/bin/ngspice" ]; then
    warn "creating $EDA with magic + ngspice from conda-forge (a few hundred MB)…"
    "$TOOLS/bin/micromamba" create -y -p "$EDA" -c conda-forge magic ngspice \
      && ok "magic + ngspice installed" || warn "conda-forge install failed"
  fi
  # LVS netgen from source (needs tcl8.6-dev + build tools; conda-forge 'netgen' is
  # the unrelated 3D mesh generator, so we build the real one).
  if [ ! -x "$EDA/bin/netgen" ]; then
    warn "building netgen-LVS from source into $EDA…"
    command -v git >/dev/null || { sudo apt-get update -y && sudo apt-get install -y git; }
    dpkg -s tcl8.6-dev >/dev/null 2>&1 || sudo apt-get install -y tcl8.6-dev tk8.6-dev build-essential
    rm -rf "$TOOLS/src/netgen"; mkdir -p "$TOOLS/src"
    if git clone --depth 1 https://github.com/RTimothyEdwards/netgen "$TOOLS/src/netgen"; then
      ( cd "$TOOLS/src/netgen" \
        && ./configure --prefix="$EDA" --with-tcl=/usr/lib/tcl8.6 --with-tk=/usr/lib/tk8.6 \
        && make -j"$(nproc)" && make install ) \
        && ok "netgen-LVS built" || warn "netgen build failed — install it manually"
    fi
  fi
fi
[ -x "$EDA/bin/magic" ]  && ok "magic:  $("$EDA/bin/magic" --version 2>/dev/null | head -1)"
[ -x "$EDA/bin/netgen" ] && ok "netgen: present ($EDA/bin/netgen)"
[ -x "$EDA/bin/ngspice" ] && ok "ngspice: $("$EDA/bin/ngspice" --version 2>/dev/null | head -1)"

# ---------------------------------------------------------------------
say "2/5  uv + Python environment (glayout from ../gLayout, editable)"
if ! command -v uv >/dev/null 2>&1; then
  warn "uv not found — installing"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
ok "uv $(uv --version)"
if [ ! -d "../gLayout/src/glayout" ]; then
  warn "../gLayout not found — clone it as a sibling of this repo:"
  warn "  (cd .. && git clone https://github.com/idea-fasoc/OpenFASOC gLayout) — or adjust"
  warn "  [tool.uv.sources] glayout path in pyproject.toml to your checkout."
fi
say "    Creating venv + installing dependencies (pulls torch + glayout, may take a while)"
uv sync
ok "Python environment ready (.venv)"

if [ ! -f .env ]; then
  cp .env.example .env
  ok "Created .env from .env.example (defaults to local Ollama qwen3.5:9b, PDK sky130)"
else
  ok ".env already exists — leaving it untouched"
fi

# ---------------------------------------------------------------------
say "3/5  Ollama + local model"
if ! command -v ollama >/dev/null 2>&1; then
  warn "ollama not found — installing"
  curl -fsSL https://ollama.com/install.sh | sh
fi
ok "ollama present"
if ! curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
  warn "ollama server not responding — starting it in the background"
  nohup ollama serve >/tmp/ollama.log 2>&1 &
  sleep 3
fi
MODEL="${OLLAMA_MODEL:-$OLLAMA_MODEL_DEFAULT}"
if ollama list 2>/dev/null | grep -q "${MODEL%%:*}"; then
  ok "Model present: $(ollama list | grep "${MODEL%%:*}" | head -1 | awk '{print $1}')"
else
  warn "Pulling $MODEL (large download)…"
  ollama pull "$MODEL"
fi

# ---------------------------------------------------------------------
say "4/5  Open PDKs (sky130 / gf180)"
PDK_ROOT="${PDK_ROOT:-$HOME/pdks}"
if [ "${SKIP_PDK:-0}" = "1" ]; then
  warn "SKIP_PDK=1 — skipping PDK download"
elif [ -d "$PDK_ROOT/sky130A" ] || [ -d "$PDK_ROOT/gf180mcuD" ]; then
  ok "PDK(s) already present under $PDK_ROOT"
else
  warn "Enabling sky130 via volare into $PDK_ROOT (a few hundred MB)…"
  PDK_ROOT="$PDK_ROOT" uv run volare enable --pdk sky130 2>/dev/null \
    && ok "sky130 enabled at $PDK_ROOT/sky130A" \
    || warn "volare enable failed — install open_pdks/volare manually into $PDK_ROOT"
fi

# ---------------------------------------------------------------------
say "5/5  Web-research agent (optional)"
if [ "${SKIP_WEB:-0}" = "1" ]; then
  warn "SKIP_WEB=1 — skipping crawl4ai/Playwright"
else
  warn "Installing crawl4ai extra + Playwright chromium (needed for web crawling)"
  uv sync --extra web || warn "web extra failed (optional)"
  uv run crawl4ai-setup || warn "crawl4ai-setup reported issues"
  # crawl4ai-setup does NOT always fetch the browser — install chromium explicitly so
  # crawls don't hang for minutes trying to launch a missing browser.
  uv run playwright install chromium || warn "playwright chromium install failed (web crawl disabled)"
fi

say "Done!"
cat <<EOF

  AnoaChip is ready.

  Build the knowledge seed from your gLayout notebooks + cells:
      uv run python scripts/build_knowledge_seed.py

  Launch the unified flow with:
      ./scripts/run.sh

  Configuration lives in .env (chat model defaults to local Ollama: $OLLAMA_MODEL_DEFAULT;
  PDK defaults to sky130 under $PDK_ROOT).
EOF
