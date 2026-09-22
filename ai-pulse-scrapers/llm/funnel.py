"""Per-category pipeline funnel counters for logs and verify reports."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from .quotas import TOPIC_CATEGORY_SLUGS

logger = logging.getLogger(__name__)

_FunnelRow = dict[str, int]

_FUNNEL: dict[str, _FunnelRow] = defaultdict(
    lambda: {
        "hn_fetched": 0,
        "brave_fetched": 0,
        "arxiv_fetched": 0,
        "after_freshness": 0,
        "after_dedupe": 0,
        "clusters_formed": 0,
        "clusters_selected": 0,
        "cards_generated": 0,
        "cards_validated": 0,
        "cards_published": 0,
        "corroboration_queries": 0,
        "corroboration_matches": 0,
        "single_source_published": 0,
    }
)


def reset_funnel() -> None:
    _FUNNEL.clear()


def bump(category: str, key: str, n: int = 1) -> None:
    if not category or n == 0:
        return
    _FUNNEL[category][key] = int(_FUNNEL[category].get(key, 0)) + int(n)


def set_count(category: str, key: str, n: int) -> None:
    if not category:
        return
    _FUNNEL[category][key] = int(n)


def snapshot() -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for slug in list(TOPIC_CATEGORY_SLUGS) + ["general"]:
        row = dict(_FUNNEL.get(slug) or {})
        if row:
            out[slug] = row
    for slug, row in _FUNNEL.items():
        if slug not in out:
            out[slug] = dict(row)
    return out


def log_funnel(prefix: str = "Funnel") -> dict[str, dict[str, int]]:
    data = snapshot()
    for slug, row in data.items():
        logger.info(
            "%s[%s]: hn=%s brave=%s arxiv=%s fresh=%s deduped=%s "
            "clusters=%s selected=%s generated=%s validated=%s published=%s "
            "corr_q=%s corr_hit=%s single_src=%s",
            prefix,
            slug,
            row.get("hn_fetched", 0),
            row.get("brave_fetched", 0),
            row.get("arxiv_fetched", 0),
            row.get("after_freshness", 0),
            row.get("after_dedupe", 0),
            row.get("clusters_formed", 0),
            row.get("clusters_selected", 0),
            row.get("cards_generated", 0),
            row.get("cards_validated", 0),
            row.get("cards_published", 0),
            row.get("corroboration_queries", 0),
            row.get("corroboration_matches", 0),
            row.get("single_source_published", 0),
        )
    return data


def funnel_as_report_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for slug, row in snapshot().items():
        rows.append({"category": slug, **row})
    return rows
