"""Data models for AI News Digest."""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


class NewsArticle(BaseModel):
    """A single news article from any source."""

    title: str
    source: str
    url: str
    published_at: datetime | None = None
    description: str = ""
    content: str = ""

    def key(self) -> str:
        """Dedup key based on normalized title."""
        return self.title.strip().lower()


class ArticleSummary(BaseModel):
    """LLM-generated summary of one article."""

    title: str
    source: str
    url: str
    summary: str
    relevance: str = ""  # why it matters


class SummaryDigest(BaseModel):
    """Complete daily digest produced by the summarizer."""

    date: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    overall_summary: str = ""
    key_trends: list[str] = Field(default_factory=list)
    article_summaries: list[ArticleSummary] = Field(default_factory=list)
    total_articles_fetched: int = 0
