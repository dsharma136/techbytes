"""
FastAPI application: daily feed cache, cards, categories, health.

Run pipeline + save: ``python -m backend.api.server --generate``
Serve: ``python -m backend.api.server`` or ``python -m backend.api.server --serve``
Or: ``uvicorn backend.api.server:app --reload --port 8000`` (from project root).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.graph import generate_daily_feed
from backend.models.schemas import CategoryCount, DailyFeedResponse, FeedCard
from backend.state import FeedState

logger = logging.getLogger(__name__)

# Project root: .../ai-pulse-scrapers
PROJECT_ROOT = Path(__file__).resolve().parents[2]
FEEDS_DIR = PROJECT_ROOT / "data" / "feeds"

CACHE_MAX_AGE = timedelta(hours=6)

# Align with ``llm.processor`` card slugs for stable category rows.
KNOWN_CATEGORY_SLUGS = frozenset(
    {
        "ai_ml",
        "chips_hardware",
        "networking_cloud",
        "cybersecurity",
        "autonomous_vehicles",
        "dev_tools",
        "general",
    }
)

CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app = FastAPI(
    title="AI Pulse API",
    description="Phase 2 API over LangGraph + Phase 1 scrapers.",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_router = APIRouter(prefix="/api")

_pipeline_lock = asyncio.Lock()


def _utc_date_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _feed_path(date_str: str) -> Path:
    return FEEDS_DIR / f"{date_str}.json"


def _parse_generated_at(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _cache_is_fresh(payload: dict) -> bool:
    raw = payload.get("generated_at")
    if not raw or not isinstance(raw, str):
        return False
    try:
        gen = _parse_generated_at(raw)
    except (TypeError, ValueError):
        return False
    return datetime.now(timezone.utc) - gen < CACHE_MAX_AGE


def _read_feed_file(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _write_feed_file(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


async def _load_feed_disk(date_str: str) -> dict | None:
    path = _feed_path(date_str)
    if not path.is_file():
        return None
    return await asyncio.to_thread(_read_feed_file, path)


async def _save_feed_disk(payload: dict, date_str: str) -> None:
    path = _feed_path(date_str)
    await asyncio.to_thread(_write_feed_file, path, payload)


def _disk_payload(resp: DailyFeedResponse) -> dict:
    return {
        "date": resp.date,
        "generated_at": resp.generated_at,
        "cards": [c.model_dump(mode="json", exclude_none=False) for c in resp.cards],
        "errors": resp.errors,
    }


def _response_from_disk(data: dict, *, cached: bool) -> DailyFeedResponse:
    return DailyFeedResponse(
        date=str(data["date"]),
        generated_at=str(data["generated_at"]),
        cards=[FeedCard.model_validate(c) for c in data.get("cards", [])],
        errors=list(data.get("errors", [])),
        cached=cached,
    )


def _state_to_response(
    state: FeedState,
    date_str: str,
    generated_at: str,
    *,
    cached: bool,
) -> DailyFeedResponse:
    raw_cards = state.get("feed_cards") or []
    errors = list(state.get("errors") or [])
    cards = [FeedCard.model_validate(c) for c in raw_cards]
    return DailyFeedResponse(
        date=date_str,
        generated_at=generated_at,
        cards=cards,
        errors=errors,
        cached=cached,
    )


async def _run_pipeline_and_persist(date_str: str) -> DailyFeedResponse:
    now_iso = datetime.now(timezone.utc).isoformat()
    state = await generate_daily_feed()
    resp = _state_to_response(state, date_str, now_iso, cached=False)
    await _save_feed_disk(_disk_payload(resp), date_str)
    return resp


def _category_counts(cards: list[FeedCard]) -> list[CategoryCount]:
    counter: Counter[str] = Counter()
    for c in cards:
        counter[c.category] += 1
    rows: list[CategoryCount] = []
    for slug, n in counter.most_common():
        rows.append(CategoryCount(category=slug, count=n))
    seen = {r.category for r in rows}
    for slug in sorted(KNOWN_CATEGORY_SLUGS - seen):
        rows.append(CategoryCount(category=slug, count=0))
    return rows


@api_router.get("/health")
async def api_health() -> dict[str, str]:
    return {"status": "ok"}


@api_router.get("/cards/today", response_model=DailyFeedResponse)
async def cards_today() -> DailyFeedResponse:
    """Return today's feed; use disk cache when younger than six hours."""
    date_str = _utc_date_str()
    data = await _load_feed_disk(date_str)
    if data and _cache_is_fresh(data):
        return _response_from_disk(data, cached=True)

    async with _pipeline_lock:
        data = await _load_feed_disk(date_str)
        if data and _cache_is_fresh(data):
            return _response_from_disk(data, cached=True)
        return await _run_pipeline_and_persist(date_str)


@api_router.get("/cards/today/cached", response_model=DailyFeedResponse)
async def cards_today_cached() -> DailyFeedResponse:
    """Always read today's JSON from ``data/feeds``; never runs the pipeline."""
    date_str = _utc_date_str()
    data = await _load_feed_disk(date_str)
    if not data:
        raise HTTPException(
            status_code=404,
            detail=f"No cached feed for {date_str} under data/feeds/",
        )
    return _response_from_disk(data, cached=True)


@api_router.post("/cards/refresh", response_model=DailyFeedResponse)
async def cards_refresh() -> DailyFeedResponse:
    """Force full pipeline run and overwrite today's cache file."""
    date_str = _utc_date_str()
    async with _pipeline_lock:
        return await _run_pipeline_and_persist(date_str)


@api_router.get("/categories", response_model=list[CategoryCount])
async def categories() -> list[CategoryCount]:
    """Category slugs with card counts from today's cached feed (no pipeline)."""
    date_str = _utc_date_str()
    data = await _load_feed_disk(date_str)
    if not data:
        return [CategoryCount(category=s, count=0) for s in sorted(KNOWN_CATEGORY_SLUGS)]
    resp = _response_from_disk(data, cached=True)
    return _category_counts(resp.cards)


app.include_router(api_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def _cli_generate() -> None:
    date_str = _utc_date_str()
    logger.info("Generating feed for %s …", date_str)
    resp = await _run_pipeline_and_persist(date_str)
    logger.info(
        "Saved %s cards to %s",
        len(resp.cards),
        _feed_path(date_str),
    )
    if resp.errors:
        for e in resp.errors:
            logger.warning("Pipeline error: %s", e)


def _cli_serve() -> None:
    import uvicorn

    uvicorn.run(
        "backend.api.server:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="AI Pulse API server / feed generator")
    mx = parser.add_mutually_exclusive_group()
    mx.add_argument(
        "--generate",
        action="store_true",
        help="Run the LangGraph pipeline, write data/feeds/YYYY-MM-DD.json, exit",
    )
    mx.add_argument(
        "--serve",
        action="store_true",
        help="Start uvicorn on 127.0.0.1:8000",
    )
    args = parser.parse_args()
    if args.generate:
        asyncio.run(_cli_generate())
    else:
        _cli_serve()


if __name__ == "__main__":
    main()
