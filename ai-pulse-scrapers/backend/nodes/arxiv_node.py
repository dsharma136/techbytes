"""
LangGraph node wrapping ``scrapers.arxiv_scraper.fetch_arxiv_articles``.
"""

from __future__ import annotations

import logging

from scrapers.arxiv_scraper import fetch_arxiv_articles

from backend.state import FeedState

logger = logging.getLogger(__name__)


async def fetch_arxiv_papers(state: FeedState) -> dict:
    """Fetch ArXiv papers, serialize to dicts, merge into ``FeedState``."""
    try:
        articles = await fetch_arxiv_articles(categories=state.get("categories"))
        return {"arxiv_papers": [a.to_dict() for a in articles]}
    except Exception as e:
        logger.warning("ArXiv fetch failed: %s", e)
        return {"arxiv_papers": [], "errors": [f"ArXiv: {e!s}"]}
