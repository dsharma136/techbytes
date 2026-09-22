"""
Pydantic models for API responses — aligned with Phase 1 / ``write_cards`` output.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SourceRef(BaseModel):
    """Article backing a card (from cluster ingest)."""

    model_config = ConfigDict(extra="ignore")

    title: str = ""
    url: str = ""
    source_type: str = ""
    source_name: str = ""
    engagement: dict | None = None
    published_at: str | None = Field(
        default=None,
        description="ISO-8601 publish time from the source article, if known",
    )

    @field_validator("title", "url", "source_type", "source_name", mode="before")
    @classmethod
    def _coerce_str(cls, v: object) -> str:
        if v is None:
            return ""
        return str(v) if not isinstance(v, str) else v

    @field_validator("published_at", mode="before")
    @classmethod
    def _coerce_published(cls, v: object) -> str | None:
        if v is None or v == "":
            return None
        return str(v)


class FeedCard(BaseModel):
    """
    One micro-learning card (Groq card writer output + optional ``order`` from graph).
    """

    model_config = ConfigDict(extra="allow")

    headline: str = Field(..., description="Short factual headline")
    blurb: str = Field(..., description="2–3 sentence takeaway")
    why_it_matters: str = Field(..., description="Broader context")
    category: str = Field(
        ...,
        description="Topic slug: ai_ml, chips_hardware, networking_cloud, etc.",
    )
    is_research_paper: bool | None = Field(
        default=None,
        description="True when the story is primarily an ArXiv paper",
    )
    order: int | None = Field(
        default=None,
        description="1-based sequence from the card_writer node",
    )
    sources: list[SourceRef] = Field(
        default_factory=list,
        description="Underlying articles for this story",
    )
    importance_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Editorial importance from clustering (0–1)",
    )
    published_at: str | None = Field(
        default=None,
        description="ISO-8601 story time (most recent source date, or feed generated_at)",
    )
    cluster_title: str | None = Field(
        default=None,
        description="Internal cluster label from the LLM",
    )
    single_source: bool | None = Field(
        default=None,
        description="True when published with fewer than two independent outlets",
    )

    @field_validator("sources", mode="before")
    @classmethod
    def _sources_default(cls, v: object) -> object:
        if not isinstance(v, list):
            return []
        return v

    @field_validator("published_at", mode="before")
    @classmethod
    def _card_published(cls, v: object) -> str | None:
        if v is None or v == "":
            return None
        return str(v)


class DailyFeedResponse(BaseModel):
    """Today's feed payload returned by the API and stored in ``data/feeds/`` JSON."""

    date: str = Field(..., description="UTC calendar date YYYY-MM-DD")
    generated_at: str = Field(
        ...,
        description="ISO-8601 timestamp when the feed was produced",
    )
    cards: list[FeedCard] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    cached: bool = Field(
        default=False,
        description="True when served from disk without running the pipeline",
    )


class CategoryCount(BaseModel):
    """Per-category card totals for ``GET /api/categories``."""

    category: str = Field(..., description="Slug, e.g. ai_ml")
    count: int = Field(..., ge=0)


# Backward-compatible alias
CardOut = FeedCard
