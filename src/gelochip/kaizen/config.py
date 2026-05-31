"""
gelochip.kaizen.config  —  central configuration for the Kaizen RAG agent.

Everything is local-first: a local ChromaDB on disk, a local HuggingFace
embedding model, and a local Ollama LLM. No cloud API keys required.

Override any value with an environment variable of the same name
(e.g. ``KAIZEN_LLM_MODEL=qwen3.5:9b``).
"""
from __future__ import annotations

import os
from pathlib import Path

# ── Project paths ─────────────────────────────────────────────────────────────
# .../src/gelochip/kaizen/config.py  →  project root is 4 levels up.
PROJECT_ROOT = Path(__file__).resolve().parents[3]

KAIZEN_DIR = PROJECT_ROOT / "notebooks" / "kaizen_architecture"
OUTPUT_DIR = Path(os.getenv("KAIZEN_OUTPUT_DIR", PROJECT_ROOT / "outputs" / "kaizen"))

# ── Dataset sources (clean top-level data/ tree) ──────────────────────────────
DATA_DIR = PROJECT_ROOT / "data"
CIRCUITS_DIR = DATA_DIR / "circuits"          # 15 DRC-clean circuit blocks (IP library)
SFT_DATASET_DIR = DATA_DIR / "glayout_code"   # human→glayout-code JSONL  → collection 1
RAW_DATA_DIR = DATA_DIR / "rf_theory"         # RF/mmWave books/papers    → collection 2
MODELS_DIR = PROJECT_ROOT / "models"          # local model weights

# Persistent ChromaDB lives under data/ ; the per-job research/extractor temp DB
# lives under outputs/ (ephemeral, promoted to the permanent store on DRC pass).
CHROMA_DIR = Path(os.getenv("KAIZEN_CHROMA_DIR", DATA_DIR / "chroma_db"))
RESEARCH_DB_DIR = Path(os.getenv("KAIZEN_RESEARCH_DB", OUTPUT_DIR / "research_db"))

# ── Models (all local) ────────────────────────────────────────────────────────
# Agent reasoning / code-generation LLM, served by Ollama.
LLM_MODEL = os.getenv("KAIZEN_LLM_MODEL", "qwen3.5:9b")
# Optional SFT-specialised model for the code-generation step only.
CODER_MODEL = os.getenv("KAIZEN_CODER_MODEL", "gds-qwen35-4b:latest")
# Vision model used by the Extractor to read figures/schematics/layouts the
# Researcher found. The default agent model (qwen3.5:9b) is itself multimodal
# (reports the `vision` capability in Ollama), so it doubles as the VLM — no
# extra pull needed. Override with KAIZEN_VLM_MODEL to use a dedicated VLM.
VLM_MODEL = os.getenv("KAIZEN_VLM_MODEL", "") or LLM_MODEL
VLM_MAX_IMAGES = int(os.getenv("KAIZEN_VLM_MAX_IMAGES", "3"))   # cap vision calls / run
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
LLM_TEMPERATURE = float(os.getenv("KAIZEN_LLM_TEMPERATURE", "0.2"))

# Local sentence-transformer embedding model (CPU-friendly, 384-dim).
# Saved on disk under models/ after the first download, then loaded from there
# (no HuggingFace download at runtime). Resolution order:
#   1. KAIZEN_EMBED_MODEL env (explicit override)
#   2. the saved local copy at EMBED_DIR, if present
#   3. the HuggingFace id (downloaded once, then auto-saved to EMBED_DIR)
EMBED_REPO = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_DIR = MODELS_DIR / "embeddings" / "all-MiniLM-L6-v2"


def _resolve_embed_model() -> str:
    env = os.getenv("KAIZEN_EMBED_MODEL")
    if env:
        return env
    if (EMBED_DIR / "config.json").exists():
        return str(EMBED_DIR)
    return EMBED_REPO


EMBED_MODEL = _resolve_embed_model()

# ── The three knowledge collections ───────────────────────────────────────────
COLL_TEMPLATES = "glayout_knowledge"   # 1: glayout layout/code knowledge (DRC-clean blocks)
COLL_THEORY = "rf_theory"              # 2: RF/mmWave theory (books, papers, notes)
COLL_LESSONS = "error_feedback"        # 3: error→fix feedback (starts EMPTY, grows at runtime)

ALL_COLLECTIONS = (COLL_TEMPLATES, COLL_THEORY, COLL_LESSONS)

# ── Retrieval / loop tuning ───────────────────────────────────────────────────
TOP_K_TEMPLATES = int(os.getenv("KAIZEN_TOPK_TEMPLATES", "3"))
TOP_K_THEORY = int(os.getenv("KAIZEN_TOPK_THEORY", "3"))
TOP_K_LESSONS = int(os.getenv("KAIZEN_TOPK_LESSONS", "3"))
MAX_KAIZEN_ITERS = int(os.getenv("KAIZEN_MAX_ITERS", "3"))   # generate→test→correct cycles

# ── EDA defaults ──────────────────────────────────────────────────────────────
PDK = "gf180"                                                # never sky130 (project rule)
PDK_ROOT = os.getenv("PDK_ROOT", str(Path.home() / "pdks"))

# ── Web server / production settings ──────────────────────────────────────────
# Comma-separated allowed CORS origins ("*" only in dev). e.g. "https://studio.acme.com"
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("KAIZEN_ALLOWED_ORIGINS", "*").split(",") if o.strip()]
MAX_CONCURRENT_RUNS = int(os.getenv("KAIZEN_MAX_CONCURRENT", "2"))   # heavy LLM+DRC jobs
MAX_PROMPT_CHARS = int(os.getenv("KAIZEN_MAX_PROMPT", "2000"))
JOB_TTL_SECONDS = int(os.getenv("KAIZEN_JOB_TTL", "1800"))          # reap finished jobs
LOG_LEVEL = os.getenv("KAIZEN_LOG_LEVEL", "INFO").upper()


def ensure_dirs() -> None:
    """Create the on-disk directories the agent writes to."""
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    RESEARCH_DB_DIR.mkdir(parents=True, exist_ok=True)
