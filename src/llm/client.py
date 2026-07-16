"""Pluggable LLM client.

Two modes, selected automatically at runtime:

  * LIVE    — ANTHROPIC_API_KEY is set (env var or Streamlit secrets):
              calls the Anthropic Messages API.
  * OFFLINE — no key: workflows fall back to deterministic, rule-based
              composition over the same retrieved context. The demo stays
              fully functional with zero external dependencies or cost.

Product rationale (docs/01-prd.md §7): reviewers and pilot users must be able
to run the prototype without credentials, and the offline path doubles as the
graceful-degradation behavior if the API is unavailable in production.
"""
from __future__ import annotations

import os

from config.settings import DEFAULT_LLM_MODEL, LLM_MODEL_ENV


def _find_api_key() -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    # Streamlit Cloud exposes secrets via st.secrets, not os.environ
    try:
        import streamlit as st  # noqa: PLC0415

        return st.secrets.get("ANTHROPIC_API_KEY")  # type: ignore[no-any-return]
    except Exception:
        return None


class OfflineClient:
    """Sentinel client: workflows branch on `is_live` and never call this."""

    is_live = False
    label = "Offline mode — deterministic fallback (no API key)"

    def complete(self, system: str, user: str, max_tokens: int = 900) -> str:
        raise RuntimeError(
            "OfflineClient.complete() should never be called — "
            "workflows must branch on client.is_live."
        )


class AnthropicClient:
    is_live = True

    def __init__(self, api_key: str):
        from anthropic import Anthropic  # imported lazily; optional offline

        self._client = Anthropic(api_key=api_key)
        self.model = os.environ.get(LLM_MODEL_ENV, DEFAULT_LLM_MODEL)
        self.label = f"Live AI — {self.model}"

    def complete(self, system: str, user: str, max_tokens: int = 900) -> str:
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(
            block.text for block in resp.content if block.type == "text"
        ).strip()


def get_client():
    """Return the live client when a key is available, else the offline sentinel."""
    key = _find_api_key()
    if key:
        try:
            return AnthropicClient(key)
        except Exception:
            return OfflineClient()
    return OfflineClient()
