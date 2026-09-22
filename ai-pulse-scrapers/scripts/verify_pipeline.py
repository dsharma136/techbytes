"""
Live pipeline verification for TechBytes.

Usage (from ``ai-pulse-scrapers``)::

    python -m scripts.verify_pipeline
    python -m scripts.verify_pipeline --skip-llm

Bypasses the file cache (``AI_PULSE_NO_CACHE=1``). Never prints API keys.
Writes ``output/verify_report.json``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["AI_PULSE_NO_CACHE"] = "1"
load_dotenv(ROOT / ".env")

from cache import file_cache  # noqa: E402
from llm import processor as llm_processor  # noqa: E402
from llm.processor import (  # noqa: E402
    _CARD_CATEGORIES,
    cluster_articles,
    generate_cards,
)
from scrapers import arxiv_scraper, brave_scraper, hn_scraper  # noqa: E402
from scrapers.page_scraper import scrape_multiple  # noqa: E402
from scrapers.schema import Article  # noqa: E402

logger = logging.getLogger("verify_pipeline")

OUTPUT_DIR = ROOT / "output"
REPORT_PATH = OUTPUT_DIR / "verify_report.json"
FEEDS_DIR = ROOT / "data" / "feeds"
API_BASE = os.environ.get("VERIFY_API_BASE", "http://127.0.0.1:8000")
MAX_AGE_DAYS = 7

# Frontend contract (FeedCard / CardExpanded / ShareCard / utils)
FRONTEND_CARD_FIELDS = {
    "headline": {"required": True},
    "blurb": {"required": True},
    "why_it_matters": {"required": True},
    "category": {"required": True},
    "is_research_paper": {"required": False},
    "importance_score": {"required": False},
    "order": {"required": False},
    "published_at": {"required": False, "note": "falls back to feed generated_at on client"},
    "sources": {"required": True},
    "id": {"required": False, "note": "client-generated via stableCardId when missing"},
}
FRONTEND_SOURCE_FIELDS = {
    "title": {"required": False},
    "url": {"required": True},
    "source_type": {"required": False},
    "source_name": {"required": False},
    "engagement": {"required": False, "note": "HN points/comments for ranking"},
    "published_at": {"required": False},
}

_checks: list[dict[str, Any]] = []
_report: dict[str, Any] = {
    "generated_at": None,
    "skip_llm": False,
    "checks": [],
    "summary": {},
}


def _line(status: str, name: str, detail: str = "", samples: list[Any] | None = None) -> None:
    samples = samples or []
    sample_s = ""
    if samples:
        shown = []
        for s in samples[:3]:
            shown.append(str(s)[:120])
        sample_s = " | samples: " + "; ".join(shown)
    msg = f"{status} {name}" + (f" — {detail}" if detail else "") + sample_s
    # Avoid Windows console encoding crashes on arrows / fancy dashes
    print(msg.replace("—", "-").replace("→", "->"))
    entry = {
        "status": status,
        "name": name,
        "detail": detail,
        "samples": [str(s)[:200] for s in samples[:5]],
    }
    _checks.append(entry)
    _report["checks"].append(entry)


def _pass(name: str, detail: str = "", samples: list[Any] | None = None) -> None:
    _line("PASS", name, detail, samples)


def _warn(name: str, detail: str = "", samples: list[Any] | None = None) -> None:
    _line("WARN", name, detail, samples)


def _fail(name: str, detail: str = "", samples: list[Any] | None = None) -> None:
    _line("FAIL", name, detail, samples)


def _rate_headers(headers: httpx.Headers) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in headers.items():
        kl = k.lower()
        if any(
            p in kl
            for p in ("rate", "quota", "limit", "remaining", "retry", "reset", "subscription")
        ):
            out[k] = v
    return out


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _is_old(published_at: str | None, days: int = MAX_AGE_DAYS) -> bool:
    dt = _parse_dt(published_at)
    if not dt:
        return False
    return datetime.now(timezone.utc) - dt > timedelta(days=days)


def _completeness(
    items: list[dict[str, Any]],
    *,
    require_points: bool,
) -> tuple[float, list[str]]:
    if not items:
        return 0.0, []
    incomplete: list[str] = []
    ok = 0
    for it in items:
        title = (it.get("title") or "").strip()
        url = (it.get("url") or "").strip()
        source = (it.get("source") or it.get("source_name") or "").strip()
        published = it.get("published_at") or it.get("published") or it.get("created_at")
        missing: list[str] = []
        if not title:
            missing.append("title")
        if not url:
            missing.append("url")
        if not source:
            missing.append("source")
        if not published:
            missing.append("published")
        if require_points:
            pts = it.get("points")
            if pts is None and isinstance(it.get("engagement"), dict):
                pts = it["engagement"].get("points")
            if pts is None:
                missing.append("points")
        if missing:
            incomplete.append(f"{title[:40] or url[:40]}: missing {','.join(missing)}")
        else:
            ok += 1
    return 100.0 * ok / len(items), incomplete


def _dup_urls(items: list[dict[str, Any]]) -> list[str]:
    c: Counter[str] = Counter()
    for it in items:
        u = (it.get("url") or "").strip()
        if u:
            c[u] += 1
    return [u for u, n in c.items() if n > 1]


# ---------------------------------------------------------------------------
# Source probes
# ---------------------------------------------------------------------------


async def _probe_hn() -> list[Article]:
    name = "Hacker News"
    queries_flat: list[tuple[str, str]] = []
    for cat, qs in hn_scraper.CATEGORY_QUERIES.items():
        for q in qs:
            queries_flat.append((cat, q))

    per_query: list[dict[str, Any]] = []
    all_raw: list[dict[str, Any]] = []
    statuses: list[int] = []
    rate_hdrs: dict[str, str] = {}

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        # Run queries with limited concurrency
        sem = asyncio.Semaphore(4)

        async def one(cat: str, q: str) -> None:
            async with sem:
                now = int(time.time())
                cutoff = now - 48 * 3600
                params = {
                    "query": q,
                    "tags": "story",
                    "numericFilters": f"points>10,created_at_i>{cutoff}",
                    "hitsPerPage": 10,
                }
                try:
                    r = await client.get(hn_scraper.HN_ALGOLIA_SEARCH, params=params)
                    statuses.append(r.status_code)
                    rate_hdrs.update(_rate_headers(r.headers))
                    hits = []
                    if r.status_code == 200:
                        data = r.json()
                        hits = [hn_scraper._hit_to_raw(h) for h in (data.get("hits") or [])]
                        for h in hits:
                            h["source"] = "HackerNews"
                            h["published_at"] = h.get("created_at")
                    per_query.append(
                        {
                            "category": cat,
                            "query": q,
                            "status": r.status_code,
                            "count": len(hits),
                        }
                    )
                    all_raw.extend(hits)
                except Exception as e:
                    per_query.append(
                        {"category": cat, "query": q, "status": 0, "count": 0, "error": str(e)}
                    )

        await asyncio.gather(*(one(c, q) for c, q in queries_flat))

    pct, incomplete = _completeness(all_raw, require_points=True)
    dups = _dup_urls(all_raw)
    old = [x for x in all_raw if _is_old(x.get("published_at"))]
    bad_status = [s for s in statuses if s and s >= 400]

    detail = (
        f"queries={len(queries_flat)} items={len(all_raw)} completeness={pct:.0f}% "
        f"cross_query_dups={len(dups)} old(>{MAX_AGE_DAYS}d)={len(old)} statuses={Counter(statuses)}"
    )
    samples = [f"{p['query']}:{p['count']}" for p in per_query[:5]]
    # Cross-query duplicate URLs are expected; scrapers dedupe later.
    if bad_status or pct < 80 or not all_raw:
        _fail(name, detail, samples + incomplete[:2])
    elif pct < 95 or old:
        _warn(name, detail, samples + incomplete[:2])
    else:
        _pass(name, detail, samples)

    if rate_hdrs:
        _pass(f"{name} rate-limit headers", json.dumps(rate_hdrs)[:200])
    else:
        _warn(f"{name} rate-limit headers", "none returned (Algolia often omits them)")

    # Full article objects via scraper (cache bypassed)
    articles = await hn_scraper.fetch_hn_articles(
        categories=["AI/ML", "cybersecurity"],
        max_per_query=5,
        scrape_pages=False,
    )
    return articles


async def _probe_arxiv() -> list[Article]:
    name = "arXiv"
    queries_flat: list[tuple[str, str]] = []
    for cat, qs in arxiv_scraper.CATEGORY_QUERIES.items():
        for q in qs:
            queries_flat.append((cat, q))

    per_query: list[dict[str, Any]] = []
    all_raw: list[dict[str, Any]] = []
    statuses: list[int] = []
    rate_hdrs: dict[str, str] = {}

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        first = True
        for cat, q in queries_flat:
            if not first:
                await asyncio.sleep(3.0)
            first = False
            params = {
                "search_query": f"all:{q}",
                "sortBy": "submittedDate",
                "sortOrder": "descending",
                "max_results": 6,
            }
            try:
                r = await client.get(arxiv_scraper.ARXIV_API, params=params)
                statuses.append(r.status_code)
                rate_hdrs.update(_rate_headers(r.headers))
                papers: list[dict[str, Any]] = []
                if r.status_code == 200:
                    import xml.etree.ElementTree as ET

                    root = ET.fromstring(r.text)
                    for entry in root.findall("atom:entry", arxiv_scraper.NS):
                        parsed = arxiv_scraper._parse_entry(entry)
                        if parsed:
                            papers.append(
                                {
                                    "title": parsed["title"],
                                    "url": parsed["abstract_url"],
                                    "source": "ArXiv",
                                    "published_at": parsed.get("published"),
                                    "published": parsed.get("published"),
                                }
                            )
                per_query.append(
                    {"category": cat, "query": q, "status": r.status_code, "count": len(papers)}
                )
                all_raw.extend(papers)
            except Exception as e:
                per_query.append(
                    {"category": cat, "query": q, "status": 0, "count": 0, "error": str(e)}
                )
                await asyncio.sleep(3.0)

    pct, incomplete = _completeness(all_raw, require_points=False)
    dups = _dup_urls(all_raw)
    old = [x for x in all_raw if _is_old(x.get("published_at"))]
    rate_limited = statuses.count(429)

    detail = (
        f"queries={len(queries_flat)} items={len(all_raw)} completeness={pct:.0f}% "
        f"cross_query_dups={len(dups)} old={len(old)} http429={rate_limited} statuses={Counter(statuses)}"
    )
    samples = [f"{p['query']}:{p['status']}/{p['count']}" for p in per_query if p["status"] != 200][
        :5
    ] or [f"{p['query']}:{p['count']}" for p in per_query[:3]]

    if not all_raw or pct < 70:
        _fail(name, detail, samples + incomplete[:2])
    elif rate_limited or pct < 90:
        _warn(name, detail, samples)
    else:
        _pass(name, detail, samples)

    if rate_hdrs:
        _pass(f"{name} rate-limit headers", json.dumps(rate_hdrs)[:200])
    else:
        _warn(f"{name} rate-limit headers", "none returned")

    articles = await arxiv_scraper.fetch_arxiv_articles(
        categories=["AI/ML", "cybersecurity"],
        max_per_query=4,
    )
    return articles


async def _probe_brave() -> list[Article]:
    name = "Brave News"
    key = (os.getenv("BRAVE_API_KEY") or "").strip()
    # Prefer live getenv over import-time constant
    if not key:
        _fail(name, "BRAVE_API_KEY missing or empty - Brave scraper cannot run")
        return []

    queries_flat: list[tuple[str, str]] = []
    for cat, qs in brave_scraper.CATEGORY_QUERIES.items():
        for q in qs:
            queries_flat.append((cat, q))

    per_query: list[dict[str, Any]] = []
    all_raw: list[dict[str, Any]] = []
    statuses: list[int] = []
    rate_hdrs: dict[str, str] = {}
    auth_rejected = False

    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": key,
    }

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        first = True
        for cat, q in queries_flat:
            if not first:
                await asyncio.sleep(1.0)
            first = False
            params = {"q": q, "count": 5, "freshness": "pd"}
            try:
                r = await client.get(brave_scraper.BRAVE_NEWS_URL, headers=headers, params=params)
                statuses.append(r.status_code)
                rate_hdrs.update(_rate_headers(r.headers))
                if r.status_code in (401, 403):
                    auth_rejected = True
                results: list[dict[str, Any]] = []
                if r.status_code == 200:
                    data = r.json()
                    for item in data.get("results") or []:
                        if not isinstance(item, dict):
                            continue
                        n = brave_scraper._normalize_result(item)
                        results.append(
                            {
                                "title": n["title"],
                                "url": n["url"],
                                "source": n["source_name"] or brave_scraper.extract_domain(n["url"]),
                                "published_at": brave_scraper.convert_age_to_iso(n.get("age") or ""),
                                "age": n.get("age"),
                            }
                        )
                per_query.append(
                    {"category": cat, "query": q, "status": r.status_code, "count": len(results)}
                )
                all_raw.extend(results)
            except Exception as e:
                per_query.append(
                    {"category": cat, "query": q, "status": 0, "count": 0, "error": str(e)}
                )

    if auth_rejected:
        _fail(name, "BRAVE_API_KEY rejected (HTTP 401/403)", [str(Counter(statuses))])
        return []

    pct, incomplete = _completeness(all_raw, require_points=False)
    dups = _dup_urls(all_raw)
    old = [x for x in all_raw if _is_old(x.get("published_at"))]
    missing_pub = sum(1 for x in all_raw if not x.get("published_at"))

    detail = (
        f"queries={len(queries_flat)} items={len(all_raw)} completeness={pct:.0f}% "
        f"dups={len(dups)} old={len(old)} missing_published={missing_pub} "
        f"statuses={Counter(statuses)}"
    )
    samples = [f"{p['query']}:{p['status']}/{p['count']}" for p in per_query[:4]]

    if not all_raw:
        _fail(name, detail, samples)
    elif pct < 70:
        _fail(name, detail, samples + incomplete[:3])
    elif missing_pub > len(all_raw) * 0.4 or pct < 90:
        _warn(name, detail, samples + incomplete[:2])
    else:
        _pass(name, detail, samples)

    if rate_hdrs:
        _pass(f"{name} rate-limit headers", json.dumps(rate_hdrs)[:240])
    else:
        _warn(f"{name} rate-limit headers", "none captured")

    articles = await brave_scraper.fetch_brave_articles(
        categories=["AI/ML", "cybersecurity"],
        results_per_query=4,
        scrape_pages=False,
    )
    return articles


async def _probe_page_scraper(urls: list[str]) -> None:
    name = "page scraper"
    urls = [u for u in urls if u.startswith("http")][:12]
    if not urls:
        _warn(name, "no URLs to scrape")
        return
    results = await scrape_multiple(urls, max_concurrent=3)
    ok = 0
    lengths: list[int] = []
    reasons: Counter[str] = Counter()
    for u, r in zip(urls, results):
        err = r.get("error")
        text = r.get("main_text") or ""
        if err:
            el = str(err).lower()
            if "timeout" in el or "timed out" in el:
                reasons["timeout"] += 1
            elif any(x in el for x in ("403", "401", "blocked", "forbidden")):
                reasons["blocked"] += 1
            elif "404" in el:
                reasons["not_found"] += 1
            else:
                reasons["other_error"] += 1
        elif not text.strip():
            reasons["empty_text"] += 1
        else:
            ok += 1
            lengths.append(len(text))

    avg_len = int(sum(lengths) / len(lengths)) if lengths else 0
    rate = 100.0 * ok / len(urls)
    detail = f"success={ok}/{len(urls)} ({rate:.0f}%) avg_text_len={avg_len} failures={dict(reasons)}"
    if rate < 40:
        _fail(name, detail)
    elif rate < 70:
        _warn(name, detail)
    else:
        _pass(name, detail)


# ---------------------------------------------------------------------------
# LLM / cards / API / frontend contract
# ---------------------------------------------------------------------------


async def _probe_llm(articles: list[Article]) -> tuple[list[dict[str, Any]], list[Article]]:
    parse_meta = {"first_try_ok": None, "calls": 0}

    orig_parse = llm_processor._parse_json_llm

    def tracked_parse(text: str) -> Any:
        parse_meta["calls"] += 1
        cleaned = llm_processor._strip_markdown_fences(text)
        try:
            json.loads(cleaned)
            if parse_meta["first_try_ok"] is None:
                parse_meta["first_try_ok"] = True
        except json.JSONDecodeError:
            if parse_meta["first_try_ok"] is None:
                parse_meta["first_try_ok"] = False
        return orig_parse(text)

    llm_processor._parse_json_llm = tracked_parse  # type: ignore[assignment]
    try:
        from llm.corroborate import corroborate_clusters

        clusters, working = await cluster_articles(articles, target_clusters=10)
        clusters, working, _corr = await corroborate_clusters(clusters, working)
        cards = await generate_cards(clusters, working)
    finally:
        llm_processor._parse_json_llm = orig_parse  # type: ignore[assignment]

    assigned: set[int] = set()
    sizes: list[int] = []
    for c in clusters:
        idxs = c.get("article_indices") or []
        sizes.append(len(idxs))
        for i in idxs:
            if isinstance(i, int):
                assigned.add(i)
    unassigned = max(0, len(working) - len(assigned))

    detail = (
        f"clusters={len(clusters)} sizes={sizes} unassigned={unassigned} "
        f"json_first_try={parse_meta['first_try_ok']} llm_parse_calls={parse_meta['calls']}"
    )
    if not clusters:
        _fail("clustering", detail)
    elif parse_meta["first_try_ok"] is False:
        _warn("clustering", detail + " (needed salvage parse)")
    elif unassigned > len(working) * 0.5:
        _warn("clustering", detail)
    else:
        _pass("clustering", detail, [c.get("cluster_title") for c in clusters[:3]])

    return cards, working


def _probe_cards(cards: list[dict[str, Any]], ingested_articles: list[Article]) -> None:
    ingested_urls = {(a.url or "").strip() for a in ingested_articles if (a.url or "").strip()}

    bad_fields: list[str] = []
    bad_cat: list[str] = []
    no_sources: list[str] = []
    invented: list[str] = []
    headlines: list[str] = []
    scores: list[float] = []
    cats: Counter[str] = Counter()

    for i, card in enumerate(cards):
        h = (card.get("headline") or "").strip()
        b = (card.get("blurb") or "").strip()
        w = (card.get("why_it_matters") or "").strip()
        cat = card.get("category")
        headlines.append(h or f"(empty #{i})")
        if not h or not b or not w:
            bad_fields.append(h or f"card[{i}]")
        if cat not in _CARD_CATEGORIES:
            bad_cat.append(f"{h[:40]}:{cat!r}")
        else:
            cats[str(cat)] += 1
        sources = card.get("sources")
        if not isinstance(sources, list) or len(sources) < 1:
            no_sources.append(h[:50] or f"card[{i}]")
        else:
            for s in sources:
                if not isinstance(s, dict):
                    invented.append(f"{h[:30]}: non-dict source")
                    continue
                u = (s.get("url") or "").strip()
                if not u:
                    invented.append(f"{h[:30]}: empty source url")
                elif u not in ingested_urls:
                    invented.append(f"{h[:30]}: {u[:80]}")
        try:
            scores.append(float(card.get("importance_score")))
        except (TypeError, ValueError):
            pass

    hc: Counter[str] = Counter(x.lower() for x in headlines if x)
    dup_heads = [h for h, n in hc.items() if n > 1]

    from llm.funnel import snapshot as funnel_snapshot
    from llm.quotas import MIN_TOTAL_CARDS, TOPIC_CATEGORY_SLUGS as _TOPICS
    from llm.sources import independent_outlet_count, is_hn_host

    short_below5 = [s for s in _TOPICS if cats.get(s, 0) < 5]
    missing_topics = [s for s in _TOPICS if cats.get(s, 0) == 0]
    total = len(cards)

    # Source-mix stats per category
    mix_notes: list[str] = []
    for slug in _TOPICS:
        cat_cards = [c for c in cards if c.get("category") == slug]
        if not cat_cards:
            continue
        multi = 0
        hn_main = 0
        singles = 0
        for card in cat_cards:
            sources = card.get("sources") if isinstance(card.get("sources"), list) else []
            n_out = independent_outlet_count(sources)
            if n_out >= 2 or card.get("is_research_paper"):
                multi += 1
            if card.get("single_source"):
                singles += 1
            if sources and isinstance(sources[0], dict):
                main = sources[0]
                sn = (main.get("source_name") or "").lower()
                url = main.get("url") or ""
                # Main link is HN only when the URL/name is the HN thread itself.
                if is_hn_host(url) or sn in {"hackernews", "hacker news", "hn"}:
                    hn_main += 1
        mix_notes.append(
            f"{slug}: multi_or_paper={multi}/{len(cat_cards)} "
            f"({100 * multi / len(cat_cards):.0f}%) "
            f"hn_main={hn_main}/{len(cat_cards)} single_source_flag={singles}"
        )

    funnel = funnel_snapshot()

    detail = (
        f"cards={total} bad_fields={len(bad_fields)} bad_cat={len(bad_cat)} "
        f"no_sources={len(no_sources)} invented_urls={len(invented)} "
        f"dup_headlines={len(dup_heads)} category_spread={dict(cats)} "
        f"missing_topics={missing_topics} below_min5={short_below5} "
        f"min_total={MIN_TOTAL_CARDS} importance_scores={scores[:5]}"
    )
    samples = headlines[:3]

    if funnel:
        _warn(
            "category funnel",
            "per-category pipeline counts",
            [f"{slug}: {row}" for slug, row in list(funnel.items())[:6]],
        )
    if mix_notes:
        _warn("source mix", "independent outlets + HN-as-main", mix_notes)

    if not cards or bad_fields or bad_cat or no_sources or invented:
        _fail("cards", detail, samples + invented[:2] + bad_fields[:2])
    elif missing_topics or short_below5 or total < MIN_TOTAL_CARDS:
        reasons = []
        if missing_topics:
            reasons.extend([f"missing: {s}" for s in missing_topics])
        if short_below5:
            reasons.extend([f"below min 5: {s}={cats.get(s, 0)}" for s in short_below5])
        if total < MIN_TOTAL_CARDS:
            reasons.append(f"total {total} < {MIN_TOTAL_CARDS}")
        _fail("cards", detail, reasons[:6])
    elif dup_heads:
        _warn("cards", detail, samples)
    else:
        _pass("cards", detail, samples)


_GROUNDING_STOP = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "of",
    "to",
    "in",
    "on",
    "for",
    "with",
    "from",
    "by",
    "as",
    "at",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "it",
    "its",
    "this",
    "that",
    "these",
    "those",
    "their",
    "they",
    "we",
    "our",
    "you",
    "your",
    "new",
    "says",
    "said",
    "will",
    "can",
    "may",
    "also",
    "into",
    "over",
    "about",
    "after",
    "before",
    "than",
    "then",
    "when",
    "while",
    "which",
    "who",
    "what",
    "how",
    "why",
    "one",
    "two",
    "first",
    "today",
    "week",
    "year",
    "years",
    "day",
    "days",
    "more",
    "most",
    "some",
    "such",
    "just",
    "only",
    "not",
    "no",
    "yes",
    "up",
    "out",
    "has",
    "have",
    "had",
    "do",
    "does",
    "did",
    "but",
    "if",
    "so",
    "via",
}


def _grounding_tokens(text: str) -> set[str]:
    """Extract specific names, numbers, and multi-char tokens for grounding checks."""
    if not text:
        return set()
    lowered = text.lower()
    tokens: set[str] = set()
    # Numbers / versions like 3.5, 120b, $2.1b, gpt-6
    for m in re.finditer(r"\$?\d+(?:\.\d+)?(?:%|[kmbt]|b)?|\b[a-z]+-?\d+(?:\.\d+)?\b", lowered):
        tokens.add(m.group(0))
    # Capitalized / CamelCase names from original (kept via word scan on original)
    for m in re.finditer(r"\b[A-Z][A-Za-z0-9.+-]{1,}\b", text):
        tok = m.group(0).lower()
        if tok not in _GROUNDING_STOP and len(tok) > 2:
            tokens.add(tok)
    # Strong product-like lowercase tokens with digits or hyphens
    for m in re.finditer(r"\b[a-z][a-z0-9]*(?:-[a-z0-9]+)+\b", lowered):
        tok = m.group(0)
        if tok not in _GROUNDING_STOP:
            tokens.add(tok)
    return tokens


def _source_corpus(card: dict[str, Any], working: list[Article] | None) -> str:
    parts: list[str] = []
    for s in card.get("sources") or []:
        if not isinstance(s, dict):
            continue
        parts.append(str(s.get("title") or ""))
        url = (s.get("url") or "").strip()
        if working and url:
            for a in working:
                if (a.url or "").strip() == url:
                    parts.append(a.title or "")
                    parts.append(a.snippet or "")
                    parts.append(a.full_text or "")
                    break
    return "\n".join(parts).lower()


def _probe_card_grounding(
    cards: list[dict[str, Any]], working: list[Article] | None = None
) -> None:
    """
    Flag cards whose specific names/numbers/claims do not appear in source text.
    Soft warn: LLM paraphrasing can create false positives.
    """
    flagged: list[str] = []
    for i, card in enumerate(cards or []):
        corpus = _source_corpus(card, working)
        if not corpus.strip():
            continue
        claim_text = " ".join(
            [
                str(card.get("headline") or ""),
                str(card.get("blurb") or ""),
                str(card.get("why_it_matters") or ""),
            ]
        )
        tokens = _grounding_tokens(claim_text)
        missing = sorted(t for t in tokens if t and t not in corpus)
        # Only flag when multiple specific tokens are unsupported (reduces noise).
        if len(missing) >= 2:
            h = (card.get("headline") or f"card[{i}]")[:50]
            flagged.append(f"{h}: missing={missing[:5]}")

    detail = f"cards={len(cards or [])} flagged={len(flagged)}"
    if flagged:
        _warn("card source grounding", detail, flagged[:3])
    else:
        _pass("card source grounding", detail)


def _probe_frontend_contract(cards: list[dict[str, Any]]) -> None:
    missing_req: list[str] = []
    nullish: list[str] = []
    source_issues: list[str] = []

    for i, card in enumerate(cards or []):
        for field, meta in FRONTEND_CARD_FIELDS.items():
            if field == "id":
                continue
            if field not in card:
                if meta.get("required"):
                    missing_req.append(f"card[{i}].{field}")
                else:
                    nullish.append(f"card[{i}].{field} absent")
                continue
            val = card.get(field)
            if meta.get("required") and (val is None or val == "" or val == []):
                missing_req.append(f"card[{i}].{field}=empty")
            if field == "sources" and isinstance(val, list):
                for j, s in enumerate(val):
                    if not isinstance(s, dict):
                        source_issues.append(f"card[{i}].sources[{j}] not object")
                        continue
                    for sf, sm in FRONTEND_SOURCE_FIELDS.items():
                        if not sm.get("required"):
                            continue
                        sv = s.get(sf)
                        if sf == "url" and not (isinstance(sv, str) and sv.strip()):
                            source_issues.append(f"card[{i}].sources[{j}].url")

    detail = (
        f"required_missing={len(missing_req)} optional_absent={len(nullish)} "
        f"source_issues={len(source_issues)}"
    )
    if missing_req or source_issues:
        _fail("frontend field contract", detail, missing_req[:3] + source_issues[:3])
    elif nullish:
        _warn("frontend field contract", detail, nullish[:3])
    else:
        _pass("frontend field contract", detail)


def _probe_store_and_api(cards: list[dict[str, Any]], date_str: str) -> None:
    from backend.api import server as api_server
    from backend.models.schemas import DailyFeedResponse, FeedCard

    now_iso = datetime.now(timezone.utc).isoformat()
    resp = DailyFeedResponse(
        date=date_str,
        generated_at=now_iso,
        cards=[FeedCard.model_validate(c) for c in cards],
        errors=[],
        cached=False,
    )
    payload = api_server._store_payload(resp)

    # Persist like the server would
    path = FEEDS_DIR / f"{date_str}.json"
    FEEDS_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    disk = json.loads(path.read_text(encoding="utf-8"))
    disk_heads = [(c.get("headline") or "") for c in disk.get("cards", [])]
    prod_heads = [(c.get("headline") or "") for c in cards]
    if disk_heads == prod_heads:
        _pass("stored feed matches pipeline", f"path={path.name} cards={len(disk_heads)}")
    else:
        _fail(
            "stored feed matches pipeline",
            f"disk={len(disk_heads)} pipeline={len(prod_heads)}",
            disk_heads[:2],
        )

    # API live check
    try:
        with httpx.Client(base_url=API_BASE, timeout=20.0) as client:
            r = client.get("/api/cards/today")
            if r.status_code != 200:
                _fail("/api/cards/today", f"status={r.status_code}")
            else:
                body = r.json()
                api_heads = [(c.get("headline") or "") for c in body.get("cards", [])]
                if api_heads == prod_heads:
                    _pass("/api/cards/today matches pipeline", f"cards={len(api_heads)}")
                else:
                    # Server may still serve previous feed until reload picks up file
                    _warn(
                        "/api/cards/today matches pipeline",
                        f"api={len(api_heads)} pipeline={len(prod_heads)} "
                        "(restart uvicorn if disk was just overwritten)",
                        api_heads[:2],
                    )

            r = client.get("/api/categories")
            if r.status_code != 200:
                _fail("/api/categories", f"status={r.status_code}")
            else:
                api_counts = {
                    row["category"]: row["count"] for row in r.json() if "category" in row
                }
                expected: Counter[str] = Counter()
                for c in cards:
                    expected[str(c.get("category"))] += 1
                mismatches = []
                for cat, n in expected.items():
                    if api_counts.get(cat, 0) != n:
                        mismatches.append(f"{cat}: api={api_counts.get(cat)} expected={n}")
                if mismatches:
                    _warn("/api/categories counts", "; ".join(mismatches[:5]))
                else:
                    _pass("/api/categories counts", f"matched {len(expected)} non-zero categories")
    except httpx.ConnectError:
        _warn(
            "API endpoints",
            f"cannot connect to {API_BASE} - start uvicorn to verify live API",
        )


async def _async_main(skip_llm: bool) -> int:
    _report["generated_at"] = datetime.now(timezone.utc).isoformat()
    _report["skip_llm"] = skip_llm

    if not file_cache._cache_disabled():
        _fail("cache bypass", "AI_PULSE_NO_CACHE did not disable file cache")
    else:
        _pass("cache bypass", "AI_PULSE_NO_CACHE=1 active")

    print("\n=== Sources ===")
    hn_articles = await _probe_hn()
    arxiv_articles = await _probe_arxiv()
    brave_articles = await _probe_brave()

    sample_urls = []
    for a in (hn_articles + brave_articles)[:8]:
        sample_urls.append(a.url)
    print("\n=== Page scraper ===")
    await _probe_page_scraper(sample_urls)

    cards: list[dict[str, Any]] = []
    working: list[Article] = []
    if skip_llm:
        _warn("clustering", "skipped (--skip-llm)")
        _warn("cards", "skipped (--skip-llm)")
        _warn("card source grounding", "skipped (--skip-llm)")
        _warn("frontend field contract", "skipped (--skip-llm)")
        _warn("stored feed / API", "skipped (--skip-llm)")
    else:
        print("\n=== Clustering + cards ===")
        all_articles = hn_articles + arxiv_articles + brave_articles
        if len(all_articles) < 3:
            _fail("pipeline articles", f"only {len(all_articles)} articles for LLM stage")
        else:
            cards, working = await _probe_llm(all_articles)
            _probe_cards(cards, all_articles)
            _probe_card_grounding(cards, working)
            _probe_frontend_contract(cards)
            print("\n=== Store + API ===")
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            _probe_store_and_api(cards, date_str)

    fails = sum(1 for c in _checks if c["status"] == "FAIL")
    warns = sum(1 for c in _checks if c["status"] == "WARN")
    passes = sum(1 for c in _checks if c["status"] == "PASS")
    _report["summary"] = {"pass": passes, "warn": warns, "fail": fails}
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(_report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSummary: PASS={passes} WARN={warns} FAIL={fails}")
    print(f"Full report: {REPORT_PATH}")
    return 1 if fails else 0


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Verify TechBytes live pipeline data quality")
    parser.add_argument(
        "--skip-llm",
        action="store_true",
        help="Only check scrapers / page scraper (no Groq tokens)",
    )
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    raise SystemExit(asyncio.run(_async_main(skip_llm=args.skip_llm)))


if __name__ == "__main__":
    main()
