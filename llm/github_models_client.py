"""GitHub Copilot / GitHub Models LLM client.

Routing logic based on token type:

  gho_* / github_pat_* / ghu_*  → GitHub Copilot API (api.githubcopilot.com)
      Full Copilot Pro model access (Claude, GPT-4o, o1, o3, Gemini, …).
      Uses the two-step token exchange flow:
        GitHub token → short-lived Copilot session token → API call.

  ghp_* (classic PAT)            → GitHub Models API (models.inference.ai.azure.com)
      Classic PATs are NOT accepted by the Copilot API but DO work on the
      GitHub Models endpoint with your Copilot Pro rate limits.

Token search order (matches Copilot CLI behaviour):
  constructor arg → COPILOT_GITHUB_TOKEN → GH_TOKEN → GITHUB_TOKEN → `gh auth token`
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
import urllib.request
from typing import Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ─── Endpoint / header constants ──────────────────────────────────────────
_COPILOT_TOKEN_EXCHANGE_URL = "https://api.github.com/copilot_internal/v2/token"
_COPILOT_API_BASE_URL = "https://api.githubcopilot.com"
_GITHUB_MODELS_ENDPOINT = "https://models.inference.ai.azure.com"

_COPILOT_ENV_VARS = ("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN")
_CLASSIC_PAT_PREFIX = "ghp_"
_COPILOT_SUPPORTED_PREFIXES = ("gho_", "github_pat_", "ghu_")

# Copilot session tokens expire after ~30 min; refresh 60 s early
_TOKEN_REFRESH_BUFFER_S = 60


def _is_classic_pat(token: str) -> bool:
    return token.strip().startswith(_CLASSIC_PAT_PREFIX)


def _resolve_github_token() -> tuple[str, str]:
    """Return (github_token, source). Accepts any token type."""
    for env_var in _COPILOT_ENV_VARS:
        val = os.getenv(env_var, "").strip()
        if val:
            return val, env_var

    token = _try_gh_cli_token()
    if token:
        return token, "gh auth token"

    return "", ""


def _try_gh_cli_token() -> Optional[str]:
    candidates: list[str] = []
    resolved = shutil.which("gh")
    if resolved:
        candidates.append(resolved)
    for path in ("/opt/homebrew/bin/gh", "/usr/local/bin/gh"):
        if path not in candidates and os.path.isfile(path) and os.access(path, os.X_OK):
            candidates.append(path)

    for gh in candidates:
        try:
            result = subprocess.run(
                [gh, "auth", "token"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return None


def _make_ssl_context():
    """Return an SSL context that trusts certifi's CA bundle (fixes macOS issues)."""
    import ssl
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
    return ctx


