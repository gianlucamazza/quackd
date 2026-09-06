"""`--provider <name>` → an `LLMProvider`, importing vendor SDKs only when asked for.

Kept separate from `__init__` so importing `quackd.agent.providers` never touches a vendor
package, and so `quackd doctor` can ask "which providers could run here?" cheaply.
"""

from __future__ import annotations

import os

from quackd.agent.providers.base import LLMProvider, ProviderError

CLOUD_NAMES = ("anthropic", "openai", "gemini", "grok", "deepseek")
LOCAL_NAMES = ("local", "ollama", "vllm", "llamacpp", "lmstudio")
PROVIDER_NAMES = ("fake", *CLOUD_NAMES, *LOCAL_NAMES)

# Defaults are env-overridable via QUACKD_MODEL. Non-Anthropic defaults should be checked
# against the vendor's current model list — see docs/faq.md. Local presets discover the
# served model from /v1/models when none is given.
DEFAULT_MODELS: dict[str, str | None] = {
    "anthropic": "claude-opus-5",
    "openai": "gpt-5.6-terra",
    "gemini": "gemini-2.5-pro",
    "grok": "grok-4",
    "deepseek": "deepseek-v4-pro",
    **{name: None for name in LOCAL_NAMES},
}

KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "grok": "XAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    **{name: "LOCAL_API_KEY" for name in LOCAL_NAMES},
}

EXTRA_FOR = {
    "anthropic": "anthropic",
    "openai": "openai",
    "gemini": "gemini",
    "grok": "grok",
    "deepseek": "deepseek",
    **{name: "openai" for name in LOCAL_NAMES},
}


def default_model(provider: str) -> str | None:
    return os.environ.get("QUACKD_MODEL") or DEFAULT_MODELS.get(provider)


def make_provider(
    name: str,
    *,
    model: str | None = None,
    duck_name: str | None = None,
    goal: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    vision: bool | None = None,
) -> LLMProvider:
    name = name.lower()
    if name == "fake":
        from quackd.agent.providers.fake import FakeProvider

        return FakeProvider.for_duck(duck_name or "", goal=goal)
    model = model or default_model(name)
    if name == "anthropic":
        from quackd.agent.providers.anthropic import AnthropicProvider

        return AnthropicProvider(model=model or "claude-opus-5")
    if name == "openai":
        from quackd.agent.providers.openai import OpenAIProvider

        return OpenAIProvider(
            model=model or "gpt-5.6-terra", api_key=api_key, base_url=base_url, vision=vision
        )
    if name == "gemini":
        from quackd.agent.providers.gemini import GeminiProvider

        return GeminiProvider(model=model or "gemini-2.5-pro", api_key=api_key)
    if name == "grok":
        from quackd.agent.providers.grok import GrokProvider

        return GrokProvider(
            model=model or "grok-4", api_key=api_key, base_url=base_url, vision=vision
        )
    if name == "deepseek":
        from quackd.agent.providers.deepseek import DeepSeekProvider

        return DeepSeekProvider(
            model=model or "deepseek-v4-pro", api_key=api_key, base_url=base_url, vision=vision
        )
    if name in LOCAL_NAMES:
        from quackd.agent.providers.local import LocalProvider

        return LocalProvider(model, preset=name, base_url=base_url, api_key=api_key, vision=vision)
    raise ProviderError(f"unknown provider {name!r}; choose one of {', '.join(PROVIDER_NAMES)}")
