"""LLM client backends — re-exports from genai-common + stock_agents-specific clients."""

# Shared clients from genai-common
from genai_common.llm import (
    BaseLLMClient,
    ClaudeLLMClient,
    FallbackLLMClient,
    GitHubModelsLLMClient,
    OllamaLLMClient,
    OpenRouterLLMClient,
    build_schema_instruction,
    strip_markdown_fences,
)

# Stock-agents-specific client
from stock_agents.llm.azure_openai_client import AzureOpenAILLMClient

# Backward compat alias
LLMClient = BaseLLMClient

__all__ = [
    "BaseLLMClient",
    "LLMClient",
    "build_schema_instruction",
    "strip_markdown_fences",
    "ClaudeLLMClient",
    "GitHubModelsLLMClient",
    "AzureOpenAILLMClient",
    "OllamaLLMClient",
    "OpenRouterLLMClient",
    "FallbackLLMClient",
]
