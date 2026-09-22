"""
LangGraph shared state for the AI Pulse pipeline.

Reducer channels use ``Annotated[..., operator.add]`` so parallel ingest nodes can
append without overwriting each other.

``cluster_working_articles`` holds the article slice aligned with ``story_clusters``
indices (from ``llm.processor.cluster_articles``); required for ``generate_cards``.
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict


class FeedState(TypedDict, total=False):
    """Graph state: categories in, serialized articles and cards out."""

    categories: list[str]
    target_card_count: int

    hn_articles: Annotated[list[dict], operator.add]
    arxiv_papers: Annotated[list[dict], operator.add]
    web_articles: Annotated[list[dict], operator.add]

    story_clusters: list[dict] | None
    cluster_working_articles: list[dict] | None
    feed_cards: list[dict] | None

    errors: Annotated[list[str], operator.add]
