"""Grok as the duck's brain: xAI's OpenAI-compatible endpoint, so it is the OpenAI provider
with a different base URL, key, and default model. Nothing else changes.
"""

from __future__ import annotations

from quackd.agent.providers.openai import OpenAIProvider

DEFAULT_MODEL = "grok-4"
XAI_BASE_URL = "https://api.x.ai/v1"


class GrokProvider(OpenAIProvider):
    name = "grok"
    key_env = "XAI_API_KEY"
    base_url = XAI_BASE_URL

    def __init__(self, model: str = DEFAULT_MODEL, **kwargs: object) -> None:
        super().__init__(model, **kwargs)  # type: ignore[arg-type]
