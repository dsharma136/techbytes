"""
LangGraph node wrapping ``llm.processor.generate_cards``.
"""

from __future__ import annotations

import logging

from llm.processor import GroqDailyLimitError, generate_cards
from scrapers.schema import Article

from backend.state import FeedState

logger = logging.getLogger(__name__)


async def write_cards(state: FeedState) -> dict:
    """
    Build cards from ``story_clusters`` and the clustered working article slice.

    Each card gets an ``order`` field (1-based sequence).
    Honors ``target_card_count`` as a hard cap when set (e.g. ``--max-cards``).
    """
    clusters = state.get("story_clusters") or []
    working_dicts = list(state.get("cluster_working_articles") or [])

    if not clusters:
        return {"feed_cards": [], "errors": ["Cards: no story clusters to process"]}

    try:
        working = [Article.from_dict(d) for d in working_dicts]
        cards = await generate_cards(clusters, working)
        max_cards = state.get("target_card_count")
        try:
            cap = int(max_cards) if max_cards is not None else None
        except (TypeError, ValueError):
            cap = None
        if cap is not None and cap > 0 and len(cards) > cap:
            logger.info(
                "Trimming feed from %s to %s cards (--max-cards / target_card_count)",
                len(cards),
                cap,
            )
            cards = cards[:cap]
        numbered: list[dict] = []
        for i, card in enumerate(cards):
            row = dict(card)
            row["order"] = i + 1
            numbered.append(row)
        return {"feed_cards": numbered}
    except GroqDailyLimitError:
        raise
    except Exception as e:
        logger.exception("Card generation failed: %s", e)
        return {"feed_cards": [], "errors": [f"Cards: {e!s}"]}
