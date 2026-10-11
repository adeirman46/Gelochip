"""Web research tools for the PandaChip agent.

Ported from the Chip-Orchestra deep-agent research module, adapted to
analog design and kept stdlib-only. Gives the design agent the ability
to FIND INFORMATION ONLINE:

* ``search_web``      - topology/sizing knowledge, ngspice/xschem fix
                        hints, PDK facts. Backends, in order: a SearXNG
                        instance (``SEARXNG_URL``), Gemini google-search
                        grounding through the same Vertex-AI ADC the
                        gemini backend uses, then GitHub + Wikipedia APIs.
* ``fetch_reference`` - pull ONE page (paper, app note, repo README) as
                        text into ``context/refs/`` on demand.

Digests are saved under the run workspace so the evidence trail stays
inside the run. Disable everything with PANDACHIP_WEB_RESEARCH=0.
"""

from __future__ import annotations

import html
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

UA = ("Mozilla/5.0 (X11; Linux x86_64; rv:128.0) "
      "Gecko/20100101 Firefox/128.0")
MAX_DIGEST = 6000


def enabled() -> bool:
    return os.getenv("PANDACHIP_WEB_RESEARCH", "1").strip().lower() \
        not in ("0", "false", "no", "off")


def _get(url: str, data: bytes | None = None, headers: dict | None = None,
         timeout: int = 30) -> str:
    h = {"User-Agent": UA}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def _slug(text: str, n: int = 48) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:n] or "query"


def _html_to_text(page: str, max_chars: int) -> str:
    page = re.sub(r"(?is)<(script|style|nav|footer|header)[^>]*>.*?</\1>",
                  " ", page)
    page = re.sub(r"(?s)<[^>]+>", " ", page)
    page = html.unescape(page)
    page = re.sub(r"[ \t\r\f]+", " ", page)
    page = re.sub(r"\n\s*\n+", "\n\n", page)
    return page.strip()[:max_chars]


def _searx(query: str, limit: int = 6) -> list[dict]:
    base = os.getenv("SEARXNG_URL", "").rstrip("/")
    if not base:
        return []
    q = urllib.parse.urlencode({"q": query, "format": "json"})
    data = json.loads(_get(f"{base}/search?{q}"))
    return [{"title": r.get("title", ""), "url": r.get("url", ""),
             "snippet": r.get("content", "")}
            for r in data.get("results", [])[:limit]]


