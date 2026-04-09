"""LLM client backends — Protocol + all provider implementations."""

from typing import Any, Protocol


class LLMClient(Protocol):
    """Protocol for LLM clients — all provider implementations satisfy this."""

    def analyze(
        self,
        system_prompt: str,
        user_message: str,
        output_schema: Any = None,
        max_retries: int = 3,
    ) -> dict | str: ...


from stock_agents.llm.claude_client import ClaudeLLMClient
from stock_agents.llm.github_models_client import GitHubModelsLLMClient
from stock_agents.llm.ollama_client import OllamaLLMClient
from stock_agents.llm.openrouter_client import OpenRouterLLMClient
from stock_agents.llm.fallback_client import FallbackLLMClient

__all__ = [
    "LLMClient",
    "ClaudeLLMClient",
    "GitHubModelsLLMClient",
    "OllamaLLMClient",
    "OpenRouterLLMClient",
    "FallbackLLMClient",
]
