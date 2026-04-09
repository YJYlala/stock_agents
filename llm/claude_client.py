"""Claude API client wrapper with retry logic."""

import json
import logging
import time

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ClaudeLLMClient:
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
        self._anthropic = anthropic
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature

    def analyze(
        self,
        system_prompt: str,
        user_message: str,
        output_schema: type[BaseModel] | None = None,
        max_retries: int = 3,
    ) -> dict | str:
        """Call Claude API with retry. Returns parsed dict if schema given, else raw text."""
        schema_instruction = ""
        if output_schema:
            schema_json = json.dumps(output_schema.model_json_schema(), indent=2, ensure_ascii=False)
            schema_instruction = (
                f"\n\nYou MUST respond with valid JSON matching this schema:\n```json\n{schema_json}\n```\n"
                "Output ONLY the JSON object, no markdown fences, no extra text."
            )

        for attempt in range(max_retries):
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    system=system_prompt + schema_instruction,
                    messages=[{"role": "user", "content": user_message}],
                )
                text = response.content[0].text.strip()

                if output_schema:
                    # Strip markdown fences if present
                    if text.startswith("```"):
                        lines = text.split("\n")
                        lines = [l for l in lines if not l.startswith("```")]
                        text = "\n".join(lines).strip()
                    return json.loads(text)

                return text

            except self._anthropic.RateLimitError:
                wait = 2 ** (attempt + 1)
                logger.warning("Rate limited, waiting %ds (attempt %d/%d)", wait, attempt + 1, max_retries)
                time.sleep(wait)
            except json.JSONDecodeError as e:
                logger.warning("JSON parse failed (attempt %d/%d): %s", attempt + 1, max_retries, e)
                if attempt == max_retries - 1:
                    logger.error("Failed to parse JSON after %d attempts, returning raw text", max_retries)
                    return text  # type: ignore
                time.sleep(1)
            except Exception as e:
                logger.error("LLM call failed (attempt %d/%d): %s", attempt + 1, max_retries, e)
                if attempt == max_retries - 1:
                    raise
                time.sleep(2 ** attempt)

        return {}
