"""Ollama local LLM client — fallback when cloud providers are unavailable.

Uses Ollama's OpenAI-compatible API (no extra deps beyond openai package).
Default model: gemma3 (best local model for financial analysis).
"""

import logging

from stock_agents.llm.base_client import BaseLLMClient

logger = logging.getLogger(__name__)

_OLLAMA_DEFAULT_ENDPOINT = "http://localhost:11434/v1"


class OllamaLLMClient(BaseLLMClient):
    """Local LLM client via Ollama's OpenAI-compatible endpoint."""

    def __init__(
        self,
        model: str = "gemma3",
        max_tokens: int = 4096,
        temperature: float = 0.3,
        endpoint: str = _OLLAMA_DEFAULT_ENDPOINT,
    ):
        try:
            from openai import OpenAI  # type: ignore
        except ImportError:
            raise ImportError(
                "openai package is required for Ollama client. "
                "Run: pip install openai"
            )

        self.client = OpenAI(
            base_url=endpoint,
            api_key="ollama",
            max_retries=0,
        )
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature

    @property
    def model_label(self) -> str:
        return f"{self.model} (Ollama)"

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

    def _is_quick_fail(self, e: Exception) -> bool:
        """Ollama not running → don't waste retries."""
        err_str = str(e)
        return any(k in err_str for k in [
            "502", "Connection refused", "Connection error", "ConnectError",
        ])
