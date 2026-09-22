"""
LangGraph node wrapping ``llm.processor.cluster_articles``.
"""

from __future__ import annotations

import logging

from llm.processor import GroqDailyLimitError, cluster_articles
from llm.corroborate import corroborate_clusters
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
    Merge ingest dicts, validate, cluster with Groq, then corroborate
    single-outlet clusters via Brave News.
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
        clusters, working, corr = await corroborate_clusters(clusters, working)
        logger.info(
            "Corroboration: queries=%s matches=%s",
            corr.get("queries"),
            corr.get("matches"),
        )

        update: dict = {
            "story_clusters": clusters,
            "cluster_working_articles": [a.to_dict() for a in working],
        }
        if val_errors:
            update["errors"] = val_errors
        return update
    except GroqDailyLimitError:
        raise
    except Exception as e:
        logger.exception("Clustering failed: %s", e)
        return {
            "story_clusters": None,
            "cluster_working_articles": None,
            "errors": [f"Cluster: {e!s}"],
        }
