"""`--provider <name>` → an `LLMProvider`, importing vendor SDKs only when asked for.

Kept separate from `__init__` so importing `quackd.agent.providers` never touches a vendor
package, and so `quackd doctor` can ask "which providers could run here?" cheaply.
"""

from __future__ import annotations

import os

from quackd.agent.providers.base import LLMProvider, ProviderError

PROVIDER_NAMES = ("fake", "anthropic", "openai", "gemini", "grok")

# Defaults are env-overridable via QUACKD_MODEL. Non-Anthropic defaults should be checked
# against the vendor's current model list — see docs/faq.md.
DEFAULT_MODELS = {
    "anthropic": "claude-opus-5",
    "openai": "gpt-5",
    "gemini": "gemini-2.5-pro",
    "grok": "grok-4",
}

KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "grok": "XAI_API_KEY",
}

EXTRA_FOR = {"anthropic": "anthropic", "openai": "openai", "gemini": "gemini", "grok": "grok"}


def default_model(provider: str) -> str | None:
    return os.environ.get("QUACKD_MODEL") or DEFAULT_MODELS.get(provider)


def make_provider(
    name: str, *, model: str | None = None, duck_name: str | None = None, goal: str | None = None
) -> LLMProvider:
    name = name.lower()
    if name == "fake":
        from quackd.agent.providers.fake import FakeProvider

        return FakeProvider.for_duck(duck_name or "", goal=goal)
    model = model or default_model(name)
    if name == "anthropic":
        from quackd.agent.providers.anthropic import AnthropicProvider

        return AnthropicProvider(model=model or DEFAULT_MODELS["anthropic"])
    if name == "openai":
        from quackd.agent.providers.openai import OpenAIProvider

        return OpenAIProvider(model=model or DEFAULT_MODELS["openai"])
    if name == "gemini":
        from quackd.agent.providers.gemini import GeminiProvider

        return GeminiProvider(model=model or DEFAULT_MODELS["gemini"])
    if name == "grok":
        from quackd.agent.providers.grok import GrokProvider

        return GrokProvider(model=model or DEFAULT_MODELS["grok"])
    raise ProviderError(f"unknown provider {name!r}; choose one of {', '.join(PROVIDER_NAMES)}")
