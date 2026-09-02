"""The LeRobot adapter: an arm with joints and a gripper, and nothing a duck has."""

from __future__ import annotations

import importlib.util
from typing import Any

import numpy as np
import pytest

from quackd.adapters.base import AdapterNotInstalled, RobotAdapter
from quackd.adapters.factory import RobotSpec, describe, make_adapter, parse_robot_spec
from quackd.adapters.lerobot import JOINTS, LeRobotAdapter, lerobot_manifest
from quackd.adapters.lerobot.mock import LeRobotMock
from quackd.adapters.lerobot.real import LeRobotReal, load_policy
from quackd.duckfile.parser import parse_duck_text
from quackd.perception.color_blob import ColorBlobDetector
from quackd.safety import ConfirmDenied, Executor, VerbNotAllowed, allow_all, deny_all
from quackd.transport.base import HeartbeatError, Intent, TransportError
from quackd.verbs.registry import registry_from_manifest

ARM_VERBS = {"observe", "report_state", "stop", "move_joints", "gripper", "place", "pick"}
DUCK_ONLY = {"move", "walk", "go_to", "walk_to", "search_scan", "say", "gaze", "kick", "sit"}
ARM_DUCK = parse_duck_text(
    "---\nduck: 1\nname: arm\ndescription: d\nrequires: [move_joints, gripper]\nverbs:\n"
    "  allow: [observe, report_state, stop, move_joints, gripper, place, pick]\n"
    "  confirm: [pick]\nsuccess: [x]\n---\n# Task\nx\n"
)
NO_LEROBOT = importlib.util.find_spec("lerobot") is None


def test_manifest_is_an_arm_with_no_duck_verbs() -> None:
    m = lerobot_manifest("mock", camera=True, policy=True)
    assert m.id == "arm-01" and m.model == "lerobot-so101" and m.vendor == "huggingface"
    assert m.embodiment == "arm" and m.mobility == "none"
    assert set(m.intents) == {"joint", "gripper", "skill"} and "twist" not in m.intents
    assert set(m.verb_names()) == ARM_VERBS
    assert not any(m.provides(v) for v in DUCK_ONLY)
    assert m.verb("pick") is not None and m.verb("pick").safety_class == "confirm"
    assert m.preconditions == {
        "move_joints": ["torque_on"],
        "place": ["holding"],
        "pick": ["torque_on"],
    }
    assert m.safety_authority.native == "torque_limit" and not m.safety_authority.deadman
    assert m.extras["joints"] == list(JOINTS)
    assert describe(parse_robot_spec("lerobot:mock")) == m
    # the static manifest of a real arm claims neither a camera nor a policy
    real = describe(parse_robot_spec("lerobot:real"))
    assert set(real.verb_names()) == {"report_state", "stop", "move_joints", "gripper", "place"}
    assert set(real.intents) == {"joint", "gripper"} and real.sensors == ["joint_state"]
    assert real.digest() != m.digest()


def test_registry_from_the_manifest_has_joints_not_legs() -> None:
    adapter = LeRobotAdapter(LeRobotMock())
    registry = registry_from_manifest(lerobot_manifest("mock", camera=True, policy=True), adapter)
    assert set(registry.names()) == ARM_VERBS
    assert "move" not in registry and "walk" not in registry and "get_frame" in registry
    schema = registry.get("move_joints").tool_schema()["input_schema"]
    assert "positions" in schema["properties"] and "duration_s" in schema["properties"]


