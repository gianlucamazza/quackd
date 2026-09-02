"""The executor is the layer that does not trust the LLM. Every rule gets a test."""

from __future__ import annotations

import asyncio

import pytest

from quackd.duckfile.parser import parse_duck_text
from quackd.duckfile.schema import Budgets, DuckFile
from quackd.safety import (
    Aborted,
    Budget,
    BudgetExceeded,
    ConfirmDenied,
    Executor,
    Heartbeat,
    VerbNotAllowed,
    allow_all,
    deny_all,
)
from quackd.transport.base import DuckState
from quackd.transport.mock import MockTransport
from quackd.verbs.registry import NoParams, Verb, VerbContext, VerbRegistry, VerbResult


def duck(allow: str, confirm: str = "", abort: str = "") -> DuckFile:
    return parse_duck_text(
        f"""---
duck: 0
name: t
description: d
verbs:
  allow: [{allow}]
  confirm: [{confirm}]
success: [x]
abort_when: [{abort}]
---
# Task
x
"""
    )


async def test_allowlist_is_enforced(registry: VerbRegistry, mock_transport: MockTransport) -> None:
    ex = Executor(registry, mock_transport, contract=duck("quack, walk").frontmatter)
    with pytest.raises(VerbNotAllowed):
        await ex.run_verb("kick")
    assert mock_transport.intents == []
    result = await ex.run_verb("quack", {"text": "hi"})
    assert result.ok and mock_transport.intents_of("sound")


async def test_stop_is_always_allowed(
    registry: VerbRegistry, mock_transport: MockTransport
) -> None:
    ex = Executor(registry, mock_transport, contract=duck("quack").frontmatter)
    assert (await ex.run_verb("stop")).ok
    assert mock_transport.stops == 1


async def test_confirm_gate(registry: VerbRegistry, mock_transport: MockTransport) -> None:
    fm = duck("quack, kick", confirm="kick").frontmatter
    ex = Executor(registry, mock_transport, contract=fm, confirm=deny_all)
    with pytest.raises(ConfirmDenied):
        await ex.run_verb("kick")
    assert mock_transport.intents_of("do") == []
    asked: list[tuple[str, dict]] = []

    def yes(name: str, params: dict) -> bool:
        asked.append((name, params))
        return True

    ex.confirm = yes
    assert (await ex.run_verb("kick", {"leg": "left"})).ok
    assert asked == [("kick", {"leg": "left"})]
    assert mock_transport.intents_of("do")[0].params == {"skill": "kick_left"}


async def test_budget_hard_stop(registry: VerbRegistry, mock_transport: MockTransport) -> None:
    budget = Budget(Budgets(max_steps=2), now=mock_transport.now)
    budget.start()
    ex = Executor(registry, mock_transport, contract=duck("quack").frontmatter, budget=budget)
    await ex.run_verb("quack")
    await ex.run_verb("quack")
    with pytest.raises(BudgetExceeded):
        await ex.run_verb("quack")
    assert budget.steps == 2


async def test_budget_minutes_uses_transport_clock(mock_transport: MockTransport) -> None:
    budget = Budget(Budgets(max_minutes=0.1), now=mock_transport.now)
    budget.start()
    budget.check()
    await mock_transport.sleep(7)
    with pytest.raises(BudgetExceeded):
        budget.check()


async def test_dry_run_sends_nothing(registry: VerbRegistry, mock_transport: MockTransport) -> None:
    ex = Executor(
        registry, mock_transport, contract=duck("walk, get_frame").frontmatter, dry_run=True
    )
    result = await ex.run_verb("walk", {"vx": 0.2})
    assert result.ok and result.data.get("dry_run") is True
    assert mock_transport.intents == []
    frame = await ex.run_verb("get_frame")  # read-only verbs still run
    assert frame.ok and "frame captured" in frame.summary


