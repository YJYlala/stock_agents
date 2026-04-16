"""Azure OpenAI LLM client — uses the OpenAI SDK with Azure endpoints.

Supports two auth modes:
  1. HP UID OAuth (preferred): fetches bearer token via client_credentials grant
  2. API key fallback: uses api-key header directly

Required environment variables:
  AZURE_OPENAI_API_KEY      – API key (also used as fallback)
  AZURE_OPENAI_ENDPOINT     – Azure endpoint URL
  AZURE_OPENAI_API_VERSION  – API version (e.g. 2025-01-01-preview)

For HP UID OAuth (optional but recommended):
  HP_UID_CLIENT_ID          – OAuth client ID
  HP_UID_CLIENT_SECRET      – OAuth client secret
  HP_UID_URL                – Token endpoint URL
"""

from __future__ import annotations

import json
import logging
import os
import ssl
import time
import urllib.request

from genai_common.llm.base_client import BaseLLMClient

logger = logging.getLogger(__name__)

# Token cache: (access_token, expiry_monotonic)
_hp_token_cache: tuple[str, float] | None = None
_TOKEN_REFRESH_BUFFER = 1800  # refresh 30 min before expiry


def _fetch_hp_uid_token() -> str:
    """Fetch an HP UID bearer token via OAuth client_credentials flow."""
    global _hp_token_cache
    now = time.monotonic()
    if _hp_token_cache is not None:
        token, expiry = _hp_token_cache
        if now < expiry - _TOKEN_REFRESH_BUFFER:
            return token

    client_id = os.getenv("HP_UID_CLIENT_ID", "")
    client_secret = os.getenv("HP_UID_CLIENT_SECRET", "")
    token_url = os.getenv("HP_UID_URL", "")

    if not all([client_id, client_secret, token_url]):
        raise ValueError(
            "HP_UID_CLIENT_ID, HP_UID_CLIENT_SECRET, and HP_UID_URL must be set "
            "for HP UID OAuth authentication."
        )

    # HP UID server uses self-signed/corporate CA — skip verification
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }).encode()

    req = urllib.request.Request(
        token_url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                body = json.loads(resp.read())
                access_token = body.get("access_token")
                if not access_token:
                    raise ValueError(f"No access_token in response: {body}")
                expires_in = float(body.get("expires_in", 1800))
                _hp_token_cache = (access_token, now + expires_in)
                logger.info("HP UID token fetched — expires in %.0fs", expires_in)
                return access_token
        except Exception as e:
            logger.warning("HP UID token fetch attempt %d/3 failed: %s", attempt + 1, e)
            if attempt < 2:
                time.sleep(1)

    raise ValueError("Failed to fetch HP UID token after 3 retries")


class AzureOpenAILLMClient(BaseLLMClient):
    """LLM client for Azure OpenAI deployments (GPT-4o, GPT-5.4, etc.)."""

    def __init__(
        self,
        api_key: str,
        endpoint: str,
        api_version: str = "2025-01-01-preview",
        deployment: str = "gpt-4o",
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ):
        try:
            from openai import AzureOpenAI  # type: ignore
            import httpx
        except ImportError:
            raise ImportError("openai and httpx packages are required.")

        self.deployment = deployment
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._api_key = api_key
        self._endpoint = endpoint
        self._api_version = api_version

        # HP corporate endpoint uses a private CA — supply the cert bundle
        verify = self._get_cert_path()

        # Try HP UID OAuth for bearer-token auth
        extra_headers = {}
        self._use_bearer = False
        if os.getenv("HP_UID_CLIENT_ID") and os.getenv("HP_UID_CLIENT_SECRET"):
            try:
                bearer_token = _fetch_hp_uid_token()
                extra_headers["Authorization"] = f"Bearer {bearer_token}"
                self._use_bearer = True
                logger.info("Using HP UID bearer token for Azure OpenAI auth")
            except Exception as e:
                logger.warning("HP UID token fetch failed, falling back to API key: %s", e)

        http_client = httpx.Client(
            verify=verify or True,
            timeout=httpx.Timeout(connect=15.0, read=300.0, write=30.0, pool=15.0),
        )

        self.client = AzureOpenAI(
            api_key=api_key,
            azure_endpoint=endpoint,
            api_version=api_version,
            max_retries=0,
            http_client=http_client,
            default_headers=extra_headers if extra_headers else None,
        )
        logger.info(
            "Azure OpenAI client ready (deployment=%s, endpoint=%s, auth=%s)",
            deployment, endpoint, "bearer" if self._use_bearer else "api-key",
        )

    @property
    def model_label(self) -> str:
        return f"{self.deployment} (Azure OpenAI)"

    def _refresh_bearer_if_needed(self):
        """Refresh the HP UID bearer token if using bearer auth."""
        if not self._use_bearer:
            return
        try:
            bearer_token = _fetch_hp_uid_token()
            self.client._custom_headers["Authorization"] = f"Bearer {bearer_token}"
        except Exception as e:
            logger.warning("Bearer token refresh failed: %s", e)

    @staticmethod
    def _get_cert_path() -> str | None:
        """Locate the HP corporate CA cert bundle."""
        local = os.path.join(os.path.dirname(__file__), "..", "ca-certifacates.crt")
        local = os.path.normpath(local)
        if os.path.isfile(local):
            return local
        sibling = os.path.join(
            os.path.dirname(__file__), "..", "..", "Genai-DocAI",
            "src", "doc_agent", "ca-certifacates.crt",
        )
        sibling = os.path.normpath(sibling)
        if os.path.isfile(sibling):
            return sibling
        try:
            import importlib.resources
            cert = importlib.resources.files("doc_agent").joinpath("ca-certifacates.crt")
            with importlib.resources.as_file(cert) as p:
                return str(p)
        except Exception:
            pass
        try:
            import certifi
            return certifi.where()
        except Exception:
            pass
        return None

    def _call_llm(self, system_prompt: str, user_message: str) -> str:
        self._refresh_bearer_if_needed()
        response = self.client.chat.completions.create(
            model=self.deployment,
            max_completion_tokens=self.max_tokens,
            temperature=self.temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )
        return (response.choices[0].message.content or "").strip()
