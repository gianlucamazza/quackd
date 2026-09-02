"""The Reachy Mini adapter: a head that looks and speaks, never walks, and lies about nothing."""

from __future__ import annotations

import math
import sys
from typing import Any

import numpy as np
import pytest
from typer.testing import CliRunner

from quackd.adapters.base import AdapterNotInstalled, RobotAdapter
from quackd.adapters.factory import describe, make_adapter, parse_robot_spec
from quackd.adapters.reachy_mini import EXPRESSIONS, ReachyMiniAdapter, reachy_manifest
from quackd.adapters.reachy_mini.mock import ReachyMiniMock
from quackd.adapters.reachy_mini.sdk import ReachyMiniSdk, parse_address
from quackd.adapters.reachy_mini.sim2d import ReachyMiniSim2D
from quackd.cli import app
from quackd.duckfile.parser import load_duck, parse_duck_text
from quackd.duckfile.validate import validate_duck
from quackd.perception.color_blob import ColorBlobDetector
from quackd.safety import Executor, allow_all
from quackd.transport.base import HeartbeatError
from quackd.verbs.registry import registry_from_manifest

REACHY_VERBS = {
    "observe",
    "report_state",
    "stop",
    "say",
    "search_scan",
    "gaze",
    "express",
    "play_sound",
    "wake_up",
}
DUCK_ONLY = {"move", "walk", "go_to", "walk_to", "approach_and", "kick", "grab", "sit", "stand"}
HEAD_DUCK = parse_duck_text(
    "---\nduck: 1\nname: head\ndescription: d\nrequires: [observe, gaze]\nverbs:\n"
    "  allow: [observe, search_scan, gaze, express, say, play_sound, report_state, stop]\n"
    "success: [x]\n---\n# Task\nx\n"
)


def test_manifest_is_a_stationary_head_that_provides_only_what_it_has() -> None:
    m = reachy_manifest("mock")
    assert m.id == "reachy-01" and m.model == "reachy-mini"
    assert m.embodiment == "stationary_head" and m.mobility == "none"
    assert set(m.intents) == {"gaze", "sound", "skill"} and "twist" not in m.intents
    assert set(m.verb_names()) == REACHY_VERBS
    assert not any(m.provides(v) for v in DUCK_ONLY)
    assert m.provides("get_frame")  # the alias of observe
    wake = m.verb("wake_up")
    assert wake is not None and wake.safety_class == "confirm"
    assert m.safety_authority.native == "none" and not m.safety_authority.deadman
    assert m.extras["speech"] == "tones" and m.limits["gaze_yaw_deg"] == 180.0
    assert reachy_manifest("sim2d").digest() == m.digest()
    assert describe(parse_robot_spec("reachy_mini:mock")) == m


def test_registry_from_the_manifest_has_no_locomotion() -> None:
    adapter = ReachyMiniAdapter(ReachyMiniMock())
    registry = registry_from_manifest(reachy_manifest("mock"), adapter)
    assert set(registry.names()) == REACHY_VERBS
    assert "walk_to" not in registry and "move" not in registry and "get_frame" in registry
    express = registry.get("express").tool_schema()["input_schema"]
    assert express["properties"]["name"]["enum"] == list(EXPRESSIONS)


async def test_mock_backend_refuses_to_walk_and_records_what_a_head_does() -> None:
    adapter = ReachyMiniAdapter(ReachyMiniMock())
    assert isinstance(adapter, RobotAdapter)
    manifest = await adapter.connect()
    ex = Executor(
        registry_from_manifest(manifest, adapter),
        adapter,
        contract=HEAD_DUCK.frontmatter,
        detector=ColorBlobDetector(),
        confirm=allow_all,
    )
    mock = adapter.transport
    assert isinstance(mock, ReachyMiniMock)
    looked = await ex.run_verb("gaze", {"bearing_deg": 120})
    assert looked.ok and abs(mock.head_yaw_deg - 120.0) < 1e-6
    assert (await ex.run_verb("express", {"name": "cheerful1"})).ok
    assert mock.expressions_played == ["cheerful1"]
    bad = await ex.run_verb("express", {"name": "moonwalk"})
    assert not bad.ok and "name" in bad.summary  # not in this robot's enum
    said = await ex.run_verb("say", {"text": "hello there!"})
    assert said.ok and said.data["voiced_as"] == "welcoming1"
    assert mock.speech == [("hello there!", "welcoming1")]
    assert (await ex.run_verb("play_sound", {"name": "wake_up.wav"})).ok
    assert mock.sounds == ["wake_up.wav"]
    refused = await ex.run_verb("play_sound", {"name": "../etc/passwd"})
    assert not refused.ok
    from quackd.transport.base import Intent

    assert not (await adapter.send_intent(Intent.move(0.1, 0.0, 0.0))).accepted
    assert not (await adapter.send_intent(Intent.enable(False))).accepted
    state = await adapter.get_state()
    assert state.battery_percent is None and state.extras["motor_mode"] == "enabled"
    health = await adapter.health()
    assert health.ok and health.battery_percent is None


