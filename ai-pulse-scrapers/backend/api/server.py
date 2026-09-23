"""
FastAPI application: feed store (Upstash Redis or local disk), cards, categories, cron.

Run pipeline + save: ``python -m backend.api.server --generate``
Serve: ``python -m backend.api.server`` or ``python -m backend.api.server --serve``
Or: ``uvicorn backend.api.server:app --reload --port 8000`` (from project root).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import secrets
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.graph import generate_daily_feed
from backend.models.schemas import CategoryCount, DailyFeedResponse, FeedCard
from backend.state import FeedState

load_dotenv()

logger = logging.getLogger(__name__)

# Project root: .../ai-pulse-scrapers
PROJECT_ROOT = Path(__file__).resolve().parents[2]
FEEDS_DIR = PROJECT_ROOT / "data" / "feeds"

REDIS_LATEST_KEY = "ai_pulse:feed:latest"
REDIS_DATE_KEY_PREFIX = "ai_pulse:feed:"

KNOWN_CATEGORY_SLUGS = frozenset(
    {
        "ai_ml",
        "chips_hardware",
        "networking_cloud",
        "cybersecurity",
        "autonomous_vehicles",
        "general",
    }
)


class EmptyFeedError(RuntimeError):
    """Pipeline finished without publishable cards; stored feed must be left alone."""

    def __init__(self, errors: list[str] | None = None):
        self.errors = list(errors or [])
        msg = "; ".join(self.errors) if self.errors else "Pipeline produced no cards"
        super().__init__(msg)


# Redact secrets if an exception message ever echoes env values.
_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|secret|token|password|authorization)\s*[:=]\s*\S+"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]+"),
    re.compile(r"\bgsk_[A-Za-z0-9]+"),
    re.compile(r"\bBSA[A-Za-z0-9_\-]+"),
)


def _sanitize_public_error(text: str, *, limit: int = 800) -> str:
    out = str(text or "")
    for pat in _SECRET_PATTERNS:
        out = pat.sub("[redacted]", out)
    return out[:limit]


def _parse_groq_tpd_fields(message: str) -> dict[str, Any]:
    """Extract Limit / Used / reset hint from a GroqDailyLimitError message."""
    limit = used = reset = None
    m = re.search(r"Limit\s+(\d+)\s*,\s*Used\s+(\d+)", message, flags=re.IGNORECASE)
    if m:
        limit = int(m.group(1))
        used = int(m.group(2))
    m2 = re.search(
        r"try again in\s+([0-9]+m[0-9.]*s|[0-9.]+s|[0-9]+h[0-9m.]*s?)",
        message,
        flags=re.IGNORECASE,
    )
    if m2:
        reset = m2.group(1)
    else:
        m3 = re.search(
            r"Resets in about\s+([0-9]+m[0-9.]*s|[0-9.]+s)",
            message,
            flags=re.IGNORECASE,
        )
        if m3:
            reset = m3.group(1)
    return {"limit": limit, "used": used, "resets_in": reset}


async def _generate_http_result() -> DailyFeedResponse | JSONResponse:
    """
    Run the pipeline for cron/refresh endpoints.

    On failure the stored feed is left untouched and a JSON error body is returned
    (never a bare 500 with no detail).
    """
    from llm.processor import GroqDailyLimitError

    try:
        return await _run_pipeline_and_persist()
    except GroqDailyLimitError as e:
        msg = _sanitize_public_error(str(e), limit=1200)
        fields = _parse_groq_tpd_fields(msg)
        logger.error(
            "GENERATE FAILED (Groq daily limit): limit=%s used=%s resets_in=%s",
            fields.get("limit"),
            fields.get("used"),
            fields.get("resets_in"),
        )
        return JSONResponse(
            status_code=429,
            content={
                "error": "groq_daily_limit",
                "message": "Groq daily token limit reached; previous feed retained",
                "limit": fields.get("limit"),
                "used": fields.get("used"),
                "resets_in": fields.get("resets_in"),
                "detail": msg,
                "previous_feed_retained": True,
            },
        )
    except EmptyFeedError as e:
        logger.error(
            "GENERATE FAILED (empty feed): reasons=%s — previous feed retained",
            e.errors,
        )
        return JSONResponse(
            status_code=502,
            content={
                "error": "empty_feed",
                "message": "Generation produced no cards; previous feed retained",
                "errors": [_sanitize_public_error(x, limit=400) for x in e.errors],
                "previous_feed_retained": True,
            },
        )
    except Exception as e:
        logger.exception("GENERATE FAILED: %s: %s", type(e).__name__, e)
        return JSONResponse(
            status_code=500,
            content={
                "error": "generate_failed",
                "exception_type": type(e).__name__,
                "message": _sanitize_public_error(str(e)),
                "previous_feed_retained": True,
            },
        )


CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


def _extra_cors_origins() -> list[str]:
    raw = os.environ.get("CORS_ORIGINS") or os.environ.get("FRONTEND_ORIGIN") or ""
    return [o.strip() for o in raw.split(",") if o.strip()]


app = FastAPI(
    title="AI Pulse API",
    description="Phase 2 API over LangGraph + Phase 1 scrapers.",
    version="0.3.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[*CORS_ORIGINS, *_extra_cors_origins()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_router = APIRouter(prefix="/api")

_pipeline_lock = asyncio.Lock()
_redis_client = None


def _utc_date_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _feed_path(date_str: str) -> Path:
    return FEEDS_DIR / f"{date_str}.json"


def _redis_enabled() -> bool:
    return bool(
        os.environ.get("KV_REST_API_URL") and os.environ.get("KV_REST_API_TOKEN")
    )


def _get_redis():
    """Lazy Upstash Redis REST client (sync; call via ``asyncio.to_thread``)."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    if not _redis_enabled():
        return None
    from upstash_redis import Redis

    _redis_client = Redis(
        url=os.environ["KV_REST_API_URL"],
        token=os.environ["KV_REST_API_TOKEN"],
    )
    return _redis_client


