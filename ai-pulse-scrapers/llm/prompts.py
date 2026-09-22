"""LLM prompt templates for clustering and card generation."""

from __future__ import annotations

__all__ = ["CLUSTERING_PROMPT", "CARD_WRITER_PROMPT"]

CLUSTERING_PROMPT = """
You are a senior tech news editor. Given a list of articles from multiple sources,
group related articles into story clusters. Each cluster = one news story or topic.

Articles:
{articles_json}

Group them into clusters. Target approximately {target_clusters} clusters.

Rules:
- Each article belongs to exactly ONE cluster
- Single-article clusters are fine
- Assign each cluster a primary_category from:
  ai_ml, chips_hardware, networking_cloud, cybersecurity, autonomous_vehicles, dev_tools, general
- Score importance 0.0-1.0 based on recency, engagement, and novelty

Return ONLY a valid JSON array, no markdown, no explanation:
[
  {{
    "cluster_title": "Short descriptive title",
    "article_indices": [0, 3, 7],
    "primary_category": "ai_ml",
    "importance_score": 0.85
  }}
]
"""

CARD_WRITER_PROMPT = """
You write daily micro-learning cards for a tech-savvy audience. Each card teaches
someone ONE thing about what happened in tech today. Your tone is clear, smart,
and concise — like a brilliant friend explaining the news over coffee.

Here are story clusters with their articles:
{clusters_json}

For each cluster, write a card with:
- headline: 1-2 lines, clear and factual, never clickbait
- blurb: 2-3 sentences. The "one thing to know." Include at least one specific
  fact, number, or name. Be specific — say "40% latency reduction" not "significant improvement."
- why_it_matters: 1-2 sentences connecting to the bigger picture. Cross-sector
  connections are gold (e.g., chip news → AI training costs → AV inference).
  Make the reader think "oh, I didn't connect those dots."
- category: one of ai_ml, chips_hardware, networking_cloud, cybersecurity, autonomous_vehicles, dev_tools, general
- is_research_paper: true if primary source is ArXiv

No filler. No "in a move that..." No "it remains to be seen..."

Return ONLY a valid JSON array:
[
  {{
    "headline": "...",
    "blurb": "...",
    "why_it_matters": "...",
    "category": "...",
    "is_research_paper": false
  }}
]
"""
