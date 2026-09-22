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
  ai_ml, chips_hardware, networking_cloud, cybersecurity, autonomous_vehicles, general
- Prefer a topic category over general whenever the articles fit a topic
- Score importance 0.0-1.0 based on recency, engagement, and novelty
- Do not merge unrelated stories into one cluster

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
and concise like a brilliant friend explaining the news over coffee.

Here are story clusters with their source articles (titles and excerpts):
{clusters_json}

Write exactly one card per cluster, in the same order. Echo each cluster's
cluster_index in the output. For each card include:
- cluster_index: the integer from the input cluster (required for matching)
- headline: 1-2 lines, clear and factual, never clickbait
- blurb: 2-3 sentences. The "one thing to know." Include at least one specific
  fact, number, or name taken from the source excerpts.
- why_it_matters: 1-2 sentences connecting to the bigger picture.
- category: one of ai_ml, chips_hardware, networking_cloud, cybersecurity, autonomous_vehicles, general
- is_research_paper: true if the primary source is ArXiv

Accuracy rules (mandatory):
- Use ONLY the articles listed under that cluster. Do not mix facts across clusters.
- Every claim, product name, model name, company name, number, and statistic MUST
  appear in the provided source titles or excerpts for that cluster.
- Do NOT invent, guess, or "correct" names (for example, do not upgrade a model
  to a newer generation if the sources do not say that).
- Do NOT swap roles of products or models if the sources describe them differently.
- If sources disagree on a detail (dates, numbers, names, outcomes), omit that
  detail rather than stating it as fact.
- If the sources are thin, write a narrower card that only states what they support.
- Prefer quoting concrete details from the excerpts over general commentary.
- Do not write two cards about the same story; each cluster is a distinct story.

No filler. No "in a move that..." No "it remains to be seen..."

Return ONLY a valid JSON array with the same length as the input clusters:
[
  {{
    "cluster_index": 0,
    "headline": "...",
    "blurb": "...",
    "why_it_matters": "...",
    "category": "...",
    "is_research_paper": false
  }}
]
"""
