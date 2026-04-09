"""Tests for LLM client module."""

import pytest

from stock_agents.llm import (
    LLMClient,
    ClaudeLLMClient,
    GitHubModelsLLMClient,
    OllamaLLMClient,
    FallbackLLMClient,
)


class TestLLMProtocol:
    """Verify all LLM clients satisfy the Protocol."""

    def test_claude_client_has_analyze(self):
        assert hasattr(ClaudeLLMClient, "analyze")

    def test_github_models_client_has_analyze(self):
        assert hasattr(GitHubModelsLLMClient, "analyze")

    def test_ollama_client_has_analyze(self):
        assert hasattr(OllamaLLMClient, "analyze")

    def test_fallback_client_has_analyze(self):
        assert hasattr(FallbackLLMClient, "analyze")


class TestOllamaClient:
    """Test Ollama client (requires local Ollama running)."""

    @pytest.fixture
    def client(self):
        try:
            import requests
            r = requests.get("http://localhost:11434/api/tags", timeout=2)
            if r.status_code != 200:
                pytest.skip("Ollama not running")
        except Exception:
            pytest.skip("Ollama not reachable")
        return OllamaLLMClient(model="gemma3", max_tokens=256, temperature=0.1)

    def test_simple_query(self, client):
        result = client.analyze(
            system_prompt="You are a helpful assistant. Reply in JSON: {\"answer\": \"...\"}",
            user_message="What is 2+2? Reply briefly.",
            max_retries=1,
        )
        assert result is not None
        print(f"\nOllama response: {result}")


class TestGitHubModelsClient:
    """Test GitHub Models client (requires GITHUB_TOKEN env var)."""

    @pytest.fixture
    def client(self):
        import os
        token = os.getenv("GITHUB_TOKEN")
        if not token:
            pytest.skip("GITHUB_TOKEN not set")
        return GitHubModelsLLMClient(
            github_token=token,
            model="gpt-4o",
            max_tokens=256,
            temperature=0.1,
        )

    def test_simple_query(self, client):
        result = client.analyze(
            system_prompt="You are a helpful assistant. Reply in JSON: {\"answer\": \"...\"}",
            user_message="What is the capital of China? Reply briefly.",
            max_retries=1,
        )
        assert result is not None
        print(f"\nGitHub Models response: {result}")


class TestFallbackClient:
    """Test fallback chain behavior with mock clients."""

    class MockLLM:
        def __init__(self, fail=False, response=None):
            self.fail = fail
            self.response = response or {"signal": "HOLD", "score": 5.0}
            self.call_count = 0

        def analyze(self, system_prompt, user_message, output_schema=None, max_retries=3):
            self.call_count += 1
            if self.fail:
                raise RuntimeError("Mock failure")
            return self.response

    def test_primary_succeeds(self):
        primary = self.MockLLM(fail=False, response={"answer": "primary"})
        secondary = self.MockLLM(fail=False, response={"answer": "secondary"})
        client = FallbackLLMClient(primary, secondary)
        result = client.analyze("sys", "user")
        assert result == {"answer": "primary"}
        assert primary.call_count == 1
        assert secondary.call_count == 0

    def test_fallback_on_failure(self):
        primary = self.MockLLM(fail=True)
        secondary = self.MockLLM(fail=False, response={"answer": "fallback"})
        client = FallbackLLMClient(primary, secondary)
        # Need 3 consecutive failures to trigger fallback
        for _ in range(3):
            try:
                client.analyze("sys", "user")
            except Exception:
                pass
        # After 3 failures, should use secondary
        result = client.analyze("sys", "user")
        assert secondary.call_count > 0
