"""Category slugs, quotas, and human-label mapping for TechBytes feeds."""

from __future__ import annotations

# Topic categories that should appear in the daily feed when they reach the minimum.
TOPIC_CATEGORY_SLUGS: tuple[str, ...] = (
    "ai_ml",
    "chips_hardware",
    "networking_cloud",
    "cybersecurity",
    "autonomous_vehicles",
)

GENERAL_SLUG = "general"

ALL_CATEGORY_SLUGS: tuple[str, ...] = TOPIC_CATEGORY_SLUGS + (GENERAL_SLUG,)

# Target cards per topic (soft ceiling). Min publish floor is 5; aim for ≥35 total.
CATEGORY_QUOTA = int(__import__("os").environ.get("CATEGORY_CARD_QUOTA", "12"))
MIN_CATEGORY_CARDS = int(__import__("os").environ.get("MIN_CATEGORY_CARDS", "5"))
MIN_TOTAL_CARDS = int(__import__("os").environ.get("MIN_TOTAL_CARDS", "35"))

# Articles selected for clustering per topic category.
ARTICLES_PER_CATEGORY = int(__import__("os").environ.get("ARTICLES_PER_CATEGORY", "24"))

# Freshness window for clustering / corroboration (days).
CLUSTER_MAX_AGE_DAYS = float(__import__("os").environ.get("CLUSTER_MAX_AGE_DAYS", "3"))
CLUSTER_MAX_AGE_CAP = float(__import__("os").environ.get("CLUSTER_MAX_AGE_CAP", "7"))

# Human labels used by scrapers → card/cluster slugs.
HUMAN_TO_SLUG: dict[str, str] = {
    "AI/ML": "ai_ml",
    "chips & hardware": "chips_hardware",
    "networking & cloud": "networking_cloud",
    "cybersecurity": "cybersecurity",
    "autonomous vehicles": "autonomous_vehicles",
}

SLUG_TO_HUMAN: dict[str, str] = {v: k for k, v in HUMAN_TO_SLUG.items()}


def human_to_slug(label: str) -> str | None:
    return HUMAN_TO_SLUG.get(label)


def merge_category_lists(*lists: list[str] | None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for lst in lists:
        for c in lst or []:
            s = str(c).strip()
            if not s or s in seen:
                continue
            # Drop retired slug if it appears on older cached articles.
            if s == "dev_tools":
                continue
            seen.add(s)
            out.append(s)
    return out
