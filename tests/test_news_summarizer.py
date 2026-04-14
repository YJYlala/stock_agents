"""Tests for news_summarizer module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ai_news_digest.config import Settings
from ai_news_digest.models import NewsArticle, SummaryDigest
from ai_news_digest.news_summarizer import NewsSummarizer


@pytest.fixture
def settings() -> Settings:
    return Settings(
        llm={"provider": "openrouter", "api_key_env": "OPENROUTER_API_KEY"},
        cache={"enabled": False},
    )


@pytest.fixture
def sample_articles() -> list[NewsArticle]:
    return [
        NewsArticle(title="GPT-5 Released", source="TC", url="https://tc.com/1",
                     description="OpenAI releases GPT-5 with major improvements."),
        NewsArticle(title="Google Gemini 3 Launch", source="Verge", url="https://v.com/2",
                     description="Google launches Gemini 3 multimodal model."),
        NewsArticle(title="AI Regulation in EU", source="BBC", url="https://bbc.com/3",
                     description="EU passes new AI safety regulations."),
    ]


# ------------------------------------------------------------------
# Summarize with mocked LLM
# ------------------------------------------------------------------

class TestNewsSummarizer:
    @patch("ai_news_digest.news_summarizer._build_llm_client")
    def test_summarize_success(self, mock_build, settings, sample_articles):
        """LLM returns proper JSON → digest is built correctly."""
        mock_llm = MagicMock()
        mock_llm.analyze.return_value = {
            "overall_summary": "Today in AI: GPT-5, Gemini 3, and EU regulation.",
            "key_trends": ["Model releases", "Regulation"],
            "article_summaries": [
                {"title": "GPT-5 Released", "source": "TC",
                 "url": "https://tc.com/1", "summary": "OpenAI launched GPT-5.",
                 "relevance": "Major model upgrade."},
                {"title": "Google Gemini 3 Launch", "source": "Verge",
                 "url": "https://v.com/2", "summary": "Google launched Gemini 3.",
                 "relevance": "Multimodal competition."},
                {"title": "AI Regulation in EU", "source": "BBC",
                 "url": "https://bbc.com/3", "summary": "EU AI Act passed.",
                 "relevance": "Policy impact."},
            ],
        }
        mock_build.return_value = mock_llm

        summarizer = NewsSummarizer(settings)
        digest = summarizer.summarize(sample_articles)

        assert isinstance(digest, SummaryDigest)
        assert "GPT-5" in digest.overall_summary
        assert len(digest.key_trends) == 2
        assert len(digest.article_summaries) == 3
        assert digest.total_articles_fetched == 3

    @patch("ai_news_digest.news_summarizer._build_llm_client")
    def test_summarize_empty_articles(self, mock_build, settings):
        """Empty article list returns placeholder digest."""
        mock_build.return_value = MagicMock()
        summarizer = NewsSummarizer(settings)
        digest = summarizer.summarize([])

        assert digest.total_articles_fetched == 0
        assert "No articles" in digest.overall_summary

    @patch("ai_news_digest.news_summarizer._build_llm_client")
    def test_summarize_llm_failure_fallback(self, mock_build, settings, sample_articles):
        """LLM exception triggers fallback digest."""
        mock_llm = MagicMock()
        mock_llm.analyze.side_effect = RuntimeError("LLM down")
        mock_build.return_value = mock_llm

        summarizer = NewsSummarizer(settings)
        digest = summarizer.summarize(sample_articles)

        assert digest.total_articles_fetched == 3
        assert len(digest.article_summaries) == 3
        # Fallback uses raw descriptions
        assert "GPT-5" in digest.article_summaries[0].title

    @patch("ai_news_digest.news_summarizer._build_llm_client")
    def test_summarize_llm_returns_string(self, mock_build, settings, sample_articles):
        """LLM returns raw string → tries JSON parse, then fallback."""
        mock_llm = MagicMock()
        mock_llm.analyze.return_value = "This is not JSON at all."
        mock_build.return_value = mock_llm

        summarizer = NewsSummarizer(settings)
        digest = summarizer.summarize(sample_articles)

        # Should fallback gracefully
        assert digest.total_articles_fetched == 3
        assert "not JSON" in digest.overall_summary or len(digest.article_summaries) > 0

    @patch("ai_news_digest.news_summarizer._build_llm_client")
    def test_summarize_llm_returns_json_string(self, mock_build, settings, sample_articles):
        """LLM returns JSON as string (with markdown fences)."""
        import json
        mock_llm = MagicMock()
        mock_llm.analyze.return_value = (
            "```json\n"
            + json.dumps({
                "overall_summary": "AI news today.",
                "key_trends": ["Trend A"],
                "article_summaries": [
                    {"title": "T1", "source": "S1", "url": "https://x.com",
                     "summary": "Sum1", "relevance": "Rel1"},
                ],
            })
            + "\n```"
        )
        mock_build.return_value = mock_llm

        summarizer = NewsSummarizer(settings)
        digest = summarizer.summarize(sample_articles)

        assert digest.overall_summary == "AI news today."
        assert len(digest.article_summaries) == 1
