"""Groq LLM integration: cluster articles and generate learning cards."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from dotenv import load_dotenv
from groq import APIStatusError, Groq

from scrapers.schema import Article

from .prompts import CARD_WRITER_PROMPT, CLUSTERING_PROMPT
from .quotas import (
    ALL_CATEGORY_SLUGS,
    ARTICLES_PER_CATEGORY,
    CATEGORY_QUOTA,
    GENERAL_SLUG,
    MIN_CATEGORY_CARDS,
    MIN_TOTAL_CARDS,
    TOPIC_CATEGORY_SLUGS,
)
from . import funnel as funnel_mod
from .corroborate import corroborate_clusters
from .sources import (
    independent_outlet_count,
    is_corroborated,
    is_hn_host,
    publisher_url_for_article,
    source_outlet_domain,
)

load_dotenv()

logger = logging.getLogger(__name__)

# Default: gpt-oss-120b (llama-3.3-70b-versatile retired). Override with GROQ_MODEL.
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
# Free-tier TPM for gpt-oss-120b is ~8K; stay under until headers teach us the real limit.
DEFAULT_TPM_CEILING = 8_000
TOKEN_BUDGET_CEILING = int(os.environ.get("TOKEN_BUDGET_CEILING", "7000"))
CLUSTER_MAX_OUT = 1200
CARDS_MAX_OUT = 1600
REASONING_EFFORT = os.environ.get("GROQ_REASONING_EFFORT", "low")

# Base freshness window (days); may widen per category up to CLUSTER_MAX_AGE_CAP.
CLUSTER_MAX_AGE_DAYS = float(os.environ.get("CLUSTER_MAX_AGE_DAYS", "3"))
CLUSTER_MAX_AGE_CAP = float(os.environ.get("CLUSTER_MAX_AGE_CAP", "7"))

# Updated from Groq ``x-ratelimit-*`` response headers when available.
_tpm_limit: int = DEFAULT_TPM_CEILING
_tpm_remaining: int | None = None
_last_retry_after: float = 0.0

# Aggregate usage for the current pipeline run (reset at cluster_articles start).
_run_stats: dict[str, Any] = {
    "calls": 0,
    "prompt_tokens_est": 0,
    "completion_tokens_est": 0,
    "prompt_tokens_api": 0,
    "completion_tokens_api": 0,
    "t0": None,
}

_CLUSTER_CATEGORIES = frozenset(ALL_CATEGORY_SLUGS)
_CARD_CATEGORIES = _CLUSTER_CATEGORIES


def create_client() -> Groq:
    """Return a Groq client. Raises if ``GROQ_API_KEY`` is missing."""
    key = os.getenv("GROQ_API_KEY")
    if not key:
        raise ValueError(
            "GROQ_API_KEY is not set. Copy .env.example to .env and add your Groq API key."
        )
    return Groq(api_key=key)


def _budget_ceiling() -> int:
    """Per-request combined budget under the observed TPM limit.

    Do not shrink based on ``_tpm_remaining`` — free-tier leftover tokens after
    clustering would force single-card batches. Callers wait for headroom instead.
    """
    global _tpm_limit
    return min(TOKEN_BUDGET_CEILING, max(2_000, _tpm_limit - 500))


async def _ensure_tpm_headroom(needed: int) -> None:
    """Sleep when remaining TPM is too low for the next request."""
    global _tpm_remaining
    if _tpm_remaining is None:
        return
    if _tpm_remaining >= needed:
        return
    # Free tier resets on a ~60s window; wait enough to recover.
    wait_s = max(8.0, min(65.0, 15.0 + (needed - _tpm_remaining) / 80.0))
    logger.warning(
        "TPM remaining=%s < needed≈%s; waiting %.1fs for headroom",
        _tpm_remaining,
        needed,
        wait_s,
    )
    await asyncio.sleep(wait_s)
    _tpm_remaining = None  # unknown until next response headers


def _update_rate_limits_from_headers(headers: Any) -> None:
    """Read Groq ``x-ratelimit-*`` headers (TPM = tokens per minute)."""
    global _tpm_limit, _tpm_remaining, _last_retry_after
    if headers is None:
        return

    def _get(name: str) -> str | None:
        try:
            if hasattr(headers, "get"):
                v = headers.get(name) or headers.get(name.lower())
                return str(v) if v is not None else None
        except Exception:
            return None
        return None

    lim = _get("x-ratelimit-limit-tokens")
    rem = _get("x-ratelimit-remaining-tokens")
    retry = _get("retry-after")
    try:
        if lim is not None:
            _tpm_limit = int(float(lim))
        if rem is not None:
            _tpm_remaining = int(float(rem))
        if retry is not None:
            _last_retry_after = float(retry)
    except (TypeError, ValueError):
        pass
    logger.info(
        "Groq rate limits: tpm_limit=%s remaining_tokens=%s retry_after=%s",
        _tpm_limit,
        _tpm_remaining,
        _last_retry_after or None,
    )


class GroqDailyLimitError(RuntimeError):
    """Raised when Groq TPD (daily token) limit is hit — do not keep retrying."""


def _groq_error_body(exc: BaseException) -> str:
    parts = [str(exc)]
    resp = getattr(exc, "response", None)
    if resp is not None:
        text = getattr(resp, "text", None)
        if text:
            parts.append(str(text))
    return "\n".join(parts)


def _is_daily_token_limit(exc: BaseException) -> bool:
    msg = _groq_error_body(exc).lower()
    return any(
        needle in msg
        for needle in (
            "tokens per day",
            "token per day",
            "(tpd)",
            "tpd:",
            "daily token",
            "per day (tpd)",
        )
    )


def _parse_reset_hint(exc: BaseException) -> str | None:
    """Pull 'try again in XmYs' style hint from Groq's error message if present."""
    text = _groq_error_body(exc)
    m = re.search(
        r"try again in\s+([0-9]+m[0-9.]*s|[0-9.]+s|[0-9]+h[0-9m.]*s?)",
        text,
        flags=re.IGNORECASE,
    )
    if m:
        return m.group(1)
    m2 = re.search(r"Please try again in ([^.]+)", text, flags=re.IGNORECASE)
    if m2:
        return m2.group(1).strip()
    return None


def _retry_after_seconds_raw(exc: APIStatusError) -> float:
    """Raw retry-after from headers / last known value (no cap)."""
    resp = getattr(exc, "response", None)
    headers = getattr(resp, "headers", None) if resp is not None else None
    if headers is not None:
        _update_rate_limits_from_headers(headers)
        try:
            raw = None
            if hasattr(headers, "get"):
                raw = headers.get("retry-after") or headers.get("Retry-After")
            if raw is not None:
                return max(1.0, float(raw))
        except (TypeError, ValueError):
            pass
    if _last_retry_after > 0:
        return max(1.0, _last_retry_after)
    return 15.0


def _raise_if_daily_or_long_429(exc: APIStatusError, *, cap_sec: float = 90.0) -> float:
    """
    For 429s: return wait seconds only for short per-minute limits.

    Daily (TPD) limits or retry-after longer than ``cap_sec`` stop the run with
    ``GroqDailyLimitError``.
    """
    wait = _retry_after_seconds_raw(exc)
    daily = _is_daily_token_limit(exc)
    if daily or wait > cap_sec:
        reset = _parse_reset_hint(exc)
        limit_name = "daily token limit (TPD)" if daily else f"long retry-after ({wait:.0f}s)"
        when = f" Resets in about {reset}." if reset else ""
        msg = (
            f"Stopping pipeline: Groq {limit_name} reached.{when} "
            f"Raw error: {_groq_error_body(exc)[:500]}"
        )
        logger.error(msg)
        raise GroqDailyLimitError(msg) from exc
    return wait


