"""Configuration for AI News Digest — loads from config.yaml + env vars."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Load .env from project root (same as stock_agents)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

_CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"


class NewsAPIConfig(BaseModel):
    api_key_env: str = "NEWSAPI_KEY"
    max_articles: int = 20
    keywords: list[str] = Field(default_factory=lambda: [
        "artificial intelligence",
        "AI",
        "large language model",
        "LLM",
        "GPT",
        "machine learning",
    ])

    @property
    def api_key(self) -> str | None:
        return os.getenv(self.api_key_env)


class RSSConfig(BaseModel):
    feeds: list[str] = Field(default_factory=lambda: [
        "https://techcrunch.com/category/artificial-intelligence/feed/",
        "https://www.artificialintelligence-news.com/feed/",
        "https://news.mit.edu/topic/artificial-intelligence2/feed",
        "https://feeds.arstechnica.com/arstechnica/technology-lab",
    ])
    max_articles: int = 30


class LLMConfig(BaseModel):
    provider: str = "openrouter"  # openrouter / ollama
    model: str = "openai/gpt-4.1-nano"
    api_key_env: str = "OPENROUTER_API_KEY"
    endpoint: str = "https://openrouter.ai/api/v1"
    max_tokens: int = 4096
    temperature: float = 0.3

    # Ollama fallback
    ollama_model: str = "gemma4"
    ollama_endpoint: str = "http://localhost:11434/v1"

    @property
    def api_key(self) -> str | None:
        return os.getenv(self.api_key_env)


class EmailConfig(BaseModel):
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    sender_env: str = "EMAIL_SENDER"
    password_env: str = "EMAIL_PASSWORD"
    recipients: list[str] = Field(default_factory=list)

    @property
    def sender(self) -> str | None:
        return os.getenv(self.sender_env)

    @property
    def password(self) -> str | None:
        return os.getenv(self.password_env)


class CacheConfig(BaseModel):
    enabled: bool = True
    ttl_seconds: int = 1800  # 30 min
    directory: str = ".cache/news"


class Settings(BaseModel):
    newsapi: NewsAPIConfig = Field(default_factory=NewsAPIConfig)
    rss: RSSConfig = Field(default_factory=RSSConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)


def load_settings() -> Settings:
    """Load settings from config.yaml, falling back to defaults."""
    if _CONFIG_PATH.exists():
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        return Settings(**raw)
    return Settings()
