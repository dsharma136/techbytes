"""
LangGraph node wrapping ``llm.processor.cluster_articles``.
"""

from __future__ import annotations

import logging

from llm.processor import cluster_articles
from scrapers.schema import Article, validate_articles

from backend.state import FeedState

logger = logging.getLogger(__name__)


def _dicts_to_articles(rows: list[dict]) -> list[Article]:
    out: list[Article] = []
    for d in rows:
        try:
            out.append(Article.from_dict(d))
        except Exception as e:
            logger.warning("Skipping malformed article dict: %s", e)
    return out


async def cluster_stories(state: FeedState) -> dict:
    """
    Merge ingest dicts, validate, cluster with Groq.

    Returns ``story_clusters`` plus ``cluster_working_articles`` (dicts) so
    ``write_cards`` can call ``generate_cards`` with the same index space.
    """
    try:
        combined_dicts = (
            list(state.get("hn_articles", []))
            + list(state.get("arxiv_papers", []))
            + list(state.get("web_articles", []))
        )
        articles = _dicts_to_articles(combined_dicts)
        valid, val_errors = validate_articles(articles)

        tc_raw = state.get("target_card_count", 20)
        try:
            tc = int(tc_raw)
        except (TypeError, ValueError):
            tc = 20
        target_clusters = min(50, max(1, tc))

        clusters, working = await cluster_articles(valid, target_clusters=target_clusters)

        update: dict = {
            "story_clusters": clusters,
            "cluster_working_articles": [a.to_dict() for a in working],
        }
        if val_errors:
            update["errors"] = val_errors
        return update
    except Exception as e:
        logger.exception("Clustering failed: %s", e)
        return {
            "story_clusters": None,
            "cluster_working_articles": None,
            "errors": [f"Cluster: {e!s}"],
        }
