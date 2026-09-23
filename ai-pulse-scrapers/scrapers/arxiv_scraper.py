"""ArXiv Atom API — standalone scraper (rate-limited)."""

from __future__ import annotations

import asyncio
import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

import httpx

from cache.file_cache import cached

from .schema import Article

try:
    from llm.quotas import human_to_slug, merge_category_lists
except ImportError:  # pragma: no cover
    def human_to_slug(label: str) -> str | None:  # type: ignore[misc]
        return None

    def merge_category_lists(*lists: list[str] | None) -> list[str]:  # type: ignore[misc]
        out: list[str] = []
        for lst in lists:
            for c in lst or []:
                if c not in out:
                    out.append(c)
        return out

logger = logging.getLogger(__name__)

ARXIV_API = "http://export.arxiv.org/api/query"

# Atom namespace for xml.etree.ElementTree (prefix form + Clark form)
NS = {"atom": "http://www.w3.org/2005/Atom"}
ATOM_NS = NS["atom"]


def _tag(local: str) -> str:
    return f"{{{ATOM_NS}}}{local}"


def _text(elem: ET.Element | None) -> str:
    if elem is None or elem.text is None:
        return ""
    return elem.text.strip()


def _parse_entry(entry: ET.Element) -> dict[str, Any] | None:
    title_raw = _text(entry.find(_tag("title")))
    title = " ".join(title_raw.split())  # strip newlines / collapse whitespace

    summary_el = entry.find(_tag("summary"))
    abstract_raw = _text(summary_el)
    abstract_clean = " ".join(abstract_raw.split())
    abstract = abstract_clean[:500] if len(abstract_clean) > 500 else abstract_clean

    authors: list[str] = []
    for author in entry.findall(_tag("author")):
        name = _text(author.find(_tag("name")))
        if name:
            authors.append(name)

    published_el = entry.find(_tag("published"))
    published = _text(published_el) if published_el is not None else ""

    id_el = entry.find(_tag("id"))
    abs_url = _text(id_el) if id_el is not None else ""

    pdf_url: str | None = None
    for link in entry.findall(_tag("link")):
        href = (link.get("href") or "").strip()
        rel = (link.get("rel") or "").lower()
        typ = (link.get("type") or "").lower()
        title_attr = (link.get("title") or "").lower()
        if rel == "alternate" and href and not abs_url:
            abs_url = href
        if "pdf" in typ or title_attr == "pdf" or href.lower().endswith(".pdf"):
            pdf_url = href

    if not abs_url:
        for link in entry.findall(_tag("link")):
            href = (link.get("href") or "").strip()
            rel = (link.get("rel") or "").lower()
            if rel == "alternate" and href:
                abs_url = href
                break

    if not pdf_url and abs_url and "/abs/" in abs_url:
        tail = abs_url.split("/abs/", 1)[1].rstrip("/")
        pdf_url = f"http://arxiv.org/pdf/{tail}.pdf"

    categories: list[str] = []
    for cat in entry.findall(_tag("category")):
        term = cat.get("term")
        if term:
            categories.append(term)

    if not title or not abs_url:
        logger.warning("Skipping ArXiv entry missing title or URL")
        return None

    return {
        "title": title,
        "abstract": abstract,
        "authors": authors,
        "published": published,
        "abstract_url": abs_url,
        "pdf_url": pdf_url or "",
        "categories": categories,
    }


@cached("arxiv")
async def search_arxiv(query: str, max_results: int = 10) -> list[dict[str, Any]]:
    """
    Query ArXiv Atom API. Returns a list of paper dicts, or [] on error.

    ``query`` may be plain keywords (wrapped as ``all:…``) or raw ArXiv syntax
    such as ``cat:cs.AR`` / ``cat:cs.RO``.
    """
    q = (query or "").strip()
    if not q:
        return []
    search_query = q if q.startswith(("cat:", "all:", "ti:", "abs:", "au:")) else f"all:{q}"
    params = {
        "search_query": search_query,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": max_results,
    }
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(ARXIV_API, params=params)
            response.raise_for_status()
            content = response.text

        root = ET.fromstring(content)
        out: list[dict[str, Any]] = []
        for entry in root.findall("atom:entry", NS):
            parsed = _parse_entry(entry)
            if parsed is not None:
                out.append(parsed)
        return out
    except Exception as e:
        logger.warning("search_arxiv failed for query=%r: %s", query, e)
        return []