def _gemini_grounded(query: str) -> dict | None:
    """Google-search-grounded digest via the same Vertex ADC as gemini.py."""
    from . import gemini
    if not Path(gemini.ADC_PATH).exists():
        return None
    model = os.getenv("PANDACHIP_RESEARCH_MODEL", "gemini-3.5-flash")
    body = json.dumps({
        "contents": [{"role": "user", "parts": [{"text":
            "Research this analog/RF IC design question and answer as a "
            "compact engineering digest (facts, equations, typical values, "
            "concrete fixes). Question: " + query}]}],
        "tools": [{"googleSearch": {}}],
        "generationConfig": {"maxOutputTokens": 4096},
    }).encode()
    url = (f"https://aiplatform.googleapis.com/v1/projects/{gemini.project()}"
           f"/locations/{gemini.LOCATION}/publishers/google/models/"
           f"{model}:generateContent")
    data = json.loads(_get(url, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {gemini._access_token()}"}, timeout=120))
    cand = (data.get("candidates") or [{}])[0]
    text = "".join(p.get("text", "")
                   for p in cand.get("content", {}).get("parts", []))
    if not text.strip():
        return None
    meta = cand.get("groundingMetadata", {})
    sources = [c.get("web", {}).get("uri", "")
               for c in meta.get("groundingChunks", [])
               if c.get("web", {}).get("uri")]
    return {"digest": text, "sources": sources,
            "queries": meta.get("webSearchQueries", [])}


def _github(query: str, limit: int = 3) -> list[dict]:
    q = urllib.parse.urlencode({"q": query, "per_page": limit,
                                "sort": "stars"})
    headers = {"Accept": "application/vnd.github+json"}
    if os.getenv("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    data = json.loads(_get(f"https://api.github.com/search/repositories?{q}",
                           headers=headers))
    return [{"title": r.get("full_name", ""),
             "url": r.get("html_url", ""),
             "snippet": (r.get("description") or "")[:200]}
            for r in data.get("items", [])[:limit]]


def _wikipedia(query: str) -> dict | None:
    q = urllib.parse.urlencode({"action": "opensearch", "search": query,
                                "format": "json", "limit": 1})
    hits = json.loads(_get(f"https://en.wikipedia.org/w/api.php?{q}"))
    if not hits[1]:
        return None
    title = hits[1][0]
    page = json.loads(_get(
        "https://en.wikipedia.org/api/rest_v1/page/summary/"
        + urllib.parse.quote(title)))
    return {"title": title, "url": hits[3][0] if hits[3] else "",
            "snippet": page.get("extract", "")[:1500]}


def _save(ws_root: Path, name: str, content: str) -> str:
    refs = ws_root / "context" / "refs"
    refs.mkdir(parents=True, exist_ok=True)
    path = refs / name
    path.write_text(content)
    return str(path.relative_to(ws_root))


def search_web(ws_root: Path, query: str) -> dict:
    """Research a design question; digest is returned AND saved to refs/."""
    if not enabled():
        return {"ok": False, "error": "web research disabled "
                                      "(PANDACHIP_WEB_RESEARCH=0)"}
    parts: list[str] = [f"# Web research\n\nQuery: {query}\n"]
    sources: list[str] = []
    errors: list[str] = []

    try:  # 1. SearXNG metasearch + page fetches
        results = _searx(query)
        if results:
            parts.append("## Search results (SearXNG)\n" + "\n".join(
                f"- [{r['title']}]({r['url']}) - {r['snippet'][:200]}"
                for r in results))
            sources += [r["url"] for r in results]
            for r in results[:2]:
                try:
                    txt = _html_to_text(_get(r["url"], timeout=20), 2500)
                    parts.append(f"## Extract: {r['url']}\n{txt}")
                except Exception:
                    pass
    except Exception as exc:
        errors.append(f"searxng: {exc}")

    if len(parts) == 1:
        try:  # 2. Gemini google-search grounding (ADC)
            g = _gemini_grounded(query)
            if g:
                parts.append("## Grounded digest (Google Search via Gemini)\n"
                             + g["digest"])
                sources += g["sources"]
        except Exception as exc:
            errors.append(f"gemini-grounding: {exc}")

    try:  # 3. reference repos + encyclopedia, always cheap to add
        repos = _github(query)
        if repos:
            parts.append("## GitHub repositories\n" + "\n".join(
                f"- [{r['title']}]({r['url']}) - {r['snippet']}"
                for r in repos))
            sources += [r["url"] for r in repos]
    except Exception as exc:
        errors.append(f"github: {exc}")
    try:
        wiki = _wikipedia(query)
        if wiki:
            parts.append(f"## Wikipedia: {wiki['title']}\n{wiki['snippet']}")
            sources.append(wiki["url"])
    except Exception as exc:
        errors.append(f"wikipedia: {exc}")

    if len(parts) == 1:
        return {"ok": False,
                "error": "no research backend reachable: " + "; ".join(errors)}
    digest = "\n\n".join(parts)
    saved = _save(ws_root, _slug(query) + ".md", digest)
    return {"ok": True, "digest": digest[:MAX_DIGEST], "saved": saved,
            "sources": sources[:10]}


def fetch_reference(ws_root: Path, url: str) -> dict:
    """Fetch one web page / raw file as text into context/refs/."""
    if not enabled():
        return {"ok": False, "error": "web research disabled "
                                      "(PANDACHIP_WEB_RESEARCH=0)"}
    try:
        raw = _get(url, timeout=45)
    except Exception as exc:
        return {"ok": False, "error": f"fetch failed: {exc}"}
    text = _html_to_text(raw, 12000) if "<" in raw[:1000] else raw[:12000]
    saved = _save(ws_root, _slug(url) + ".md",
                  f"# Reference\n\nSource: {url}\n\n{text}")
    return {"ok": True, "saved": saved, "extract": text[:MAX_DIGEST]}
