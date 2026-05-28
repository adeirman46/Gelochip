"""
gelochip.kaizen  —  Kaizen RAG agent for gf180 RF/mmWave chip generation.

A self-correcting Retrieval-Augmented Generation pipeline (used *instead of*
SFT) backed by three local ChromaDB collections and a local Ollama LLM:

    config        paths, model names, collection names
    embeddings    shared local HuggingFace sentence-transformer
    collections   build / query the 3 ChromaDB collections + runtime lessons
    executor      run generated glayout code → GDS → DRC → preview
    agent         LangGraph plan→retrieve→generate→test→critic→kaizen loop

Quick start:
    from gelochip.kaizen import collections, agent
    collections.build_all()                 # one-time ingest
    state = agent.run("Design a gf180 NMOS current mirror, ratio 2")
    print(state["answer"])
"""
from gelochip.kaizen import config  # noqa: F401

__all__ = ["config", "embeddings", "collections", "executor", "agent"]
