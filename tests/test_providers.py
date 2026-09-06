"""Provider request/response mapping against stubbed SDK clients. No network, no SDKs."""

from __future__ import annotations

import json
from types import SimpleNamespace as NS
from typing import Any

import pytest

from quackd.agent.providers.anthropic import AnthropicProvider
from quackd.agent.providers.anthropic import render_messages as a_messages
from quackd.agent.providers.base import Decision, Exchange, Observation, ProviderError, ToolCall
from quackd.agent.providers.deepseek import DeepSeekProvider
from quackd.agent.providers.factory import make_provider
from quackd.agent.providers.gemini import GeminiProvider, clean_schema, render_contents
from quackd.agent.providers.grok import GrokProvider
from quackd.agent.providers.openai import OpenAIProvider
from quackd.agent.providers.openai import render_messages as o_messages

PNG = b"\x89PNG\r\n\x1a\nfake"
TOOLS = [
    {
        "name": "walk",
        "description": "Walk.",
        "input_schema": {
            "type": "object",
            "properties": {"vx": {"type": "number", "default": 0.1, "title": "Vx"}},
            "additionalProperties": False,
        },
    }
]


def history() -> list[Exchange]:
    first = Exchange(
        observation=Observation(text="obs 1", image_png=PNG),
        decision=Decision(
            tool_call=ToolCall(id="call-1", name="walk", arguments={"vx": 0.1}), text="going"
        ),
    )
    second = Exchange(
        observation=Observation(text="obs 2 (result)", image_png=PNG, tool_call_id="call-1")
    )
    return [first, second]


# ── anthropic ───────────────────────────────────────────────────────────────────────────


class FakeAnthropic:
    def __init__(self, response: Any, *, beta_ok: bool = True) -> None:
        self.kwargs: dict[str, Any] = {}
        self.beta_used = False
        self._response = response

        async def plain(**kwargs: Any) -> Any:
            self.kwargs = kwargs
            return self._response

        async def beta(**kwargs: Any) -> Any:
            if not beta_ok:
                raise TypeError("unexpected keyword argument 'fallbacks'")
            self.beta_used = True
            self.kwargs = kwargs
            return self._response

        self.messages = NS(create=plain)
        self.beta = NS(messages=NS(create=beta))


def anthropic_response(*blocks: Any, stop_reason: str = "tool_use") -> Any:
    return NS(
        content=list(blocks),
        stop_reason=stop_reason,
        usage=NS(input_tokens=120, output_tokens=30),
        stop_details=None,
    )


