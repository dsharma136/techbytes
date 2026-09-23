"""Tests for verify helpers and cache bypass."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from cache import file_cache
from scrapers.brave_scraper import _brave_api_key


def test_file_cache_disabled_by_ai_pulse_no_cache(monkeypatch, tmp_path):
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.setenv("AI_PULSE_NO_CACHE", "1")
    monkeypatch.setattr(file_cache, "CACHE_DIR", tmp_path)
    assert file_cache._cache_disabled() is True
    file_cache.put("abc", {"x": 1})
    assert list(tmp_path.iterdir()) == []
    assert file_cache.get("abc") is None


def test_file_cache_enabled_without_bypass(monkeypatch, tmp_path):
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("AI_PULSE_NO_CACHE", raising=False)
    monkeypatch.setattr(file_cache, "CACHE_DIR", tmp_path)
    assert file_cache._cache_disabled() is False
    file_cache.put("xyz", {"y": 2})
    assert (tmp_path / "xyz.json").is_file()
    assert file_cache.get("xyz") == {"y": 2}


def test_brave_api_key_reads_env_at_call_time(monkeypatch):
    monkeypatch.setenv("BRAVE_API_KEY", "test-key-value")
    assert _brave_api_key() == "test-key-value"
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    assert _brave_api_key() == ""


def test_generate_cards_assigns_order():
    """Cards always get 1-based order for frontend stable ids."""
    cards = [
        {"headline": "a", "blurb": "b", "why_it_matters": "c", "category": "ai_ml"},
        {"headline": "d", "blurb": "e", "why_it_matters": "f", "category": "general"},
    ]
    for i, card in enumerate(cards):
        card["order"] = i + 1
    assert [c["order"] for c in cards] == [1, 2]


def test_verify_completeness_requires_points_for_hn():
    from scripts.verify_pipeline import _completeness

    items = [
        {
            "title": "A",
            "url": "https://example.com/a",
            "source": "HackerNews",
            "published_at": "2026-09-22T00:00:00+00:00",
            "points": 10,
        }
    ]
    pct, bad = _completeness(items, require_points=True)
    assert pct == 100.0
    assert bad == []

    items[0].pop("points")
    pct, bad = _completeness(items, require_points=True)
    assert pct == 0.0
    assert bad


def test_independent_outlet_count_treats_hn_publisher_as_one():
    from llm.sources import independent_outlet_count, publisher_url_for_article
    from scrapers.schema import Article

    a = Article(
        title="Story",
        url="https://www.theverge.com/article",
        source_type="hackernews",
        source_name="HackerNews",
        snippet="",
        full_text=None,
        published_at=None,
        fetched_at="2026-09-22T00:00:00+00:00",
        engagement={"points": 10},
        authors=[],
        categories=["ai_ml"],
        image_url=None,
        extra={"hn_url": "https://news.ycombinator.com/item?id=1"},
    )
    assert publisher_url_for_article(a) == "https://www.theverge.com/article"
    sources = [
        {"url": publisher_url_for_article(a), "source_name": "theverge.com"},
        {"url": "https://news.ycombinator.com/item?id=1", "source_name": "HackerNews"},
    ]
    assert independent_outlet_count(sources) == 2
    assert (
        independent_outlet_count(
            [{"url": "https://www.theverge.com/a", "source_name": "theverge.com"}]
        )
        == 1
    )


def test_same_story_match_requires_shared_cues():
    from llm.sources import same_story_match

    assert same_story_match(
        cluster_title="Waymo robotaxi Austin expansion",
        seed_titles=["Waymo expands robotaxi service in Austin"],
        candidate_title="Waymo robotaxi fleet grows in Austin Texas",
        seed_dates=["2026-09-20T12:00:00+00:00"],
        candidate_published_at="2026-09-21T08:00:00+00:00",
    )
    assert not same_story_match(
        cluster_title="Waymo robotaxi Austin expansion",
        seed_titles=["Waymo expands robotaxi service in Austin"],
        candidate_title="NVIDIA announces new GPU architecture",
        seed_dates=["2026-09-20T12:00:00+00:00"],
        candidate_published_at="2026-09-21T08:00:00+00:00",
    )
    assert not same_story_match(
        cluster_title="China semiconductor export controls",
        seed_titles=["US tightens China chip export rules"],
        candidate_title="Top 17 China Wholesale Websites",
        seed_dates=["2026-09-20T12:00:00+00:00"],
        candidate_published_at="2026-09-21T08:00:00+00:00",
        candidate_url="https://example.com/top-wholesale",
    )


def test_feed_quality_audit_flags_fixture_problems():
    import json
    from pathlib import Path

    from llm.quality import audit_feed_cards

    path = Path(__file__).resolve().parent / "fixtures" / "feed_2026-09-23.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    flags = audit_feed_cards(data["cards"])
    # Production fixture is known-bad; at least one family should fire.
    assert any(flags[k] for k in flags)
    assert flags["category_mismatch"] or flags["off_topic"] or flags["mixed_cluster"]


def test_meta_language_and_category_suggest():
    from llm.quality import has_meta_language, suggest_category

    assert has_meta_language("A Hacker News post says OpenAI shipped a model")
    assert suggest_category("Waymo expands robotaxi service in Austin") == "autonomous_vehicles"
    assert suggest_category("Disney+ raises subscription price for ad tier") == "not_tech_news"


def test_groq_daily_limit_detection():
    from llm.processor import GroqDailyLimitError, _is_daily_token_limit, _parse_reset_hint

    class FakeExc(Exception):
        pass

    e = FakeExc(
        "Error code: 429 - Rate limit reached for model on tokens per day (TPD): "
        "Limit 200000, Used 198921. Please try again in 9m35.424s."
    )
    assert _is_daily_token_limit(e) is True
    assert _parse_reset_hint(e) == "9m35.424s"
    assert _is_daily_token_limit(FakeExc("Rate limit: tokens per minute (TPM)")) is False


def test_gpt_oss_out_budget_leaves_reasoning_room():
    from llm.processor import GPT_OSS_MIN_COMPLETION, _gpt_oss_out_budget

    out = _gpt_oss_out_budget(max_tokens=1200, est_in=1500, ceiling=7000)
    assert out >= GPT_OSS_MIN_COMPLETION
    retry = _gpt_oss_out_budget(
        max_tokens=1200, est_in=800, ceiling=7000, prefer_large=True
    )
    assert retry >= out


def test_empty_feed_error_keeps_reasons():
    from backend.api.server import EmptyFeedError

    err = EmptyFeedError(["Cluster: blank", "Cards: none"])
    assert "Cluster: blank" in err.errors
    assert "blank" in str(err)