def _retry_after_seconds(exc: APIStatusError) -> float:
    """Seconds to wait after a short TPM 429 (raises on daily / long waits)."""
    cap = float(os.environ.get("GROQ_RETRY_AFTER_CAP_SEC", "90"))
    return _raise_if_daily_or_long_429(exc, cap_sec=cap)


def _reset_run_stats() -> None:
    _run_stats["calls"] = 0
    _run_stats["prompt_tokens_est"] = 0
    _run_stats["completion_tokens_est"] = 0
    _run_stats["prompt_tokens_api"] = 0
    _run_stats["completion_tokens_api"] = 0
    _run_stats["t0"] = time.perf_counter()


def get_run_token_totals() -> dict[str, int | float | None]:
    """Return current run API token totals for CLI / logging."""
    api_in = int(_run_stats.get("prompt_tokens_api") or 0)
    api_out = int(_run_stats.get("completion_tokens_api") or 0)
    t0 = _run_stats.get("t0")
    elapsed = (time.perf_counter() - t0) if t0 else None
    return {
        "calls": int(_run_stats.get("calls") or 0),
        "prompt_tokens": api_in,
        "completion_tokens": api_out,
        "total_tokens": api_in + api_out,
        "elapsed_s": elapsed,
    }


def _log_run_stats(phase: str = "pipeline") -> None:
    t0 = _run_stats.get("t0")
    elapsed = (time.perf_counter() - t0) if t0 else 0.0
    api_in = int(_run_stats.get("prompt_tokens_api") or 0)
    api_out = int(_run_stats.get("completion_tokens_api") or 0)
    est_in = int(_run_stats.get("prompt_tokens_est") or 0)
    est_out = int(_run_stats.get("completion_tokens_est") or 0)
    total = (api_in + api_out) if (api_in or api_out) else (est_in + est_out)
    logger.info(
        "%s LLM usage: calls=%s api_tokens=%s (in=%s out=%s) est_tokens=%s (in=%s out=%s) elapsed=%.1fs",
        phase,
        _run_stats.get("calls"),
        total if (api_in or api_out) else None,
        api_in or None,
        api_out or None,
        est_in + est_out,
        est_in,
        est_out,
        elapsed,
    )
    if api_in or api_out:
        logger.info(
            "Groq run token total: %s (prompt=%s completion=%s) across %s calls",
            api_in + api_out,
            api_in,
            api_out,
            _run_stats.get("calls"),
        )


def _record_usage(prompt: str, max_out: int, resp: Any | None = None) -> None:
    _run_stats["calls"] = int(_run_stats.get("calls") or 0) + 1
    call_n = int(_run_stats["calls"])
    _run_stats["prompt_tokens_est"] = int(_run_stats.get("prompt_tokens_est") or 0) + _estimate_input_tokens(
        prompt
    )
    _run_stats["completion_tokens_est"] = int(_run_stats.get("completion_tokens_est") or 0) + max_out
    usage = getattr(resp, "usage", None) if resp is not None else None
    if usage is not None:
        try:
            pin = int(getattr(usage, "prompt_tokens", 0) or 0)
            cout = int(getattr(usage, "completion_tokens", 0) or 0)
            _run_stats["prompt_tokens_api"] = int(_run_stats.get("prompt_tokens_api") or 0) + pin
            _run_stats["completion_tokens_api"] = (
                int(_run_stats.get("completion_tokens_api") or 0) + cout
            )
            run_total = int(_run_stats["prompt_tokens_api"]) + int(
                _run_stats["completion_tokens_api"]
            )
            logger.info(
                "Groq call #%s usage: +%s tokens (in=%s out=%s) run_total=%s",
                call_n,
                pin + cout,
                pin,
                cout,
                run_total,
            )
        except (TypeError, ValueError):
            logger.info("Groq call #%s usage: unavailable", call_n)
    else:
        logger.info(
            "Groq call #%s usage: no usage field (est in≈%s)",
            call_n,
            _estimate_input_tokens(prompt),
        )


def _estimate_input_tokens(text: str) -> int:
    """Rough input-token estimate (characters / 4)."""
    return max(1, len(text) // 4)


def _log_token_estimate(phase: str, prompt: str, max_output: int) -> int:
    est = _estimate_input_tokens(prompt)
    ceiling = _budget_ceiling()
    logger.info(
        "%s: ~%s input tokens (char/4 est.), max_output=%s, est. combined=%s (ceiling=%s, tpm=%s)",
        phase,
        est,
        max_output,
        est + max_output,
        ceiling,
        _tpm_limit,
    )
    return est


def _points(a: Article) -> int:
    e = a.engagement
    if not e:
        return 0
    p = e.get("points")
    try:
        return int(p) if p is not None else 0
    except (TypeError, ValueError):
        return 0


def _recency_ts(a: Article) -> float:
    for s in (a.published_at, a.fetched_at):
        if not s:
            continue
        try:
            t = str(s).strip()
            if t.endswith("Z"):
                t = t[:-1] + "+00:00"
            return datetime.fromisoformat(t).timestamp()
        except Exception:
            continue
    return 0.0


def _article_event_dt(a: Article) -> datetime | None:
    """Best publish/event time for freshness (published_at, else fetched_at)."""
    for s in (a.published_at, a.fetched_at):
        if not s:
            continue
        try:
            t = str(s).strip()
            if t.endswith("Z"):
                t = t[:-1] + "+00:00"
            dt = datetime.fromisoformat(t)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            continue
    return None


def _filter_fresh_articles(
    articles: list[Article], *, max_age_days: float | None = None
) -> list[Article]:
    """Keep articles within ``max_age_days`` (default ``CLUSTER_MAX_AGE_DAYS``) of now (UTC)."""
    days = CLUSTER_MAX_AGE_DAYS if max_age_days is None else max_age_days
    if days <= 0:
        return list(articles)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    kept: list[Article] = []
    dropped = 0
    for a in articles:
        dt = _article_event_dt(a)
        if dt is None:
            dropped += 1
            continue
        if dt < cutoff:
            dropped += 1
            continue
        kept.append(a)
    if dropped:
        logger.info(
            "Freshness filter (<%sd): kept %s, dropped %s",
            days,
            len(kept),
            dropped,
        )
    return kept


def _article_has_slug(a: Article, slug: str) -> bool:
    cats = a.categories or []
    return slug in cats


def _primary_topic_slug(a: Article) -> str | None:
    """First topic slug stamped on the article (query category that found it)."""
    for c in a.categories or []:
        if c in TOPIC_CATEGORY_SLUGS:
            return c
    return None


def _pick_articles_for_category(
    articles: list[Article], slug: str
) -> tuple[list[Article], float]:
    """
    Select up to ``ARTICLES_PER_CATEGORY`` fresh articles for ``slug``.
    Widens the freshness window from ``CLUSTER_MAX_AGE_DAYS`` to ``CLUSTER_MAX_AGE_CAP``
    one day at a time until at least ``MIN_CATEGORY_CARDS`` articles are available
    (or the cap is reached).
    """
    age = float(CLUSTER_MAX_AGE_DAYS)
    pool: list[Article] = []
    while True:
        # Only articles whose primary topic stamp is this slug (avoid cross-topic drift).
        stamped = [a for a in articles if _primary_topic_slug(a) == slug]
        fresh = _filter_fresh_articles(stamped, max_age_days=age)
        # Prefer HN by points, then others by recency.
        hn = sorted(
            [a for a in fresh if a.source_type == "hackernews"],
            key=_points,
            reverse=True,
        )
        other = sorted(
            [a for a in fresh if a.source_type != "hackernews"],
            key=_recency_ts,
            reverse=True,
        )
        merged: list[Article] = []
        seen: set[str] = set()
        for a in hn + other:
            u = (a.url or "").strip()
            if not u or u in seen:
                continue
            seen.add(u)
            merged.append(a)
            if len(merged) >= ARTICLES_PER_CATEGORY:
                break
        pool = merged
        if len(pool) >= MIN_CATEGORY_CARDS or age >= CLUSTER_MAX_AGE_CAP:
            break
        age = min(CLUSTER_MAX_AGE_CAP, age + 1.0)
        logger.info(
            "Category %s short on articles (%s < %s); widening freshness to %sd",
            slug,
            len(pool),
            MIN_CATEGORY_CARDS,
            age,
        )
    logger.info(
        "Category %s: selected %s articles at freshness≤%sd (need ≥%s for cards)",
        slug,
        len(pool),
        age,
        MIN_CATEGORY_CARDS,
    )
    return pool, age


def _select_clustering_articles(articles: list[Article]) -> list[Article]:
    """
    Build a working set for clustering: per-topic selection with freshness widening.
    Articles may appear once even if stamped with multiple categories.
    """
    seen: set[str] = set()
    working: list[Article] = []
    for slug in TOPIC_CATEGORY_SLUGS:
        picked, _age = _pick_articles_for_category(articles, slug)
        for a in picked:
            u = (a.url or "").strip()
            if not u or u in seen:
                continue
            seen.add(u)
            working.append(a)
    # Residual articles (no topic stamp) for possible General overflow.
    residual = [
        a
        for a in _filter_fresh_articles(articles, max_age_days=CLUSTER_MAX_AGE_CAP)
        if (a.url or "").strip()
        and (a.url or "").strip() not in seen
        and not any(s in (a.categories or []) for s in TOPIC_CATEGORY_SLUGS)
    ]
    residual = sorted(residual, key=_recency_ts, reverse=True)[:ARTICLES_PER_CATEGORY]
    for a in residual:
        u = (a.url or "").strip()
        if u and u not in seen:
            seen.add(u)
            working.append(a)
    logger.info(
        "Clustering working set: %s articles across topics (+ residual)",
        len(working),
    )
    return working


def _trim_working_for_token_budget(
    working: list[Article],
    build_prompt: Callable[[list[Article]], str],
    max_output: int,
    phase: str,
) -> tuple[list[Article], str]:
    """Drop articles from the end until est. input + max_output <= ceiling."""
    wk = list(working)
    ceiling = _budget_ceiling()
    while True:
        prompt = build_prompt(wk)
        est = _estimate_input_tokens(prompt)
        if est + max_output <= ceiling:
            return wk, prompt
        if len(wk) <= 1:
            logger.warning(
                "%s: still ~%s input + %s output over budget with 1 article; proceeding anyway",
                phase,
                est,
                max_output,
            )
            return wk, prompt
        wk = wk[:-1]
        logger.warning(
            "%s: trimming to %s articles to stay under token budget (est. input was ~%s)",
            phase,
            len(wk),
            est,
        )


def _strip_markdown_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE | re.MULTILINE)
        t = re.sub(r"\s*```\s*$", "", t, flags=re.MULTILINE)
    return t.strip()