async def test_invalid_params_are_feedback_not_crash(
    registry: VerbRegistry, mock_transport: MockTransport
) -> None:
    ex = Executor(registry, mock_transport, contract=duck("walk").frontmatter)
    result = await ex.run_verb("walk", {"vx": 5.0})
    assert not result.ok and "vx" in result.summary
    assert mock_transport.intents == []


async def test_preconditions_block_unsafe_verbs(registry: VerbRegistry) -> None:
    fallen = MockTransport(states=[DuckState(fallen=True, posture="fallen")])
    ex = Executor(registry, fallen, contract=duck("walk, stand_up").frontmatter)
    result = await ex.run_verb("walk")
    assert not result.ok and "fallen" in result.summary
    assert fallen.intents_of("move") == []


async def test_repeat_failure_abort(registry: VerbRegistry) -> None:
    refusing = MockTransport(refuse_kinds={"do"})
    ex = Executor(
        registry,
        refusing,
        contract=duck("kick", abort="Same verb fails 2 times in a row").frontmatter,
    )
    assert not (await ex.run_verb("kick")).ok
    with pytest.raises(Aborted):
        await ex.run_verb("kick")
    assert ex.abort.is_set()


async def test_battery_abort(registry: VerbRegistry) -> None:
    low = MockTransport(states=[DuckState(battery_percent=10, posture="standing")])
    ex = Executor(registry, low, contract=duck("quack", abort="Battery below 15%").frontmatter)
    with pytest.raises(Aborted):
        await ex.run_verb("quack")


async def test_verb_timeout_stops_the_duck(mock_transport: MockTransport) -> None:
    registry = VerbRegistry()

    async def slow(ctx: VerbContext, _: NoParams) -> VerbResult:
        await asyncio.sleep(1)
        return VerbResult.success("never")

    registry.register(Verb("slow", "slow", slow, timeout_s=0.05))
    ex = Executor(registry, mock_transport, contract=duck("slow").frontmatter)
    result = await ex.run_verb("slow")
    assert not result.ok and "timed out" in result.summary
    assert mock_transport.stops == 1


async def test_buggy_verb_stops_the_duck(mock_transport: MockTransport) -> None:
    registry = VerbRegistry()

    async def boom(ctx: VerbContext, _: NoParams) -> VerbResult:
        raise RuntimeError("kaboom")

    registry.register(Verb("boom", "boom", boom))
    ex = Executor(registry, mock_transport, contract=duck("boom").frontmatter)
    result = await ex.run_verb("boom")
    assert not result.ok and "kaboom" in result.summary
    assert mock_transport.stops == 1


async def test_no_contract_allows_safe_verbs_only(
    registry: VerbRegistry, mock_transport: MockTransport
) -> None:
    registry.register(Verb("nuke", "dangerous", lambda c, p: None, safety_class="dangerous"))  # type: ignore[arg-type]
    ex = Executor(registry, mock_transport, contract=None, confirm=allow_all)
    assert "move" in ex.allowed and "nuke" not in ex.allowed
    assert ex.is_allowed("walk") and not ex.is_allowed("nuke")


async def test_walk_feeds_the_deadman(
    registry: VerbRegistry, mock_transport: MockTransport
) -> None:
    ex = Executor(registry, mock_transport, contract=duck("walk").frontmatter)
    await ex.run_verb("walk", {"vx": 0.1, "duration_s": 1.0})
    moves = mock_transport.intents_of("move")
    assert len(moves) == 10  # re-sent every 100 ms
    assert mock_transport.intents[-1].kind == "stop"


async def test_heartbeat_failure_stops_and_aborts() -> None:
    transport = MockTransport(fail_heartbeat_after=1)
    abort = asyncio.Event()
    hb = Heartbeat(transport, abort, period_s=0.01)
    hb.start()
    await asyncio.wait_for(abort.wait(), timeout=2)
    await hb.stop()
    assert transport.stops >= 1
    assert hb.failure is not None
