"""Hacker News via Algolia API — standalone scraper."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from cache.file_cache import cached

from .page_scraper import scrape_multiple
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

HN_ALGOLIA_SEARCH = "http://hn.algolia.com/api/v1/search"

DEFAULT_CATEGORIES = [
    "AI/ML",
    "chips & hardware",
    "networking & cloud",
    "cybersecurity",
    "autonomous vehicles",
]

CATEGORY_QUERIES: dict[str, list[str]] = {
    "AI/ML": [
        "artificial intelligence",
        "machine learning",
        "LLM",
        "GPT",
        "deep learning",
        "Claude AI",
        "OpenAI",
        "Anthropic",
    ],
    "chips & hardware": [
        "semiconductor",
        "NVIDIA",
        "TSMC",
        "GPU",
        "AMD",
        "chip",
        "Intel",
        "Apple silicon",
        "chip fabrication",
        "semiconductor export",
        "foundry",
        "HBM memory",
    ],
    "networking & cloud": [
        "data center",
        "Cisco",
        "Arista",
        "5G",
        "cloud infrastructure",
        "AWS",
        "Cloudflare",
        "Kubernetes",
    ],
    "cybersecurity": [
        "cybersecurity",
        "zero trust",
        "ransomware",
        "CrowdStrike",
        "data breach",
        "CVE",
        "vulnerability",
    ],
    "autonomous vehicles": [
        "self-driving",
        "autonomous vehicle",
        "Waymo",
        "robotaxi",
        "Tesla FSD",
        "lidar",
        "AV safety",
        "self-driving software",
        "AV regulation",
        "autonomous trucking",
        "self-driving car",
        "autonomous truck",
        "delivery robot",
        "drone delivery",
        "DJI drone",
        "FCC drone",
        "vehicle cybersecurity",
        "robotaxi regulation",
    ],
}


def _story_url(hit: dict[str, Any]) -> str:
    oid = str(hit.get("objectID", ""))
    external = (hit.get("url") or "").strip()
    if external:
        return external
    return f"https://news.ycombinator.com/item?id={oid}"


def _hit_to_raw(hit: dict[str, Any]) -> dict[str, Any]:
    oid = str(hit.get("objectID", ""))
    url = _story_url(hit)
    created_at_i = hit.get("created_at_i")
    if created_at_i is not None:
        created_at = datetime.fromtimestamp(int(created_at_i), tz=timezone.utc).isoformat()
    else:
        created_at = hit.get("created_at") or ""

    return {
        "title": (hit.get("title") or "").strip(),
        "url": url,
        "points": int(hit.get("points") or 0),
        "num_comments": int(hit.get("num_comments") or 0),
        "author": (hit.get("author") or "").strip(),
        "created_at": created_at,
        "objectID": oid,
    }


@cached("hn")
async def search_hn(
    query: str,
    min_points: int = 10,
    hours_back: int = 48,
    max_results: int = 15,
) -> list[dict[str, Any]]:
    """
    Search HN stories via Algolia. Returns raw hit dicts or [] on failure.
    """
    try:
        now = int(time.time())
        cutoff = now - hours_back * 3600
        numeric_filters = f"points>{min_points},created_at_i>{cutoff}"
        params = {
            "query": query,
            "tags": "story",
            "numericFilters": numeric_filters,
            "hitsPerPage": max_results,
        }
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.get(HN_ALGOLIA_SEARCH, params=params)
            response.raise_for_status()
            data = response.json()
        hits = data.get("hits") or []
        return [_hit_to_raw(h) for h in hits]
    except Exception as e:
        logger.warning("search_hn failed for query=%r: %s", query, e)
        return []


def _snippet_from_scrape(scraped: dict[str, Any] | None, title: str) -> str:
    if not scraped or scraped.get("error"):
        return (title or "")[:200] if title else ""
    md = scraped.get("meta_description") or ""
    mt = scraped.get("main_text") or ""
    body_prefix = mt[:200] if mt else ""
    return (md or body_prefix or (title or "")[:200] or "").strip() or (title or "")[:200]


def _full_text_from_scrape(scraped: dict[str, Any] | None) -> str | None:
    if not scraped or scraped.get("error"):
        return None
    return scraped.get("main_text")


def _image_from_scrape(scraped: dict[str, Any] | None) -> str | None:
    if not scraped or scraped.get("error"):
        return None
    og = scraped.get("og_image")
    return og if og else None


def _hit_to_article(hit: dict[str, Any], scraped: dict[str, Any] | None) -> Article:
    title = hit["title"] or "(no title)"
    cats = list(hit.get("_query_cats") or [])
    return Article(
        title=title,
        url=hit["url"],
        source_type="hackernews",
        source_name="HackerNews",
        snippet=_snippet_from_scrape(scraped, hit["title"]),
        full_text=_full_text_from_scrape(scraped),
        published_at=hit["created_at"] or None,
        fetched_at=datetime.now(timezone.utc).isoformat(),
        engagement={"points": hit["points"], "comments": hit["num_comments"]},
        authors=[hit["author"]] if hit.get("author") else [],
        categories=cats,
        image_url=_image_from_scrape(scraped),
        extra={"hn_url": f"https://news.ycombinator.com/item?id={hit['objectID']}"},
    )


async def fetch_hn_articles(
    categories: list[str] | None = None,
    hours_back: int = 168,
    max_per_query: int = 12,
    scrape_pages: bool = True,
) -> list[Article]:
    """Main entry point. Returns Article objects matching the shared schema."""
    cats = categories if categories is not None else DEFAULT_CATEGORIES
    all_hits: list[dict[str, Any]] = []
    per_cat_raw: dict[str, int] = {}

    for cat in cats:
        queries = CATEGORY_QUERIES.get(cat)
        if not queries:
            logger.warning("Unknown category %r — skipping", cat)
            continue
        slug = human_to_slug(cat) or cat
        logger.info("Category %r: running %d queries concurrently", cat, len(queries))
        batches = await asyncio.gather(
            *[
                search_hn(
                    q,
                    min_points=5,
                    hours_back=hours_back,
                    max_results=max_per_query,
                )
                for q in queries
            ]
        )
        n_batch = 0
        for batch in batches:
            for h in batch:
                row = dict(h)
                row["_query_cats"] = merge_category_lists(row.get("_query_cats"), [slug])
                all_hits.append(row)
                n_batch += 1
        per_cat_raw[slug] = per_cat_raw.get(slug, 0) + n_batch

    by_url: dict[str, dict[str, Any]] = {}
    for h in all_hits:
        u = h["url"]
        if u not in by_url:
            by_url[u] = h
            continue
        existing = by_url[u]
        if h["points"] > existing["points"]:
            # Winner keeps its primary category first.
            cats = merge_category_lists(h.get("_query_cats"), existing.get("_query_cats"))
            by_url[u] = h
            by_url[u]["_query_cats"] = cats
        else:
            by_url[u]["_query_cats"] = merge_category_lists(
                existing.get("_query_cats"), h.get("_query_cats")
            )

    sorted_hits = sorted(by_url.values(), key=lambda x: x["points"], reverse=True)
    logger.info("After dedupe: %d unique stories (by points desc)", len(sorted_hits))
    logger.info("HN raw hits per category: %s", per_cat_raw)

    scraped_by_url: dict[str, dict[str, Any]] = {}
    if scrape_pages and sorted_hits:
        top_urls = [h["url"] for h in sorted_hits[:40]]
        logger.info("Scraping top %d URLs (page content)", len(top_urls))
        scrape_results = await scrape_multiple(top_urls, max_concurrent=3)
        scraped_by_url = {u: r for u, r in zip(top_urls, scrape_results)}

    articles: list[Article] = []
    final_counts: dict[str, int] = {}
    for h in sorted_hits:
        if not (h.get("title") or "").strip():
            logger.warning("Skipping hit with empty title objectID=%s", h.get("objectID"))
            continue
        scraped = scraped_by_url.get(h["url"])
        art = _hit_to_article(h, scraped)
        articles.append(art)
        for c in art.categories:
            final_counts[c] = final_counts.get(c, 0) + 1
    logger.info("HN articles per category (after dedupe): %s", final_counts)

    return articles


if __name__ == "__main__":
    import asyncio, json, sys
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
    articles = asyncio.run(fetch_hn_articles())
    elapsed = time.perf_counter() - t0

    print(f"\n{'=' * 60}")
    print(f"Fetched {len(articles)} articles from HackerNews")
    print(f"{'=' * 60}\n")
    for i, a in enumerate(articles[:10]):
        print(f"{i + 1}. [{a.engagement['points']}↑] {a.title}")
        print(f"   {a.url}")
        print(f"   Snippet: {a.snippet[:100]}...")
        print()

    Path("output").mkdir(parents=True, exist_ok=True)
    output = [a.to_dict() for a in articles]
    with open("output/hn_articles.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    print("Full output saved to output/hn_articles.json")
    print(f"Total execution time: {elapsed:.2f}s")
