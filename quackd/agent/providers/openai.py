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

DEFAULT_MODEL = "gpt-5.6-terra"


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


def render_responses_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "name": t["name"],
            "description": t["description"],
            "parameters": t["input_schema"],
        }
        for t in tools
    ]


def render_response_input(history: list[Exchange]) -> list[dict[str, Any]]:
    """Render vendor-neutral exchanges as Responses API input items."""
    items: list[dict[str, Any]] = []
    for ex in history:
        obs = ex.observation
        if obs.tool_call_id:
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": obs.tool_call_id,
                    "output": obs.text,
                }
            )
            if obs.image_png:
                items.append(
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": "Current camera frame:"},
                            {
                                "type": "input_image",
                                "image_url": _image_part(obs.image_png)["image_url"]["url"],
                            },
                        ],
                    }
                )
        else:
            content: list[dict[str, Any]] = [{"type": "input_text", "text": obs.text}]
            if obs.image_png:
                content.append(
                    {
                        "type": "input_image",
                        "image_url": _image_part(obs.image_png)["image_url"]["url"],
                    }
                )
            items.append({"role": "user", "content": content})
        if ex.decision is not None:
            tc = ex.decision.tool_call
            items.append(
                {
                    "type": "function_call",
                    "call_id": tc.id,
                    "name": tc.name,
                    "arguments": json.dumps(tc.arguments),
                }
            )
    return items


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


def parse_responses_response(response: Any) -> ProviderTurn:
    tool_calls: list[ToolCall] = []
    texts: list[str] = []
    for item in getattr(response, "output", None) or []:
        kind = getattr(item, "type", None)
        if kind == "function_call":
            raw_args = getattr(item, "arguments", "{}")
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            except (TypeError, json.JSONDecodeError):
                args = {"_unparsed": raw_args}
            tool_calls.append(
                ToolCall(
                    id=str(getattr(item, "call_id", "")),
                    name=str(getattr(item, "name", "")),
                    arguments=args,
                )
            )
        elif kind == "message":
            for content in getattr(item, "content", None) or []:
                if getattr(content, "type", None) == "output_text":
                    texts.append(str(getattr(content, "text", "")))
    usage = getattr(response, "usage", None)
    return ProviderTurn(
        tool_calls=tool_calls,
        text=getattr(response, "output_text", None) or "\n".join(texts) or None,
        usage=Usage(
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        ),
        stop_reason=getattr(response, "status", None),
        raw=None,
    )


class OpenAIProvider:
    """OpenAI's own API. Subclasses (Grok, the local servers) only change the class knobs."""

    name = "openai"
    supports_vision = True
    key_env = "OPENAI_API_KEY"
    base_url: str | None = None
    default_tool_choice: str | None = "required"
    """`required` forces a call on OpenAI. `auto` for servers that reject `required`,
    `none` to omit the field entirely."""
    send_parallel_flag = True
    """OpenAI accepts `parallel_tool_calls=False`. Some local servers 400 on unknown fields."""
    prompt_hint = ""
    """Extra system-prompt text a provider wants (the local one explains the JSON fallback)."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        client: Any = None,
        api_key: str | None = None,
        base_url: str | None = None,
        tool_choice: str | None = None,
        vision: bool | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        self.model = model
        self.calls = 0
        self.reasoning_effort = reasoning_effort
        if base_url is not None:
            self.base_url = base_url
        if vision is not None:
            self.supports_vision = vision
        self.tool_choice = tool_choice if tool_choice is not None else self.default_tool_choice
        if client is None:
            import os

            key = api_key or os.environ.get(self.key_env) or self._fallback_key()
            if not key:
                raise ProviderMissingKey(self.name, self.key_env)
            try:
                from openai import AsyncOpenAI
            except ImportError as e:
                extra = "grok" if self.name == "grok" else "openai"
                raise ProviderNotInstalled(self.name, extra) from e
            client = AsyncOpenAI(api_key=key, base_url=self.base_url)
        self.client = client

    def _fallback_key(self) -> str | None:
        """What to use when no key is configured. Cloud: nothing (error). Local: a dummy."""
        return None

    def _params(
        self, system: str, history: list[Exchange], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": self.model,
            "messages": render_messages(system, history),
            "tools": render_tools(tools),
        }
        if self.tool_choice and self.tool_choice != "none":
            params["tool_choice"] = self.tool_choice
        if self.send_parallel_flag:
            params["parallel_tool_calls"] = False
        # The current gpt-5.6 Chat Completions surface requires reasoning to be explicitly
        # disabled when function tools are used. Reasoning-enabled runs need Responses API.
        if self.name == "openai" and self.model.startswith("gpt-5.6"):
            params["reasoning_effort"] = "none"
        return params

    def _responses_params(
        self, system: str, history: list[Exchange], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": self.model,
            "instructions": system,
            "input": render_response_input(history),
            "tools": render_responses_tools(tools),
            "parallel_tool_calls": False,
        }
        if self.tool_choice == "required":
            params["tool_choice"] = "required"
        effort = self.reasoning_effort
        if effort is None and self.model.startswith("gpt-5.6"):
            effort = "high" if self.model.endswith("-sol") else "none"
        if effort is not None:
            params["reasoning"] = {"effort": effort}
        return params

    def _fallback(self, turn: ProviderTurn, tools: list[dict[str, Any]]) -> ProviderTurn:
        """Hook for providers that can rescue a tool call from plain text. Base: nothing."""
        return turn

    async def step(
        self, system: str, history: list[Exchange], tools: list[dict[str, Any]]
    ) -> ProviderTurn:
        self.calls += 1
        try:
            if self.name == "openai" and self.model.startswith("gpt-5.6"):
                response = await self.client.responses.create(
                    **self._responses_params(system, history, tools)
                )
                turn = parse_responses_response(response)
            else:
                response = await self.client.chat.completions.create(
                    **self._params(system, history, tools)
                )
                turn = parse_response(response)
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(f"{self.name}: {type(e).__name__}: {e}") from e
        if not turn.tool_calls:
            turn = self._fallback(turn, tools)
        return turn
