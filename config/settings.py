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


class LLMConfig(BaseModel):
    provider: Literal["anthropic", "github_models", "ollama"] = "github_models"
    model: str = "gpt-4o"
    model_final: str = "gpt-4o"
    max_tokens: int = 4096
    temperature: float = 0.3
    api_key_env: str = "GITHUB_TOKEN"
    endpoint: str = "https://models.inference.ai.azure.com"
    fallback: Literal["ollama", "none"] = "ollama"

    @property
    def api_key(self) -> str:
        key = os.getenv(self.api_key_env, "")
        if not key:
            raise ValueError(f"Environment variable {self.api_key_env} is not set")
        return key


class FutuConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 11111
    market: str = "SH"


class THSConfig(BaseModel):
    """同花顺 configuration — supports file-based and live (easytrader) modes."""

    positions_file: str | None = None
    cash_file: str | None = None
    watchlist_file: str | None = None
    sync_watchlist: bool = True
    # Live (easytrader) settings
    live: bool = True            # prefer live connection over files
    exe_path: str | None = None  # path to 同花顺下单客户端 exe (auto-detect if None)


class AccountConfig(BaseModel):
    """Account provider routing."""

    provider: Literal["futu", "ths", "none"] = "ths"


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


class Settings(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    account: AccountConfig = Field(default_factory=AccountConfig)
    futu: FutuConfig = Field(default_factory=FutuConfig)
    ths: THSConfig = Field(default_factory=THSConfig)
    watchlist: list[str] = Field(default_factory=lambda: ["600519"])
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    compliance: ComplianceConfig = Field(default_factory=ComplianceConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)

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
