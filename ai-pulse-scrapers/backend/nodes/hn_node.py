"""
LangGraph node wrapping ``scrapers.hn_scraper.fetch_hn_articles``.
"""

from __future__ import annotations

import logging

from scrapers.hn_scraper import fetch_hn_articles

from backend.state import FeedState

logger = logging.getLogger(__name__)


async def fetch_hackernews(state: FeedState) -> dict:
    """Fetch HN stories, serialize to dicts, merge into ``FeedState``."""
    try:
        articles = await fetch_hn_articles(
            categories=state.get("categories"),
            scrape_pages=True,
        )
        return {"hn_articles": [a.to_dict() for a in articles]}
    except Exception as e:
        logger.warning("HackerNews fetch failed: %s", e)
        return {"hn_articles": [], "errors": [f"HN: {e!s}"]}
