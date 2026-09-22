"""Shared article schema for all ingest sources."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

__all__ = ["Article", "validate_articles"]

_EXPECTED_SOURCE_TYPES = frozenset({"hackernews", "arxiv", "brave"})


@dataclass
class Article:
    """Shared schema for articles from any source. All three scrapers output this."""

    title: str
    url: str
    source_type: str  # "hackernews" | "arxiv" | "brave"
    source_name: str  # "HackerNews" | "ArXiv" | "TechCrunch" etc.
    snippet: str  # 1-3 sentence summary/abstract/description
    full_text: str | None  # Full article text if scraped (truncated 3000 chars)
    published_at: str | None  # ISO format timestamp
    fetched_at: str  # When we fetched it
    engagement: dict | None  # {"points": int, "comments": int} for HN, None for others
    authors: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    image_url: str | None = None  # OG image if available
    extra: dict | None = None  # Source-specific data (e.g., pdf_url for ArXiv, hn_url for HN)

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Article:
        """Reconstruct from dict."""
        return cls(**data)


def validate_articles(articles: list[Article]) -> tuple[list[Article], list[str]]:
    """Validate a list of articles. Returns (valid_articles, error_messages)."""
    valid: list[Article] = []
    errors: list[str] = []

    for i, article in enumerate(articles):
        prefix = f"article[{i}]"
        if not (article.title or "").strip():
            errors.append(f"{prefix}: title is empty")
            continue
        url = (article.url or "").strip()
        if not url:
            errors.append(f"{prefix}: url is empty")
            continue
        if not (url.startswith("http://") or url.startswith("https://")):
            errors.append(f"{prefix}: url does not look like an HTTP(S) URL: {url!r}")
            continue
        if article.source_type not in _EXPECTED_SOURCE_TYPES:
            errors.append(
                f"{prefix}: source_type must be one of {sorted(_EXPECTED_SOURCE_TYPES)}, "
                f"got {article.source_type!r}"
            )
            continue
        valid.append(article)

    return valid, errors
