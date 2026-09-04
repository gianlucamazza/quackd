"""The deliberation loop, end to end on the mock transport with the scripted provider."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from quackd.agent.loop import RunConfig, run_duck
from quackd.agent.providers.base import Exchange, ProviderTurn, ToolCall
from quackd.agent.providers.fake import FakeProvider
from quackd.agent.transcript import Transcript
from quackd.duckfile.schema import Budgets, DuckFile
from quackd.transport.mock import MockTransport

GOLDEN_HELLO = ["quack", "walk", "quack", "declare_success"]


async def test_hello_world_golden(hello_duck: DuckFile, tmp_path: Path) -> None:
    transport = MockTransport()
    result = await run_duck(
        RunConfig(
            duck=hello_duck,
            provider=FakeProvider.for_duck("hello-world"),
            transport=transport,
            runs_dir=tmp_path,
        )
    )
    assert result.outcome == "success", result.reason
    assert result.steps == 3 and result.llm_calls == 4
    events = Transcript.read(result.run_dir / "transcript.jsonl")
    kinds = [e["kind"] for e in events]
    assert kinds[0] == "run_start" and kinds[-1] == "run_end"
    assert {"observation", "llm", "verb", "declare"} <= set(kinds)
    calls = [tc["name"] for e in events if e["kind"] == "llm" for tc in e["tool_calls"]]
    assert calls == GOLDEN_HELLO
    assert (result.run_dir / "summary.json").exists()
    assert [i.kind for i in transport.intents if i.kind != "stop"] == ["sound"] + ["move"] * 10 + [
        "sound"
    ]
    assert transport.intents[-1].kind == "stop"  # the loop always stops the duck on exit
    assert not transport.connected  # and closes the transport
    assert (result.run_dir / "frames").is_dir()


class NoToolProvider:
    name = "no-tool"
    model = "x"
    supports_vision = False

    async def step(
        self, system: str, history: list[Exchange], tools: list[dict[str, Any]]
    ) -> ProviderTurn:
        return ProviderTurn(tool_calls=[], text="I would rather talk.")


class ClockAdvancingProvider:
    name = "clock-advancing"
    model = "test"
    supports_vision = False

    def __init__(
        self, transport: MockTransport, seconds: float, declaration: str = "declare_success"
    ) -> None:
        self.transport = transport
        self.seconds = seconds
        self.declaration = declaration

    async def step(
        self, system: str, history: list[Exchange], tools: list[dict[str, Any]]
    ) -> ProviderTurn:
        await self.transport.sleep(self.seconds)
        return ProviderTurn(
            tool_calls=[ToolCall(name=self.declaration, arguments={"reason": "provider response"})]
        )


class PassiveAffectiveSpy:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def observe(self, kind: str, **_kwargs: Any) -> dict[str, Any]:
        self.events.append(kind)
        return {"valence": 0.0, "arousal": 0.1, "dominance": 0.5, "mood": {}}

    def summary(self) -> dict[str, Any]:
        return {"valence": 0.0, "arousal": 0.1, "dominance": 0.5, "mood": {}}

    def close(self) -> None:
        pass


async def test_affective_runtime_is_passive_in_observation_loop(
    hello_duck: DuckFile, tmp_path: Path
) -> None:
    affective = PassiveAffectiveSpy()
    result = await run_duck(
        RunConfig(
            duck=hello_duck,
            provider=FakeProvider.for_duck("hello-world"),
            transport=MockTransport(),
            runs_dir=tmp_path,
            affective=affective,
        )
    )
    assert result.ok
    assert "observation" not in affective.events
    assert affective.events == ["verb_success"] * 3 + ["success"]
    events = Transcript.read(result.run_dir / "transcript.jsonl")
    assert all(
        "affective" not in event["features"] for event in events if event["kind"] == "observation"
    )


async def test_affective_context_uses_cached_event_snapshot(
    hello_duck: DuckFile, tmp_path: Path
) -> None:
    affective = PassiveAffectiveSpy()
    result = await run_duck(
        RunConfig(
            duck=hello_duck,
            provider=FakeProvider.for_duck("hello-world"),
            transport=MockTransport(),
            runs_dir=tmp_path,
            affective=affective,
            affective_context=True,
        )
    )
    assert result.ok
    assert affective.events == ["verb_success"] * 3 + ["success"]
    events = Transcript.read(result.run_dir / "transcript.jsonl")
    observations = [event for event in events if event["kind"] == "observation"]
    assert observations and all("affective" in event["features"] for event in observations)


async def test_no_tool_call_is_reprompted_once_then_failure(
    hello_duck: DuckFile, tmp_path: Path
) -> None:
    result = await run_duck(
        RunConfig(
            duck=hello_duck, provider=NoToolProvider(), transport=MockTransport(), runs_dir=tmp_path
        )
    )
    assert result.outcome == "failure" and "no tool call" in result.reason
    assert result.llm_calls == 2


@pytest.mark.parametrize("declaration", ["declare_success", "declare_failure"])
async def test_time_budget_wins_over_late_declaration(
    hello_duck: DuckFile, tmp_path: Path, declaration: str
) -> None:
    hello_duck.frontmatter.budgets = Budgets(max_minutes=0.1)
    transport = MockTransport()
    result = await run_duck(
        RunConfig(
            duck=hello_duck,
            provider=ClockAdvancingProvider(transport, 7, declaration),
            transport=transport,
            runs_dir=tmp_path,
        )
    )

    assert result.outcome == "budget"
    assert result.reason == "max_minutes (0.1) exceeded"
    assert transport.now() == 7
    events = Transcript.read(result.run_dir / "transcript.jsonl")
    kinds = [event["kind"] for event in events]
    assert "llm" in kinds and "declare" not in kinds


async def test_provider_response_before_time_budget_is_processed(
    hello_duck: DuckFile, tmp_path: Path
) -> None:
    hello_duck.frontmatter.budgets = Budgets(max_minutes=0.1, max_llm_calls=1)
    transport = MockTransport()
    result = await run_duck(
        RunConfig(
            duck=hello_duck,
            provider=ClockAdvancingProvider(transport, 5),
            transport=transport,
            runs_dir=tmp_path,
        )
    )

    assert result.outcome == "success"
    assert result.reason == "provider response"
    assert result.llm_calls == 1
    assert transport.now() == 5
    events = Transcript.read(result.run_dir / "transcript.jsonl")
    assert "declare" in [event["kind"] for event in events]


async def test_budget_ends_the_run(hello_duck: DuckFile, tmp_path: Path) -> None:
    forever = FakeProvider(script=[ToolCall(name="quack", arguments={})])
    result = await run_duck(
        RunConfig(
            duck=hello_duck,
            provider=forever,
            transport=MockTransport(),
            runs_dir=tmp_path,
            max_steps=2,
        )
    )
    assert result.outcome == "budget" and "max_steps" in result.reason
    assert result.steps == 2


async def test_disallowed_verb_is_feedback(hello_duck: DuckFile, tmp_path: Path) -> None:
    naughty = FakeProvider(
        script=[
            ToolCall(name="kick", arguments={}),
            ToolCall(name="declare_failure", arguments={"reason": "refused"}),
        ]
    )
    transport = MockTransport()
    result = await run_duck(
        RunConfig(duck=hello_duck, provider=naughty, transport=transport, runs_dir=tmp_path)
    )
    assert result.outcome == "failure"
    events = Transcript.read(result.run_dir / "transcript.jsonl")
    verb_events = [e for e in events if e["kind"] == "verb"]
    assert verb_events[0]["name"] == "kick" and not verb_events[0]["ok"]
    assert "allowlist" in verb_events[0]["summary"]
    assert transport.intents_of("do") == []


async def test_heartbeat_failure_aborts_the_run(hello_duck: DuckFile, tmp_path: Path) -> None:
    transport = MockTransport(fail_heartbeat_after=0)
    forever = FakeProvider(script=[ToolCall(name="walk", arguments={"duration_s": 2.0})])
    result = await run_duck(
        RunConfig(
            duck=hello_duck,
            provider=forever,
            transport=transport,
            runs_dir=tmp_path,
            heartbeat_period_s=0.001,
        )
    )
    assert result.outcome == "aborted"
    assert "heartbeat" in result.reason
    assert transport.stops >= 1


async def test_dry_run_touches_nothing(hello_duck: DuckFile, tmp_path: Path) -> None:
    transport = MockTransport()
    result = await run_duck(
        RunConfig(
            duck=hello_duck,
            provider=FakeProvider.for_duck("hello-world"),
            transport=transport,
            runs_dir=tmp_path,
            dry_run=True,
        )
    )
    assert result.outcome == "success"
    assert [i.kind for i in transport.intents] == ["stop"]  # only the final safety stop