async def test_mock_arm_runs_every_verb_through_the_executor() -> None:
    adapter = LeRobotAdapter(LeRobotMock())
    assert isinstance(adapter, RobotAdapter)
    manifest = await adapter.connect()
    ex = Executor(
        registry_from_manifest(manifest, adapter),
        adapter,
        contract=ARM_DUCK.frontmatter,
        detector=ColorBlobDetector(),
        confirm=allow_all,
        manifest=manifest,
    )
    mock = adapter.transport
    assert isinstance(mock, LeRobotMock)
    assert "ball" in (await ex.run_verb("observe")).summary  # the object is in view at rest
    moved = await ex.run_verb("move_joints", {"positions": {"shoulder_pan": 30}, "duration_s": 0.2})
    assert (
        moved.ok
        and mock.joints["shoulder_pan"] == 30.0
        and moved.data["joints"]["shoulder_pan"] == 30.0
    )
    bad = await ex.run_verb("move_joints", {"positions": {"tail": 5}})
    assert not bad.ok and "unknown joints" in bad.summary
    far = await ex.run_verb("move_joints", {"positions": {"elbow_flex": 400}})
    assert not far.ok
    # nothing is held yet: place is refused by its precondition, closing far away holds nothing
    nothing = await ex.run_verb("place")
    assert not nothing.ok and "nothing is held" in nothing.summary
    closed = await ex.run_verb("gripper", {"open": False})
    assert closed.ok and closed.data["holding"] is False
    # pick is one skill intent: the scripted policy goes there and grasps
    picked = await ex.run_verb("pick", {"target": "cup", "max_s": 5})
    assert picked.ok, picked.summary
    assert mock.policy_runs == ["cup"] and (await adapter.get_state()).holding
    assert "ball" not in (await ex.run_verb("observe")).summary  # it is in the gripper now
    placed = await ex.run_verb("place")
    assert placed.ok and not (await adapter.get_state()).holding
    with pytest.raises(VerbNotAllowed):
        await ex.run_verb("move", {"vx": 0.1})
    assert not (await adapter.send_intent(Intent.move(0.1, 0.0, 0.0))).accepted
    assert not (await adapter.send_intent(Intent.enable(False))).accepted
    health = await adapter.health()
    assert health.ok and health.battery_percent is None and health.extras["holding"] is False


async def test_pick_is_confirm_gated_and_a_sick_arm_reports_it() -> None:
    adapter = LeRobotAdapter(LeRobotMock(fail_heartbeat_after=0))
    manifest = await adapter.connect()
    ex = Executor(registry_from_manifest(manifest, adapter), adapter, confirm=deny_all)
    with pytest.raises(ConfirmDenied):
        await ex.run_verb("pick", {})
    assert not (await adapter.health()).ok


class FakeArm:
    """The slice of a LeRobot `Robot` the real backend touches, verified names only."""

    def __init__(self, *, calibrated: bool = True, camera: bool = True) -> None:
        self.calibrated = calibrated
        self.camera = camera
        self.connected = False
        self.calls: list[tuple[Any, ...]] = []
        self.actions: list[dict[str, float]] = []
        self.positions = {j: 0.0 for j in JOINTS}
        self.positions["gripper"] = 100.0
        self.torque_disabled = 0

    @property
    def observation_features(self) -> dict[str, Any]:
        feats: dict[str, Any] = {f"{j}.pos": float for j in JOINTS}
        if self.camera:
            feats["front"] = (48, 64, 3)
        return feats

    @property
    def is_connected(self) -> bool:
        return self.connected

    @property
    def is_calibrated(self) -> bool:
        return self.calibrated

    def connect(self, calibrate: bool = True) -> None:
        self.calls.append(("connect", calibrate))
        self.connected = True

    def disconnect(self) -> None:
        self.calls.append(("disconnect",))
        self.connected = False

    def get_observation(self) -> dict[str, Any]:
        obs: dict[str, Any] = {f"{j}.pos": v for j, v in self.positions.items()}
        if self.camera:
            obs["front"] = np.zeros((48, 64, 3), dtype=np.uint8)
        return obs

    def send_action(self, action: dict[str, float]) -> dict[str, float]:
        self.actions.append(dict(action))
        for key, value in action.items():
            self.positions[key.removesuffix(".pos")] = float(value)
        return dict(action)

    def disable_torque(self) -> None:
        self.torque_disabled += 1


