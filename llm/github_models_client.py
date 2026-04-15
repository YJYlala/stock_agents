"""GitHub Copilot / GitHub Models LLM client.

Based on the authentication approach from NousResearch/hermes-agent.
Uses the Copilot API (api.githubcopilot.com) for full model catalog access
under a GitHub Copilot Pro subscription.

Routing logic based on token type:

  gho_* / github_pat_* / ghu_*  → GitHub Copilot API (api.githubcopilot.com)
      Full Copilot Pro model access (Claude, GPT-5.4, Gemini, …).
      Two-step token exchange: GitHub token → short-lived Copilot session token → API call.

  ghp_* (classic PAT)            → GitHub Models API (models.inference.ai.azure.com)
      Classic PATs are NOT supported by the Copilot API.
      Use `copilot-login` CLI command or `gh auth login` to get a proper token.

Token search order (matches Copilot CLI / Hermes behaviour):
  constructor arg → COPILOT_GITHUB_TOKEN → GH_TOKEN → GITHUB_TOKEN → `gh auth token`

OAuth device code flow:
  For users without `gh` CLI, use `python -m stock_agents copilot-login` to
  authenticate via browser and get a gho_* token automatically.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

from stock_agents.llm.base_client import BaseLLMClient

logger = logging.getLogger(__name__)

# ─── Endpoint / header constants ──────────────────────────────────────────
_COPILOT_API_BASE_URL = "https://api.githubcopilot.com"
_COPILOT_MODELS_URL = f"{_COPILOT_API_BASE_URL}/models"
_GITHUB_MODELS_ENDPOINT = "https://models.inference.ai.azure.com"

# OAuth device code flow — same client ID as opencode / Copilot CLI / Hermes
_COPILOT_OAUTH_CLIENT_ID = "Ov23li8tweQw6odWQebz"

_COPILOT_ENV_VARS = ("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN")
_CLASSIC_PAT_PREFIX = "ghp_"
_COPILOT_SUPPORTED_PREFIXES = ("gho_", "github_pat_", "ghu_")

# Copilot API request headers (matches Hermes / opencode / Copilot CLI)
_COPILOT_HEADERS = {
    "Editor-Version": "vscode/1.104.1",
    "User-Agent": "StockAgents/1.0",
    "Copilot-Integration-Id": "vscode-chat",
    "Openai-Intent": "conversation-edits",
    "x-initiator": "agent",
}

# Credential file for OAuth tokens
_TOKEN_CACHE_PATH = Path.home() / ".stock-agents" / "copilot_token.json"


def _is_classic_pat(token: str) -> bool:
    return token.strip().startswith(_CLASSIC_PAT_PREFIX)


def validate_copilot_token(token: str) -> tuple[bool, str]:
    """Validate that a token is usable with the Copilot API. Returns (valid, message)."""
    token = token.strip()
    if not token:
        return False, "Empty token"
    if token.startswith(_CLASSIC_PAT_PREFIX):
        return False, (
            "Classic Personal Access Tokens (ghp_*) are not supported by the "
            "Copilot API. Use one of:\n"
            "  → `python -m stock_agents copilot-login` to authenticate via OAuth\n"
            "  → A fine-grained PAT (github_pat_*) with Copilot Requests permission\n"
            "  → `gh auth login` with the default device code flow (produces gho_* tokens)"
        )
    return True, "OK"


def _resolve_github_token() -> tuple[str, str]:
    """Return (github_token, source). Searches env vars, cached token, then gh CLI."""
    # 1. Env vars
    for env_var in _COPILOT_ENV_VARS:
        val = os.getenv(env_var, "").strip()
        if val:
            return val, env_var

    # 2. Cached OAuth token from `copilot-login`
    token = _load_cached_token()
    if token:
        return token, "cached OAuth token (~/.stock-agents/copilot_token.json)"

    # 3. gh CLI fallback
    token = _try_gh_cli_token()
    if token:
        return token, "gh auth token"

    return "", ""


def _load_cached_token() -> Optional[str]:
    """Load a previously cached OAuth token."""
    try:
        if _TOKEN_CACHE_PATH.exists():
            data = json.loads(_TOKEN_CACHE_PATH.read_text())
            token = data.get("token", "")
            if token:
                return token
    except Exception:
        pass
    return None


def _save_cached_token(token: str) -> None:
    """Cache an OAuth token for future use."""
    try:
        _TOKEN_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _TOKEN_CACHE_PATH.write_text(json.dumps({"token": token}))
        _TOKEN_CACHE_PATH.chmod(0o600)
    except Exception as e:
        logger.warning("Could not cache token: %s", e)


def _try_gh_cli_token() -> Optional[str]:
    """Return a token from ``gh auth token`` when the GitHub CLI is available.

    Strips GITHUB_TOKEN / GH_TOKEN from the subprocess env so ``gh`` reads
    from its own credential store (hosts.yml) instead of echoing the env var.
    """
    candidates: list[str] = []
    resolved = shutil.which("gh")
    if resolved:
        candidates.append(resolved)
    for path in ("/opt/homebrew/bin/gh", "/usr/local/bin/gh",
                 str(Path.home() / ".local" / "bin" / "gh")):
        if path not in candidates and os.path.isfile(path) and os.access(path, os.X_OK):
            candidates.append(path)

    # Clean env so gh doesn't short-circuit on GITHUB_TOKEN / GH_TOKEN
    clean_env = {k: v for k, v in os.environ.items()
                 if k not in ("GITHUB_TOKEN", "GH_TOKEN")}

    hostname = os.getenv("COPILOT_GH_HOST", "").strip()

    for gh in candidates:
        cmd = [gh, "auth", "token"]
        if hostname:
            cmd += ["--hostname", hostname]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=5, env=clean_env,
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


# ─── OAuth Device Code Flow ────────────────────────────────────────────────

def copilot_device_code_login(
    *,
    host: str = "github.com",
    timeout_seconds: float = 300,
) -> Optional[str]:
    """Run the GitHub OAuth device code flow for Copilot.

    Same flow as opencode, Hermes Agent, and the Copilot CLI.
    Prints instructions, polls for completion, returns OAuth access token
    on success, or None on failure/cancellation. Caches the token.
    """
    domain = host.rstrip("/")
    device_code_url = f"https://{domain}/login/device/code"
    access_token_url = f"https://{domain}/login/oauth/access_token"

    # Step 1: Request device code
    data = urllib.parse.urlencode({
        "client_id": _COPILOT_OAUTH_CLIENT_ID,
        "scope": "read:user",
    }).encode()

    req = urllib.request.Request(
        device_code_url, data=data,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "StockAgents/1.0",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=15, context=_make_ssl_context()) as resp:
            device_data = json.loads(resp.read().decode())
    except Exception as exc:
        logger.error("Failed to initiate device authorization: %s", exc)
        print(f"  ✗ Failed to start device authorization: {exc}")
        return None

    verification_uri = device_data.get("verification_uri", "https://github.com/login/device")
    user_code = device_data.get("user_code", "")
    device_code = device_data.get("device_code", "")
    interval = max(device_data.get("interval", 5), 1)

    if not device_code or not user_code:
        print("  ✗ GitHub did not return a device code.")
        return None

    # Step 2: Show instructions
    print()
    print(f"  Open this URL in your browser: {verification_uri}")
    print(f"  Enter this code: {user_code}")
    print()
    print("  Waiting for authorization...", end="", flush=True)

    # Step 3: Poll for completion
    deadline = time.time() + timeout_seconds

    while time.time() < deadline:
        time.sleep(interval + 3)  # safety margin

        poll_data = urllib.parse.urlencode({
            "client_id": _COPILOT_OAUTH_CLIENT_ID,
            "device_code": device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        }).encode()

        poll_req = urllib.request.Request(
            access_token_url, data=poll_data,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "StockAgents/1.0",
            },
        )

        try:
            with urllib.request.urlopen(poll_req, timeout=10, context=_make_ssl_context()) as resp:
                result = json.loads(resp.read().decode())
        except Exception:
            print(".", end="", flush=True)
            continue

        if result.get("access_token"):
            print(" ✓")
            token = result["access_token"]
            _save_cached_token(token)
            return token

        error = result.get("error", "")
        if error == "authorization_pending":
            print(".", end="", flush=True)
        elif error == "slow_down":
            server_interval = result.get("interval")
            if isinstance(server_interval, (int, float)) and server_interval > 0:
                interval = int(server_interval)
            else:
                interval += 5
            print(".", end="", flush=True)
        elif error == "expired_token":
            print("\n  ✗ Device code expired. Please try again.")
            return None
        elif error == "access_denied":
            print("\n  ✗ Authorization was denied.")
            return None
        elif error:
            print(f"\n  ✗ Authorization failed: {error}")
            return None

    print("\n  ✗ Timed out waiting for authorization.")
    return None


# ─── Model Catalog ─────────────────────────────────────────────────────────

def fetch_copilot_model_catalog(api_key: str = "") -> Optional[list[dict]]:
    """Fetch available models from the Copilot API /models endpoint.

    Returns list of model dicts with 'id' and metadata, or None on failure.
    Requires a valid Copilot session token (not GitHub token).
    """
    headers = {**_COPILOT_HEADERS}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(_COPILOT_MODELS_URL, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10, context=_make_ssl_context()) as resp:
            data = json.loads(resp.read().decode())
            items = data if isinstance(data, list) else data.get("data", data.get("models", []))
            models = []
            seen: set[str] = set()
            for item in items:
                model_id = str(item.get("id", "")).strip()
                if not model_id or model_id in seen:
                    continue
                # Filter to chat-capable models
                caps = item.get("capabilities", {})
                if isinstance(caps, dict) and caps.get("type") and caps["type"] != "chat":
                    continue
                seen.add(model_id)
                models.append(item)
            return models if models else None
    except Exception as e:
        logger.debug("Failed to fetch Copilot model catalog: %s", e)
        return None


def list_copilot_models(github_token: str = "") -> list[str]:
    """Return model IDs available under the current Copilot Pro subscription.

    Uses the OAuth/fine-grained token directly as Bearer token (no exchange).
    """
    if not github_token:
        github_token, _ = _resolve_github_token()
    if not github_token or _is_classic_pat(github_token):
        return []

    try:
        catalog = fetch_copilot_model_catalog(github_token)
        if catalog:
            return [item["id"] for item in catalog if item.get("id")]
    except Exception as e:
        logger.debug("Could not list Copilot models: %s", e)
    return []


class GitHubModelsLLMClient(BaseLLMClient):
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
                "GITHUB_TOKEN, run `gh auth login`, or use:\n"
                "  python -m stock_agents copilot-login"
            )

        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._models_endpoint = endpoint

        if _is_classic_pat(self._github_token):
            valid, msg = validate_copilot_token(self._github_token)
            logger.warning(
                "Classic PAT (ghp_*) detected — limited to GitHub Models endpoint. "
                "For full Copilot Pro model catalog, %s", msg,
            )
            self._use_copilot_api = False
            self.client = self._build_models_client()
        else:
            self._use_copilot_api = True
            self.client = self._build_copilot_client()
            logger.info(
                "Using GitHub Copilot API (full model catalog) — token from %s",
                self._github_token_source,
            )

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
        """OpenAI client for the Copilot API endpoint.

        Uses the GitHub OAuth/fine-grained token directly as Bearer token
        (same approach as Hermes Agent — no session token exchange needed).
        """
        return self._OpenAI(
            base_url=_COPILOT_API_BASE_URL,
            api_key=self._github_token,
            default_headers=_COPILOT_HEADERS,
            max_retries=0,
        )

    def _call_llm(self, system_prompt: str, user_message: str) -> str:
        """Route to the correct API path: Responses API / reasoning / standard."""
        _model_lower = self.model.lower()
        _is_reasoning = _model_lower.startswith(("o1", "o3", "o4"))
        _use_responses = _model_lower.startswith("gpt-5")

        if _use_responses:
            response = self.client.responses.create(
                model=self.model,
                instructions=system_prompt,
                input=user_message,
                temperature=self.temperature,
                max_output_tokens=self.max_tokens,
            )
            return (response.output_text or "").strip()
        elif _is_reasoning:
            # Reasoning models don't support system prompts
            response = self.client.chat.completions.create(
                model=self.model,
                max_completion_tokens=self.max_tokens,
                messages=[{"role": "user", "content": f"{system_prompt}\n\n{user_message}"}],
            )
            return (response.choices[0].message.content or "").strip()
        else:
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
