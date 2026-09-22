"""Groq LLM integration: cluster articles and generate learning cards."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any

from dotenv import load_dotenv
from groq import APIStatusError, Groq

from scrapers.schema import Article

from .prompts import CARD_WRITER_PROMPT, CLUSTERING_PROMPT

load_dotenv()

logger = logging.getLogger(__name__)

# Groq free tier: stay under TPM — tight prompts + output caps.
GROQ_MODEL = "llama-3.3-70b-versatile"
TOKEN_BUDGET_CEILING = 10_000
CLUSTER_MAX_OUT = 2000
CARDS_MAX_OUT = 3000

HN_CLUSTER_SLOTS = 8
BRAVE_CLUSTER_SLOTS = 4
ARXIV_CLUSTER_SLOTS = 3
MAX_CARD_CLUSTERS = 10

_CLUSTER_CATEGORIES = frozenset(
    {
        "ai_ml",
        "chips_hardware",
        "networking_cloud",
        "cybersecurity",
        "autonomous_vehicles",
        "dev_tools",
        "general",
    }
)

_CARD_CATEGORIES = _CLUSTER_CATEGORIES


def create_client() -> Groq:
    """Return a Groq client. Raises if ``GROQ_API_KEY`` is missing."""
    key = os.getenv("GROQ_API_KEY")
    if not key:
        raise ValueError(
            "GROQ_API_KEY is not set. Copy .env.example to .env and add your Groq API key."
        )
    return Groq(api_key=key)


def _estimate_input_tokens(text: str) -> int:
    """Rough input-token estimate (characters / 4)."""
    return max(1, len(text) // 4)


def _log_token_estimate(phase: str, prompt: str, max_output: int) -> int:
    est = _estimate_input_tokens(prompt)
    logger.info(
        "%s: ~%s input tokens (char/4 est.), max_output=%s, est. combined=%s (ceiling=%s)",
        phase,
        est,
        max_output,
        est + max_output,
        TOKEN_BUDGET_CEILING,
    )
    return est


def _points(a: Article) -> int:
    e = a.engagement
    if not e:
        return 0
    p = e.get("points")
    try:
        return int(p) if p is not None else 0
    except (TypeError, ValueError):
        return 0


def _recency_ts(a: Article) -> float:
    for s in (a.published_at, a.fetched_at):
        if not s:
            continue
        try:
            t = str(s).strip()
            if t.endswith("Z"):
                t = t[:-1] + "+00:00"
            return datetime.fromisoformat(t).timestamp()
        except Exception:
            continue
    return 0.0


def _select_clustering_articles(articles: list[Article]) -> list[Article]:
    """
    Up to 15 articles for clustering: top 8 HN by points, top 4 Brave by recency,
    top 3 ArXiv by recency (fewer if a source is missing).
    """
    hn = [a for a in articles if a.source_type == "hackernews"]
    br = [a for a in articles if a.source_type == "brave"]
    ax = [a for a in articles if a.source_type == "arxiv"]
    hn_pick = sorted(hn, key=_points, reverse=True)[:HN_CLUSTER_SLOTS]
    br_pick = sorted(br, key=_recency_ts, reverse=True)[:BRAVE_CLUSTER_SLOTS]
    ax_pick = sorted(ax, key=_recency_ts, reverse=True)[:ARXIV_CLUSTER_SLOTS]
    return hn_pick + br_pick + ax_pick


def _trim_working_for_token_budget(
    working: list[Article],
    build_prompt: Callable[[list[Article]], str],
    max_output: int,
    phase: str,
) -> tuple[list[Article], str]:
    """Drop articles from the end until est. input + max_output <= ceiling."""
    wk = list(working)
    while True:
        prompt = build_prompt(wk)
        est = _estimate_input_tokens(prompt)
        if est + max_output <= TOKEN_BUDGET_CEILING:
            return wk, prompt
        if len(wk) <= 1:
            logger.warning(
                "%s: still ~%s input + %s output over budget with 1 article; proceeding anyway",
                phase,
                est,
                max_output,
            )
            return wk, prompt
        wk = wk[:-1]
        logger.warning(
            "%s: trimming to %s articles to stay under token budget (est. input was ~%s)",
            phase,
            len(wk),
            est,
        )


def _strip_markdown_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE | re.MULTILINE)
        t = re.sub(r"\s*```\s*$", "", t, flags=re.MULTILINE)
    return t.strip()


def _parse_json_llm(text: str) -> Any:
    """Parse JSON from LLM output; log raw text on failure; try bracket salvage."""
    cleaned = _strip_markdown_fences(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.warning("JSON parse failed: %s", e)
        logger.warning("Raw LLM response (truncated): %s", text[:4000])

    for pattern in (r"\[[\s\S]*\]", r"\{[\s\S]*\}"):
        m = re.search(pattern, cleaned)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                continue
    return None


def _groq_status_code(exc: APIStatusError) -> int | None:
    for source in (exc, getattr(exc, "response", None)):
        if source is None:
            continue
        code = getattr(source, "status_code", None)
        if code is not None:
            try:
                return int(code)
            except (TypeError, ValueError):
                continue
    return None


def _should_halve_clustering_input(exc: BaseException) -> bool:
    if not isinstance(exc, APIStatusError):
        return False
    code = _groq_status_code(exc)
    if code == 413:
        return True
    if code == 429:
        return True
    msg = str(exc).lower()
    if "rate_limit" in msg or "rate limit" in msg or "rate_limit_exceeded" in msg:
        return True
    if "tokens per minute" in msg or "tpm" in msg:
        return True
    resp = getattr(exc, "response", None)
    if resp is not None:
        body = (getattr(resp, "text", None) or "").lower()
        if "rate_limit" in body or "rate_limit_exceeded" in body:
            return True
    return False


async def call_llm(
    prompt: str,
    max_tokens: int = 4000,
    *,
    model: str = GROQ_MODEL,
    retry_with_half_prompt: Callable[[], str] | None = None,
) -> str:
    client = create_client()

    def _sync_call(p: str) -> str:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": p}],
            temperature=0.3,
            max_tokens=max_tokens,
        )
        choice = resp.choices[0].message
        return (choice.content or "").strip()

    try:
        return await asyncio.to_thread(_sync_call, prompt)
    except APIStatusError as e:
        if retry_with_half_prompt is not None and _should_halve_clustering_input(e):
            logger.warning(
                "Groq rate/payload limit (%s), retrying once with halved clustering input",
                e,
            )
            prompt2 = retry_with_half_prompt()
            try:
                return await asyncio.to_thread(_sync_call, prompt2)
            except APIStatusError as e2:
                logger.exception("Groq API failed after halved-input retry: %s", e2)
                raise
        logger.exception("Groq API call failed: %s", e)
        raise
    except Exception as e:
        logger.exception("Groq API call failed: %s", e)
        raise


def _validate_cluster(
    c: dict[str, Any], n_articles: int
) -> dict[str, Any] | None:
    title = c.get("cluster_title")
    if not title or not str(title).strip():
        return None
    raw_idx = c.get("article_indices")
    if not isinstance(raw_idx, list):
        return None
    indices: list[int] = []
    for x in raw_idx:
        try:
            i = int(x)
        except (TypeError, ValueError):
            return None
        if not (0 <= i < n_articles):
            logger.warning("Invalid article index %s (n=%s)", i, n_articles)
            return None
        indices.append(i)
    cat = c.get("primary_category")
    if cat not in _CLUSTER_CATEGORIES:
        logger.warning("Invalid primary_category %r, coercing to general", cat)
        cat = "general"
    score = c.get("importance_score", 0.5)
    try:
        score_f = float(score)
        score_f = max(0.0, min(1.0, score_f))
    except (TypeError, ValueError):
        score_f = 0.5
    return {
        "cluster_title": str(title).strip(),
        "article_indices": indices,
        "primary_category": cat,
        "importance_score": score_f,
    }


def _validate_card(c: dict[str, Any]) -> dict[str, Any] | None:
    headline = (c.get("headline") or "").strip()
    blurb = (c.get("blurb") or "").strip()
    why = (c.get("why_it_matters") or "").strip()
    category = c.get("category")
    if not headline or not blurb or not why:
        return None
    if category not in _CARD_CATEGORIES:
        logger.warning("Invalid card category %r, coercing to general", category)
        category = "general"
    out: dict[str, Any] = {
        "headline": headline,
        "blurb": blurb,
        "why_it_matters": why,
        "category": category,
    }
    if "is_research_paper" in c:
        out["is_research_paper"] = bool(c.get("is_research_paper"))
    return out


def _make_clustering_simplified(wk: list[Article]) -> list[dict[str, Any]]:
    """Minimal fields for clustering prompt (token budget)."""
    return [
        {"index": i, "title": a.title, "source_type": a.source_type}
        for i, a in enumerate(wk)
    ]


async def cluster_articles(
    articles: list[Article], target_clusters: int = 50
) -> tuple[list[dict[str, Any]], list[Article]]:
    """
    Cluster articles with the LLM.

    Returns ``(clusters, working_articles)``. ``article_indices`` refer to
    ``working_articles`` (pass this list to ``generate_cards``).
    """
    working = _select_clustering_articles(articles)
    if not working:
        return [], []

    def _cluster_prompt_for(wk: list[Article]) -> str:
        simp = _make_clustering_simplified(wk)
        return CLUSTERING_PROMPT.format(
            articles_json=json.dumps(simp, indent=2, ensure_ascii=False),
            target_clusters=target_clusters,
        )

    working, prompt = _trim_working_for_token_budget(
        working,
        _cluster_prompt_for,
        CLUSTER_MAX_OUT,
        "clustering",
    )
    n = len(working)
    simplified = _make_clustering_simplified(working)

    def _halve_and_rebuild_prompt() -> str:
        nonlocal working, simplified, n
        half_n = max(1, n // 2)
        working = working[:half_n]
        simplified = _make_clustering_simplified(working)
        n = len(working)
        return CLUSTERING_PROMPT.format(
            articles_json=json.dumps(simplified, indent=2, ensure_ascii=False),
            target_clusters=target_clusters,
        )

    _log_token_estimate("clustering", prompt, CLUSTER_MAX_OUT)
    raw = await call_llm(
        prompt,
        max_tokens=CLUSTER_MAX_OUT,
        model=GROQ_MODEL,
        retry_with_half_prompt=_halve_and_rebuild_prompt,
    )
    parsed = _parse_json_llm(raw)
    if parsed is None:
        logger.error("Could not parse clustering JSON; returning no clusters")
        return [], working

    if not isinstance(parsed, list):
        logger.error("Clustering response is not a JSON array")
        return [], working

    out: list[dict[str, Any]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        v = _validate_cluster(item, n)
        if v:
            out.append(v)

    if not out:
        logger.warning("No valid clusters after validation")
    return out, working


def _build_minimal_card_payload(
    clusters_slice: list[dict[str, Any]], articles: list[Article]
) -> list[dict[str, Any]]:
    """Only cluster_title and article titles (no snippets)."""
    payload: list[dict[str, Any]] = []
    for c in clusters_slice:
        idxs = c.get("article_indices") or []
        titles: list[str] = []
        for i in idxs:
            if isinstance(i, int) and 0 <= i < len(articles):
                titles.append(articles[i].title)
        payload.append(
            {
                "cluster_title": c.get("cluster_title"),
                "article_titles": titles,
            }
        )
    return payload


def _trim_clusters_for_card_budget(
    cluster_slice: list[dict[str, Any]],
    articles: list[Article],
) -> tuple[list[dict[str, Any]], str]:
    """Reduce cluster count until est. prompt + CARDS_MAX_OUT fits ceiling."""
    sl = list(cluster_slice)

    def build_prompt(clusters: list[dict[str, Any]]) -> str:
        pl = _build_minimal_card_payload(clusters, articles)
        return CARD_WRITER_PROMPT.format(
            clusters_json=json.dumps(pl, indent=2, ensure_ascii=False),
        )

    while True:
        prompt = build_prompt(sl)
        est = _estimate_input_tokens(prompt)
        if est + CARDS_MAX_OUT <= TOKEN_BUDGET_CEILING:
            return sl, prompt
        if len(sl) <= 1:
            logger.warning(
                "cards: ~%s input + %s output still over budget with 1 cluster; proceeding",
                est,
                CARDS_MAX_OUT,
            )
            return sl, prompt
        sl = sl[:-1]
        logger.warning(
            "cards: trimming to %s clusters for token budget (est. input was ~%s)",
            len(sl),
            est,
        )


async def generate_cards(
    clusters: list[dict[str, Any]], articles: list[Article]
) -> list[dict[str, Any]]:
    """Generate cards for up to 10 clusters (importance), minimal prompt payload."""
    if not clusters:
        return []

    sorted_clusters = sorted(
        clusters,
        key=lambda c: float(c.get("importance_score") or 0),
        reverse=True,
    )
    cluster_slice = sorted_clusters[:MAX_CARD_CLUSTERS]

    cluster_slice, prompt = _trim_clusters_for_card_budget(cluster_slice, articles)

    _log_token_estimate("cards", prompt, CARDS_MAX_OUT)
    raw = await call_llm(prompt, max_tokens=CARDS_MAX_OUT, model=GROQ_MODEL)
    parsed = _parse_json_llm(raw)
    if parsed is None:
        logger.error("Could not parse card JSON; returning no cards")
        return []

    if not isinstance(parsed, list):
        logger.error("Card response is not a JSON array")
        return []

    out: list[dict[str, Any]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        v = _validate_card(item)
        if v:
            out.append(v)

    if len(out) != len(cluster_slice):
        logger.warning(
            "Card count (%s) differs from cluster slice count (%s)",
            len(out),
            len(cluster_slice),
        )

    n = min(len(out), len(cluster_slice))
    for i in range(n):
        c = cluster_slice[i]
        card = out[i]
        idxs = c.get("article_indices") or []
        sources: list[dict[str, Any]] = []
        for j in idxs:
            if isinstance(j, int) and 0 <= j < len(articles):
                a = articles[j]
                sources.append(
                    {
                        "title": a.title,
                        "url": a.url,
                        "source_type": a.source_type,
                        "source_name": a.source_name,
                        "engagement": a.engagement,
                    }
                )
        card["sources"] = sources
        try:
            card["importance_score"] = float(c.get("importance_score") or 0)
        except (TypeError, ValueError):
            card["importance_score"] = 0.5
        ct = c.get("cluster_title")
        if ct:
            card["cluster_title"] = str(ct).strip()

    return out


if __name__ == "__main__":
    import asyncio

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    test_articles = [
        Article(
            title="NVIDIA announces new B300 GPU",
            url="https://example.com/1",
            source_type="hackernews",
            source_name="HN",
            snippet="NVIDIA unveiled next-gen accelerators for data centers.",
            full_text=None,
            published_at="2026-04-03T12:00:00Z",
            fetched_at="2026-04-03T12:00:00Z",
            engagement={"points": 500, "comments": 200},
            authors=["nvidia"],
            categories=[],
            image_url=None,
            extra=None,
        ),
        Article(
            title="Scaling laws for sparse transformers",
            url="https://arxiv.org/abs/1234.5678",
            source_type="arxiv",
            source_name="ArXiv",
            snippet="We study scaling behavior of sparse attention on long contexts.",
            full_text=None,
            published_at="2026-04-01T00:00:00Z",
            fetched_at="2026-04-03T10:00:00Z",
            engagement=None,
            authors=["a", "b"],
            categories=["cs.LG"],
            image_url=None,
            extra={"pdf_url": "https://arxiv.org/pdf/1234.5678.pdf"},
        ),
        Article(
            title="Major cloud outage traced to BGP misconfiguration",
            url="https://example.com/3",
            source_type="brave",
            source_name="reuters.com",
            snippet="A routing error disrupted traffic across three regions for two hours.",
            full_text=None,
            published_at="2026-04-02T15:00:00Z",
            fetched_at="2026-04-03T09:00:00Z",
            engagement=None,
            authors=[],
            categories=[],
            image_url=None,
            extra=None,
        ),
        Article(
            title="CISA warns of actively exploited zero-day in popular VPN",
            url="https://example.com/4",
            source_type="hackernews",
            source_name="HN",
            snippet="Federal agencies urge patching within 24 hours.",
            full_text=None,
            published_at="2026-04-03T08:00:00Z",
            fetched_at="2026-04-03T11:00:00Z",
            engagement={"points": 1200, "comments": 400},
            authors=["cisa"],
            categories=[],
            image_url=None,
            extra=None,
        ),
        Article(
            title="Rust 1.78 ships with faster compile times for large workspaces",
            url="https://example.com/5",
            source_type="brave",
            source_name="blog.rust-lang.org",
            snippet="The release focuses on incremental compilation and diagnostics.",
            full_text=None,
            published_at="2026-04-03T00:00:00Z",
            fetched_at="2026-04-03T07:00:00Z",
            engagement=None,
            authors=[],
            categories=[],
            image_url=None,
            extra=None,
        ),
    ]

    async def _run() -> None:
        clusters, working = await cluster_articles(test_articles, target_clusters=3)
        cards = await generate_cards(clusters, working)
        print(json.dumps(cards, indent=2, ensure_ascii=False))

    asyncio.run(_run())
