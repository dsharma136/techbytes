"""Independent-source helpers: domains, HN publisher links, single-source flags."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

_HN_HOSTS = frozenset(
    {
        "news.ycombinator.com",
        "hn.algolia.com",
        "ycombinator.com",
    }
)


def extract_domain(url: str) -> str:
    """Hostname without leading www.; empty string if unparseable."""
    try:
        host = (urlparse((url or "").strip()).hostname or "").lower()
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def is_hn_host(domain_or_url: str) -> bool:
    d = extract_domain(domain_or_url) if "://" in domain_or_url else (domain_or_url or "").lower()
    return d in _HN_HOSTS or d.endswith(".ycombinator.com")


def publisher_url_for_article(article: Any) -> str:
    """
    Prefer the original publisher URL over an HN discussion thread.

    HN ingest already stores the story URL on ``article.url`` and the thread in
    ``extra.hn_url``. If ``url`` itself points at HN, fall back to any non-HN
    link in extra.
    """
    url = (getattr(article, "url", None) or "").strip()
    if url and not is_hn_host(url):
        return url
    extra = getattr(article, "extra", None) or {}
    if isinstance(extra, dict):
        for key in ("original_url", "story_url", "url"):
            cand = (extra.get(key) or "").strip()
            if cand and not is_hn_host(cand):
                return cand
    return url


def source_outlet_domain(source: dict[str, Any] | Any) -> str:
    """Domain used for independent-outlet counting (never treat HN as a second outlet)."""
    if isinstance(source, dict):
        url = (source.get("url") or "").strip()
        name = (source.get("source_name") or "").strip().lower()
    else:
        url = publisher_url_for_article(source)
        name = (getattr(source, "source_name", None) or "").strip().lower()
    domain = extract_domain(url)
    if is_hn_host(domain) or name in {"hackernews", "hacker news", "hn"}:
        # Count the publisher domain when we have one; otherwise HN itself.
        if domain and not is_hn_host(domain):
            return domain
        return "news.ycombinator.com"
    return domain or name or "unknown"


def independent_outlet_count(sources: list[dict[str, Any]] | list[Any]) -> int:
    domains = {source_outlet_domain(s) for s in (sources or []) if s}
    domains.discard("")
    return len(domains)


def is_corroborated(sources: list[dict[str, Any]] | list[Any]) -> bool:
    return independent_outlet_count(sources) >= 2


_STOP = frozenset(
    """
    a an the and or of to in on for with from by as at is are was were be been
    this that these those it its their new update news says said after over into
    about how why what when who will can may just more most also than then
    """.split()
)


def significant_tokens(text: str, *, limit: int = 12) -> set[str]:
    """Lowercased tokens useful for same-story matching (names, numbers, products)."""
    raw = re.findall(r"[A-Za-z][A-Za-z0-9+._-]{1,}|\d+(?:\.\d+)?", text or "")
    out: set[str] = set()
    for t in raw:
        tl = t.lower().strip(".")
        if len(tl) < 2 or tl in _STOP:
            continue
        out.add(tl)
        if len(out) >= limit:
            break
    return out


def same_story_match(
    *,
    cluster_title: str,
    seed_titles: list[str],
    candidate_title: str,
    seed_dates: list[str | None],
    candidate_published_at: str | None,
    max_day_gap: float = 3.0,
) -> bool:
    """
    True when the candidate looks like coverage of the same story.

    Requires overlapping significant tokens (company/product/event cues) and a
    publish date within ``max_day_gap`` days when both sides have dates.
    """
    seed = significant_tokens(
        " ".join([cluster_title or "", *seed_titles]),
        limit=20,
    )
    cand = significant_tokens(candidate_title or "", limit=16)
    if not seed or not cand:
        return False
    overlap = seed & cand
    # Need at least two shared cues, or one strong multi-char proper-ish token
    # plus another token when titles are short.
    if len(overlap) < 2:
        strong = {t for t in overlap if len(t) >= 5 or any(ch.isdigit() for ch in t)}
        if len(strong) < 1 or len(overlap) < 1:
            return False
        if len(overlap) < 2 and len(strong) < 1:
            return False
        if len(overlap) == 1 and len(strong) == 1 and len(next(iter(strong))) < 6:
            return False

    from datetime import datetime, timezone

    def _parse(s: str | None) -> datetime | None:
        if not s:
            return None
        try:
            t = str(s).strip()
            if t.endswith("Z"):
                t = t[:-1] + "+00:00"
            dt = datetime.fromisoformat(t)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            return None

    cand_dt = _parse(candidate_published_at)
    seed_dts = [d for d in (_parse(x) for x in seed_dates) if d is not None]
    if cand_dt and seed_dts:
        nearest = min(abs((cand_dt - d).total_seconds()) for d in seed_dts)
        if nearest > max_day_gap * 86400:
            return False
    return len(overlap) >= 2 or (
        len(overlap) >= 1 and any(len(t) >= 6 for t in overlap)
    )
