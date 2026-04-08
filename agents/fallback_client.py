"""Fallback-aware LLM wrapper — tries primary, falls back to secondary on failure."""

import logging

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class FallbackLLMClient:
    """Wraps a primary LLM client with an automatic fallback to a secondary one.

    On each `analyze()` call, tries the primary client first. If it raises
    any exception, logs a warning and retries with the fallback.
    Tracks consecutive failures to permanently switch when the primary
    seems truly down (not just rate-limited).
    """

    def __init__(self, primary, fallback):
        self.primary = primary
        self.fallback = fallback
        self._consecutive_failures = 0
        self._permanent_fallback = False

    def analyze(
        self,
        system_prompt: str,
        user_message: str,
        output_schema: type[BaseModel] | None = None,
        max_retries: int = 3,
    ) -> dict | str:
        # If we permanently switched (3+ consecutive failures), skip primary
        if self._permanent_fallback:
            return self._call_fallback(system_prompt, user_message, output_schema, max_retries)

        try:
            result = self.primary.analyze(
                system_prompt, user_message, output_schema, max_retries
            )
            self._consecutive_failures = 0  # reset on success
            return result
        except Exception as e:
            self._consecutive_failures += 1
            if self._consecutive_failures >= 3:
                logger.warning(
                    "Primary LLM failed %d times consecutively (%s), "
                    "switching to fallback permanently",
                    self._consecutive_failures, e,
                )
                self._permanent_fallback = True
            else:
                logger.warning(
                    "Primary LLM failed (%s), trying fallback (failure %d/3)",
                    e, self._consecutive_failures,
                )
            return self._call_fallback(system_prompt, user_message, output_schema, max_retries)

    def _call_fallback(self, system_prompt, user_message, output_schema, max_retries):
        """Try the fallback LLM. If it also fails, raise the error."""
        try:
            return self.fallback.analyze(
                system_prompt, user_message, output_schema, max_retries
            )
        except Exception as fallback_err:
            logger.error("Fallback LLM also failed: %s", fallback_err)
            raise
