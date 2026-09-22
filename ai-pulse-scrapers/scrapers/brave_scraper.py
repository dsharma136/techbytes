"""Brave Search News API — standalone scraper."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

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

load_dotenv()

logger = logging.getLogger(__name__)

BRAVE_NEWS_URL = "https://api.search.brave.com/res/v1/news/search"

# Last successful response quota-related headers (for CLI / debugging)
_LAST_QUOTA_HEADERS: dict[str, str] = {}
_QUOTA_HEADERS_LOCK = threading.Lock()


def _brave_api_key() -> str:
    """Read key at call time so dotenv / env changes are respected."""
    return (os.getenv("BRAVE_API_KEY") or "").strip()


def _merge_quota_headers(headers: httpx.Headers) -> None:
    global _LAST_QUOTA_HEADERS
    for k, v in headers.items():
        kl = k.lower()
        if any(
            part in kl
            for part in (
                "rate",
                "quota",
                "limit",
                "remaining",
                "reset",
                "subscription",
                "usage",
                "brave",
            )
        ):
            _LAST_QUOTA_HEADERS[k] = v


CATEGORY_QUERIES: dict[str, list[str]] = {
    "AI/ML": [
        "AI product launch",
        "machine learning news today",
        "LLM update",
        "OpenAI Anthropic Google AI",
    ],
    "chips & hardware": [
        "semiconductor news today",
        "NVIDIA AMD news",
        "chip industry",
        "TSMC Intel GPU",
        "chip fabrication fab news",
        "semiconductor export controls",
        "GPU accelerator news",
        "chip foundry capacity",
    ],
    "networking & cloud": [
        "cloud infrastructure news",
        "data center networking",
        "5G telecom",
        "AWS Azure Cloudflare",
    ],
    "cybersecurity": [
        "cybersecurity breach today",
        "zero trust news",
        "ransomware attack today",
        "CVE vulnerability",
    ],
    "autonomous vehicles": [
        "autonomous vehicle news",
        "self-driving update",
        "robotaxi news",
        "Waymo Tesla FSD",
        "self-driving software update",
        "AV regulation news",
        "autonomous trucking news",
        "lidar robotaxi",
    ],
}

DEFAULT_CATEGORIES = list(CATEGORY_QUERIES.keys())


def extract_domain(url: str) -> str:
    """Return hostname without leading www."""
    try:
        p = urlparse(url.strip())
        host = p.netloc or ""
        if not host and p.path:
            host = p.path.split("/")[0]
        if host.lower().startswith("www."):
            host = host[4:]
        return host or "unknown"
    except Exception:
        return "unknown"


def convert_age_to_iso(age_str: str) -> str | None:
    """
    Best-effort: Brave relative ages like '5 hours ago', '2 days ago' → UTC ISO-8601.
    """
    if not age_str or not str(age_str).strip():
        return None
    s = str(age_str).strip().lower()
    now = datetime.now(timezone.utc)

    try:
        if s in ("just now", "now", "moments ago"):
            return now.isoformat()

        m = re.match(
            r"^(\d+)\s*(second|seconds|minute|minutes|hour|hours|day|days|week|weeks|month|months|year|years)\s+ago$",
            s,
        )
        if not m:
            return None
        n = int(m.group(1))
        unit = m.group(2)
        if unit.startswith("second"):
            delta = timedelta(seconds=n)
        elif unit.startswith("minute"):
            delta = timedelta(minutes=n)
        elif unit.startswith("hour"):
            delta = timedelta(hours=n)
        elif unit.startswith("day"):
            delta = timedelta(days=n)
        elif unit.startswith("week"):
            delta = timedelta(weeks=n)
        elif unit.startswith("month"):
            delta = timedelta(days=30 * n)
        elif unit.startswith("year"):
            delta = timedelta(days=365 * n)
        else:
            return None
        return (now - delta).isoformat()
    except Exception:
        return None


def _normalize_result(item: dict[str, Any]) -> dict[str, Any]:
    title = (item.get("title") or "").strip()
    url = (item.get("url") or "").strip()
    description = (item.get("description") or "").strip()
    age = (item.get("age") or "").strip()
    meta_url = item.get("meta_url")
    source_name = "Unknown"
    if isinstance(meta_url, dict):
        host = (meta_url.get("hostname") or "").strip()
        if host:
            source_name = host
    return {
        "title": title,
        "url": url,
        "description": description,
        "age": age,
        "source_name": source_name,
    }


@cached("brave")
async def search_brave_news(
    query: str, count: int = 8, freshness: str = "pw"
) -> list[dict[str, Any]]:
    """
    Search Brave News. Returns normalized dicts, or [] if unconfigured / on error.
    Retries once on HTTP 429 after a 2s delay.
    ``freshness``: Brave codes ``pd`` (day), ``pw`` (week), ``pm`` (month).
    """
    api_key = _brave_api_key()
    if not api_key:
        logger.error("BRAVE_API_KEY is not set; Brave scraper returning no results")
        return []

    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key,
    }
    params: dict[str, Any] = {"q": query, "count": count, "freshness": freshness}

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(BRAVE_NEWS_URL, headers=headers, params=params)
            if response.status_code == 429:
                logger.warning("Brave News 429 for query=%r — retrying in 2s", query)
                await asyncio.sleep(2.0)
                response = await client.get(BRAVE_NEWS_URL, headers=headers, params=params)

            if response.status_code >= 400:
                logger.warning(
                    "search_brave_news failed query=%r status=%s body=%s",
                    query,
                    response.status_code,
                    response.text[:500],
                )
                return []

            with _QUOTA_HEADERS_LOCK:
                _merge_quota_headers(response.headers)

            data = response.json()
            raw_results = data.get("results") or []
            return [_normalize_result(x) for x in raw_results if isinstance(x, dict)]
    except Exception as e:
        logger.warning("search_brave_news failed for query=%r: %s", query, e)
        return []


def _snippet_for_article(result: dict[str, Any], scraped: dict[str, Any] | None) -> str:
    desc = result.get("description") or ""
    if desc.strip():
        return desc.strip()
    if scraped and not scraped.get("error"):
        md = scraped.get("meta_description") or ""
        if isinstance(md, str) and md.strip():
            return md.strip()
    return ""


def _full_text(scraped: dict[str, Any] | None) -> str | None:
    if not scraped or scraped.get("error"):
        return None
    return scraped.get("main_text")


def _og_image(scraped: dict[str, Any] | None) -> str | None:
    if not scraped or scraped.get("error"):
        return None
    og = scraped.get("og_image")
    return og if og else None


def _result_to_article(result: dict[str, Any], scraped: dict[str, Any] | None) -> Article:
    url = result["url"]
    cats = list(result.get("_query_cats") or [])
    return Article(
        title=result["title"] or "(no title)",
        url=url,
        source_type="brave",
        source_name=extract_domain(url),
        snippet=_snippet_for_article(result, scraped),
        full_text=_full_text(scraped),
        published_at=convert_age_to_iso(result.get("age") or ""),
        fetched_at=datetime.now(timezone.utc).isoformat(),
        engagement=None,
        authors=[],
        categories=cats,
        image_url=_og_image(scraped),
        extra=None,
    )


async def fetch_brave_articles(
    categories: list[str] | None = None,
    results_per_query: int = 8,
    scrape_pages: bool = True,
    freshness: str = "pw",
) -> list[Article]:
    """
    Fetch news via Brave (serialized: 1 req/s free tier), optionally enrich with page_scraper.
    """
    global _LAST_QUOTA_HEADERS
    _LAST_QUOTA_HEADERS = {}

    if not _brave_api_key():
        logger.error("BRAVE_API_KEY is not set; Brave scraper returning no results")
        return []

    cats = categories if categories is not None else DEFAULT_CATEGORIES
    sem = asyncio.Semaphore(1)
    flat: list[dict[str, Any]] = []
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
                await asyncio.sleep(1)
            first = False
            logger.info("Brave query [%s]: %r", cat, q)
            async with sem:
                batch = await search_brave_news(
                    q, count=results_per_query, freshness=freshness
                )
            for item in batch:
                row = dict(item)
                row["_query_cats"] = merge_category_lists(row.get("_query_cats"), [slug])
                flat.append(row)
                per_cat_raw[slug] = per_cat_raw.get(slug, 0) + 1

    seen: set[str] = set()
    ordered: list[dict[str, Any]] = []
    by_url: dict[str, dict[str, Any]] = {}
    for r in flat:
        u = (r.get("url") or "").strip()
        if not u or not (u.startswith("http://") or u.startswith("https://")):
            continue
        if u not in by_url:
            by_url[u] = r
        else:
            by_url[u]["_query_cats"] = merge_category_lists(
                by_url[u].get("_query_cats"), r.get("_query_cats")
            )
    for u, r in by_url.items():
        if u in seen:
            continue
        seen.add(u)
        ordered.append(r)

    logger.info("Brave raw hits per category: %s", per_cat_raw)
    logger.info("Brave unique articles after dedupe: %s", len(ordered))

    scraped_by_url: dict[str, dict[str, Any]] = {}
    if scrape_pages and ordered:
        top_urls = [r["url"] for r in ordered[:30]]
        logger.info("Scraping top %d article URLs", len(top_urls))
        scrape_results = await scrape_multiple(top_urls, max_concurrent=3)
        scraped_by_url = {u: s for u, s in zip(top_urls, scrape_results)}

    articles: list[Article] = []
    final_counts: dict[str, int] = {}
    for r in ordered:
        if not (r.get("title") or "").strip() and not (r.get("url") or "").strip():
            continue
        u = r.get("url") or ""
        scraped = scraped_by_url.get(u)
        art = _result_to_article(r, scraped)
        articles.append(art)
        for c in art.categories:
            final_counts[c] = final_counts.get(c, 0) + 1
    logger.info("Brave articles per category (after dedupe): %s", final_counts)

    return articles


if __name__ == "__main__":
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
    articles = asyncio.run(fetch_brave_articles())
    elapsed = time.perf_counter() - t0

    print(f"\nFetched {len(articles)} articles from Brave News\n")
    for i, a in enumerate(articles[:10]):
        snip = (a.snippet or "")[:160]
        print(f"{i + 1}. {a.title}")
        print(f"   Source (domain): {a.source_name}")
        print(f"   Snippet: {snip}...")
        print()

    if _LAST_QUOTA_HEADERS:
        print("API quota / rate-limit headers (last responses):")
        for k, v in sorted(_LAST_QUOTA_HEADERS.items()):
            print(f"  {k}: {v}")
    else:
        print("No quota-related response headers captured (check API key or response).")

    Path("output").mkdir(parents=True, exist_ok=True)
    out_path = Path("output") / "brave_articles.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump([a.to_dict() for a in articles], f, indent=2)
    print(f"\nSaved to {out_path}")
    print(f"Total execution time: {elapsed:.2f}s")
