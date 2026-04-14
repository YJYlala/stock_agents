"""Lightweight LLM client for AI News Digest.

Uses OpenAI-compatible API (works with OpenRouter, Ollama, etc.)
Self-contained — no dependency on stock_agents package.
"""

from __future__ import annotations

import json
import logging
import time

logger = logging.getLogger(__name__)


class LLMClient:
    """OpenAI-compatible LLM client with retry logic."""

    def __init__(
        self,
        api_key: str,
        model: str,
        endpoint: str = "https://openrouter.ai/api/v1",
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ):
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("openai package required: pip install openai")

        self.client = OpenAI(
            base_url=endpoint,
            api_key=api_key,
            max_retries=0,
        )
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature

    def analyze(
        self,
        system_prompt: str,
        user_message: str,
        max_retries: int = 3,
    ) -> dict | str:
        """Send a prompt to the LLM with retry logic. Returns dict or string."""
        text = ""
        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                )
                text = (response.choices[0].message.content or "").strip()

                # Try to parse as JSON
                clean = text
                if clean.startswith("```"):
                    lines = clean.split("\n")
                    lines = [l for l in lines if not l.startswith("```")]
                    clean = "\n".join(lines).strip()
                try:
                    return json.loads(clean)
                except json.JSONDecodeError:
                    return text

            except Exception as e:
                err_str = str(e).lower()
                if "rate" in err_str or "429" in err_str:
                    wait = 10 * (attempt + 1)
                    logger.warning("Rate limited, waiting %ds (attempt %d/%d)", wait, attempt + 1, max_retries)
                    time.sleep(wait)
                elif any(k in err_str for k in ["502", "connection refused", "connecterror"]):
                    logger.error("Server not available: %s", e)
                    raise
                else:
                    logger.error("LLM call failed (attempt %d/%d): %s", attempt + 1, max_retries, e)
                    if attempt == max_retries - 1:
                        raise
                    time.sleep(2 ** attempt)

        raise RuntimeError(f"LLM call failed after {max_retries} retries")
