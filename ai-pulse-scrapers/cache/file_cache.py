"""Simple file-based JSON cache (dev-friendly; avoids repeated API calls)."""

from __future__ import annotations

import functools
import hashlib
import inspect
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

CACHE_DIR = Path(".cache")

__all__ = [
    "CACHE_DIR",
    "make_key",
    "get",
    "put",
    "cached",
    "clear",
]


def make_key(prefix: str, *args) -> str:
    """Combine prefix + str(args), SHA256 hash, return hex digest."""
    combined = prefix + str(args)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def get(key: str, ttl_hours: int = 12) -> Any | None:
    path = CACHE_DIR / f"{key}.json"
    if not path.is_file():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
        cached_at_str = payload.get("_cached_at")
        if not cached_at_str:
            return None
        s = str(cached_at_str).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        cached_at = datetime.fromisoformat(s)
        if cached_at.tzinfo is None:
            cached_at = cached_at.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if now - cached_at > timedelta(hours=ttl_hours):
            return None
        if "data" not in payload:
            return None
        return payload["data"]
    except Exception as e:
        logger.warning("cache get failed for key=%s: %s", key[:16], e)
        return None


def put(key: str, data: Any) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{key}.json"
    payload = {
        "_cached_at": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
    except TypeError as e:
        logger.warning("cache put skipped (not JSON-serializable): %s", e)
    except Exception as e:
        logger.warning("cache put failed: %s", e)


def cached(prefix: str, ttl_hours: int = 12):
    """
    Cache decorator for sync or async callables.
    Key = SHA256(prefix + str(args) + str(sorted(kwargs))).
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                key = make_key(prefix, args, tuple(sorted(kwargs.items())))
                hit = get(key, ttl_hours)
                if hit is not None:
                    return hit
                result = await fn(*args, **kwargs)
                put(key, result)
                return result

            return async_wrapper

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            key = make_key(prefix, args, tuple(sorted(kwargs.items())))
            hit = get(key, ttl_hours)
            if hit is not None:
                return hit
            result = fn(*args, **kwargs)
            put(key, result)
            return result

        return sync_wrapper

    return decorator


def clear() -> int:
    """Delete all files in CACHE_DIR; return number removed."""
    if not CACHE_DIR.exists():
        return 0
    n = 0
    for p in CACHE_DIR.iterdir():
        if p.is_file():
            try:
                p.unlink()
                n += 1
            except OSError as e:
                logger.warning("cache clear failed for %s: %s", p, e)
    return n


if __name__ == "__main__":
    deleted = clear()
    print(deleted)
