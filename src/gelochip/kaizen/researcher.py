"""
gelochip.kaizen.researcher  —  Researcher + Extractor agents.

Researcher: finds external knowledge for a design request — arXiv papers, web
pages, and GitHub repos (all best-effort; degrades gracefully offline).
Extractor: turns the hits into text chunks and builds a **temporary** per-job
ChromaDB collection (`temp_research_<job>`) used as extra grounding during
generation. On a DRC-clean result the agent promotes this knowledge — plus the
verified code (process knowledge) and any error→fix lessons — into the permanent
collections, then drops the temp one.
"""
from __future__ import annotations

import re
import uuid
from typing import Any

from gelochip.kaizen import config


# Network timeout (s) for every external call — keeps the agent snappy offline.
NET_TIMEOUT = float(__import__("os").getenv("KAIZEN_NET_TIMEOUT", "8"))


# ── Researcher: external search (best-effort, hard-timeouts) ──────────────────
def search_arxiv(query: str, max_results: int = 4) -> list[dict]:
    """Query the arXiv API via httpx (https + follow redirects — the http URL 301s)."""
    try:
        import html
        import httpx
        r = httpx.get("https://export.arxiv.org/api/query",
                      params={"search_query": f"all:{query}", "max_results": max_results},
                      timeout=NET_TIMEOUT, follow_redirects=True)
        out = []
        for e in re.findall(r"<entry>(.*?)</entry>", r.text, re.S):
            t = re.search(r"<title>(.*?)</title>", e, re.S)
            s = re.search(r"<summary>(.*?)</summary>", e, re.S)
            u = re.search(r"<id>(.*?)</id>", e, re.S)
            if t and s:
                out.append({"title": html.unescape(t.group(1).strip()),
                            "text": html.unescape(re.sub(r"\s+", " ", s.group(1)).strip()),
                            "url": u.group(1).strip() if u else "", "source": "arxiv"})
        return out
    except Exception:
        return []


def search_web(query: str, max_results: int = 4, github: bool = False) -> list[dict]:
    """Web/GitHub search via the `ddgs` library (robust, no API key)."""
    q = query + (" site:github.com" if github else "")
    try:
        from ddgs import DDGS
        out = []
        for r in DDGS().text(q, max_results=max_results):
            out.append({"title": r.get("title", ""), "text": r.get("body", "") or "",
                        "url": r.get("href", "") or r.get("url", ""),
                        "source": "github" if github else "web"})
        return out
    except Exception:
        return []


def crawl_pages(urls: list[str], max_chars: int = 4000, max_imgs: int = 3) -> dict[str, dict]:
    """Use crawl4ai to extract page TEXT + IMAGES per URL (best-effort, hard-bounded).

    Returns {url: {"text": markdown, "images": [img_src, ...]}}. The whole crawl
    (browser launch + all pages) is capped by a total timeout so it can never hang
    the agent. Disable with KAIZEN_USE_CRAWL4AI=0.
    """
    import os
    if not urls or os.getenv("KAIZEN_USE_CRAWL4AI", "1") != "1":
        return {}
    try:
        import asyncio
        from crawl4ai import AsyncWebCrawler

        async def _run():
            res = {}
            async with AsyncWebCrawler(verbose=False) as crawler:
                for u in urls:
                    try:
                        out = await asyncio.wait_for(crawler.arun(url=u), timeout=NET_TIMEOUT)
                        md = (getattr(out, "markdown", "") or "")
                        if hasattr(md, "raw_markdown"):           # crawl4ai MarkdownResult
                            md = md.raw_markdown
                        md = str(md)[:max_chars]
                        # extract image URLs (figures, schematics, layouts)
                        media = getattr(out, "media", {}) or {}
                        imgs = []
                        for im in (media.get("images") or [])[: max_imgs * 3]:
                            src = im.get("src") or im.get("url") or ""
                            if src.startswith("http") and re.search(r"\.(png|jpe?g|gif|svg|webp)", src, re.I):
                                imgs.append(src)
                            if len(imgs) >= max_imgs:
                                break
                        if md or imgs:
                            res[u] = {"text": md, "images": imgs}
                    except Exception:
                        continue
            return res

        async def _bounded():
            return await asyncio.wait_for(_run(), timeout=NET_TIMEOUT * len(urls) + 25)
        return asyncio.run(_bounded())
    except Exception:
        return {}


