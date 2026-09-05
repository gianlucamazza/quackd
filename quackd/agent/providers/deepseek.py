"""DeepSeek's OpenAI-compatible API provider."""

from __future__ import annotations

from quackd.agent.providers.openai import OpenAIProvider

DEFAULT_MODEL = "deepseek-v4-pro"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"


class DeepSeekProvider(OpenAIProvider):
    """DeepSeek chat completions with quackd's standard tool-call mapping."""

    name = "deepseek"
    key_env = "DEEPSEEK_API_KEY"
    base_url = DEEPSEEK_BASE_URL
    supports_vision = False
    # DeepSeek thinking mode rejects tool_choice="required"; quackd enforces one tool call
    # in the provider-neutral loop and re-prompts when the model returns plain text.
    default_tool_choice = "auto"

    def __init__(self, model: str = DEFAULT_MODEL, **kwargs: object) -> None:
        super().__init__(model, **kwargs)  # type: ignore[arg-type]
