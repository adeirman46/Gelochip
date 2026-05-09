"""
Search tools for the Gelochip agent.

- arxiv_search: Query ArXiv for analog/RF design papers
- web_search:   Fallback generic web search via Crawl4AI
"""
from __future__ import annotations
import asyncio
from typing import Any

import arxiv
from langchain_core.tools import tool


@tool
def arxiv_search(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """
    Search ArXiv for analog/RF/EDA papers.

    Args:
        query:       Search query (e.g. "cascode LNA 5GHz sky130 low noise figure").
        max_results: Maximum number of papers to return (default 5).

    Returns:
        List of dicts with keys: title, authors, summary, pdf_url, published.
    """
    client = arxiv.Client()
    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.Relevance,
    )
    results = []
    for paper in client.results(search):
        results.append({
            "title": paper.title,
            "authors": [a.name for a in paper.authors[:3]],
            "summary": paper.summary[:500],
            "pdf_url": paper.pdf_url,
            "published": str(paper.published.date()),
            "categories": paper.categories,
        })
    return results


@tool
def web_search_analog(query: str, max_pages: int = 3) -> list[dict[str, str]]:
    """
    Search the web for analog/RF design resources.

    Uses a simple HTTP-based search. For production use, configure
    a proper search API key (Google Custom Search / Bing / Brave).

    Args:
        query:     Search query string.
        max_pages: Maximum number of pages to fetch.

    Returns:
        List of dicts with keys: url, title, snippet.
    """
    try:
        from crawl4ai import AsyncWebCrawler
        from crawl4ai.extraction_strategy import LLMExtractionStrategy

        async def _crawl():
            results = []
            async with AsyncWebCrawler(verbose=False) as crawler:
                search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
                r = await crawler.arun(url=search_url)
                if r.success:
                    results.append({
                        "url": search_url,
                        "title": "Google Search",
                        "snippet": r.markdown[:500] if r.markdown else "",
                    })
            return results

        return asyncio.run(_crawl())
    except Exception as e:
        return [{"url": "", "title": "Search unavailable", "snippet": str(e)}]
