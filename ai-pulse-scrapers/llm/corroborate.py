"""Brave News corroboration for single-outlet clusters."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from scrapers.brave_scraper import (
    _LAST_QUOTA_HEADERS,
    _result_to_article,
    convert_age_to_iso,
    search_brave_news,
)
from scrapers.schema import Article

from .funnel import bump
from .quotas import CLUSTER_MAX_AGE_DAYS, TOPIC_CATEGORY_SLUGS
from .sources import (
    extract_domain,
    independent_outlet_count,
    is_hn_host,
    publisher_url_for_article,
    same_story_match,
    significant_tokens,
    source_outlet_domain,
)

logger = logging.getLogger(__name__)

# Track corroboration Brave calls for the current run.
_CORR_QUERIES = 0


def reset_corroboration_stats() -> None:
    global _CORR_QUERIES
    _CORR_QUERIES = 0


def corroboration_query_count() -> int:
    return _CORR_QUERIES


def _cluster_articles(
    cluster: dict[str, Any], articles: list[Article]
) -> list[Article]:
    out: list[Article] = []
    for i in cluster.get("article_indices") or []:
        if isinstance(i, int) and 0 <= i < len(articles):
            out.append(articles[i])
    return out


def _build_query(cluster: dict[str, Any], arts: list[Article]) -> str:
    title = (cluster.get("cluster_title") or "").strip()
    if not title and arts:
        title = (arts[0].title or "").strip()
    tokens = significant_tokens(
        " ".join([title] + [(a.title or "") for a in arts[:3]]),
        limit=8,
    )
    # Prefer longer tokens (product/company names).
    ranked = sorted(tokens, key=lambda t: (-len(t), t))[:5]
    if ranked:
        return " ".join(ranked)
    return title[:80]


def _freshness_code() -> str:
    # Brave: pd=day, pw=week. Map our clustering window roughly.
    try:
        days = float(CLUSTER_MAX_AGE_DAYS)
    except Exception:
        days = 3.0
    if days <= 1.5:
        return "pd"
    return "pw"


async def corroborate_clusters(
    clusters: list[dict[str, Any]],
    articles: list[Article],
    *,
    max_queries: int | None = None,
) -> tuple[list[dict[str, Any]], list[Article], dict[str, Any]]:
    """
    For clusters with fewer than two independent outlets, search Brave News for
    matching coverage and append those articles to the working set.

    Returns updated ``(clusters, articles, stats)``.
    """
    global _CORR_QUERIES
    reset_corroboration_stats()

    if not clusters:
        return clusters, articles, {"queries": 0, "matches": 0, "quota_headers": {}}

    working = list(articles)
    url_to_idx = {
        (a.url or "").strip(): i
        for i, a in enumerate(working)
        if (a.url or "").strip()
    }
    queries = 0
    matches = 0
    # Soft cap: prioritize high-importance single-outlet clusters.
    budget = max_queries if max_queries is not None else int(
        __import__("os").environ.get("CORROBORATION_MAX_QUERIES", "20")
    )

    # Process highest-importance single-outlet clusters first.
    ordered = sorted(
        clusters,
        key=lambda c: (
            0
            if independent_outlet_count(_cluster_articles(c, working)) < 2
            else 1,
            -float(c.get("importance_score") or 0),
        ),
    )

    for cluster in ordered:
        arts = _cluster_articles(cluster, working)
        if not arts:
            continue
        cat = cluster.get("primary_category") or "general"
        outlets = {source_outlet_domain(a) for a in arts}
        outlets.discard("")
        is_research = all(a.source_type == "arxiv" for a in arts)

        if len(outlets) >= 2 and not is_research:
            cluster["corroborated"] = True
            continue

        # Research papers may already be "complete" with arXiv alone, but still
        # try to attach news/discussion when available.
        if len(outlets) >= 2 and is_research:
            cluster["corroborated"] = True
            # still attempt one news search below if we only have arxiv domains
            only_arxiv = all(
                (a.source_type == "arxiv") or extract_domain(publisher_url_for_article(a)).endswith(
                    "arxiv.org"
                )
                for a in arts
            )
            if not only_arxiv:
                continue

        if queries >= budget:
            cluster["corroborated"] = len(outlets) >= 2
            continue

        query = _build_query(cluster, arts)
        if not query.strip():
            cluster["corroborated"] = len(outlets) >= 2
            continue

        if cat in TOPIC_CATEGORY_SLUGS:
            bump(cat, "corroboration_queries", 1)
        elif arts:
            stamp = next(
                (s for s in (arts[0].categories or []) if s in TOPIC_CATEGORY_SLUGS),
                "general",
            )
            bump(stamp, "corroboration_queries", 1)

        logger.info(
            "Corroboration Brave query [%s]: %r (outlets=%s research=%s)",
            cat,
            query[:80],
            sorted(outlets),
            is_research,
        )
        results = await search_brave_news(
            query, count=6, freshness=_freshness_code()
        )
        queries += 1
        _CORR_QUERIES = queries
        await asyncio.sleep(1.05)  # free-tier ~1 req/s

        seed_titles = [a.title or "" for a in arts]
        seed_dates = [a.published_at for a in arts]
        cluster_title = str(cluster.get("cluster_title") or "")
        existing_domains = set(outlets)
        added_idxs: list[int] = []

        for raw in results:
            if not isinstance(raw, dict):
                continue
            title = (raw.get("title") or "").strip()
            url = (raw.get("url") or "").strip()
            if not title or not url or is_hn_host(url):
                continue
            domain = extract_domain(url)
            if not domain or domain in existing_domains:
                continue
            pub = convert_age_to_iso(raw.get("age") or "")
            if not same_story_match(
                cluster_title=cluster_title,
                seed_titles=seed_titles,
                candidate_title=title,
                seed_dates=seed_dates,
                candidate_published_at=pub,
            ):
                continue

            if url in url_to_idx:
                idx = url_to_idx[url]
            else:
                art = _result_to_article(raw, None)
                # Stamp cluster topic so funnel / category logic stays consistent.
                if cat in TOPIC_CATEGORY_SLUGS:
                    art.categories = list(
                        dict.fromkeys([*(art.categories or []), cat])
                    )
                idx = len(working)
                working.append(art)
                url_to_idx[url] = idx
            if idx not in (cluster.get("article_indices") or []):
                added_idxs.append(idx)
                existing_domains.add(domain)
                matches += 1
                if cat in TOPIC_CATEGORY_SLUGS:
                    bump(cat, "corroboration_matches", 1)
            if len(existing_domains) >= 3:
                break

        if added_idxs:
            idxs = list(cluster.get("article_indices") or [])
            for i in added_idxs:
                if i not in idxs:
                    idxs.append(i)
            cluster["article_indices"] = idxs

        final_arts = _cluster_articles(cluster, working)
        outlet_n = independent_outlet_count(
            [
                {
                    "url": publisher_url_for_article(a),
                    "source_name": a.source_name,
                    "source_type": a.source_type,
                }
                for a in final_arts
            ]
        )
        has_news = any(a.source_type != "arxiv" for a in final_arts)
        if is_research:
            cluster["research_primary"] = True
            # arXiv alone is publishable; mark corroborated only when news is attached.
            cluster["corroborated"] = outlet_n >= 2 or (has_news and outlet_n >= 1)
        else:
            cluster["corroborated"] = outlet_n >= 2

    headers = dict(_LAST_QUOTA_HEADERS or {})
    logger.info(
        "Corroboration complete: brave_queries=%s matches_attached=%s "
        "quota_headers=%s",
        queries,
        matches,
        headers or "(none)",
    )
    if headers:
        # Compare query volume to plan-ish limits when headers expose them.
        rem = None
        lim = None
        for k, v in headers.items():
            kl = k.lower()
            if "remaining" in kl and rem is None:
                rem = v
            if ("limit" in kl or "quota" in kl) and lim is None:
                lim = v
        logger.info(
            "Brave corroboration vs plan headers: queries_used=%s "
            "header_limit=%s header_remaining=%s",
            queries,
            lim,
            rem,
        )

    return (
        clusters,
        working,
        {"queries": queries, "matches": matches, "quota_headers": headers},
    )
