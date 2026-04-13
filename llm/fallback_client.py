"""Fallback-aware LLM wrapper — tries primary, falls back to secondary on failure."""

import logging
import time

from pydantic import BaseModel

logger = logging.getLogger(__name__)


def _is_rate_limit_error(e: Exception) -> bool:
    """Check if the exception is a rate limit (429) error."""
    msg = str(e).lower()
    return "429" in msg or "rate limit" in msg or "rate_limit" in msg


class FallbackLLMClient:
    """Wraps a primary LLM client with an automatic fallback to a secondary one.

    Rate-limit errors (429) trigger extra backoff+retry on the primary — they
    never count toward the permanent-switch counter.
    Only real errors (auth, network, model not found, etc.) count.
    """

    def __init__(self, primary, fallback):
        self.primary = primary
        self.fallback = fallback
        self._consecutive_real_failures = 0
        self._permanent_fallback = False

    @property
    def model_label(self) -> str:
        active = self.fallback if self._permanent_fallback else self.primary
        return getattr(active, "model_label", str(active))

    def analyze(
        self,
        system_prompt: str,
        user_message: str,
        output_schema: type[BaseModel] | None = None,
        max_retries: int = 5,
    ) -> dict | str:
        # If permanently switched (3+ non-rate-limit failures), skip primary
        if self._permanent_fallback:
            return self._call_fallback(system_prompt, user_message, output_schema, max_retries)

        try:
            result = self.primary.analyze(
                system_prompt, user_message, output_schema, max_retries
            )
            self._consecutive_real_failures = 0
            return result
        except Exception as e:
            if _is_rate_limit_error(e):
                # Rate limit — backoff and retry primary (don't count as real failure)
                logger.warning("Primary LLM rate-limited after retries, backing off 60s...")
                time.sleep(60)
                try:
                    result = self.primary.analyze(
                        system_prompt, user_message, output_schema, max_retries
                    )
                    self._consecutive_real_failures = 0
                    return result
                except Exception as retry_err:
                    logger.warning("Primary still failing after backoff: %s", retry_err)
                    return self._call_fallback(
                        system_prompt, user_message, output_schema, max_retries
                    )
            else:
                # Real failure — count toward permanent switch
                self._consecutive_real_failures += 1
                if self._consecutive_real_failures >= 3:
                    logger.warning(
                        "Primary LLM failed %d times consecutively (%s), "
                        "switching to fallback permanently",
                        self._consecutive_real_failures, e,
                    )
                    self._permanent_fallback = True
                else:
                    logger.warning(
                        "Primary LLM failed (%s), trying fallback (failure %d/3)",
                        e, self._consecutive_real_failures,
                    )
                return self._call_fallback(
                    system_prompt, user_message, output_schema, max_retries
                )

    def _call_fallback(self, system_prompt, user_message, output_schema, max_retries):
        """Try the fallback LLM. If it also fails, raise the error."""
        try:
            return self.fallback.analyze(
                system_prompt, user_message, output_schema, max_retries
            )
        except Exception as fallback_err:
            logger.error("Fallback LLM also failed: %s", fallback_err)
            raise
