"""Configuration management for Stock Agents system."""

import os
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()
# Also try loading from project root if .env is there
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_BASE_DIR = Path(__file__).resolve().parent.parent


class OllamaConfig(BaseModel):
    """Ollama local model configuration."""

    model: str = "gemma3"
    endpoint: str = "http://localhost:11434/v1"
    max_tokens: int = 4096
    temperature: float = 0.3


class OpenRouterConfig(BaseModel):
    """OpenRouter configuration."""

    model: str = "openai/gpt-oss-120b:free"
    api_key_env: str = "OPENROUTER_API_KEY"
    endpoint: str = "https://openrouter.ai/api/v1"
    max_tokens: int = 4096
    temperature: float = 0.3

    @property
    def api_key(self) -> str:
        key = os.getenv(self.api_key_env, "")
        if not key:
            raise ValueError(f"Environment variable {self.api_key_env} is not set")
        return key


class LLMConfig(BaseModel):
    provider: Literal["anthropic", "github_models", "azure_openai", "ollama", "openrouter"] = "github_models"
    model: str = "gpt-4o"
    model_final: str = "gpt-4o"
    max_tokens: int = 4096
    temperature: float = 0.3
    api_key_env: str = "GITHUB_TOKEN"
    endpoint: str = "https://models.inference.ai.azure.com"
    fallback: Literal["ollama", "none"] = "ollama"
    # Azure OpenAI specific
    azure_api_version: str = "2025-01-01-preview"
    azure_deployment: str = ""  # deployment name (overrides model for Azure)
    # Per-agent model overrides — key is agent type, value is model name
    # Agents not listed here use the default `model` above.
    # Example: {"risk": "o4-mini", "quant": "o4-mini", "fund_manager": "gpt-54"}
    agent_models: dict[str, str] = Field(default_factory=dict)

    @property
    def api_key(self) -> str:
        key = os.getenv(self.api_key_env, "")
        if not key:
            raise ValueError(f"Environment variable {self.api_key_env} is not set")
        return key


class AnalysisConfig(BaseModel):
    lookback_days: int = 250
    financial_quarters: int = 8
    news_count: int = 20


class RiskConfig(BaseModel):
    max_single_position_pct: float = 0.10
    max_sector_pct: float = 0.30
    max_drawdown_pct: float = 0.15
    total_capital: float = 1_000_000


class CacheConfig(BaseModel):
    enabled: bool = True
    ttl_seconds: int = 900
    directory: str = ".cache"


class ComplianceConfig(BaseModel):
    log_directory: str = "logs"


class OutputConfig(BaseModel):
    format: str = "markdown"
    save_to_file: bool = True
    output_directory: str = "reports"


class EmailNotificationConfig(BaseModel):
    enabled: bool = False
    smtp_server: str = "smtp.gmail.com"
    smtp_port: int = 587
    from_addr_env: str = "EMAIL_FROM"
    password_env: str = "EMAIL_PASSWORD"
    to_addr: str | list[str] = ""


class TelegramNotificationConfig(BaseModel):
    enabled: bool = False
    bot_token_env: str = "TELEGRAM_BOT_TOKEN"
    chat_id_env: str = "TELEGRAM_CHAT_ID"


class WeChatNotificationConfig(BaseModel):
    enabled: bool = False
    webhook_url_env: str = "WECHAT_WEBHOOK_URL"


class PushPlusNotificationConfig(BaseModel):
    enabled: bool = False
    token_env: str = "PUSHPLUS_TOKEN"


class NotificationConfig(BaseModel):
    email: EmailNotificationConfig = Field(default_factory=EmailNotificationConfig)
    telegram: TelegramNotificationConfig = Field(default_factory=TelegramNotificationConfig)
    wechat: WeChatNotificationConfig = Field(default_factory=WeChatNotificationConfig)
    pushplus: PushPlusNotificationConfig = Field(default_factory=PushPlusNotificationConfig)


class ScheduleConfig(BaseModel):
    skip_holidays: bool = True
    notification: NotificationConfig = Field(default_factory=NotificationConfig)


class Settings(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    openrouter: OpenRouterConfig = Field(default_factory=OpenRouterConfig)
    watchlist: list[str] = Field(default_factory=lambda: ["600519"])
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    compliance: ComplianceConfig = Field(default_factory=ComplianceConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)

    @property
    def base_dir(self) -> Path:
        return _BASE_DIR

    @property
    def cache_dir(self) -> Path:
        return _BASE_DIR / self.cache.directory

    @property
    def log_dir(self) -> Path:
        return _BASE_DIR / self.compliance.log_directory

    @property
    def report_dir(self) -> Path:
        return _BASE_DIR / self.output.output_directory


def load_settings(config_path: str | Path | None = None) -> Settings:
    """Load settings from YAML config file, falling back to defaults."""
    if config_path is None:
        config_path = _BASE_DIR / "config.yaml"
    config_path = Path(config_path)

    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        return Settings(**raw)

    # Try config.example.yaml
    example = _BASE_DIR / "config.example.yaml"
    if example.exists():
        with open(example, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        return Settings(**raw)

    return Settings()
