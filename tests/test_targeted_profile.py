import math

import pytest
from typer.testing import CliRunner

from quackd.agent.loop import RunConfig, run_duck
from quackd.agent.providers.base import ProviderTurn, ToolCall
from quackd.cli import app
from quackd.duckfile.parser import load_duck
from quackd.perception.color_blob import ColorBlobDetector
from quackd.sim2d.profiles import advance_targeted, configure_targeted
from quackd.sim2d.world import World
from quackd.transport.sim2d import Sim2DTransport


class FetchReference:
    name = "reference"
    model = "fetch-reference-v1"
    supports_vision = False

    async def step(self, system, history, tools):
        state = history[-1].observation.features["state"]
        last = history[-1].observation.features.get("last_result")
        if state["holding"]:
            name, params = (
                ("declare_success", {"reason": "returned"})
                if last and last["verb"] == "walk"
                else ("walk", {"vx": -0.1, "duration_s": 6})
            )
        elif last and last["verb"] == "walk_to" and last["ok"]:
            name, params = "grab", {}
        elif last and last["verb"] == "grab" and not last["ok"]:
            name, params = "walk", {"vy": 0.05, "duration_s": 0.5}
        else:
            name, params = "walk_to", {"target": "ball", "stop_distance": 0.15}
        return ProviderTurn(tool_calls=[ToolCall(name=name, arguments=params)])


class FollowReference(FetchReference):
    model = "follow-reference-v1"

    def __init__(self):
        self.previous = None
        self.legs = 0

    async def step(self, system, history, tools):
        features = history[-1].observation.features
        state = features["state"]
        point = (state["x"], state["y"])
        visible = any(d["label"] == "person" for d in features["detections"])
        if self.previous is not None and math.dist(point, self.previous) > 0.01 and visible:
            self.legs += 1
        self.previous = point
        name, params = (
            ("declare_success", {"reason": "three moving approaches"})
            if self.legs >= 3
            else ("walk_to", {"target": "person", "stop_distance": 0.5})
        )
        return ProviderTurn(tool_calls=[ToolCall(name=name, arguments=params)])


class PatrolReference(FetchReference):
    model = "patrol-reference-v1"

    def __init__(self):
        self.legs = 0
        self.visible = False
        self.due = 0

    async def step(self, system, history, tools):
        features = history[-1].observation.features
        visible = any(d["label"] in {"person", "pet"} for d in features["detections"])
        if visible and not self.visible:
            self.due = 2
        self.visible = visible
        if self.due:
            self.due -= 1
            name, params = "quack", {}
        elif self.legs < 3:
            self.legs += 1
            name, params = "walk", {"vy": 0.1, "duration_s": 2}
        else:
            name, params = "declare_success", {"reason": "patrol complete"}
        return ProviderTurn(tool_calls=[ToolCall(name=name, arguments=params)])


@pytest.mark.parametrize("seed", range(10))
@pytest.mark.parametrize(
    "scenario,reference",
    [
        ("fetch", FetchReference),
        ("follow-me", FollowReference),
        ("patrol-and-quack", PatrolReference),
    ],
)
async def test_reference_tasks(seed, scenario, reference, tmp_path):
    import json

    from benchmarks.verification import verify

    transport = Sim2DTransport(seed=seed)
    configure_targeted(transport.world)
    result = await run_duck(
        RunConfig(
            duck=load_duck(scenario),
            provider=reference(),
            transport=transport,
            detector=ColorBlobDetector(),
            runs_dir=tmp_path,
        )
    )
    summary = json.loads((result.run_dir / "summary.json").read_text())
    events = [
        json.loads(line) for line in (result.run_dir / "transcript.jsonl").read_text().splitlines()
    ]
    assert verify(scenario, summary, events)["success"] is True, result.reason


@pytest.mark.parametrize("seed", range(10))
def test_profile_geometry_and_trajectory_are_reproducible(seed):
    first, second = World(seed=seed), World(seed=seed)
    configure_targeted(first)
    configure_targeted(second)
    duck = first.ducks[0]
    assert math.hypot(first.ball.x - duck.x, first.ball.y - duck.y) == pytest.approx(1)
    origin = (first.people[0].x, first.people[0].y)
    for t in (0, 10, 22.5, 32.5, 50, 65):
        advance_targeted(first, t)
        advance_targeted(second, t)
        assert first.people == second.people
        assert abs(first.people[0].x) < 0.8 and abs(first.people[0].y) < 0.8
    assert (first.people[0].x, first.people[0].y) == pytest.approx(origin)
    advance_targeted(first, 10)
    assert math.dist(origin, (first.people[0].x, first.people[0].y)) == pytest.approx(0.4)


def test_profile_is_rejected_on_non_sim_robot_before_provider_creation():
    result = CliRunner().invoke(
        app, ["run", "hello-world", "--robot", "microduck:mock", "--sim-profile", "targeted-v1"]
    )
    assert result.exit_code != 0
    assert "requires a single microduck:sim2d" in result.output