async def test_mock_frame_and_gaze_sweep_find_the_ball() -> None:
    adapter = ReachyMiniAdapter(ReachyMiniMock(ball_bearing_deg=100.0, ball_distance_m=0.7))
    manifest = await adapter.connect()
    ex = Executor(
        registry_from_manifest(manifest, adapter),
        adapter,
        contract=HEAD_DUCK.frontmatter,
        detector=ColorBlobDetector(),
    )
    assert "ball" not in (await ex.run_verb("observe")).summary  # 100 deg off: out of view
    found = await ex.run_verb("search_scan", {"target": "ball", "step_deg": 45})
    assert found.ok, found.summary
    # the sweep looks at 0, +45, -45, +90: the ball at +100 is caught on the fourth look
    assert found.data["gaze_yaw_deg"] == 90.0 and found.data["steps"] == 3
    assert not adapter.transport.intents_of("move")  # type: ignore[attr-defined]
    assert abs(found.data["detections"][0]["est_distance_m"] - 0.7) < 0.2


@pytest.mark.parametrize("seed", range(10))
async def test_sim2d_head_finds_the_ball_by_sweeping(seed: int) -> None:
    adapter = ReachyMiniAdapter(ReachyMiniSim2D(seed=seed))
    manifest = await adapter.connect()
    assert adapter.world.ducks == [] and len(adapter.world.heads) == 1
    ex = Executor(
        registry_from_manifest(manifest, adapter),
        adapter,
        contract=HEAD_DUCK.frontmatter,
        detector=ColorBlobDetector(),
    )
    found = await ex.run_verb("search_scan", {"target": "ball"})
    assert found.ok, found.summary
    assert found.data["steps"] <= 8
    truth_dist, truth_bearing = adapter.world.relative_head(
        adapter.world.ball.x, adapter.world.ball.y
    )
    assert abs(math.degrees(truth_bearing)) < 46  # the head was left pointing at the ball
    est = found.data["detections"][0]["est_distance_m"]
    assert abs(est - truth_dist) / truth_dist < 0.3
    state = await adapter.get_state()
    assert (
        "kicks" not in state.extras and state.extras["head_yaw_deg"] == found.data["gaze_yaw_deg"]
    )
    await adapter.disconnect()


def test_validate_find_and_kick_against_the_head_fails_on_kick() -> None:
    problems = validate_duck(
        load_duck("find-and-kick"), [describe(parse_robot_spec("reachy_mini:mock"))]
    )
    assert "requires kick, but reachy-01 (reachy-mini) does not provide it" in [
        p.message for p in problems
    ]
    result = CliRunner().invoke(
        app, ["validate", "ducks/find-and-kick.duck", "--robot", "reachy_mini:mock"]
    )
    assert result.exit_code == 1
    assert "requires kick, but reachy-01 (reachy-mini) does not provide it" in result.output
    assert validate_duck(HEAD_DUCK, [reachy_manifest("mock")]) == []


def test_importing_the_adapter_never_imports_the_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, "reachy_mini", raising=False)
    monkeypatch.delitem(sys.modules, "reachy_mini.motion.recorded_move", raising=False)
    make_adapter("reachy_mini:mock")
    make_adapter("reachy_mini:sim2d")
    describe(parse_robot_spec("reachy_mini:sdk"))
    assert "reachy_mini" not in sys.modules