async def test_anthropic_request_and_response_mapping() -> None:
    client = FakeAnthropic(
        anthropic_response(
            NS(
                type="thinking",
                thinking="",
                model_dump=lambda: {"type": "thinking", "thinking": "", "signature": "sig"},
            ),
            NS(
                type="tool_use",
                id="toolu_1",
                name="walk",
                input={"vx": 0.2},
                model_dump=lambda: {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "walk",
                    "input": {"vx": 0.2},
                },
            ),
        )
    )
    p = AnthropicProvider(model="claude-opus-5", client=client, effort="medium")
    turn = await p.step("SYS", history(), TOOLS)
    assert client.beta_used
    kw = client.kwargs
    assert kw["model"] == "claude-opus-5" and kw["system"] == "SYS"
    assert kw["tool_choice"] == {"type": "any", "disable_parallel_tool_use": True}
    assert kw["output_config"] == {"effort": "medium"}
    assert "thinking" not in kw  # adaptive by default on Opus 5
    assert kw["betas"] == ["server-side-fallback-2026-07-01"] and kw["fallbacks"] == "default"
    assert kw["tools"][0]["input_schema"]["additionalProperties"] is False
    msgs = kw["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert msgs[0]["content"][0]["type"] == "image" and msgs[0]["content"][1]["text"] == "obs 1"
    assert msgs[1]["content"][-1] == {
        "type": "tool_use",
        "id": "call-1",
        "name": "walk",
        "input": {"vx": 0.1},
    }
    result = msgs[2]["content"][0]
    assert result["type"] == "tool_result" and result["tool_use_id"] == "call-1"
    assert [c["type"] for c in result["content"]] == ["text", "image"]
    assert turn.tool_calls == [ToolCall(id="toolu_1", name="walk", arguments={"vx": 0.2})]
    assert turn.usage.input_tokens == 120 and turn.stop_reason == "tool_use"
    assert turn.raw[0]["type"] == "thinking"  # replayed verbatim next turn


def test_anthropic_replays_raw_blocks() -> None:
    ex = Exchange(
        observation=Observation(text="o"),
        decision=Decision(
            tool_call=ToolCall(id="t", name="walk"),
            raw=[
                {"type": "thinking", "thinking": "", "signature": "s"},
                {"type": "tool_use", "id": "t", "name": "walk", "input": {}},
            ],
        ),
    )
    msgs = a_messages([ex])
    assert msgs[1]["content"][0]["type"] == "thinking"


async def test_anthropic_falls_back_to_plain_endpoint_on_old_sdk() -> None:
    client = FakeAnthropic(
        anthropic_response(NS(type="tool_use", id="1", name="walk", input={})), beta_ok=False
    )
    p = AnthropicProvider(client=client)
    await p.step("S", history()[:1], TOOLS)
    assert not client.beta_used and p.fallbacks is False
    assert "fallbacks" not in client.kwargs


async def test_anthropic_refusal_yields_no_tool_call() -> None:
    resp = anthropic_response(
        NS(type="text", text="no", model_dump=lambda: {"type": "text", "text": "no"}),
        stop_reason="refusal",
    )
    resp.stop_details = NS(category="x", explanation="policy")
    p = AnthropicProvider(client=FakeAnthropic(resp))
    turn = await p.step("S", history()[:1], TOOLS)
    assert turn.tool_calls == [] and turn.stop_reason == "refusal" and "policy" in (turn.text or "")


async def test_anthropic_errors_are_classified() -> None:
    class RateLimitError(Exception):
        response = NS(headers={"retry-after": "7"})

    async def boom(**_: Any) -> Any:
        raise RateLimitError("429")

    client = NS(messages=NS(create=boom), beta=NS(messages=NS(create=boom)))
    with pytest.raises(ProviderError, match=r"rate limited \(retry-after 7s\)"):
        await AnthropicProvider(client=client).step("S", history()[:1], TOOLS)


# ── openai / grok ───────────────────────────────────────────────────────────────────────


class FakeOpenAI:
    def __init__(self, response: Any) -> None:
        self.kwargs: dict[str, Any] = {}

        async def create(**kwargs: Any) -> Any:
            self.kwargs = kwargs
            return response

        self.chat = NS(completions=NS(create=create))


class FakeResponses:
    def __init__(self, *, arguments: str = '{"vx": 0.3}') -> None:
        self.kwargs: dict[str, Any] = {}
        self._arguments = arguments

        async def create(**kwargs: Any) -> Any:
            self.kwargs = kwargs
            return NS(
                output=[
                    NS(
                        type="function_call",
                        call_id="call_9",
                        name="walk",
                        arguments=self._arguments,
                    )
                ],
                output_text=None,
                usage=NS(input_tokens=50, output_tokens=9),
                status="completed",
            )

        self.create = create


def openai_response(name: str, args: str, content: str | None = None) -> Any:
    tc = NS(id="call_9", function=NS(name=name, arguments=args))
    return NS(
        choices=[NS(message=NS(content=content, tool_calls=[tc]), finish_reason="tool_calls")],
        usage=NS(prompt_tokens=50, completion_tokens=9),
    )


async def test_openai_request_and_response_mapping() -> None:
    client = FakeOpenAI(openai_response("walk", json.dumps({"vx": 0.3})))
    p = OpenAIProvider(model="gpt-5", client=client)
    turn = await p.step("SYS", history(), TOOLS)
    kw = client.kwargs
    assert kw["tool_choice"] == "required" and kw["parallel_tool_calls"] is False
    assert kw["tools"][0]["type"] == "function" and kw["tools"][0]["function"]["name"] == "walk"
    roles = [m["role"] for m in kw["messages"]]
    assert roles == ["system", "user", "assistant", "tool", "user"]  # image after tool result
    assert kw["messages"][2]["tool_calls"][0]["function"]["arguments"] == '{"vx": 0.1}'
    assert kw["messages"][3]["tool_call_id"] == "call-1"
    assert kw["messages"][4]["content"][1]["type"] == "image_url"
    assert turn.tool_calls == [ToolCall(id="call_9", name="walk", arguments={"vx": 0.3})]
    assert turn.usage.input_tokens == 50 and turn.stop_reason == "tool_calls"


async def test_deepseek_uses_chat_tools_without_required_tool_choice() -> None:
    client = FakeOpenAI(openai_response("walk", json.dumps({"vx": 0.3})))
    turn = await DeepSeekProvider(client=client).step("SYS", history(), TOOLS)
    assert client.kwargs["tool_choice"] == "auto"
    assert client.kwargs["parallel_tool_calls"] is False
    assert turn.tool_calls == [ToolCall(id="call_9", name="walk", arguments={"vx": 0.3})]


async def test_modern_openai_tool_calls_use_responses_api() -> None:
    responses = FakeResponses()
    client = NS(responses=responses)
    turn = await OpenAIProvider(model="gpt-5.6-terra", client=client).step("SYS", history(), TOOLS)
    assert responses.kwargs["reasoning"] == {"effort": "none"}
    assert responses.kwargs["tools"][0]["type"] == "function"
    assert turn.tool_calls == [ToolCall(id="call_9", name="walk", arguments={"vx": 0.3})]


async def test_openai_bad_json_arguments_do_not_crash() -> None:
    p = OpenAIProvider(model="gpt-5", client=FakeOpenAI(openai_response("walk", "{not json")))
    turn = await p.step("S", history()[:1], TOOLS)
    assert "_unparsed" in turn.tool_calls[0].arguments


def test_openai_history_without_images_has_no_extra_user_turn() -> None:
    ex = Exchange(
        observation=Observation(text="o"),
        decision=Decision(tool_call=ToolCall(id="c", name="stop")),
    )
    msgs = o_messages("S", [ex, Exchange(observation=Observation(text="r", tool_call_id="c"))])
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "tool"]


