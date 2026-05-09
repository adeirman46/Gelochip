"""
Search tools for the Gelochip agent.

- arxiv_search: Query ArXiv for analog/RF design papers
- web_search:   Fallback generic web search via Crawl4AI
"""
from __future__ import annotations
import asyncio
from pathlib import Path
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
def download_paper_figures(
    pdf_url: str,
    paper_id: str,
    max_figures: int = 4,
    output_dir: str | None = None,
) -> dict:
    """
    Download an ArXiv paper PDF, save it, and extract figures (circuit diagrams).

    Uses PyMuPDF (fitz) to extract images from the PDF pages.
    Images are filtered to >100x100 pixels to skip decorative elements.
    The PDF itself is saved as paper.pdf alongside the figures.

    Args:
        pdf_url:     Direct URL to the PDF (e.g. https://arxiv.org/pdf/2301.12345).
        paper_id:    ArXiv paper ID (used as the output sub-directory name).
        max_figures: Maximum number of figures to extract (default 4).
        output_dir:  Where to save figures and PDF. Defaults to
                     /tmp/gelochip_output/paper_figures/{paper_id}.

    Returns:
        Dict with keys:
            saved_paths (list[str]): Absolute paths to saved PNG files.
            pdf_path    (str|None):  Absolute path to the saved PDF file.
            count       (int):       Number of figures successfully extracted.
            error       (str|None):  Error message, or None on success.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return {"saved_paths": [], "pdf_path": None, "count": 0, "error": "PyMuPDF not installed. Run: pip install pymupdf"}

    try:
        import httpx
    except ImportError:
        return {"saved_paths": [], "pdf_path": None, "count": 0, "error": "httpx not installed. Run: pip install httpx"}

    import shutil
    import tempfile

    if output_dir:
        fig_dir = Path(output_dir)
    else:
        _here = Path(__file__).resolve()
        for _p in _here.parents:
            if (_p / "pyproject.toml").exists():
                fig_dir = _p / "outputs" / "papers" / paper_id
                break
        else:
            fig_dir = Path.cwd() / "outputs" / "papers" / paper_id
    fig_dir.mkdir(parents=True, exist_ok=True)

    saved_paths: list[str] = []
    pdf_save_path: str | None = None

    try:
        # Download the PDF to a temporary file
        with httpx.Client(follow_redirects=True, timeout=60.0) as client:
            response = client.get(pdf_url)
            response.raise_for_status()

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_pdf:
            tmp_pdf.write(response.content)
            tmp_pdf_path = tmp_pdf.name

        try:
            # Save a permanent copy of the PDF
            dest_pdf = fig_dir / "paper.pdf"
            shutil.copy2(tmp_pdf_path, str(dest_pdf))
            pdf_save_path = str(dest_pdf)

            doc = fitz.open(tmp_pdf_path)
            figure_index = 0

            for page_num in range(len(doc)):
                if figure_index >= max_figures:
                    break

                page = doc[page_num]
                image_list = page.get_images(full=True)

                for img_info in image_list:
                    if figure_index >= max_figures:
                        break

                    xref = img_info[0]
                    try:
                        base_image = doc.extract_image(xref)
                        width  = base_image.get("width", 0)
                        height = base_image.get("height", 0)

                        # Skip thumbnails and decorative images
                        if width < 100 or height < 100:
                            continue

                        image_bytes = base_image["image"]
                        png_path = fig_dir / f"fig_{figure_index}.png"

                        # Convert to PNG regardless of original format using fitz
                        pix = fitz.Pixmap(fitz.csRGB, fitz.Pixmap(image_bytes))
                        pix.save(str(png_path))

                        saved_paths.append(str(png_path))
                        figure_index += 1

                    except Exception:
                        # Skip images that can't be extracted
                        continue

            doc.close()
        finally:
            Path(tmp_pdf_path).unlink(missing_ok=True)

        return {"saved_paths": saved_paths, "pdf_path": pdf_save_path, "count": len(saved_paths), "error": None}

    except Exception as exc:
        return {"saved_paths": saved_paths, "pdf_path": pdf_save_path, "count": len(saved_paths), "error": str(exc)}


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
