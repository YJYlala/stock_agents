"""Shared retry, parsing, and schema logic for all LLM clients.

Every provider client inherits from BaseLLMClient and only implements
`_call_llm()` — the single provider-specific API call.  Retry loops,
rate-limit handling, JSON parsing, and schema instruction injection
are handled here exactly once.
"""

from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod

from pydantic import BaseModel

from stock_agents.llm.schema_builder import build_schema_instruction, strip_markdown_fences

logger = logging.getLogger(__name__)

# Default retry budget shared by all providers
DEFAULT_MAX_RETRIES = 3


def _is_rate_limit_error(e: Exception) -> bool:
    """Check if the exception is a rate limit (429) error."""
    msg = str(e).lower()
    return "429" in msg or "rate limit" in msg or "rate_limit" in msg


class BaseLLMClient(ABC):
    """Base class that centralises retry, parsing, and schema logic.

    Subclasses must implement:
        _call_llm(system_prompt, user_message) -> str
        model_label (property)
    """

    @property
    @abstractmethod
    def model_label(self) -> str:
        """Human-readable label for logging (e.g. 'gpt-4o (GitHub Copilot)')."""

    @abstractmethod
    def _call_llm(self, system_prompt: str, user_message: str) -> str:
        """Execute a single LLM call and return the raw text response.

        Raise on any provider error — retries are handled by the caller.
        """

    # ── Public API (identical interface for every provider) ───────────

    def analyze(
        self,
        system_prompt: str,
        user_message: str,
        output_schema: type[BaseModel] | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> dict | str:
        """Call the LLM with retry.  Returns parsed dict if *output_schema*
        is given, otherwise raw text."""

        full_system = system_prompt + build_schema_instruction(output_schema)
        text = ""

        for attempt in range(max_retries):
            try:
                text = self._call_llm(full_system, user_message)

                if output_schema:
                    return json.loads(strip_markdown_fences(text))
                return text

            except json.JSONDecodeError as e:
                logger.warning(
                    "JSON parse failed (attempt %d/%d): %s",
                    attempt + 1, max_retries, e,
                )
                if attempt == max_retries - 1:
                    logger.error(
                        "Failed to parse JSON after %d attempts, returning raw text",
                        max_retries,
                    )
                    return text
                time.sleep(1)

            except Exception as e:
                if _is_rate_limit_error(e):
                    wait = 15 * (attempt + 1)
                    logger.warning(
                        "Rate limited, waiting %ds (attempt %d/%d)",
                        wait, attempt + 1, max_retries,
                    )
                    time.sleep(wait)
                elif self._is_quick_fail(e):
                    raise
                else:
                    logger.error(
                        "LLM call failed (attempt %d/%d): %s",
                        attempt + 1, max_retries, e,
                    )
                    if attempt == max_retries - 1:
                        raise
                    time.sleep(2 ** attempt)

        raise RuntimeError(f"LLM call failed after {max_retries} retries")

    # ── Override point for provider-specific quick-fail logic ─────────

    def _is_quick_fail(self, e: Exception) -> bool:
        """Return True if this error should NOT be retried (e.g. Ollama offline)."""
        return False