def _parse_json_llm(text: str) -> Any:
    """Parse JSON from LLM output; log raw text on failure; try bracket salvage."""
    cleaned = _strip_markdown_fences(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.warning("JSON parse failed: %s", e)
        logger.warning("Raw LLM response (truncated): %s", text[:4000])

    for pattern in (r"\[[\s\S]*\]", r"\{[\s\S]*\}"):
        m = re.search(pattern, cleaned)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                continue

    # Truncated array: keep complete objects up to the last closing brace.
    if cleaned.lstrip().startswith("["):
        objs: list[Any] = []
        depth = 0
        start: int | None = None
        for i, ch in enumerate(cleaned):
            if ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and start is not None:
                    chunk = cleaned[start : i + 1]
                    try:
                        objs.append(json.loads(chunk))
                    except json.JSONDecodeError:
                        pass
                    start = None
        if objs:
            logger.warning("Salvaged %s complete JSON objects from truncated array", len(objs))
            return objs
    return None


def _groq_status_code(exc: APIStatusError) -> int | None:
    for source in (exc, getattr(exc, "response", None)):
        if source is None:
            continue
        code = getattr(source, "status_code", None)
        if code is not None:
            try:
                return int(code)
            except (TypeError, ValueError):
                continue
    return None


def _should_halve_clustering_input(exc: BaseException) -> bool:
    if not isinstance(exc, APIStatusError):
        return False
    code = _groq_status_code(exc)
    if code == 413:
        return True
    if code == 429:
        return True
    msg = str(exc).lower()
    if "rate_limit" in msg or "rate limit" in msg or "rate_limit_exceeded" in msg:
        return True
    if "tokens per minute" in msg or "tpm" in msg:
        return True
    resp = getattr(exc, "response", None)
    if resp is not None:
        body = (getattr(resp, "text", None) or "").lower()
        if "rate_limit" in body or "rate_limit_exceeded" in body:
            return True
    return False


async def call_llm(
    prompt: str,
    max_tokens: int = 2000,
    *,
    model: str = GROQ_MODEL,
    retry_with_half_prompt: Callable[[], str] | None = None,
) -> str:
    """
    Call Groq chat completions.

    For ``openai/gpt-oss-*`` reasoning models: low reasoning effort, final answer
    only in ``message.content`` (never reasoning text). Respects TPM via headers
    and waits on HTTP 429 ``retry-after``.
    """
    client = create_client()
    ceiling = _budget_ceiling()
    est_in = _estimate_input_tokens(prompt)
    # Keep prompt + completion (incl. reasoning tokens billed in completion) under TPM.
    allowed_out = max(256, min(max_tokens, ceiling - est_in))
    if allowed_out < max_tokens:
        logger.warning(
            "Capping max_completion_tokens from %s to %s for TPM budget (est_in=%s ceiling=%s)",
            max_tokens,
            allowed_out,
            est_in,
            ceiling,
        )

    # Wait so we are not starting a call with almost-empty remaining TPM.
    await _ensure_tpm_headroom(est_in + allowed_out)

    is_gpt_oss = "gpt-oss" in model

    def _sync_call(p: str, out_tokens: int) -> str:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": p}],
            "temperature": 0.3 if not is_gpt_oss else 0.5,
            "max_completion_tokens": out_tokens,
        }
        if is_gpt_oss:
            kwargs["reasoning_effort"] = REASONING_EFFORT
            kwargs["include_reasoning"] = False

        # Prefer raw response so we can read rate-limit headers.
        create = client.chat.completions.create
        with_raw = getattr(client.chat.completions, "with_raw_response", None)
        if with_raw is not None:
            raw = with_raw.create(**kwargs)
            _update_rate_limits_from_headers(getattr(raw, "headers", None))
            resp = raw.parse()
        else:
            resp = create(**kwargs)
            # Some SDK versions expose headers on the http response via private attrs.
            http_resp = getattr(resp, "_response", None) or getattr(resp, "response", None)
            if http_resp is not None:
                _update_rate_limits_from_headers(getattr(http_resp, "headers", None))

        _record_usage(p, out_tokens, resp)
        choice = resp.choices[0].message
        # Final answer only — never use the reasoning field.
        content = (getattr(choice, "content", None) or "").strip()
        if not content:
            raise ValueError("Groq returned empty final content (reasoning-only or blank)")
        return content

    def _call_with_429_retry(p: str, out_tokens: int) -> str:
        attempts = 0
        while True:
            try:
                return _sync_call(p, out_tokens)
            except GroqDailyLimitError:
                raise
            except APIStatusError as e:
                code = _groq_status_code(e)
                if code == 429 and attempts < 3:
                    # Raises GroqDailyLimitError for TPD / long retry-after.
                    wait_s = _retry_after_seconds(e)
                    attempts += 1
                    logger.warning(
                        "Groq 429 TPM limit; sleeping %.1fs then retry (%s/3)",
                        wait_s,
                        attempts,
                    )
                    time.sleep(wait_s)
                    continue
                raise

    try:
        return await asyncio.to_thread(_call_with_429_retry, prompt, allowed_out)
    except GroqDailyLimitError:
        raise
    except APIStatusError as e:
        if (
            retry_with_half_prompt is not None
            and _should_halve_clustering_input(e)
            and not _is_daily_token_limit(e)
        ):
            # Only half-retry on payload / short TPM issues, never on TPD.
            try:
                _raise_if_daily_or_long_429(e)
            except GroqDailyLimitError:
                raise
            logger.warning(
                "Groq rate/payload limit (%s), retrying once with halved clustering input",
                e,
            )
            prompt2 = retry_with_half_prompt()
            est2 = _estimate_input_tokens(prompt2)
            out2 = max(256, min(allowed_out, _budget_ceiling() - est2))
            try:
                return await asyncio.to_thread(_call_with_429_retry, prompt2, out2)
            except GroqDailyLimitError:
                raise
            except APIStatusError as e2:
                logger.exception("Groq API failed after halved-input retry: %s", e2)
                raise
        logger.exception("Groq API call failed: %s", e)
        raise
    except Exception as e:
        logger.exception("Groq API call failed: %s", e)
        raise


