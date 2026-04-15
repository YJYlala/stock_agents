"""LLM client backends — BaseLLMClient + all provider implementations."""

from stock_agents.llm.base_client import BaseLLMClient, DEFAULT_MAX_RETRIES
from stock_agents.llm.schema_builder import build_schema_instruction, strip_markdown_fences
from stock_agents.llm.claude_client import ClaudeLLMClient
from stock_agents.llm.github_models_client import GitHubModelsLLMClient
from stock_agents.llm.azure_openai_client import AzureOpenAILLMClient
from stock_agents.llm.ollama_client import OllamaLLMClient
from stock_agents.llm.openrouter_client import OpenRouterLLMClient
from stock_agents.llm.fallback_client import FallbackLLMClient

# Keep Protocol for backward compat (external code may import it)
LLMClient = BaseLLMClient

__all__ = [
    "BaseLLMClient",
    "LLMClient",
    "DEFAULT_MAX_RETRIES",
    "build_schema_instruction",
    "strip_markdown_fences",
    "ClaudeLLMClient",
    "GitHubModelsLLMClient",
    "AzureOpenAILLMClient",
    "OllamaLLMClient",
    "OpenRouterLLMClient",
    "FallbackLLMClient",
]
