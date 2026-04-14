"""Fetch AI news from NewsAPI and RSS feeds."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import requests

from ai_news_digest.config import Settings
from ai_news_digest.models import NewsArticle

logger = logging.getLogger(__name__)

_NEWSAPI_ENDPOINT = "https://newsapi.org/v2/everything"


class NewsFetcher:
    """Multi-source AI news fetcher with caching and deduplication."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._cache_dir = Path(settings.cache.directory)
        if settings.cache.enabled:
            self._cache_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_all(self) -> list[NewsArticle]:
        """Fetch from all configured sources, deduplicate, sort by date."""
        articles: list[NewsArticle] = []

        # 1. Try NewsAPI (if key configured)
        if self.settings.newsapi.api_key:
            try:
                articles.extend(self._fetch_newsapi())
            except Exception as e:
                logger.warning("NewsAPI fetch failed: %s", e)
        else:
            logger.info("NewsAPI key not set, skipping (set NEWSAPI_KEY in .env)")

        # 2. RSS feeds (always available, no key needed)
        try:
            articles.extend(self._fetch_rss())
        except Exception as e:
            logger.warning("RSS fetch failed: %s", e)

        if not articles:
            logger.error("No articles fetched from any source!")
            return []

        # 3. Deduplicate by normalized title
        seen: set[str] = set()
        unique: list[NewsArticle] = []
        for a in articles:
            k = a.key()
            if k not in seen:
                seen.add(k)
                unique.append(a)

        # 4. Sort by date (newest first), None dates go to end
        unique.sort(
            key=lambda a: a.published_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

        logger.info("Fetched %d unique articles (from %d total)", len(unique), len(articles))
        return unique

    # ------------------------------------------------------------------
    # NewsAPI
    # ------------------------------------------------------------------

    def _fetch_newsapi(self) -> list[NewsArticle]:
        """Query NewsAPI for AI-related articles."""
        cached = self._cache_get("newsapi")
        if cached is not None:
            logger.info("Using cached NewsAPI results (%d articles)", len(cached))
            return [NewsArticle(**a) for a in cached]

        api_key = self.settings.newsapi.api_key
        keywords = " OR ".join(f'"{kw}"' for kw in self.settings.newsapi.keywords)
        from_date = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d")

        params = {
            "q": keywords,
            "from": from_date,
            "sortBy": "publishedAt",
            "pageSize": self.settings.newsapi.max_articles,
            "language": "en",
            "apiKey": api_key,
        }

        resp = requests.get(_NEWSAPI_ENDPOINT, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") != "ok":
            raise RuntimeError(f"NewsAPI error: {data.get('message', 'unknown')}")

        articles = []
        for item in data.get("articles", []):
            pub = item.get("publishedAt")
            published_at = None
            if pub:
                try:
                    published_at = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    pass
            articles.append(NewsArticle(
                title=item.get("title", "Untitled"),
                source=item.get("source", {}).get("name", "Unknown"),
                url=item.get("url", ""),
                published_at=published_at,
                description=item.get("description") or "",
                content=(item.get("content") or "")[:1000],
            ))

        logger.info("NewsAPI returned %d articles", len(articles))
        self._cache_set("newsapi", [a.model_dump(mode="json") for a in articles])
        return articles

    # ------------------------------------------------------------------
    # RSS Feeds
    # ------------------------------------------------------------------

    def _fetch_rss(self) -> list[NewsArticle]:
        """Parse configured RSS feeds for AI news."""
        cached = self._cache_get("rss")
        if cached is not None:
            logger.info("Using cached RSS results (%d articles)", len(cached))
            return [NewsArticle(**a) for a in cached]

        articles: list[NewsArticle] = []
        for feed_url in self.settings.rss.feeds:
            try:
                articles.extend(self._parse_single_feed(feed_url))
            except Exception as e:
                logger.warning("RSS feed %s failed: %s", feed_url, e)

        # Trim to max
        articles = articles[: self.settings.rss.max_articles]
        logger.info("RSS feeds returned %d articles", len(articles))
        self._cache_set("rss", [a.model_dump(mode="json") for a in articles])
        return articles

    def _parse_single_feed(self, feed_url: str) -> list[NewsArticle]:
        """Parse one RSS feed into NewsArticle list."""
        feed = feedparser.parse(feed_url)
        articles: list[NewsArticle] = []

        for entry in feed.entries[:15]:  # max 15 per feed
            published_at = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                try:
                    published_at = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                except (TypeError, ValueError):
                    pass

            # Filter: only keep entries with AI-related keywords in title/summary
            text = f"{entry.get('title', '')} {entry.get('summary', '')}".lower()
            ai_keywords = ["ai", "artificial intelligence", "machine learning",
                           "llm", "gpt", "neural", "deep learning", "openai",
                           "anthropic", "google ai", "chatbot", "generative"]
            if not any(kw in text for kw in ai_keywords):
                continue

            articles.append(NewsArticle(
                title=entry.get("title", "Untitled"),
                source=feed.feed.get("title", feed_url),
                url=entry.get("link", ""),
                published_at=published_at,
                description=entry.get("summary", "")[:500],
                content=entry.get("summary", "")[:1000],
            ))

        return articles

    # ------------------------------------------------------------------
    # Simple file-based cache
    # ------------------------------------------------------------------

    def _cache_key_path(self, key: str) -> Path:
        h = hashlib.md5(key.encode()).hexdigest()
        return self._cache_dir / f"{h}.json"

    def _cache_get(self, key: str) -> list[dict] | None:
        if not self.settings.cache.enabled:
            return None
        path = self._cache_key_path(key)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            ts = data.get("_ts", 0)
            if time.time() - ts > self.settings.cache.ttl_seconds:
                path.unlink(missing_ok=True)
                return None
            return data.get("items", [])
        except (json.JSONDecodeError, KeyError):
            path.unlink(missing_ok=True)
            return None

    def _cache_set(self, key: str, items: list[dict]) -> None:
        if not self.settings.cache.enabled:
            return
        path = self._cache_key_path(key)
        path.write_text(
            json.dumps({"_ts": time.time(), "items": items}, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
