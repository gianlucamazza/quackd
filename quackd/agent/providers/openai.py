"""OpenAI as the duck's brain, via the `openai` SDK (optional extra). Also the base for Grok.

Chat Completions with function tools, `tool_choice="required"` and
`parallel_tool_calls=False` for one call per turn. Tool results go back as `tool` messages;
because a `tool` message cannot carry an image, the frame follows in a `user` message.
"""

from __future__ import annotations

import base64
import json
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

DEFAULT_MODEL = "gpt-5"


def _image_part(png: bytes) -> dict[str, Any]:
    data = base64.standard_b64encode(png).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{data}"}}


def render_messages(system: str, history: list[Exchange]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for ex in history:
        obs = ex.observation
        if obs.tool_call_id:
            messages.append({"role": "tool", "tool_call_id": obs.tool_call_id, "content": obs.text})
            if obs.image_png:
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Current camera frame:"},
                            _image_part(obs.image_png),
                        ],
                    }
                )
        else:
            parts: list[dict[str, Any]] = [{"type": "text", "text": obs.text}]
            if obs.image_png:
                parts.append(_image_part(obs.image_png))
            messages.append({"role": "user", "content": parts})
        if ex.decision is not None:
            tc = ex.decision.tool_call
            messages.append(
                {
                    "role": "assistant",
                    "content": ex.decision.text,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                        }
                    ],
                }
            )
    return messages


def render_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in tools
    ]


def parse_response(response: Any) -> ProviderTurn:
    choice = response.choices[0]
    message = choice.message
    tool_calls: list[ToolCall] = []
    for tc in getattr(message, "tool_calls", None) or []:
        fn = tc.function
        raw_args = fn.arguments
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args or {})
        except json.JSONDecodeError:
            args = {"_unparsed": raw_args}
        tool_calls.append(ToolCall(id=str(tc.id), name=str(fn.name), arguments=args))
    usage = getattr(response, "usage", None)
    return ProviderTurn(
        tool_calls=tool_calls,
        text=getattr(message, "content", None) or None,
        usage=Usage(
            input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
        ),
        stop_reason=getattr(choice, "finish_reason", None),
        raw=None,
    )


class OpenAIProvider:
    name = "openai"
    supports_vision = True
    key_env = "OPENAI_API_KEY"
    base_url: str | None = None

    def __init__(
        self, model: str = DEFAULT_MODEL, *, client: Any = None, api_key: str | None = None
    ) -> None:
        self.model = model
        self.calls = 0
        if client is None:
            import os

            key = api_key or os.environ.get(self.key_env)
            if not key:
                raise ProviderMissingKey(self.name, self.key_env)
            try:
                from openai import AsyncOpenAI
            except ImportError as e:
                raise ProviderNotInstalled(
                    self.name, "openai" if self.name == "openai" else "grok"
                ) from e
            client = AsyncOpenAI(api_key=key, base_url=self.base_url)
        self.client = client

    def _params(
        self, system: str, history: list[Exchange], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": render_messages(system, history),
            "tools": render_tools(tools),
            "tool_choice": "required",
            "parallel_tool_calls": False,
        }

    async def step(
        self, system: str, history: list[Exchange], tools: list[dict[str, Any]]
    ) -> ProviderTurn:
        self.calls += 1
        try:
            response = await self.client.chat.completions.create(
                **self._params(system, history, tools)
            )
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(f"{self.name}: {type(e).__name__}: {e}") from e
        return parse_response(response)
