"""A scripted LLM, so the whole system can be tested — and demoed — with no API key.

Two modes: a fixed script of tool calls, or a *strategy* (a function of the structured
observation) that plays the starter ducks well enough to prove the loop closes. The
strategies are intentionally dumb rules; the point is that the same verbs, executor and
transcript run whether the pilot is a rule or a frontier model.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from quackd.agent.providers.base import Exchange, Observation, ProviderTurn, ToolCall, Usage

Strategy = Callable[[Observation, int, list[Exchange]], ToolCall]


def _detections(obs: Observation, label: str) -> list[dict[str, Any]]:
    return [d for d in obs.features.get("detections", []) if d.get("label") == label]


def _last(obs: Observation) -> dict[str, Any]:
    return obs.features.get("last_result") or {}


def _count_calls(history: list[Exchange], name: str) -> int:
    return sum(1 for ex in history if ex.decision and ex.decision.tool_call.name == name)


def hello_world_strategy(obs: Observation, step: int, history: list[Exchange]) -> ToolCall:
    script = [
        ToolCall(name="quack", arguments={"text": "hello!"}),
        ToolCall(name="walk", arguments={"vx": 0.1, "duration_s": 1.0}),
        ToolCall(name="quack", arguments={"text": "done"}),
        ToolCall(name="declare_success", arguments={"reason": "quacked and walked one step"}),
    ]
    return script[min(step, len(script) - 1)]


def find_and_kick_strategy(obs: Observation, step: int, history: list[Exchange]) -> ToolCall:
    last = _last(obs)
    last_name = last.get("verb")
    if last_name == "kick" and last.get("ok"):
        moved = (last.get("data") or {}).get("ball_moved_m")
        if moved is not None and moved >= 0.3:
            if _count_calls(history, "quack") == 0:
                return ToolCall(name="quack", arguments={"text": "yay, got it!"})
        elif moved is None:
            return ToolCall(
                name="declare_success", arguments={"reason": "kicked; no displacement telemetry"}
            )
    if last_name == "quack" and _count_calls(history, "kick") > 0:
        return ToolCall(name="declare_success", arguments={"reason": "ball displaced by the kick"})
    balls = _detections(obs, "ball")
    if not balls:
        if (
            _count_calls(history, "search_scan") >= 3
            and last_name == "search_scan"
            and not last.get("ok")
        ):
            return ToolCall(
                name="declare_failure", arguments={"reason": "no ball found after repeated scans"}
            )
        return ToolCall(name="search_scan", arguments={"target": "ball"})
    dist = balls[0].get("est_distance_m")
    bearing = abs(balls[0].get("bearing_deg") or 0.0)
    if dist is not None and dist <= 0.3 and bearing < 30:
        return ToolCall(name="kick", arguments={"leg": "right"})
    return ToolCall(name="walk_to", arguments={"target": "ball", "stop_distance": 0.22})


def patrol_strategy(obs: Observation, step: int, history: list[Exchange]) -> ToolCall:
    people = _detections(obs, "person") + _detections(obs, "pet")
    last = _last(obs)
    if people and last.get("verb") != "quack":
        return ToolCall(name="quack", arguments={"text": "quack quack! someone is here"})
    legs = _count_calls(history, "walk")
    if legs >= 3:
        return ToolCall(name="declare_success", arguments={"reason": "patrol lap complete"})
    if step % 2 == 0:
        return ToolCall(name="walk", arguments={"vx": 0.12, "duration_s": 2.0})
    return ToolCall(name="search_scan", arguments={"target": "person", "max_steps": 4})


def generic_strategy(obs: Observation, step: int, history: list[Exchange]) -> ToolCall:
    allowed = obs.features.get("allowed", [])
    if step == 0 and "quack" in allowed:
        return ToolCall(name="quack", arguments={"text": "hello"})
    if step < 2 and "search_scan" in allowed:
        return ToolCall(name="search_scan", arguments={})
    return ToolCall(
        name="declare_success", arguments={"reason": "scripted pilot: nothing more to do"}
    )


STRATEGIES: dict[str, Strategy] = {
    "hello-world": hello_world_strategy,
    "find-and-kick": find_and_kick_strategy,
    "patrol-and-quack": patrol_strategy,
}


class FakeProvider:
    name = "fake"
    supports_vision = False

    def __init__(
        self,
        strategy: Strategy | None = None,
        script: list[ToolCall] | None = None,
        model: str = "scripted",
    ) -> None:
        self.model = model
        self._strategy = strategy
        self._script = script
        self.calls = 0

    @classmethod
    def for_duck(cls, duck_name: str) -> FakeProvider:
        return cls(
            strategy=STRATEGIES.get(duck_name, generic_strategy), model=f"scripted:{duck_name}"
        )

    async def step(
        self, system: str, history: list[Exchange], tools: list[dict[str, Any]]
    ) -> ProviderTurn:
        obs = history[-1].observation
        decisions = sum(1 for ex in history if ex.decision is not None)
        if self._script is not None:
            call = self._script[min(decisions, len(self._script) - 1)]
        elif self._strategy is not None:
            call = self._strategy(obs, decisions, history)
        else:
            call = ToolCall(
                name="declare_failure", arguments={"reason": "fake provider has no strategy"}
            )
        self.calls += 1
        call = call.model_copy(update={"id": f"fake-{self.calls}"})
        usage = Usage(input_tokens=len(system) // 4 + len(obs.text) // 4, output_tokens=16)
        return ProviderTurn(tool_calls=[call], text=None, usage=usage, stop_reason="tool_use")
