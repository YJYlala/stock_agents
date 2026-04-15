"""Shared schema instruction builder for all LLM clients.

Centralizes the output_schema → JSON instruction logic so every provider
produces identical prompting.  Edit THIS file when you need to change how
the model is told to format its JSON output.
"""

from __future__ import annotations

import json
from typing import Any

# Fields injected by the agent layer after LLM returns — skip in the schema example
_SYSTEM_FIELDS = frozenset({
    "agent_name", "agent_role", "symbol", "timestamp", "data_used",
})


def build_schema_instruction(output_schema: Any) -> str:
    """Build the schema instruction appended to the system prompt.

    Args:
        output_schema: A Pydantic BaseModel *class* (not instance).
                       If None, returns empty string.

    Returns:
        A string to append to the system prompt that tells the model
        exactly what JSON fields to output and how to format them.
    """
    if output_schema is None:
        return ""

    schema = output_schema.model_json_schema()
    props = schema.get("properties", {})

    example_fields: dict[str, Any] = {}
    for field_name, field_info in props.items():
        if field_name in _SYSTEM_FIELDS:
            continue
        field_type = field_info.get("type", "string")
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

    return (
        f"\n\nYou MUST respond with a JSON object containing these fields:\n"
        f"```json\n{example_json}\n```\n"
        "Fill in ALL fields with your actual analysis. "
        "Output ONLY the JSON object, no markdown fences, no extra text. "
        "For 'signal' use one of: BUY, SELL, HOLD. "
        "For 'score' use 0-10. For 'confidence' use 0.0-1.0. "
        "For 'reasoning' provide detailed analysis. "
        "For 'key_factors' and 'risks' provide lists of strings."
    )


def strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences from LLM output before JSON parsing."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [line for line in lines if not line.startswith("```")]
        text = "\n".join(lines).strip()
    return text