def _read_feed_file(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _write_feed_file(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _load_latest_feed_disk() -> dict | None:
    """Most recent ``data/feeds/YYYY-MM-DD.json`` by filename date, then generated_at."""
    if not FEEDS_DIR.is_dir():
        return None
    files = sorted(FEEDS_DIR.glob("????-??-??.json"), reverse=True)
    best: dict | None = None
    best_ts: str = ""
    for path in files:
        try:
            data = _read_feed_file(path)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Skipping bad feed file %s: %s", path, e)
            continue
        gen = str(data.get("generated_at") or "")
        date_name = path.stem
        # Prefer newer generated_at; fall back to filename date.
        rank = gen or date_name
        if best is None or rank > best_ts:
            best = data
            best_ts = rank
    return best


def _save_feed_disk(payload: dict, date_str: str) -> None:
    _write_feed_file(_feed_path(date_str), payload)


def _redis_get_latest() -> dict | None:
    client = _get_redis()
    if client is None:
        return None
    raw = client.get(REDIS_LATEST_KEY)
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if isinstance(raw, dict):
        return raw
    return json.loads(raw)


def _redis_set_feed(payload: dict, date_str: str) -> None:
    client = _get_redis()
    if client is None:
        return
    text = json.dumps(payload, ensure_ascii=False)
    client.set(REDIS_LATEST_KEY, text)
    client.set(f"{REDIS_DATE_KEY_PREFIX}{date_str}", text)


async def _load_latest_feed() -> dict | None:
    if _redis_enabled():
        data = await asyncio.to_thread(_redis_get_latest)
        if data is not None:
            return data
        logger.warning("Redis enabled but no latest feed; falling back to disk")
    return await asyncio.to_thread(_load_latest_feed_disk)


async def _save_feed(payload: dict, date_str: str) -> None:
    if _redis_enabled():
        await asyncio.to_thread(_redis_set_feed, payload, date_str)
        return
    await asyncio.to_thread(_save_feed_disk, payload, date_str)


def _store_payload(resp: DailyFeedResponse) -> dict:
    return {
        "date": resp.date,
        "generated_at": resp.generated_at,
        "cards": [c.model_dump(mode="json", exclude_none=False) for c in resp.cards],
        "errors": resp.errors,
    }


def _response_from_store(data: dict, *, cached: bool) -> DailyFeedResponse:
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
    filled: list[dict] = []
    for c in raw_cards:
        if not isinstance(c, dict):
            continue
        d = dict(c)
        # No dated sources → fall back to feed generation time.
        if not d.get("published_at"):
            d["published_at"] = generated_at
        filled.append(d)
    cards = [FeedCard.model_validate(c) for c in filled]
    return DailyFeedResponse(
        date=date_str,
        generated_at=generated_at,
        cards=cards,
        errors=errors,
        cached=cached,
    )


async def _run_pipeline_and_persist(
    date_str: str | None = None,
    *,
    categories: list[str] | None = None,
    max_cards: int | None = None,
) -> DailyFeedResponse:
    date_str = date_str or _utc_date_str()
    now_iso = datetime.now(timezone.utc).isoformat()
    target = int(max_cards) if max_cards is not None else 60
    state = await generate_daily_feed(categories=categories, target_cards=target)
    resp = _state_to_response(state, date_str, now_iso, cached=False)
    if not resp.cards:
        reasons = list(resp.errors) or ["Pipeline produced no cards"]
        logger.error(
            "Generation produced 0 cards — keeping previous stored feed. reasons=%s",
            reasons,
        )
        raise EmptyFeedError(reasons)
    await _save_feed(_store_payload(resp), date_str)
    return resp


def _parse_categories_arg(raw: str | None) -> list[str] | None:
    if not raw or not str(raw).strip():
        return None
    parts = [p.strip() for p in str(raw).split(",")]
    return [p for p in parts if p]


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


def _check_cron_secret(authorization: str | None) -> None:
    secret = os.environ.get("CRON_SECRET")
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="CRON_SECRET is not configured on the server",
        )
    expected = f"Bearer {secret}"
    if not authorization or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


@api_router.get("/health")
async def api_health() -> dict[str, str]:
    return {
        "status": "ok",
        "store": "redis" if _redis_enabled() else "disk",
    }


@api_router.get("/cards/today", response_model=DailyFeedResponse)
async def cards_today() -> DailyFeedResponse:
    """Serve the most recent stored feed (never runs the pipeline)."""
    data = await _load_latest_feed()
    if not data:
        raise HTTPException(
            status_code=404,
            detail="No feed stored yet. Wait for the daily cron or run --generate.",
        )
    return _response_from_store(data, cached=True)


@api_router.get("/cards/today/cached", response_model=DailyFeedResponse)
async def cards_today_cached() -> DailyFeedResponse:
    """Same as ``/cards/today``: most recent store, no pipeline."""
    data = await _load_latest_feed()
    if not data:
        raise HTTPException(
            status_code=404,
            detail="No feed stored yet. Wait for the daily cron or run --generate.",
        )
    return _response_from_store(data, cached=True)


@api_router.post("/cards/refresh", response_model=None)
async def cards_refresh(
    authorization: str | None = Header(default=None),
) -> DailyFeedResponse | JSONResponse:
    """Force full pipeline run (requires ``Authorization: Bearer <CRON_SECRET>``)."""
    _check_cron_secret(authorization)
    async with _pipeline_lock:
        return await _generate_http_result()


@api_router.get("/cron/generate", response_model=None)
async def cron_generate(
    authorization: str | None = Header(default=None),
) -> DailyFeedResponse | JSONResponse:
    """
    Daily cron entrypoint: run pipeline and persist to Redis/disk.

    Requires ``Authorization: Bearer <CRON_SECRET>`` (Vercel Cron sends this when
    ``CRON_SECRET`` is set in the project env). Failed/empty/Groq-limit runs do
    not overwrite the previous feed; errors return JSON (429 / 502 / 500).
    """
    _check_cron_secret(authorization)
    async with _pipeline_lock:
        return await _generate_http_result()


@api_router.get("/categories", response_model=list[CategoryCount])
async def categories() -> list[CategoryCount]:
    """Category counts from the most recent stored feed (no pipeline)."""
    data = await _load_latest_feed()
    if not data:
        return [
            CategoryCount(category=s, count=0) for s in sorted(KNOWN_CATEGORY_SLUGS)
        ]
    resp = _response_from_store(data, cached=True)
    return _category_counts(resp.cards)


app.include_router(api_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def _cli_generate(
    *,
    categories: list[str] | None = None,
    max_cards: int | None = None,
) -> None:
    from llm.processor import GroqDailyLimitError, get_run_token_totals, _log_run_stats

    date_str = _utc_date_str()
    logger.info(
        "Generating feed for %s … categories=%s max_cards=%s",
        date_str,
        categories or "(all)",
        max_cards or "(default)",
    )
    t0 = time.perf_counter()
    try:
        resp = await _run_pipeline_and_persist(
            date_str, categories=categories, max_cards=max_cards
        )
    except GroqDailyLimitError as e:
        totals = get_run_token_totals()
        logger.error("Generate aborted: %s", e)
        logger.info(
            "Tokens used before abort: total=%s (in=%s out=%s) calls=%s",
            totals.get("total_tokens"),
            totals.get("prompt_tokens"),
            totals.get("completion_tokens"),
            totals.get("calls"),
        )
        raise SystemExit(2) from e
    except EmptyFeedError as e:
        totals = get_run_token_totals()
        logger.error("Generate produced no cards; previous feed kept. %s", e)
        logger.info(
            "Tokens used: total=%s (in=%s out=%s) calls=%s",
            totals.get("total_tokens"),
            totals.get("prompt_tokens"),
            totals.get("completion_tokens"),
            totals.get("calls"),
        )
        raise SystemExit(1) from e
    elapsed = time.perf_counter() - t0
    store = "redis" if _redis_enabled() else str(_feed_path(date_str))
    totals = get_run_token_totals()
    _log_run_stats("cli-generate")
    logger.info("Full pipeline complete: %s cards in %.1fs", len(resp.cards), elapsed)
    logger.info(
        "Groq token total for this run: %s (prompt=%s completion=%s, calls=%s)",
        totals.get("total_tokens"),
        totals.get("prompt_tokens"),
        totals.get("completion_tokens"),
        totals.get("calls"),
    )
    logger.info("Saved %s cards to %s", len(resp.cards), store)
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
        help="Run the LangGraph pipeline, persist feed, exit",
    )
    mx.add_argument(
        "--serve",
        action="store_true",
        help="Start uvicorn on 127.0.0.1:8000",
    )
    parser.add_argument(
        "--max-cards",
        type=int,
        default=None,
        metavar="N",
        help="With --generate: cap published cards (small test runs)",
    )
    parser.add_argument(
        "--categories",
        type=str,
        default=None,
        metavar="LIST",
        help='With --generate: comma-separated human labels, e.g. "AI/ML,cybersecurity"',
    )
    args = parser.parse_args()
    if args.generate:
        cats = _parse_categories_arg(args.categories)
        asyncio.run(_cli_generate(categories=cats, max_cards=args.max_cards))
    else:
        _cli_serve()


if __name__ == "__main__":
    main()