def test_grok_is_openai_with_xai_endpoint() -> None:
    p = GrokProvider(client=FakeOpenAI(None))
    assert p.name == "grok" and p.base_url == "https://api.x.ai/v1" and p.model == "grok-4"


def test_deepseek_is_openai_compatible_with_current_endpoint() -> None:
    p = DeepSeekProvider(client=FakeOpenAI(None))
    assert (
        p.name == "deepseek"
        and p.base_url == "https://api.deepseek.com"
        and p.key_env == "DEEPSEEK_API_KEY"
        and p.model == "deepseek-v4-pro"
        and not p.supports_vision
        and p.tool_choice == "auto"
    )


def test_missing_keys_are_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="OPENAI_API_KEY"):
        OpenAIProvider()
    with pytest.raises(ProviderError, match="XAI_API_KEY"):
        GrokProvider()
    with pytest.raises(ProviderError, match="GEMINI_API_KEY"):
        GeminiProvider()
    with pytest.raises(ProviderError, match="DEEPSEEK_API_KEY"):
        DeepSeekProvider()


# ── gemini ──────────────────────────────────────────────────────────────────────────────


class FakeGemini:
    def __init__(self, response: Any) -> None:
        self.kwargs: dict[str, Any] = {}

        async def generate_content(**kwargs: Any) -> Any:
            self.kwargs = kwargs
            return response

        self.aio = NS(models=NS(generate_content=generate_content))


async def test_gemini_request_and_response_mapping() -> None:
    part = NS(function_call=NS(name="walk", args={"vx": 0.25}), text=None)
    response = NS(
        candidates=[NS(content=NS(parts=[part]), finish_reason="STOP")],
        usage_metadata=NS(prompt_token_count=70, candidates_token_count=12),
    )
    client = FakeGemini(response)
    turn = await GeminiProvider(client=client).step("SYS", history(), TOOLS)
    kw = client.kwargs
    assert kw["model"] == "gemini-2.5-pro"
    assert kw["config"]["system_instruction"] == "SYS"
    assert kw["config"]["tool_config"] == {"function_calling_config": {"mode": "ANY"}}
    decl = kw["config"]["tools"][0]["function_declarations"][0]
    assert decl["name"] == "walk"
    assert "additionalProperties" not in decl["parameters"]
    assert "title" not in decl["parameters"]["properties"]["vx"]
    contents = kw["contents"]
    assert [c["role"] for c in contents] == ["user", "model", "user"]
    assert contents[1]["parts"][-1]["function_call"] == {"name": "walk", "args": {"vx": 0.1}}
    assert contents[2]["parts"][0]["function_response"]["name"] == "walk"
    assert contents[2]["parts"][1]["inline_data"]["mime_type"] == "image/png"
    assert turn.tool_calls == [ToolCall(id="gemini-0", name="walk", arguments={"vx": 0.25})]
    assert turn.usage.input_tokens == 70


def test_gemini_clean_schema_is_recursive() -> None:
    schema = {
        "type": "object",
        "title": "T",
        "properties": {"a": {"type": "array", "items": {"default": 1, "type": "integer"}}},
    }
    cleaned = clean_schema(schema)
    assert "title" not in cleaned and "default" not in cleaned["properties"]["a"]["items"]


def test_gemini_first_turn_has_no_function_response() -> None:
    contents = render_contents([Exchange(observation=Observation(text="hi", tool_call_id="x"))])
    assert contents[0]["parts"][0] == {"text": "hi"}


# ── factory ─────────────────────────────────────────────────────────────────────────────


def test_factory_fake_and_unknown() -> None:
    assert make_provider("fake", duck_name="hello-world").name == "fake"
    with pytest.raises(ProviderError, match="unknown provider"):
        make_provider("hal")


def test_factory_reports_missing_extra_or_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ProviderError):
        make_provider("openai")
