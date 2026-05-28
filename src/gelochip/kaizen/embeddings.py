"""
gelochip.kaizen.embeddings  —  local embedding model, cached as a singleton.

Uses a HuggingFace sentence-transformer (default all-MiniLM-L6-v2) so the whole
RAG stack runs offline with no API keys. The model is downloaded once to the
HuggingFace cache and reused across the agent, ingestion, and the web backend.
"""
from __future__ import annotations

from functools import lru_cache

from gelochip.kaizen import config


@lru_cache(maxsize=1)
def get_embeddings():
    """Return a shared LangChain ``HuggingFaceEmbeddings`` instance.

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

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return HuggingFaceEmbeddings(
            model_name=config.EMBED_MODEL,
            encode_kwargs={"normalize_embeddings": True},
        )