CATEGORY_QUERIES: dict[str, list[str]] = {
    "AI/ML": [
        "large language model",
        "transformer architecture",
        "reinforcement learning",
        "generative AI",
    ],
    "chips & hardware": [
        "cat:cs.AR",
        "neural network accelerator",
        "GPU architecture",
        "chip design machine learning",
        "semiconductor hardware accelerator",
    ],
    "networking & cloud": [
        "software defined networking",
        "network optimization",
        "congestion control",
    ],
    "cybersecurity": [
        "adversarial machine learning",
        "intrusion detection",
        "LLM security",
    ],
    "autonomous vehicles": [
        "cat:cs.RO",
        "autonomous driving",
        "lidar perception",
        "motion planning",
        "robotaxi autonomous vehicle",
        "self-driving car",
        "autonomous truck",
        "delivery robot",
        "UAV drone regulation",
        "vehicle cybersecurity",
    ],
}

DEFAULT_CATEGORIES = list(CATEGORY_QUERIES.keys())


def _paper_to_article(paper: dict[str, Any]) -> Article:
    abstract = paper["abstract"]
    query_cats = list(paper.get("_query_cats") or [])
    arxiv_cats = list(paper.get("categories") or [])
    return Article(
        title=paper["title"],
        url=paper["abstract_url"],
        source_type="arxiv",
        source_name="ArXiv",
        snippet=abstract[:300],
        full_text=abstract,
        published_at=paper["published"] or None,
        fetched_at=datetime.now(timezone.utc).isoformat(),
        engagement=None,
        authors=list(paper["authors"]),
        categories=merge_category_lists(query_cats, arxiv_cats),
        image_url=None,
        extra={"pdf_url": paper["pdf_url"]},
    )


async def fetch_arxiv_articles(
    categories: list[str] | None = None,
    max_per_query: int = 10,
) -> list[Article]:
    """
    Fetch papers for each category query, strictly serialized for ArXiv rate limits.
    """
    cats = categories if categories is not None else DEFAULT_CATEGORIES
    sem = asyncio.Semaphore(1)
    all_papers: list[dict[str, Any]] = []
    first = True
    per_cat_raw: dict[str, int] = {}

    for cat in cats:
        queries = CATEGORY_QUERIES.get(cat)
        if not queries:
            logger.warning("Unknown category %r — skipping", cat)
            continue
        slug = human_to_slug(cat) or cat
        for q in queries:
            if not first:
                await asyncio.sleep(3)
            first = False
            logger.info("ArXiv query [%s]: %r", cat, q)
            async with sem:
                batch = await search_arxiv(q, max_results=max_per_query)
            for p in batch:
                row = dict(p)
                row["_query_cats"] = merge_category_lists(row.get("_query_cats"), [slug])
                all_papers.append(row)
                per_cat_raw[slug] = per_cat_raw.get(slug, 0) + 1

    by_url: dict[str, dict[str, Any]] = {}
    for p in all_papers:
        u = p["abstract_url"]
        if u not in by_url:
            by_url[u] = p
        else:
            by_url[u]["_query_cats"] = merge_category_lists(
                by_url[u].get("_query_cats"), p.get("_query_cats")
            )

    articles = [_paper_to_article(p) for p in by_url.values()]
    final_counts: dict[str, int] = {}
    for a in articles:
        for c in a.categories:
            if c in (
                "ai_ml",
                "chips_hardware",
                "networking_cloud",
                "cybersecurity",
                "autonomous_vehicles",
            ):
                final_counts[c] = final_counts.get(c, 0) + 1
    logger.info("ArXiv raw hits per category: %s", per_cat_raw)
    logger.info("fetch_arxiv_articles: %d unique papers; topic stamps %s", len(articles), final_counts)
    return articles


if __name__ == "__main__":
    import asyncio
    import json
    import sys
    from pathlib import Path

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    t0 = time.perf_counter()
    articles = asyncio.run(fetch_arxiv_articles())
    elapsed = time.perf_counter() - t0

    print(f"\nFetched {len(articles)} papers from ArXiv\n")
    for i, a in enumerate(articles[:10]):
        auth = ", ".join(a.authors) if a.authors else "(no authors)"
        snip = (a.snippet or "")[:200]
        print(f"{i + 1}. {a.title}")
        print(f"   Authors: {auth}")
        print(f"   Snippet: {snip}...")
        print()

    Path("output").mkdir(parents=True, exist_ok=True)
    out_path = Path("output") / "arxiv_papers.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump([a.to_dict() for a in articles], f, indent=2)
    print(f"Saved to {out_path}")
    print(f"Total execution time: {elapsed:.2f}s")
