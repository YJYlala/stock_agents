"""Claude API client wrapper — thin layer over Anthropic SDK."""

import logging

from stock_agents.llm.base_client import BaseLLMClient

logger = logging.getLogger(__name__)


class ClaudeLLMClient(BaseLLMClient):
    """Wrapper around the Anthropic SDK for agent calls."""

    def __init__(self, api_key: str, model: str, max_tokens: int = 4096, temperature: float = 0.3):
        try:
            import anthropic  # type: ignore
        except ImportError:
            raise ImportError(
                "anthropic package is required for ClaudeLLMClient. "
                "Run: pip install anthropic"
            )
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature

    @property
    def model_label(self) -> str:
        return f"{self.model} (Anthropic)"

    def _call_llm(self, system_prompt: str, user_message: str) -> str:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        return response.content[0].text.strip()
