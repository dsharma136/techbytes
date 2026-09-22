"""
LangGraph node wrapping ``llm.processor.generate_cards``.
"""

from __future__ import annotations

import logging

from llm.processor import generate_cards
from scrapers.schema import Article

from backend.state import FeedState

logger = logging.getLogger(__name__)


async def write_cards(state: FeedState) -> dict:
    """
    Build cards from ``story_clusters`` and the clustered working article slice.

    Each card gets an ``order`` field (1-based sequence).
    """
    clusters = state.get("story_clusters") or []
    working_dicts = list(state.get("cluster_working_articles") or [])

    if not clusters:
        return {"feed_cards": [], "errors": ["Cards: no story clusters to process"]}

    try:
        working = [Article.from_dict(d) for d in working_dicts]
        cards = await generate_cards(clusters, working)
        numbered: list[dict] = []
        for i, card in enumerate(cards):
            row = dict(card)
            row["order"] = i + 1
            numbered.append(row)
        return {"feed_cards": numbered}
    except Exception as e:
        logger.exception("Card generation failed: %s", e)
        return {"feed_cards": [], "errors": [f"Cards: {e!s}"]}