async def test_sdk_backend_without_the_extra_names_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "reachy_mini", None)  # import raises ImportError
    adapter = make_adapter("reachy_mini:sdk")
    with pytest.raises(AdapterNotInstalled, match=r"quackd\[reachy\]"):
        await adapter.connect()
    assert parse_address(None) == ("reachy-mini.local", 8000)
    assert parse_address("10.0.0.7:9000") == ("10.0.0.7", 9000)
    assert parse_address("localhost") == ("localhost", 8000)


class _Status:
    def __init__(self, state: str = "running", error: str | None = None) -> None:
        self.state = state
        self.robot_name = "reachy_mini"
        self.wireless_version = False
        self.version = "1.10.0"
        self.hardware_id = "abc"
        self.backend_status = type("B", (), {"error": error, "motor_control_mode": "enabled"})()


class FakeReachy:
    """Records every SDK call quackd makes; the names are the VERIFIED ones."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.status = _Status()
        self.client = type(
            "C", (), {"get_status": lambda *_: self.status, "disconnect": lambda *_: None}
        )()
        self.media = type(
            "M",
            (),
            {
                "get_frame": lambda *_: np.zeros((8, 8, 3), dtype=np.uint8),
                "play_sound": lambda _s, name: self.calls.append(("play_sound", (name,))),
            },
        )()

    def look_at_world(self, x: float, y: float, z: float, duration: float) -> None:
        self.calls.append(("look_at_world", (x, y, z, duration)))

    def get_current_joint_positions(self) -> tuple[list[float], list[float]]:
        return [0.5, 0, 0, 0, 0, 0, 0], [0.0, 0.0]

    def get_current_head_pose(self) -> Any:
        yaw = 0.25
        return np.array(
            [
                [math.cos(yaw), -math.sin(yaw), 0, 0],
                [math.sin(yaw), math.cos(yaw), 0, 0],
                [0, 0, 1, 0],
                [0, 0, 0, 1],
            ]
        )

    def cancel_move(self) -> None:
        self.calls.append(("cancel_move", ()))

    def enable_motors(self) -> None:
        self.calls.append(("enable_motors", ()))

    def disable_motors(self) -> None:
        raise AssertionError("quackd must never limp the robot")

    def wake_up(self) -> None:
        self.calls.append(("wake_up", ()))

    def play_move(self, move: Any) -> None:
        self.calls.append(("play_move", (move,)))

    def __exit__(self, *a: Any) -> None:
        self.calls.append(("__exit__", ()))


async def test_sdk_backend_maps_intents_onto_verified_names() -> None:
    fake = FakeReachy()
    backend = ReachyMiniSdk(client=fake, gaze_s=0.3)
    adapter = ReachyMiniAdapter(backend)
    manifest = await adapter.connect()
    assert manifest.backend == "sdk" and "express" not in manifest.verb_names()  # no library
    assert "microphone" in manifest.sensors
    from quackd.transport.base import Intent

    assert (await adapter.send_intent(Intent.look(0.0, 1.0, 0.0))).accepted
    assert fake.calls[-1] == ("look_at_world", (0.0, 1.0, 0.0, 0.3))
    await adapter.stop()
    assert fake.calls[-1] == ("cancel_move", ())
    assert not (await adapter.send_intent(Intent.enable(False))).accepted
    assert not (await adapter.send_intent(Intent.move(0.1, 0, 0))).accepted
    voiced = await adapter.send_intent(Intent.sound("cheerful1", "yay"))
    assert not voiced.accepted and "no emotion library" in (voiced.reason or "")
    assert (await adapter.send_intent(Intent.do("play_sound:wake_up.wav"))).accepted
    assert ("play_sound", ("wake_up.wav",)) in fake.calls
    state = await adapter.get_state()
    assert state.posture == "standing" and state.battery_percent is None
    assert abs(state.extras["head_yaw_deg"] - math.degrees(0.5 + 0.25)) < 0.1
    assert "assumptions" in state.extras
    frame = await adapter.get_frame()
    assert frame is not None and frame.size == (8, 8)
    await adapter.heartbeat()
    fake.status = _Status(state="error", error="motors silent")
    with pytest.raises(HeartbeatError, match="motors silent"):
        await adapter.heartbeat()
    await adapter.disconnect()
    assert fake.calls[-1] == ("__exit__", ())
