"""
LangGraph node wrapping ``scrapers.brave_scraper.fetch_brave_articles`` (web/news).
"""

from __future__ import annotations

import logging

from scrapers.brave_scraper import fetch_brave_articles

from backend.state import FeedState

logger = logging.getLogger(__name__)


async def fetch_web_articles(state: FeedState) -> dict:
    """Fetch Brave news results, serialize to dicts, merge into ``FeedState``."""
    try:
        articles = await fetch_brave_articles(
            categories=state.get("categories"),
            scrape_pages=True,
        )
        return {"web_articles": [a.to_dict() for a in articles]}
    except Exception as e:
        logger.warning("Brave/web fetch failed: %s", e)
        return {"web_articles": [], "errors": [f"Brave: {e!s}"]}