def _exchange_for_copilot_token(github_token: str) -> tuple[str, float]:
    """Exchange a GitHub OAuth/fine-grained PAT for a Copilot session token."""
    req = urllib.request.Request(
        _COPILOT_TOKEN_EXCHANGE_URL,
        headers={
            "Authorization": f"token {github_token}",
            "Accept": "application/json",
            "User-Agent": "GitHubCopilotClient/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=15, context=_make_ssl_context()) as resp:
        data = json.loads(resp.read().decode())

    token = data.get("token", "")
    expires_at_str = data.get("expires_at", "")
    if not token:
        raise ValueError(f"Copilot token exchange returned no token: {data}")


    expires_at: float = time.time() + 1800
    if expires_at_str:
        try:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
            expires_at = dt.astimezone(timezone.utc).timestamp()
        except Exception:
            pass

    return token, expires_at


class GitHubModelsLLMClient:
    """LLM client supporting both GitHub Copilot API and GitHub Models API."""

    def __init__(
        self,
        github_token: str = "",
        model: str = "gpt-4o",
        max_tokens: int = 4096,
        temperature: float = 0.3,
        endpoint: str = _GITHUB_MODELS_ENDPOINT,
    ):
        try:
            from openai import OpenAI  # type: ignore
            self._OpenAI = OpenAI
        except ImportError:
            raise ImportError("openai package is required. Run: pip install openai")

        # Resolve token
        if github_token:
            self._github_token = github_token.strip()
            self._github_token_source = "constructor argument"
        else:
            self._github_token, self._github_token_source = _resolve_github_token()

        if not self._github_token:
            raise ValueError(
                "No GitHub token found. Set COPILOT_GITHUB_TOKEN / GH_TOKEN / "
                "GITHUB_TOKEN or run `gh auth login`."
            )

        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature

        if _is_classic_pat(self._github_token):
            self._use_copilot_api = False
            self._models_endpoint = endpoint
            self._copilot_token: str = ""
            self._copilot_token_expires_at: float = 0.0
            self.client = self._build_models_client()
        else:
            self._models_endpoint = endpoint
            self._copilot_token = ""
            self._copilot_token_expires_at = 0.0
            try:
                self._refresh_copilot_token()
                self._use_copilot_api = True
                self.client = self._build_copilot_client()
                logger.info("Using GitHub Copilot API (full model catalog).")
            except Exception:
                # Token exchange failed — use GitHub Models endpoint directly.
                # Works for fine-grained PATs with Copilot Pro subscription.
                logger.info("Using GitHub Models endpoint (%s).", endpoint)
                self._use_copilot_api = False
                self.client = self._build_models_client()

    # ── Client builders ────────────────────────────────────────────────────

    @property
    def model_label(self) -> str:
        provider = "GitHub Copilot" if getattr(self, "_use_copilot_api", False) else "GitHub Models"
        return f"{self.model} ({provider})"

    def _build_models_client(self):
        """OpenAI client for the GitHub Models endpoint (classic PAT path)."""
        return self._OpenAI(
            base_url=self._models_endpoint,
            api_key=self._github_token,
            max_retries=0,
        )

    def _build_copilot_client(self):
        """OpenAI client for the Copilot API endpoint."""
        return self._OpenAI(
            base_url=_COPILOT_API_BASE_URL,
            api_key=self._copilot_token,
            default_headers={
                "Editor-Version": "vscode/1.104.1",
                "User-Agent": "GitHubCopilotClient/1.0",
                "Openai-Intent": "conversation-edits",
                "x-initiator": "agent",
            },
            max_retries=0,
        )

    def _refresh_copilot_token(self) -> None:
        logger.debug("Exchanging GitHub token for Copilot session token…")
        self._copilot_token, self._copilot_token_expires_at = (
            _exchange_for_copilot_token(self._github_token)
        )

    def _ensure_fresh_token(self) -> None:
        """Refresh the Copilot session token before it expires (no-op for GitHub Models path)."""
        if not self._use_copilot_api:
            return
        if time.time() >= self._copilot_token_expires_at - _TOKEN_REFRESH_BUFFER_S:
            try:
                self._refresh_copilot_token()
                self.client = self._build_copilot_client()
            except Exception as exc:
                logger.warning("Copilot token refresh failed (%s), retrying with existing token.", exc)

    def analyze(
        self,
        system_prompt: str,
        user_message: str,
        output_schema: type[BaseModel] | None = None,
        max_retries: int = 3,
    ) -> dict | str:
        """Call GitHub Copilot/Models API with retry. Same interface as ClaudeLLMClient."""
        schema_instruction = ""
        if output_schema:
            # Build a simplified example showing just the field names and types
            # rather than the full JSON Schema (which GPT-4o tends to echo back)
            schema = output_schema.model_json_schema()
            props = schema.get("properties", {})
            example_fields = {}
            for field_name, field_info in props.items():
                field_type = field_info.get("type", "string")
                if field_name in ("agent_name", "agent_role", "symbol", "timestamp", "data_used"):
                    continue  # skip fields handled by the system
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

        # Reasoning models (o-series) use different params:
        #   - max_completion_tokens instead of max_tokens
        #   - no system role (merge into user message)
        #   - no temperature
        _is_reasoning = self.model.lower().startswith(("o1", "o3", "o4"))

        for attempt in range(max_retries):
            try:
                self._ensure_fresh_token()

                if _is_reasoning:
                    messages = [{"role": "user", "content": f"{full_system}\n\n{user_message}"}]
                    response = self.client.chat.completions.create(
                        model=self.model,
                        max_completion_tokens=self.max_tokens,
                        messages=messages,
                    )
                else:
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
                    # Strip markdown fences if present
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
                    wait = 15 * (attempt + 1)  # 15s, 30s, 45s, 60s, 75s
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