def _validate_cluster(
    c: dict[str, Any], n_articles: int
) -> dict[str, Any] | None:
    title = c.get("cluster_title")
    if not title or not str(title).strip():
        return None
    raw_idx = c.get("article_indices")
    if not isinstance(raw_idx, list):
        return None
    indices: list[int] = []
    for x in raw_idx:
        try:
            i = int(x)
        except (TypeError, ValueError):
            return None
        if not (0 <= i < n_articles):
            logger.warning("Invalid article index %s (n=%s)", i, n_articles)
            return None
        indices.append(i)
    cat = c.get("primary_category")
    if cat not in _CLUSTER_CATEGORIES:
        logger.warning("Invalid primary_category %r — dropping cluster %r", cat, title)
        return None
    score = c.get("importance_score", 0.5)
    try:
        score_f = float(score)
        score_f = max(0.0, min(1.0, score_f))
    except (TypeError, ValueError):
        score_f = 0.5
    return {
        "cluster_title": str(title).strip(),
        "article_indices": indices,
        "primary_category": cat,
        "importance_score": score_f,
    }


def _validate_card(c: dict[str, Any]) -> dict[str, Any] | None:
    headline = (c.get("headline") or "").strip()
    blurb = (c.get("blurb") or "").strip()
    why = (c.get("why_it_matters") or "").strip()
    category = c.get("category")
    if not headline or not blurb or not why:
        return None
    # Drop retired / unknown categories (e.g. legacy ``dev_tools``) instead of
    # parking them in general.
    if category not in _CARD_CATEGORIES:
        logger.warning("Dropping card with invalid category %r: %s", category, headline[:60])
        return None
    out: dict[str, Any] = {
        "headline": headline,
        "blurb": blurb,
        "why_it_matters": why,
        "category": category,
    }
    if "is_research_paper" in c:
        out["is_research_paper"] = bool(c.get("is_research_paper"))
    if "cluster_index" in c:
        out["cluster_index"] = c.get("cluster_index")
    return out


def _make_clustering_simplified(wk: list[Article]) -> list[dict[str, Any]]:
    """Minimal fields for clustering prompt (token budget)."""
    return [
        {"index": i, "title": a.title, "source_type": a.source_type}
        for i, a in enumerate(wk)
    ]


