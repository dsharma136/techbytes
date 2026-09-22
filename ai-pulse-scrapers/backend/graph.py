"""
LangGraph orchestration: parallel ingest → cluster → cards.

``compiled`` is the compiled graph; ``generate_daily_feed`` is the main entrypoint.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from langgraph.graph import END, START, StateGraph

from backend.nodes.arxiv_node import fetch_arxiv_papers as fetch_arxiv
from backend.nodes.card_node import write_cards
from backend.nodes.cluster_node import cluster_stories
from backend.nodes.hn_node import fetch_hackernews
from backend.nodes.web_node import fetch_web_articles as fetch_web_news
from backend.state import FeedState

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Awaitable[dict[str, Any]]])


def _timed_node(node_id: str, fn: F) -> F:
    """Wrap an async node to log wall-clock duration."""

    async def wrapped(state: FeedState) -> dict[str, Any]:
        t0 = time.perf_counter()
        logger.info("Node %r started", node_id)
        try:
            return await fn(state)
        finally:
            logger.info(
                "Node %r finished in %.2fs",
                node_id,
                time.perf_counter() - t0,
            )

    wrapped.__name__ = f"{fn.__name__}_timed"
    wrapped.__doc__ = fn.__doc__
    return wrapped  # type: ignore[return-value]


graph = StateGraph(FeedState)

graph.add_node("hn_agent", _timed_node("hn_agent", fetch_hackernews))
graph.add_node("arxiv_agent", _timed_node("arxiv_agent", fetch_arxiv))
graph.add_node("web_agent", _timed_node("web_agent", fetch_web_news))
graph.add_node("clustering", _timed_node("clustering", cluster_stories))
graph.add_node("card_writer", _timed_node("card_writer", write_cards))

graph.add_edge(START, "hn_agent")
graph.add_edge(START, "arxiv_agent")
graph.add_edge(START, "web_agent")

graph.add_edge("hn_agent", "clustering")
graph.add_edge("arxiv_agent", "clustering")
graph.add_edge("web_agent", "clustering")

graph.add_edge("clustering", "card_writer")
graph.add_edge("card_writer", END)

compiled = graph.compile()


_DEFAULT_CATEGORIES = [
    "AI/ML",
    "chips & hardware",
    "networking & cloud",
    "cybersecurity",
    "autonomous vehicles",
    "dev tools",
]


async def generate_daily_feed(
    categories: list[str] | None = None,
    target_cards: int = 50,
) -> FeedState:
    """
    Run the full pipeline asynchronously and return final ``FeedState``.

    Parallel: HN, ArXiv, Brave → clustering (join) → card writer.
    """
    if categories is None:
        categories = list(_DEFAULT_CATEGORIES)

    initial: FeedState = {
        "categories": categories,
        "target_card_count": target_cards,
        "hn_articles": [],
        "arxiv_papers": [],
        "web_articles": [],
        "story_clusters": None,
        "cluster_working_articles": None,
        "feed_cards": None,
        "errors": [],
    }
    result = await compiled.ainvoke(initial)
    return result  # type: ignore[return-value]


__all__ = ["compiled", "generate_daily_feed", "graph"]


if __name__ == "__main__":
    import asyncio

    async def _cli() -> None:
        result = await generate_daily_feed()
        cards = result.get("feed_cards") or []
        errors = list(result.get("errors") or [])

        print(f"Total cards generated: {len(cards)}")
        print(f"Errors ({len(errors)}):")
        if errors:
            for err in errors:
                print(f"  - {err}")
        else:
            print("  (none)")
        print("\nFirst 5 card headlines:")
        for i, card in enumerate(cards[:5], start=1):
            headline = card.get("headline", "(no headline)")
            category = card.get("category", "n/a")
            print(f"  {i}. [{category}] {headline}")
        if not cards:
            print("  (none)")

    asyncio.run(_cli())
