"""Offline tests for cron/refresh generate error responses (mocked pipeline)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api.server import EmptyFeedError, app
from llm.processor import GroqDailyLimitError

CRON_SECRET = "test-cron-secret-for-unit-tests"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("CRON_SECRET", CRON_SECRET)
    # Avoid accidental Redis / live store side effects in assertions.
    monkeypatch.delenv("KV_REST_API_URL", raising=False)
    monkeypatch.delenv("KV_REST_API_TOKEN", raising=False)
    with TestClient(app) as c:
        yield c


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {CRON_SECRET}"}


def test_cron_generate_returns_429_on_groq_daily_limit(client, monkeypatch):
    async def _boom(*_a, **_k):
        raise GroqDailyLimitError(
            "Stopping pipeline: Groq daily token limit (TPD) reached. "
            "Resets in about 9m0.864s. Raw error: Rate limit reached for model "
            "on tokens per day (TPD): Limit 200000, Used 199614, Requested 1638. "
            "Please try again in 9m0.864s."
        )

    monkeypatch.setattr(
        "backend.api.server._run_pipeline_and_persist",
        _boom,
    )
    r = client.get("/api/cron/generate", headers=_auth())
    assert r.status_code == 429
    body = r.json()
    assert body["error"] == "groq_daily_limit"
    assert body["previous_feed_retained"] is True
    assert body["limit"] == 200000
    assert body["used"] == 199614
    assert body["resets_in"] == "9m0.864s"
    assert "gsk_" not in str(body).lower()


def test_cron_generate_returns_502_on_empty_feed(client, monkeypatch):
    async def _boom(*_a, **_k):
        raise EmptyFeedError(
            ["Cluster: Groq returned empty final content", "Cards: no story clusters"]
        )

    monkeypatch.setattr(
        "backend.api.server._run_pipeline_and_persist",
        _boom,
    )
    r = client.get("/api/cron/generate", headers=_auth())
    assert r.status_code == 502
    body = r.json()
    assert body["error"] == "empty_feed"
    assert body["previous_feed_retained"] is True
    assert any("empty final content" in e for e in body["errors"])


def test_cron_generate_returns_500_json_on_unexpected_error(client, monkeypatch):
    async def _boom(*_a, **_k):
        raise RuntimeError("simulated boom with BRAVE_API_KEY=should-not-leak")

    monkeypatch.setattr(
        "backend.api.server._run_pipeline_and_persist",
        _boom,
    )
    r = client.get("/api/cron/generate", headers=_auth())
    assert r.status_code == 500
    body = r.json()
    assert body["error"] == "generate_failed"
    assert body["exception_type"] == "RuntimeError"
    assert body["previous_feed_retained"] is True
    assert "should-not-leak" not in body["message"]
    assert "[redacted]" in body["message"]


def test_refresh_returns_429_on_groq_daily_limit(client, monkeypatch):
    async def _boom(*_a, **_k):
        raise GroqDailyLimitError(
            "Stopping pipeline: Groq daily token limit (TPD) reached. "
            "Resets in about 2m10s. Limit 200000, Used 200000."
        )

    monkeypatch.setattr(
        "backend.api.server._run_pipeline_and_persist",
        _boom,
    )
    r = client.post("/api/cards/refresh", headers=_auth())
    assert r.status_code == 429
    body = r.json()
    assert body["error"] == "groq_daily_limit"
    assert body["limit"] == 200000
    assert body["used"] == 200000


def test_scrape_page_403_logs_info(caplog, monkeypatch):
    import httpx
    from scrapers import page_scraper

    class FakeResp:
        status_code = 403
        text = "Forbidden"

        def raise_for_status(self):
            raise httpx.HTTPStatusError(
                "403 Forbidden",
                request=httpx.Request("GET", "https://example.com/x"),
                response=httpx.Response(403, request=httpx.Request("GET", "https://example.com/x")),
            )

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return FakeResp()

    monkeypatch.setattr(page_scraper.httpx, "AsyncClient", FakeClient)

    import asyncio

    with caplog.at_level("INFO", logger="scrapers.page_scraper"):
        out = asyncio.run(page_scraper.scrape_page("https://example.com/blocked"))
    assert out["error"]
    assert any("scrape_page 403" in r.message for r in caplog.records)
    assert not any(
        r.levelname == "WARNING" and "scrape_page" in r.message for r in caplog.records
    )