async def test_real_backend_maps_intents_to_verified_names_and_never_limps() -> None:
    arm = FakeArm()
    adapter = LeRobotAdapter(LeRobotReal("COM5", robot=arm))
    manifest = await adapter.connect()
    assert arm.calls[0] == ("connect", False)  # calibration is interactive: never triggered
    assert manifest.provides("observe") and not manifest.provides("pick")
    assert "camera" in manifest.sensors and manifest.backend == "real"
    ex = Executor(registry_from_manifest(manifest, adapter), adapter, manifest=manifest)
    assert (
        await ex.run_verb("move_joints", {"positions": {"shoulder_pan": 10}, "duration_s": 0.2})
    ).ok
    assert arm.actions[-1] == {"shoulder_pan.pos": 10.0}
    assert (await ex.run_verb("gripper", {"open": False})).ok
    assert arm.actions[-1] == {"gripper.pos": 0.0} and (await adapter.get_state()).holding
    assert (await ex.run_verb("stop")).ok
    assert set(arm.actions[-1]) == {f"{j}.pos" for j in JOINTS}  # hold: present positions
    assert arm.actions[-1]["shoulder_pan.pos"] == 10.0 and arm.torque_disabled == 0
    frame = await adapter.get_frame()
    assert frame is not None and frame.size == (64, 48)
    state = await adapter.get_state()
    assert state.extras["joints"]["shoulder_pan"] == 10.0 and state.battery_percent is None
    assert "GRIPPER_OPEN_VALUE" in state.extras["assumptions"]
    await adapter.heartbeat()
    await adapter.close()
    assert ("disconnect",) in arm.calls
    with pytest.raises(HeartbeatError):
        await adapter.heartbeat()


async def test_real_backend_refuses_an_uncalibrated_arm() -> None:
    arm = FakeArm(calibrated=False)
    adapter = LeRobotAdapter(LeRobotReal("COM5", robot=arm))
    with pytest.raises(TransportError, match="not calibrated"):
        await adapter.connect()
    assert ("disconnect",) in arm.calls


class FakePolicy:
    def __init__(self) -> None:
        self.n = 0
        self.tasks: list[str] = []

    def act(self, observation: dict[str, Any], *, task: str) -> dict[str, float] | None:
        assert "shoulder_pan.pos" in observation
        self.tasks.append(task)
        self.n += 1
        return {"shoulder_pan": 5.0 * self.n} if self.n < 3 else None


async def test_real_backend_runs_an_injected_policy_for_pick() -> None:
    arm = FakeArm(camera=False)
    policy = FakePolicy()
    adapter = LeRobotAdapter(LeRobotReal("COM5", robot=arm, policy=policy))
    manifest = await adapter.connect()
    assert (
        manifest.provides("pick")
        and "skill" in manifest.intents
        and not manifest.provides("observe")
    )
    ex = Executor(registry_from_manifest(manifest, adapter), adapter, confirm=allow_all)
    picked = await ex.run_verb("pick", {"target": "cup", "max_s": 5})
    assert picked.ok, picked.summary
    assert policy.tasks == ["cup", "cup", "cup"]
    assert {"shoulder_pan.pos": 5.0} in arm.actions and {"shoulder_pan.pos": 10.0} in arm.actions
    assert (await adapter.get_state()).holding
    assert (await adapter.get_state()).policy == "idle"
    await adapter.close()


@pytest.mark.skipif(not NO_LEROBOT, reason="lerobot is installed here")
async def test_real_backend_without_the_extra_names_it() -> None:
    adapter = make_adapter(RobotSpec("lerobot", "real", "arm-01"), address="COM5")
    with pytest.raises(AdapterNotInstalled, match=r"quackd\[lerobot\]"):
        await adapter.connect()
    with pytest.raises(AdapterNotInstalled, match=r"quackd\[lerobot\]"):
        load_policy("some/checkpoint")
