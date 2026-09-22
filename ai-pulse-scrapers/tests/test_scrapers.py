"""
Live integration tests for scrapers (real APIs, no mocks).

Run from project root:
    python -m tests.test_scrapers

These are skipped under normal ``pytest`` so offline CI / local runs never
hit Groq, Brave, Hacker News, or arXiv.
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest
from dotenv import load_dotenv

from scrapers.arxiv_scraper import fetch_arxiv_articles
from scrapers.brave_scraper import fetch_brave_articles
from scrapers.hn_scraper import fetch_hn_articles
from scrapers.schema import Article, validate_articles

pytestmark = pytest.mark.skip(
    reason="Live API integration — run manually: python -m tests.test_scrapers"
)

load_dotenv()

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


async def test_hn_scraper() -> list[Article]:
    """Test HackerNews scraper returns valid Article objects."""
    articles = await fetch_hn_articles(
        categories=["AI/ML"],
        max_per_query=3,
        scrape_pages=False,
    )
    assert len(articles) > 0, "HN scraper returned no articles"
    for a in articles:
        assert a.title, f"Article missing title: {a}"
        assert a.url, f"Article missing url: {a}"
        assert a.source_type == "hackernews"
        assert a.engagement is not None, "HN articles should have engagement data"
        assert a.engagement["points"] >= 0
    print(f"✅ HN Scraper: {len(articles)} articles, all valid")
    return articles


async def test_arxiv_scraper() -> list[Article]:
    """Test ArXiv scraper returns valid Article objects."""
    articles = await fetch_arxiv_articles(categories=["AI/ML"], max_per_query=3)
    assert len(articles) > 0, "ArXiv scraper returned no articles"
    for a in articles:
        assert a.title
        assert a.url
        assert a.source_type == "arxiv"
        assert a.snippet, "ArXiv articles should have abstracts as snippets"
        assert a.extra and "pdf_url" in a.extra, "ArXiv articles should have pdf_url"
    print(f"✅ ArXiv Scraper: {len(articles)} articles, all valid")
    return articles


async def test_brave_scraper() -> list[Article]:
    """Test Brave Search scraper returns valid Article objects."""
    if not os.getenv("BRAVE_API_KEY"):
        print("⚠️  Brave Scraper: BRAVE_API_KEY not set, skipping")
        return []
    articles = await fetch_brave_articles(
        categories=["AI/ML"],
        results_per_query=3,
        scrape_pages=False,
    )
    assert len(articles) > 0, "Brave scraper returned no articles"
    for a in articles:
        assert a.title
        assert a.url
        assert a.source_type == "brave"
    print(f"✅ Brave Scraper: {len(articles)} articles, all valid")
    return articles


async def test_combined() -> list[Article]:
    """Test all scrapers and validate combined output."""
    hn = await test_hn_scraper()
    arxiv = await test_arxiv_scraper()
    brave = await test_brave_scraper()

    all_articles = hn + arxiv + brave
    valid, errors = validate_articles(all_articles)

    print(f"\n{'=' * 60}")
    print("COMBINED RESULTS")
    print(f"  HN: {len(hn)} | ArXiv: {len(arxiv)} | Brave: {len(brave)}")
    print(f"  Total: {len(all_articles)} | Valid: {len(valid)} | Errors: {len(errors)}")
    if errors:
        for e in errors:
            print(f"  ⚠️  {e}")
    print(f"{'=' * 60}")
    return valid


if __name__ == "__main__":
    asyncio.run(test_combined())
