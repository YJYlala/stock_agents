"""OpenRouter API client — OpenAI-compatible, supports free and paid models.

OpenRouter aggregates many LLM providers (OpenAI, Anthropic, Google, Meta, etc.)
behind a single OpenAI-compatible endpoint. Free models available at no cost.
Docs: https://openrouter.ai/docs
"""

import logging

from stock_agents.llm.base_client import BaseLLMClient

logger = logging.getLogger(__name__)

_OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1"


class OpenRouterLLMClient(BaseLLMClient):
    """LLM client that calls OpenRouter's OpenAI-compatible API."""

    def __init__(
        self,
        api_key: str,
        model: str = "google/gemini-2.0-flash-exp:free",
        max_tokens: int = 4096,
        temperature: float = 0.3,
        endpoint: str = _OPENROUTER_ENDPOINT,
    ):
        try:
            from openai import OpenAI  # type: ignore
        except ImportError:
            raise ImportError(
                "openai package is required for OpenRouter. "
                "Run: pip install openai"
            )

        self.client = OpenAI(
            base_url=endpoint,
            api_key=api_key,
            max_retries=0,
        )
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature

    @property
    def model_label(self) -> str:
        return f"{self.model} (OpenRouter)"

    def _call_llm(self, system_prompt: str, user_message: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )
        return (response.choices[0].message.content or "").strip()
