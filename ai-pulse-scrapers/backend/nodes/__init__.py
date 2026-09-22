"""LangGraph node callables wrapping Phase 1 scrapers and LLM helpers."""

from backend.nodes.arxiv_node import fetch_arxiv_papers
from backend.nodes.card_node import write_cards
from backend.nodes.cluster_node import cluster_stories
from backend.nodes.hn_node import fetch_hackernews
from backend.nodes.web_node import fetch_web_articles

__all__ = [
    "fetch_arxiv_papers",
    "fetch_hackernews",
    "fetch_web_articles",
    "cluster_stories",
    "write_cards",
]
