"""Tests for configuration loading."""

import pytest
from pathlib import Path

from stock_agents.config.settings import Settings, load_settings


class TestSettings:
    def test_default_settings(self):
        settings = Settings()
        assert settings.llm.provider == "github_models"
        assert settings.llm.model == "gpt-4o"
        assert settings.risk.max_single_position_pct == 0.10
        assert settings.cache.ttl_seconds == 900

    def test_load_from_yaml(self):
        config_path = Path(__file__).resolve().parent.parent / "config.yaml"
        if not config_path.exists():
            pytest.skip("config.yaml not found")
        settings = load_settings(config_path)
        assert settings.llm.provider in ("anthropic", "github_models", "ollama")
        print(f"\nLoaded config: provider={settings.llm.provider}, model={settings.llm.model}")

    def test_base_dir(self):
        settings = Settings()
        assert settings.base_dir.exists()

    def test_risk_limits(self):
        settings = Settings()
        assert 0 < settings.risk.max_single_position_pct <= 1.0
        assert 0 < settings.risk.max_drawdown_pct <= 1.0

    def test_watchlist(self):
        settings = Settings()
        assert isinstance(settings.watchlist, list)
        assert len(settings.watchlist) > 0


class TestPrompts:
    def test_all_prompts_defined(self):
        from stock_agents.config import prompts
        assert hasattr(prompts, "FUNDAMENTAL_ANALYST")
        assert hasattr(prompts, "TECHNICAL_ANALYST")
        assert hasattr(prompts, "SENTIMENT_ANALYST")
        assert hasattr(prompts, "FUND_MANAGER")
        assert hasattr(prompts, "RISK_MANAGER")

    def test_prompts_non_empty(self):
        from stock_agents.config import prompts
        assert len(prompts.FUNDAMENTAL_ANALYST) > 100
        assert len(prompts.TECHNICAL_ANALYST) > 100
        assert len(prompts.FUND_MANAGER) > 100

    def test_fund_manager_prompt_has_position_sizing(self):
        """Verify the prompt instructs position sizing for all actions."""
        from stock_agents.config.prompts import FUND_MANAGER
        assert "ALWAYS compute" in FUND_MANAGER or "ALWAYS calculate" in FUND_MANAGER, \
            "Fund manager prompt should instruct computing position size for all actions"
