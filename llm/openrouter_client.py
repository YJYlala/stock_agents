"""OpenRouter API client — OpenAI-compatible, supports free and paid models.

OpenRouter aggregates many LLM providers (OpenAI, Anthropic, Google, Meta, etc.)
behind a single OpenAI-compatible endpoint. Free models available at no cost.
Docs: https://openrouter.ai/docs
"""

import json
import logging
import time

from pydantic import BaseModel

logger = logging.getLogger(__name__)

_OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1"


class OpenRouterLLMClient:
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

    def analyze(
        self,
        system_prompt: str,
        user_message: str,
        output_schema: type[BaseModel] | None = None,
        max_retries: int = 3,
    ) -> dict | str:
        """Call OpenRouter API with retry. Same interface as other LLM clients."""
        schema_instruction = ""
        if output_schema:
            schema = output_schema.model_json_schema()
            props = schema.get("properties", {})
            example_fields = {}
            for field_name, field_info in props.items():
                field_type = field_info.get("type", "string")
                if field_name in ("agent_name", "agent_role", "symbol", "timestamp", "data_used"):
                    continue
                if field_type == "number":
                    example_fields[field_name] = 0.0
                elif field_type == "integer":
                    example_fields[field_name] = 0
                elif field_type == "array":
                    example_fields[field_name] = ["item1", "item2"]
                elif field_type == "boolean":
                    example_fields[field_name] = True
                else:
                    example_fields[field_name] = "..."
            example_json = json.dumps(example_fields, indent=2, ensure_ascii=False)
            schema_instruction = (
                f"\n\nYou MUST respond with a JSON object containing these fields:\n"
                f"```json\n{example_json}\n```\n"
                "Fill in ALL fields with your actual analysis. "
                "Output ONLY the JSON object, no markdown fences, no extra text. "
                "For 'signal' use one of: BUY, SELL, HOLD. "
                "For 'score' use 0-10. For 'confidence' use 0.0-1.0. "
                "For 'reasoning' provide detailed analysis. "
                "For 'key_factors' and 'risks' provide lists of strings."
            )

        full_system = system_prompt + schema_instruction
        text = ""

        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    messages=[
                        {"role": "system", "content": full_system},
                        {"role": "user", "content": user_message},
                    ],
                )
                text = (response.choices[0].message.content or "").strip()

                if output_schema:
                    if text.startswith("```"):
                        lines = text.split("\n")
                        lines = [l for l in lines if not l.startswith("```")]
                        text = "\n".join(lines).strip()
                    return json.loads(text)

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
                err_str = str(e).lower()
                if "rate" in err_str or "429" in err_str:
                    wait = 10 * (attempt + 1)
                    logger.warning(
                        "Rate limited, waiting %ds (attempt %d/%d)",
                        wait, attempt + 1, max_retries,
                    )
                    time.sleep(wait)
                else:
                    logger.error(
                        "LLM call failed (attempt %d/%d): %s",
                        attempt + 1, max_retries, e,
                    )
                    if attempt == max_retries - 1:
                        raise
                    time.sleep(2 ** attempt)

        raise RuntimeError(f"LLM call failed after {max_retries} retries")