async def _cluster_one_batch(
    working: list[Article],
    *,
    target_clusters: int,
    forced_category: str | None = None,
    phase: str = "clustering",
) -> list[dict[str, Any]]:
    """Run one clustering LLM call over ``working`` (local indices 0..n-1)."""
    if not working:
        return []

    def _cluster_prompt_for(wk: list[Article]) -> str:
        simp = _make_clustering_simplified(wk)
        return CLUSTERING_PROMPT.format(
            articles_json=json.dumps(simp, indent=2, ensure_ascii=False),
            target_clusters=target_clusters,
        )

    wk, prompt = _trim_working_for_token_budget(
        working,
        _cluster_prompt_for,
        CLUSTER_MAX_OUT,
        phase,
    )
    n = len(wk)

    def _halve_and_rebuild_prompt() -> str:
        nonlocal wk, n
        half_n = max(1, n // 2)
        wk = wk[:half_n]
        n = len(wk)
        return CLUSTERING_PROMPT.format(
            articles_json=json.dumps(
                _make_clustering_simplified(wk), indent=2, ensure_ascii=False
            ),
            target_clusters=min(target_clusters, max(1, n)),
        )

    _log_token_estimate(phase, prompt, CLUSTER_MAX_OUT)
    raw = await call_llm(
        prompt,
        max_tokens=CLUSTER_MAX_OUT,
        model=GROQ_MODEL,
        retry_with_half_prompt=_halve_and_rebuild_prompt,
    )
    parsed = _parse_json_llm(raw)
    if parsed is None or not isinstance(parsed, list):
        logger.warning(
            "%s: clustering JSON unusable — retrying once with halved article set",
            phase,
        )
        await asyncio.sleep(2.0)
        prompt2 = _halve_and_rebuild_prompt()
        _log_token_estimate(f"{phase}:retry", prompt2, CLUSTER_MAX_OUT)
        raw2 = await call_llm(
            prompt2,
            max_tokens=CLUSTER_MAX_OUT,
            model=GROQ_MODEL,
        )
        parsed = _parse_json_llm(raw2)
    if parsed is None or not isinstance(parsed, list):
        logger.error("%s: could not parse clustering JSON after retry", phase)
        return []

    out: list[dict[str, Any]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        v = _validate_cluster(item, n)
        if not v:
            continue
        if forced_category:
            v["primary_category"] = forced_category
        v["_local_articles"] = wk
        out.append(v)

    # Thin salvage: if we kept fewer clusters than the floor, retry once with a
    # smaller article set (common when Groq truncates mid-JSON).
    if len(out) < min(target_clusters, MIN_CATEGORY_CARDS) and len(wk) > MIN_CATEGORY_CARDS:
        logger.warning(
            "%s: only %s valid clusters (wanted ≥%s) — retrying with halved set",
            phase,
            len(out),
            min(target_clusters, MIN_CATEGORY_CARDS),
        )
        await asyncio.sleep(2.0)
        prompt2 = _halve_and_rebuild_prompt()
        _log_token_estimate(f"{phase}:thin-retry", prompt2, CLUSTER_MAX_OUT)
        raw2 = await call_llm(
            prompt2,
            max_tokens=CLUSTER_MAX_OUT,
            model=GROQ_MODEL,
        )
        parsed2 = _parse_json_llm(raw2)
        if isinstance(parsed2, list):
            retry_out: list[dict[str, Any]] = []
            for item in parsed2:
                if not isinstance(item, dict):
                    continue
                v = _validate_cluster(item, n)
                if not v:
                    continue
                if forced_category:
                    v["primary_category"] = forced_category
                v["_local_articles"] = wk
                retry_out.append(v)
            if len(retry_out) > len(out):
                logger.info(
                    "%s: thin-retry improved clusters %s → %s",
                    phase,
                    len(out),
                    len(retry_out),
                )
                out = retry_out

    return out


async def cluster_articles(
    articles: list[Article], target_clusters: int = 50
) -> tuple[list[dict[str, Any]], list[Article]]:
    """
    Cluster articles per topic category (separate Groq calls to stay under TPM).

    Returns ``(clusters, working_articles)``. ``article_indices`` refer to
    ``working_articles`` (pass this list to ``generate_cards``).
    """
    _reset_run_stats()
    funnel_mod.reset_funnel()
    # Ingest counts by primary topic stamp.
    for a in articles:
        slug = None
        for s in a.categories or []:
            if s in TOPIC_CATEGORY_SLUGS:
                slug = s
                break
        if not slug:
            continue
        if a.source_type == "hackernews":
            funnel_mod.bump(slug, "hn_fetched", 1)
        elif a.source_type == "brave":
            funnel_mod.bump(slug, "brave_fetched", 1)
        elif a.source_type == "arxiv":
            funnel_mod.bump(slug, "arxiv_fetched", 1)
    per_cat: dict[str, list[Article]] = {}
    for slug in TOPIC_CATEGORY_SLUGS:
        picked, age = _pick_articles_for_category(articles, slug)
        if len(picked) < MIN_CATEGORY_CARDS:
            logger.warning(
                "Skipping category %s for clustering: only %s articles within %sd "
                "(need ≥%s)",
                slug,
                len(picked),
                age,
                MIN_CATEGORY_CARDS,
            )
            continue
        per_cat[slug] = picked
        funnel_mod.set_count(slug, "after_freshness", len(picked))
        # Dedupe by URL within the picked pool.
        seen_u: set[str] = set()
        deduped: list[Article] = []
        for a in picked:
            u = (a.url or "").strip()
            if not u or u in seen_u:
                continue
            seen_u.add(u)
            deduped.append(a)
        per_cat[slug] = deduped
        funnel_mod.set_count(slug, "after_dedupe", len(deduped))

    # Residual pool for General overflow.
    used_urls = {(a.url or "").strip() for pool in per_cat.values() for a in pool}
    residual = [
        a
        for a in _filter_fresh_articles(articles, max_age_days=CLUSTER_MAX_AGE_CAP)
        if (a.url or "").strip()
        and (a.url or "").strip() not in used_urls
        and not any(s in (a.categories or []) for s in TOPIC_CATEGORY_SLUGS)
    ]
    residual = sorted(residual, key=_recency_ts, reverse=True)[:ARTICLES_PER_CATEGORY]
    if len(residual) >= MIN_CATEGORY_CARDS:
        per_cat[GENERAL_SLUG] = residual

    # Build global working list and remapped clusters.
    working: list[Article] = []
    url_to_global: dict[str, int] = {}
    all_clusters: list[dict[str, Any]] = []

    for slug, pool in per_cat.items():
        # Append unseen articles to working.
        local_articles: list[Article] = []
        for a in pool:
            u = (a.url or "").strip()
            if not u:
                continue
            if u not in url_to_global:
                url_to_global[u] = len(working)
                working.append(a)
            local_articles.append(a)

        quota = CATEGORY_QUOTA
        target = min(quota + 2, max(MIN_CATEGORY_CARDS, len(local_articles)))
        phase = f"clustering[{slug}]"
        raw_clusters = await _cluster_one_batch(
            local_articles,
            target_clusters=target,
            forced_category=slug if slug != GENERAL_SLUG else None,
            phase=phase,
        )
        for c in raw_clusters:
            # Map from local trimmed indices → local_articles → global.
            local_arts: list[Article] = c.pop("_local_articles", local_articles)
            remapped: list[int] = []
            for i in c.get("article_indices") or []:
                if not isinstance(i, int) or not (0 <= i < len(local_arts)):
                    continue
                u = (local_arts[i].url or "").strip()
                gi = url_to_global.get(u)
                if gi is not None:
                    remapped.append(gi)
            if not remapped:
                continue
            c["article_indices"] = remapped
            if slug != GENERAL_SLUG:
                c["primary_category"] = slug
            elif c.get("primary_category") not in _CLUSTER_CATEGORIES:
                c["primary_category"] = GENERAL_SLUG
            all_clusters.append(c)
        # Pause between category calls so free-tier TPM can recover.
        await asyncio.sleep(2.0)

    _log_run_stats("clustering")
    if not all_clusters:
        logger.warning("No valid clusters after per-category clustering")
    return all_clusters, working


def _build_minimal_card_payload(
    clusters_slice: list[dict[str, Any]], articles: list[Article]
) -> list[dict[str, Any]]:
    """Cluster title plus grounded article title/snippet excerpts for the writer."""
    payload: list[dict[str, Any]] = []
    for idx, c in enumerate(clusters_slice):
        idxs = c.get("article_indices") or []
        arts: list[dict[str, str]] = []
        for i in idxs:
            if isinstance(i, int) and 0 <= i < len(articles):
                a = articles[i]
                excerpt = (a.snippet or a.full_text or "")[:220]
                arts.append(
                    {
                        "title": a.title,
                        "excerpt": excerpt,
                        "source_type": a.source_type,
                    }
                )
        payload.append(
            {
                "cluster_index": idx,
                "cluster_title": c.get("cluster_title"),
                "articles": arts,
            }
        )
    return payload


def _align_cards_to_clusters(
    cards: list[dict[str, Any]], cluster_count: int
) -> list[dict[str, Any]]:
    """
    Map LLM cards back to clusters by ``cluster_index`` when present;
    otherwise keep order and truncate to ``cluster_count``.
    """

    def _clean(card: dict[str, Any]) -> dict[str, Any]:
        c = dict(card)
        c.pop("cluster_index", None)
        return c

    by_idx: dict[int, dict[str, Any]] = {}
    ordered_fallback: list[dict[str, Any]] = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        ordered_fallback.append(card)
        raw = card.get("cluster_index")
        try:
            ci = int(raw) if raw is not None else -1
        except (TypeError, ValueError):
            ci = -1
        if 0 <= ci < cluster_count and ci not in by_idx:
            by_idx[ci] = card

    if len(by_idx) == cluster_count:
        return [_clean(by_idx[i]) for i in range(cluster_count)]

    return [_clean(c) for c in ordered_fallback[:cluster_count]]


def _trim_clusters_for_card_budget(
    cluster_slice: list[dict[str, Any]],
    articles: list[Article],
) -> tuple[list[dict[str, Any]], str]:
    """Reduce cluster count until est. prompt + CARDS_MAX_OUT fits ceiling."""
    sl = list(cluster_slice)

    def build_prompt(clusters: list[dict[str, Any]]) -> str:
        pl = _build_minimal_card_payload(clusters, articles)
        return CARD_WRITER_PROMPT.format(
            clusters_json=json.dumps(pl, indent=2, ensure_ascii=False),
        )

    while True:
        prompt = build_prompt(sl)
        est = _estimate_input_tokens(prompt)
        ceiling = _budget_ceiling()
        if est + CARDS_MAX_OUT <= ceiling:
            return sl, prompt
        if len(sl) <= 1:
            logger.warning(
                "cards: ~%s input + %s output still over budget with 1 cluster; proceeding",
                est,
                CARDS_MAX_OUT,
            )
            return sl, prompt
        sl = sl[:-1]
        logger.warning(
            "cards: trimming to %s clusters for token budget (est. input was ~%s)",
            len(sl),
            est,
        )


def _attach_sources_and_meta(
    card: dict[str, Any], cluster: dict[str, Any], articles: list[Article]
) -> dict[str, Any]:
    idxs = cluster.get("article_indices") or []
    sources: list[dict[str, Any]] = []
    latest_pub: datetime | None = None
    seen_domains: set[str] = set()
    for j in idxs:
        if isinstance(j, int) and 0 <= j < len(articles):
            a = articles[j]
            pub_url = publisher_url_for_article(a)
            if not pub_url:
                continue
            # Prefer publisher domain; HN discussion threads are not independent outlets.
            if is_hn_host(pub_url):
                # Self-post / no external link — keep as last-resort single source.
                domain = "news.ycombinator.com"
                if domain in seen_domains:
                    continue
                seen_domains.add(domain)
                sources.append(
                    {
                        "title": a.title,
                        "url": pub_url,
                        "source_type": "hackernews",
                        "source_name": "HackerNews",
                        "engagement": a.engagement,
                        "published_at": a.published_at,
                    }
                )
                continue
            domain = source_outlet_domain(
                {"url": pub_url, "source_name": a.source_name, "source_type": a.source_type}
            )
            if domain in seen_domains:
                continue
            seen_domains.add(domain)
            source_name = domain or (a.source_name or "Unknown")
            sources.append(
                {
                    "title": a.title,
                    "url": pub_url,
                    "source_type": a.source_type,
                    "source_name": source_name,
                    "engagement": a.engagement,
                    "published_at": a.published_at,
                }
            )
            if a.published_at:
                try:
                    t = str(a.published_at).strip()
                    if t.endswith("Z"):
                        t = t[:-1] + "+00:00"
                    pdt = datetime.fromisoformat(t)
                    if pdt.tzinfo is None:
                        pdt = pdt.replace(tzinfo=timezone.utc)
                    pdt = pdt.astimezone(timezone.utc)
                    if latest_pub is None or pdt > latest_pub:
                        latest_pub = pdt
                except Exception:
                    pass
    # Research fallback: if we stripped everything, keep arXiv.
    if not sources:
        for j in idxs:
            if isinstance(j, int) and 0 <= j < len(articles):
                a = articles[j]
                if a.source_type == "arxiv" or "arxiv.org" in (a.url or ""):
                    sources.append(
                        {
                            "title": a.title,
                            "url": a.url,
                            "source_type": "arxiv",
                            "source_name": a.source_name or "ArXiv",
                            "engagement": a.engagement,
                            "published_at": a.published_at,
                        }
                    )
                    break
    card["sources"] = sources
    multi = is_corroborated(sources) or bool(cluster.get("corroborated"))
    is_paper = bool(card.get("is_research_paper")) or bool(
        cluster.get("research_primary")
    ) or any(s.get("source_type") == "arxiv" for s in sources)
    if is_paper:
        card["is_research_paper"] = True
    # single_source: news cards with <2 outlets (research-only arXiv is allowed).
    if is_paper and independent_outlet_count(sources) <= 1:
        card["single_source"] = False
    else:
        card["single_source"] = not multi and independent_outlet_count(sources) < 2
    if latest_pub is not None:
        card["published_at"] = latest_pub.isoformat()
    try:
        card["importance_score"] = float(cluster.get("importance_score") or 0)
    except (TypeError, ValueError):
        card["importance_score"] = 0.5
    # Boost corroborated stories in ranking.
    if multi and not card.get("single_source"):
        card["importance_score"] = min(
            1.0, float(card.get("importance_score") or 0) + 0.08
        )
    ct = cluster.get("cluster_title")
    if ct:
        card["cluster_title"] = str(ct).strip()
    cat = cluster.get("primary_category")
    if cat in _CARD_CATEGORIES:
        card["category"] = cat
    return card


def _source_urls(card: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for s in card.get("sources") or []:
        if isinstance(s, dict):
            u = (s.get("url") or "").strip()
            if u:
                out.add(u)
    return out


def _headline_key(card: dict[str, Any]) -> str:
    return re.sub(r"\W+", " ", (card.get("headline") or "").lower()).strip()


def _dedupe_cards(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop cards that share sources or near-identical headlines with a kept card."""
    kept: list[dict[str, Any]] = []
    used_urls: set[str] = set()
    used_heads: set[str] = set()
    for card in sorted(
        cards,
        key=lambda c: float(c.get("importance_score") or 0),
        reverse=True,
    ):
        urls = _source_urls(card)
        head = _headline_key(card)
        if urls and urls & used_urls:
            logger.info(
                "Deduping card (shared source): %s",
                (card.get("headline") or "")[:60],
            )
            continue
        if head and head in used_heads:
            logger.info(
                "Deduping card (duplicate headline): %s",
                (card.get("headline") or "")[:60],
            )
            continue
        kept.append(card)
        used_urls |= urls
        if head:
            used_heads.add(head)
    return kept


async def _generate_cards_for_clusters(
    cluster_slice: list[dict[str, Any]],
    articles: list[Article],
    *,
    forced_category: str,
    phase: str,
) -> list[dict[str, Any]]:
    if not cluster_slice:
        return []
    # Free-tier TPM: generate in small batches so JSON is not truncated mid-card.
    batch_size = 4
    out: list[dict[str, Any]] = []
    for start in range(0, len(cluster_slice), batch_size):
        batch = cluster_slice[start : start + batch_size]
        batch, prompt = _trim_clusters_for_card_budget(batch, articles)
        batch_phase = f"{phase}[{start}:{start + len(batch)}]"
        _log_token_estimate(batch_phase, prompt, CARDS_MAX_OUT)
        raw = await call_llm(prompt, max_tokens=CARDS_MAX_OUT, model=GROQ_MODEL)
        parsed = _parse_json_llm(raw)
        if parsed is None or not isinstance(parsed, list):
            logger.error("%s: could not parse card JSON", batch_phase)
            continue

        validated: list[dict[str, Any]] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            v = _validate_card(item)
            if v:
                validated.append(v)

        if len(validated) != len(batch):
            logger.warning(
                "%s: card count (%s) differs from cluster slice (%s)",
                batch_phase,
                len(validated),
                len(batch),
            )
        aligned = _align_cards_to_clusters(validated, len(batch))
        for i, card in enumerate(aligned):
            c = batch[i]
            card = _attach_sources_and_meta(card, c, articles)
            card["category"] = forced_category
            out.append(card)
        await asyncio.sleep(1.0)
    return out


def _cluster_fingerprint(cluster: dict[str, Any]) -> tuple[int, ...]:
    idxs = cluster.get("article_indices") or []
    return tuple(sorted(i for i in idxs if isinstance(i, int)))


async def generate_cards(
    clusters: list[dict[str, Any]], articles: list[Article]
) -> list[dict[str, Any]]:
    """
    Corroborate clusters, then generate cards in two passes per category.

    Pass 1 secures ``MIN_CATEGORY_CARDS`` (preferring multi-outlet stories).
    Pass 2 tops each category toward ``CATEGORY_QUOTA`` (~12).
    Single-source news cards are used only to meet the per-category floor and
    are flagged ``single_source=True``. Aim for ``MIN_TOTAL_CARDS`` overall.
    """
    if not clusters:
        return []

    # Corroboration normally runs in cluster_node; skip if clusters already tagged.
    if not any("corroborated" in c or "research_primary" in c for c in clusters):
        clusters, articles, corr_stats = await corroborate_clusters(clusters, articles)
        logger.info(
            "Post-corroboration (cards path): clusters=%s articles=%s "
            "brave_queries=%s matches=%s",
            len(clusters),
            len(articles),
            corr_stats.get("queries"),
            corr_stats.get("matches"),
        )
    else:
        logger.info(
            "Skipping corroboration in generate_cards (already done upstream); "
            "clusters=%s articles=%s",
            len(clusters),
            len(articles),
        )

    by_cat: dict[str, list[dict[str, Any]]] = {s: [] for s in ALL_CATEGORY_SLUGS}
    for c in clusters:
        cat = c.get("primary_category") or GENERAL_SLUG
        if cat not in by_cat:
            cat = GENERAL_SLUG
        if cat == GENERAL_SLUG:
            idxs = c.get("article_indices") or []
            topic_votes = set()
            for j in idxs:
                if isinstance(j, int) and 0 <= j < len(articles):
                    for s in articles[j].categories or []:
                        if s in TOPIC_CATEGORY_SLUGS:
                            topic_votes.add(s)
            if len(topic_votes) == 1:
                cat = next(iter(topic_votes))
            elif len(topic_votes) > 1:
                for s in TOPIC_CATEGORY_SLUGS:
                    if s in topic_votes:
                        cat = s
                        break
        c["primary_category"] = cat
        by_cat[cat].append(c)
        if cat in TOPIC_CATEGORY_SLUGS or cat == GENERAL_SLUG:
            funnel_mod.bump(cat, "clusters_formed", 1)

    def _cluster_rank_key(c: dict[str, Any]) -> tuple:
        arts = []
        for j in c.get("article_indices") or []:
            if isinstance(j, int) and 0 <= j < len(articles):
                arts.append(articles[j])
        multi = bool(c.get("corroborated")) or independent_outlet_count(arts) >= 2
        research = bool(c.get("research_primary")) or (
            arts and all(a.source_type == "arxiv" for a in arts)
        )
        # Prefer corroborated / multi-outlet, then research, then importance.
        return (
            0 if multi else (1 if research else 2),
            -float(c.get("importance_score") or 0),
        )

    cards_by_cat: dict[str, list[dict[str, Any]]] = {
        s: [] for s in list(TOPIC_CATEGORY_SLUGS) + [GENERAL_SLUG]
    }
    used_fps: dict[str, set[tuple[int, ...]]] = {s: set() for s in cards_by_cat}

    async def _write_slice(
        slug: str,
        cluster_slice: list[dict[str, Any]],
        *,
        phase: str,
        limit: int,
        allow_single: bool,
    ) -> list[dict[str, Any]]:
        if not cluster_slice or limit <= 0:
            return []
        funnel_mod.bump(slug, "clusters_selected", len(cluster_slice))
        cards = await _generate_cards_for_clusters(
            cluster_slice,
            articles,
            forced_category=slug,
            phase=phase,
        )
        funnel_mod.bump(slug, "cards_generated", len(cards))
        cards = _dedupe_cards(cards)
        # Attach already done inside _generate; re-evaluate single_source preference.
        kept: list[dict[str, Any]] = []
        for card in sorted(
            cards,
            key=lambda c: (
                1 if c.get("single_source") else 0,
                -float(c.get("importance_score") or 0),
            ),
        ):
            is_paper = bool(card.get("is_research_paper"))
            single = bool(card.get("single_source")) and not is_paper
            if single and not allow_single:
                continue
            # News cards should have ≥1 source URL after attach.
            if not (card.get("sources") or []):
                continue
            kept.append(card)
            if len(kept) >= limit:
                break
        funnel_mod.bump(slug, "cards_validated", len(kept))
        # Only mark clusters that we actually attempted (whole slice) so pass2
        # can still use leftovers — mark by fingerprint of slice items.
        for c in cluster_slice:
            used_fps[slug].add(_cluster_fingerprint(c))
        return kept

    # Pass 1: floor with corroborated first; allow single-source only as needed.
    for slug in list(TOPIC_CATEGORY_SLUGS) + [GENERAL_SLUG]:
        group = by_cat.get(slug) or []
        if not group:
            if slug != GENERAL_SLUG:
                logger.warning(
                    "Category %s has zero clusters after clustering — "
                    "cannot publish cards for this topic",
                    slug,
                )
            continue
        ranked = sorted(group, key=_cluster_rank_key)
        floor = MIN_CATEGORY_CARDS
        # Take only the floor for pass 1 so remaining clusters stay for pass 2.
        multi = [
            c
            for c in ranked
            if c.get("corroborated")
            or independent_outlet_count(
                [
                    articles[j]
                    for j in (c.get("article_indices") or [])
                    if isinstance(j, int) and 0 <= j < len(articles)
                ]
            )
            >= 2
            or bool(c.get("research_primary"))
        ]
        single = [c for c in ranked if c not in multi]
        slice_multi = multi[:floor]
        need_single = max(0, floor - len(slice_multi))
        slice1 = slice_multi + single[:need_single]
        # If still short, pad from ranked.
        if len(slice1) < floor:
            for c in ranked:
                if c not in slice1:
                    slice1.append(c)
                if len(slice1) >= floor:
                    break

        cards = await _write_slice(
            slug,
            slice1,
            phase=f"cards.pass1[{slug}]",
            limit=floor,
            allow_single=True,
        )
        # Prefer dropping single-source extras above the floor.
        multi_cards = [c for c in cards if not c.get("single_source") or c.get("is_research_paper")]
        single_cards = [c for c in cards if c.get("single_source") and not c.get("is_research_paper")]
        secured = multi_cards[:floor]
        if len(secured) < floor:
            secured = secured + single_cards[: floor - len(secured)]
        cards_by_cat[slug] = secured
        if len(secured) < floor:
            logger.warning(
                "Category %s below floor after pass 1: %s cards (wanted >=%s).",
                slug,
                len(secured),
                floor,
            )
        else:
            logger.info("Category %s: pass 1 secured %s cards", slug, len(secured))
        await asyncio.sleep(1.5)

    # Pass 2: top toward quota with corroborated-only when possible.
    for slug in list(TOPIC_CATEGORY_SLUGS) + [GENERAL_SLUG]:
        group = by_cat.get(slug) or []
        if not group:
            continue
        have = len(cards_by_cat[slug])
        quota = CATEGORY_QUOTA
        if have >= quota:
            continue
        ranked = sorted(group, key=_cluster_rank_key)
        remaining = [
            c for c in ranked if _cluster_fingerprint(c) not in used_fps[slug]
        ]
        # Prefer multi-outlet for fill.
        remaining_multi = [
            c
            for c in remaining
            if c.get("corroborated")
            or independent_outlet_count(
                [
                    articles[j]
                    for j in (c.get("article_indices") or [])
                    if isinstance(j, int) and 0 <= j < len(articles)
                ]
            )
            >= 2
            or bool(c.get("research_primary"))
        ]
        need = quota - have
        if not remaining_multi and have >= MIN_CATEGORY_CARDS:
            logger.info(
                "Category %s: pass 2 skipped (no unused multi-outlet clusters; have %s/%s)",
                slug,
                have,
                quota,
            )
            continue
        slice2 = (remaining_multi or remaining)[: need + 2]
        if not slice2:
            continue
        more = await _write_slice(
            slug,
            slice2,
            phase=f"cards.pass2[{slug}]",
            limit=need,
            allow_single=have < MIN_CATEGORY_CARDS,
        )
        # Drop single-source additions in pass 2 unless still under floor.
        if have >= MIN_CATEGORY_CARDS:
            more = [
                c
                for c in more
                if not c.get("single_source") or c.get("is_research_paper")
            ]
        merged = _dedupe_cards(cards_by_cat[slug] + more)
        merged = sorted(
            merged,
            key=lambda c: (
                1 if c.get("single_source") else 0,
                -float(c.get("importance_score") or 0),
            ),
        )[:quota]
        cards_by_cat[slug] = merged
        logger.info(
            "Category %s: pass 2 -> %s cards (target %s)",
            slug,
            len(merged),
            quota,
        )
        await asyncio.sleep(1.5)

    # Optional fill pass toward MIN_TOTAL_CARDS from leftover multi-outlet clusters.
    total = sum(len(v) for v in cards_by_cat.values())
    if total < MIN_TOTAL_CARDS:
        logger.info(
            "Total cards %s < MIN_TOTAL_CARDS %s — fill pass from leftover clusters",
            total,
            MIN_TOTAL_CARDS,
        )
        for slug in TOPIC_CATEGORY_SLUGS:
            if total >= MIN_TOTAL_CARDS:
                break
            group = by_cat.get(slug) or []
            if not group:
                continue
            if len(cards_by_cat[slug]) >= CATEGORY_QUOTA:
                continue
            ranked = sorted(group, key=_cluster_rank_key)
            remaining = [
                c
                for c in ranked
                if _cluster_fingerprint(c) not in used_fps[slug]
                and (
                    c.get("corroborated")
                    or independent_outlet_count(
                        [
                            articles[j]
                            for j in (c.get("article_indices") or [])
                            if isinstance(j, int) and 0 <= j < len(articles)
                        ]
                    )
                    >= 2
                )
            ]
            room = min(CATEGORY_QUOTA - len(cards_by_cat[slug]), MIN_TOTAL_CARDS - total)
            if room <= 0 or not remaining:
                continue
            more = await _write_slice(
                slug,
                remaining[: room + 1],
                phase=f"cards.fill[{slug}]",
                limit=room,
                allow_single=False,
            )
            cards_by_cat[slug] = _dedupe_cards(cards_by_cat[slug] + more)[:CATEGORY_QUOTA]
            total = sum(len(v) for v in cards_by_cat.values())
            await asyncio.sleep(1.0)

    all_cards: list[dict[str, Any]] = []
    for slug in list(TOPIC_CATEGORY_SLUGS) + [GENERAL_SLUG]:
        cards = cards_by_cat.get(slug) or []
        if not cards:
            if slug != GENERAL_SLUG:
                logger.warning(
                    "Omitting category %s from feed: zero cards after both passes",
                    slug,
                )
            continue
        if len(cards) < MIN_CATEGORY_CARDS:
            logger.warning(
                "Publishing category %s with only %s cards (below min %s)",
                slug,
                len(cards),
                MIN_CATEGORY_CARDS,
            )
        else:
            logger.info("Category %s: publishing %s cards", slug, len(cards))
        singles = sum(
            1
            for c in cards
            if c.get("single_source") and not c.get("is_research_paper")
        )
        if singles:
            funnel_mod.set_count(slug, "single_source_published", singles)
            logger.warning(
                "Category %s: %s single-source card(s) published to meet floor",
                slug,
                singles,
            )
        funnel_mod.set_count(slug, "cards_published", len(cards))
        all_cards.extend(cards)

    all_cards = _dedupe_cards(all_cards)
    counts: dict[str, int] = {}
    for c in all_cards:
        cat = c.get("category") or GENERAL_SLUG
        counts[cat] = counts.get(cat, 0) + 1
    final: list[dict[str, Any]] = list(all_cards)
    for cat, n in counts.items():
        if 0 < n < MIN_CATEGORY_CARDS:
            logger.warning(
                "Category %s still below min after cross-dedupe: %s < %s cards "
                "(keeping in feed)",
                cat,
                n,
                MIN_CATEGORY_CARDS,
            )

    order_index = {
        s: i for i, s in enumerate(list(TOPIC_CATEGORY_SLUGS) + [GENERAL_SLUG])
    }
    final.sort(
        key=lambda c: (
            order_index.get(c.get("category") or GENERAL_SLUG, 99),
            1 if c.get("single_source") else 0,
            -float(c.get("importance_score") or 0),
        )
    )
    for i, card in enumerate(final):
        card["order"] = i + 1

    _log_run_stats("cards+clustering")
    funnel_mod.log_funnel()
    logger.info(
        "Published cards by category: %s (total=%s, min_total=%s)",
        {
            s: sum(1 for c in final if c.get("category") == s)
            for s in list(TOPIC_CATEGORY_SLUGS) + [GENERAL_SLUG]
            if any(c.get("category") == s for c in final)
        },
        len(final),
        MIN_TOTAL_CARDS,
    )
    if len(final) < MIN_TOTAL_CARDS:
        logger.warning(
            "Feed total %s is below MIN_TOTAL_CARDS=%s",
            len(final),
            MIN_TOTAL_CARDS,
        )
    return final



if __name__ == "__main__":
    import asyncio

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    test_articles = [
        Article(
            title="NVIDIA announces new B300 GPU",
            url="https://example.com/1",
            source_type="hackernews",
            source_name="HN",
            snippet="NVIDIA unveiled next-gen accelerators for data centers.",
            full_text=None,
            published_at="2026-04-03T12:00:00Z",
            fetched_at="2026-04-03T12:00:00Z",
            engagement={"points": 500, "comments": 200},
            authors=["nvidia"],
            categories=[],
            image_url=None,
            extra=None,
        ),
        Article(
            title="Scaling laws for sparse transformers",
            url="https://arxiv.org/abs/1234.5678",
            source_type="arxiv",
            source_name="ArXiv",
            snippet="We study scaling behavior of sparse attention on long contexts.",
            full_text=None,
            published_at="2026-04-01T00:00:00Z",
            fetched_at="2026-04-03T10:00:00Z",
            engagement=None,
            authors=["a", "b"],
            categories=["cs.LG"],
            image_url=None,
            extra={"pdf_url": "https://arxiv.org/pdf/1234.5678.pdf"},
        ),
        Article(
            title="Major cloud outage traced to BGP misconfiguration",
            url="https://example.com/3",
            source_type="brave",
            source_name="reuters.com",
            snippet="A routing error disrupted traffic across three regions for two hours.",
            full_text=None,
            published_at="2026-04-02T15:00:00Z",
            fetched_at="2026-04-03T09:00:00Z",
            engagement=None,
            authors=[],
            categories=[],
            image_url=None,
            extra=None,
        ),
        Article(
            title="CISA warns of actively exploited zero-day in popular VPN",
            url="https://example.com/4",
            source_type="hackernews",
            source_name="HN",
            snippet="Federal agencies urge patching within 24 hours.",
            full_text=None,
            published_at="2026-04-03T08:00:00Z",
            fetched_at="2026-04-03T11:00:00Z",
            engagement={"points": 1200, "comments": 400},
            authors=["cisa"],
            categories=[],
            image_url=None,
            extra=None,
        ),
        Article(
            title="Rust 1.78 ships with faster compile times for large workspaces",
            url="https://example.com/5",
            source_type="brave",
            source_name="blog.rust-lang.org",
            snippet="The release focuses on incremental compilation and diagnostics.",
            full_text=None,
            published_at="2026-04-03T00:00:00Z",
            fetched_at="2026-04-03T07:00:00Z",
            engagement=None,
            authors=[],
            categories=[],
            image_url=None,
            extra=None,
        ),
    ]

    async def _run() -> None:
        clusters, working = await cluster_articles(test_articles, target_clusters=3)
        cards = await generate_cards(clusters, working)
        print(json.dumps(cards, indent=2, ensure_ascii=False))

    asyncio.run(_run())
