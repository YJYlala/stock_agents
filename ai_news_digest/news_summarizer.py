"""Summarize fetched AI news articles using an LLM."""

from __future__ import annotations

import json
import logging
from datetime import datetime

from ai_news_digest.config import Settings
from ai_news_digest.models import ArticleSummary, NewsArticle, SummaryDigest

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are an AI news analyst. Your job is to create a concise daily digest of AI news.

Given a list of recent AI news articles, produce a JSON response with:
1. "overall_summary": A 2-3 sentence overview of today's AI landscape.
2. "key_trends": A list of 3-5 major themes/trends from the articles.
3. "article_summaries": For each article, provide:
   - "title": The original article title
   - "source": The source name
   - "url": The original URL
   - "summary": A 1-2 sentence summary of the article
   - "relevance": Why this matters (1 sentence)

Output ONLY valid JSON, no markdown fences, no extra text.
"""


def _build_llm_client(settings: Settings):
    """Build an LLM client from settings (OpenRouter or Ollama)."""
    from ai_news_digest.llm_client import LLMClient

    cfg = settings.llm

    if cfg.provider == "openrouter" and cfg.api_key:
        return LLMClient(
            api_key=cfg.api_key,
            model=cfg.model,
            endpoint=cfg.endpoint,
            max_tokens=cfg.max_tokens,
            temperature=cfg.temperature,
        )

    # Fallback to Ollama
    logger.info("Using Ollama (%s) for summarization", cfg.ollama_model)
    return LLMClient(
        api_key="ollama",
        model=cfg.ollama_model,
        endpoint=cfg.ollama_endpoint,
        max_tokens=cfg.max_tokens,
        temperature=cfg.temperature,
    )


class NewsSummarizer:
    """Use an LLM to produce a structured digest from raw articles."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.llm = _build_llm_client(settings)

    def summarize(self, articles: list[NewsArticle]) -> SummaryDigest:
        """Summarize a list of articles into a SummaryDigest."""
        if not articles:
            return SummaryDigest(
                overall_summary="No articles were available to summarize.",
                total_articles_fetched=0,
            )

        # Build the user message with article data
        article_data = []
        for i, a in enumerate(articles[:20], 1):  # cap at 20 to fit context
            article_data.append({
                "index": i,
                "title": a.title,
                "source": a.source,
                "url": a.url,
                "date": a.published_at.strftime("%Y-%m-%d %H:%M") if a.published_at else "unknown",
                "description": a.description[:300],
            })

        user_message = (
            f"Today is {datetime.now().strftime('%Y-%m-%d')}.\n\n"
            f"Here are {len(article_data)} recent AI news articles:\n\n"
            f"{json.dumps(article_data, indent=2, ensure_ascii=False)}"
        )

        logger.info("Sending %d articles to LLM for summarization...", len(article_data))

        try:
            result = self.llm.analyze(
                system_prompt=_SYSTEM_PROMPT,
                user_message=user_message,
                max_retries=3,
            )
        except Exception as e:
            logger.error("LLM summarization failed: %s", e)
            return self._fallback_digest(articles)

        return self._parse_response(result, articles)

    def _parse_response(
        self, result: dict | str, articles: list[NewsArticle]
    ) -> SummaryDigest:
        """Parse LLM response into SummaryDigest."""
        if isinstance(result, str):
            # Try to extract JSON from string
            text = result.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                lines = [l for l in lines if not l.startswith("```")]
                text = "\n".join(lines).strip()
            try:
                result = json.loads(text)
            except json.JSONDecodeError:
                logger.warning("Could not parse LLM response as JSON, using fallback")
                return self._fallback_digest(articles, raw_summary=text)

        if not isinstance(result, dict):
            return self._fallback_digest(articles)

        # Build ArticleSummary list
        summaries = []
        for item in result.get("article_summaries", []):
            summaries.append(ArticleSummary(
                title=item.get("title", ""),
                source=item.get("source", ""),
                url=item.get("url", ""),
                summary=item.get("summary", ""),
                relevance=item.get("relevance", ""),
            ))

        return SummaryDigest(
            overall_summary=result.get("overall_summary", ""),
            key_trends=result.get("key_trends", []),
            article_summaries=summaries,
            total_articles_fetched=len(articles),
        )

    def _fallback_digest(
        self, articles: list[NewsArticle], raw_summary: str = ""
    ) -> SummaryDigest:
        """Produce a basic digest when LLM fails."""
        summaries = [
            ArticleSummary(
                title=a.title,
                source=a.source,
                url=a.url,
                summary=a.description[:200] if a.description else "No description.",
            )
            for a in articles[:20]
        ]
        return SummaryDigest(
            overall_summary=raw_summary or "LLM summarization unavailable. Showing raw articles.",
            article_summaries=summaries,
            total_articles_fetched=len(articles),
        )
