"""Gemini as the duck's brain, via `google-genai` (optional extra).

Function calling with `mode="ANY"` so a turn always yields a call; images ride as inline
PNG parts; tool results go back as `function_response` parts. Gemini's schema dialect
rejects a few JSON-Schema keywords, so `render_tools` strips them.
"""

from __future__ import annotations

import os
from typing import Any

from quackd.agent.providers.base import (
    Exchange,
    ProviderError,
    ProviderMissingKey,
    ProviderNotInstalled,
    ProviderTurn,
    ToolCall,
    Usage,
)

DEFAULT_MODEL = "gemini-2.5-pro"
UNSUPPORTED_SCHEMA_KEYS = {"additionalProperties", "title", "default", "$schema", "$id"}


def clean_schema(schema: Any) -> Any:
    """Drop keywords Gemini's function-declaration schema does not accept."""
    if isinstance(schema, dict):
        return {k: clean_schema(v) for k, v in schema.items() if k not in UNSUPPORTED_SCHEMA_KEYS}
    if isinstance(schema, list):
        return [clean_schema(v) for v in schema]
    return schema


def render_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One `Tool` with all function declarations, as plain dicts (the SDK accepts dicts)."""
    return [
        {
            "function_declarations": [
                {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": clean_schema(t["input_schema"]),
                }
                for t in tools
            ]
        }
    ]


def render_contents(history: list[Exchange]) -> list[dict[str, Any]]:
    contents: list[dict[str, Any]] = []
    for ex in history:
        obs = ex.observation
        parts: list[dict[str, Any]] = []
        if obs.tool_call_id and ex is not history[0]:
            prev = _previous_decision(history, ex)
            if prev is not None:
                parts.append(
                    {
                        "function_response": {
                            "name": prev.tool_call.name,
                            "response": {"result": obs.text},
                        }
                    }
                )
            else:
                parts.append({"text": obs.text})
        else:
            parts.append({"text": obs.text})
        if obs.image_png:
            parts.append({"inline_data": {"mime_type": "image/png", "data": obs.image_png}})
        contents.append({"role": "user", "parts": parts})
        if ex.decision is not None:
            tc = ex.decision.tool_call
            model_parts: list[dict[str, Any]] = []
            if ex.decision.text:
                model_parts.append({"text": ex.decision.text})
            model_parts.append({"function_call": {"name": tc.name, "args": tc.arguments}})
            contents.append({"role": "model", "parts": model_parts})
    return contents


def _previous_decision(history: list[Exchange], current: Exchange) -> Any:
    idx = history.index(current)
    for ex in reversed(history[:idx]):
        if ex.decision is not None:
            return ex.decision
    return None


def parse_response(response: Any) -> ProviderTurn:
    tool_calls: list[ToolCall] = []
    texts: list[str] = []
    candidates = getattr(response, "candidates", None) or []
    parts = (
        getattr(getattr(candidates[0], "content", None), "parts", None) or [] if candidates else []
    )
    for i, part in enumerate(parts):
        fc = getattr(part, "function_call", None)
        if fc is not None and getattr(fc, "name", None):
            args = dict(getattr(fc, "args", None) or {})
            tool_calls.append(ToolCall(id=f"gemini-{i}", name=str(fc.name), arguments=args))
        elif getattr(part, "text", None):
            texts.append(part.text)
    meta = getattr(response, "usage_metadata", None)
    finish = getattr(candidates[0], "finish_reason", None) if candidates else None
    return ProviderTurn(
        tool_calls=tool_calls,
        text="\n".join(texts) or None,
        usage=Usage(
            input_tokens=int(getattr(meta, "prompt_token_count", 0) or 0),
            output_tokens=int(getattr(meta, "candidates_token_count", 0) or 0),
        ),
        stop_reason=str(finish) if finish is not None else None,
        raw=None,
    )


class GeminiProvider:
    name = "gemini"
    supports_vision = True

    def __init__(
        self, model: str = DEFAULT_MODEL, *, client: Any = None, api_key: str | None = None
    ) -> None:
        self.model = model
        self.calls = 0
        if client is None:
            key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
            if not key:
                raise ProviderMissingKey("gemini", "GEMINI_API_KEY")
            try:
                from google import genai
            except ImportError as e:
                raise ProviderNotInstalled("gemini", "gemini") from e
            client = genai.Client(api_key=key)
        self.client = client

    def _config(self, system: str, tools: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "system_instruction": system,
            "tools": render_tools(tools),
            "tool_config": {"function_calling_config": {"mode": "ANY"}},
        }

    async def step(
        self, system: str, history: list[Exchange], tools: list[dict[str, Any]]
    ) -> ProviderTurn:
        self.calls += 1
        try:
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=render_contents(history),
                config=self._config(system, tools),
            )
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(f"gemini: {type(e).__name__}: {e}") from e
        return parse_response(response)