def research(query: str, want: int = 8) -> list[dict]:
    """Gather external knowledge: arXiv + broad web + GitHub, with crawl4ai
    extracting full page TEXT and IMAGES (figures/schematics/layouts).
    De-duplicated; degrades to [] offline.

    Each doc: {title, text, url, source} where source ∈ {arxiv, web, github, image}.
    """
    docs = search_arxiv(query, max_results=4)
    web = search_web(query, max_results=4) + search_web(query, max_results=3, github=True)

    # crawl4ai: extract full text + images from the web/github hits
    crawled = crawl_pages([w["url"] for w in web if w.get("url")])
    images: list[dict] = []
    for w in web:
        page = crawled.get(w["url"], {})
        w["text"] = (page.get("text") or "").strip() or w.get("text") or w["title"]
        for src in page.get("images", []):
            images.append({"title": f"image from {w['title'][:60]}", "text": w["title"],
                           "url": src, "source": "image"})

    seen, uniq = set(), []
    for d in docs + web + images:
        key = d.get("url", "") or d.get("title", "")
        if key and key not in seen and (d.get("text") or d.get("source") == "image"):
            seen.add(key); uniq.append(d)
    return uniq[:want]


# ── Extractor: build a temporary per-job RAG collection ───────────────────────
def _temp_name(job_id: str) -> str:
    return f"temp_research_{re.sub(r'[^a-zA-Z0-9]', '', job_id)[:16]}"


def build_temp_rag(docs: list[dict], job_id: str):
    """Ingest researched docs into a TEMP ChromaDB under outputs/research_db."""
    from langchain_core.documents import Document
    from gelochip.kaizen.collections import get_vectorstore, _splitter

    store = get_vectorstore(_temp_name(job_id), persist_dir=config.RESEARCH_DB_DIR)
    splitter = _splitter(chunk_size=900, overlap=120)
    chunks: list[Document] = []
    for d in docs:
        for c in splitter.split_text(d["text"]):
            chunks.append(Document(page_content=f"{d['title']}\n{c}",
                                   metadata={"source": d["source"], "url": d.get("url", ""),
                                             "doc_type": "research"}))
    if chunks:
        ids = [f"res-{uuid.uuid4().hex[:8]}-{i}" for i in range(len(chunks))]
        store.add_documents(chunks, ids=ids)
    return store


def query_temp_rag(job_id: str, query: str, k: int = 3) -> list:
    from gelochip.kaizen.collections import get_vectorstore
    try:
        return get_vectorstore(_temp_name(job_id),
                               persist_dir=config.RESEARCH_DB_DIR).similarity_search(query, k=k)
    except Exception:
        return []


def drop_temp_rag(job_id: str) -> None:
    from gelochip.kaizen.collections import get_vectorstore
    try:
        get_vectorstore(_temp_name(job_id), persist_dir=config.RESEARCH_DB_DIR
                        )._client.delete_collection(_temp_name(job_id))
    except Exception:
        pass


# ── Persist on success: temp research + process knowledge → permanent ─────────
def persist_on_success(job_id: str, query: str, code: str, circuit: str,
                       research_docs: list[dict]) -> dict:
    """Promote temp research → rf_theory, and verified code → glayout_knowledge."""
    from langchain_core.documents import Document
    from gelochip.kaizen import collections

    added = {"theory": 0, "knowledge": 0}
    # 1. research knowledge → rf_theory (permanent)
    if research_docs:
        store = collections.get_vectorstore(config.COLL_THEORY)
        docs = [Document(page_content=f"{d['title']}\n{d['text']}",
                         metadata={"source": d["source"], "url": d.get("url", ""),
                                   "doc_type": "research", "circuit": circuit})
                for d in research_docs if d.get("text")]
        if docs:
            ids = [f"res-{collections._slug(circuit)}-{uuid.uuid4().hex[:6]}-{i}"
                   for i in range(len(docs))]
            store.add_documents(docs, ids=ids)
            added["theory"] = len(docs)
    # 2. verified process knowledge (the DRC-clean code) → glayout_knowledge
    if code.strip():
        collections.add_template(
            f"Generate DRC-clean glayout code for: {query}", code,
            circuit=circuit, source="agent_verified", also_jsonl=False)
        added["knowledge"] = 1
    drop_temp_rag(job_id)
    return added
