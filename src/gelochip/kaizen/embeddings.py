"""
gelochip.kaizen.embeddings  —  local embedding model, cached as a singleton.

Uses a HuggingFace sentence-transformer (default all-MiniLM-L6-v2) so the whole
RAG stack runs offline with no API keys. The model is downloaded ONCE, saved to
``models/embeddings/`` on disk, and loaded from there on every subsequent run —
so the app never reaches out to HuggingFace at runtime (no network, no token).
"""
from __future__ import annotations

import logging
from functools import lru_cache

from gelochip.kaizen import config

log = logging.getLogger("kaizen")


def _save_local(emb) -> None:
    """Persist the freshly-downloaded model to EMBED_DIR for offline reuse."""
    try:
        # langchain-huggingface stores the SentenceTransformer on _client (or client)
        client = getattr(emb, "_client", None) or getattr(emb, "client", None)
        if client is None and hasattr(emb, "show_progress"):  # lazy-init fallback
            from sentence_transformers import SentenceTransformer
            client = SentenceTransformer(config.EMBED_REPO)
        if client is not None and hasattr(client, "save"):
            config.EMBED_DIR.parent.mkdir(parents=True, exist_ok=True)
            client.save(str(config.EMBED_DIR))
            log.info("saved embedding model locally → %s", config.EMBED_DIR)
    except Exception as e:
        log.warning("could not save embedding model locally: %s", e)


@lru_cache(maxsize=1)
def get_embeddings():
    """Return a shared LangChain ``HuggingFaceEmbeddings`` instance.

    Loads from the on-disk copy if present, else downloads from HuggingFace once
    and saves it locally so future runs are fully offline.

    Silences the harmless ``embeddings.position_ids | UNEXPECTED`` load report:
    newer transformers dropped that non-functional position buffer, but the
    cached MiniLM checkpoint still includes it — it's ignored and the embedder
    works correctly.
    """
    import warnings

    try:
        from transformers.utils import logging as _hf_logging
        _hf_logging.set_verbosity_error()
    except Exception:
        pass
    from langchain_huggingface import HuggingFaceEmbeddings

    model_name = config.EMBED_MODEL
    is_local = (config.EMBED_DIR / "config.json").exists() and model_name == str(config.EMBED_DIR)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        emb = HuggingFaceEmbeddings(
            model_name=model_name,
            encode_kwargs={"normalize_embeddings": True},
        )

    if not is_local:                # just downloaded from HF → cache to disk
        _save_local(emb)
    return emb


def download_embedding_model() -> str:
    """Eagerly download + save the embedding model. Returns the local path."""
    get_embeddings()
    return str(config.EMBED_DIR)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("embedding model available at:", download_embedding_model())
