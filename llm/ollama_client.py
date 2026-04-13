"""Ollama local LLM client — fallback when cloud providers are unavailable.

Uses Ollama's OpenAI-compatible API (no extra deps beyond openai package).
Default model: gemma3 (best local model for financial analysis).
"""

import json
import logging
import time

from pydantic import BaseModel

logger = logging.getLogger(__name__)

_OLLAMA_DEFAULT_ENDPOINT = "http://localhost:11434/v1"


class OllamaLLMClient:
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
            api_key="ollama",  # Ollama doesn't need a real key
            max_retries=0,  # Disable SDK internal retries
        )
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature

    @property
    def model_label(self) -> str:
        return f"{self.model} (Ollama)"

    def analyze(
        self,
        system_prompt: str,
        user_message: str,
        output_schema: type[BaseModel] | None = None,
        max_retries: int = 3,
    ) -> dict | str:
        """Call Ollama API with retry. Same interface as other LLM clients."""
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
                    "Ollama JSON parse failed (attempt %d/%d): %s",
                    attempt + 1, max_retries, e,
                )
                if attempt == max_retries - 1:
                    return text
                time.sleep(1)
            except Exception as e:
                err_str = str(e)
                # Quick fail if Ollama is not running
                if any(k in err_str for k in ["502", "Connection refused", "Connection error", "ConnectError"]):
                    logger.error("Ollama not available: %s", e)
                    raise  # Don't retry, fail immediately
                logger.error(
                    "Ollama call failed (attempt %d/%d): %s",
                    attempt + 1, max_retries, e,
                )
                if attempt == max_retries - 1:
                    raise
                time.sleep(2 ** attempt)

        raise RuntimeError(f"Ollama LLM call failed after {max_retries} retries")
