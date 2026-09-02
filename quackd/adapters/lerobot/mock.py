"""An arm that does exactly what the test tells it to.

`LeRobotMock` is a six-joint arm in memory: joint goals land instantly, the gripper closes
on an object when the arm is near it, a scripted "policy" answers `pick`, and the camera
is a synthetic frame with an orange disc that slides as the shoulder pans. Enough to run
every arm verb, the executor's gates and the detector offline.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

from quackd.adapters.lerobot.verbs import GRIPPER_CLOSED, GRIPPER_OPEN, JOINTS
from quackd.sim2d.render import BALL, FLOOR, HORIZON, SKY, focal_px
from quackd.transport.base import Ack, DuckState, Intent
from quackd.transport.mock import MockTransport

REST = {
    "shoulder_pan": 0.0,
    "shoulder_lift": -90.0,
    "elbow_flex": 90.0,
    "wrist_flex": 0.0,
    "wrist_roll": 0.0,
    "gripper": GRIPPER_OPEN,
}
OBJECT_AT = {"shoulder_pan": 30.0, "shoulder_lift": -20.0, "elbow_flex": 40.0}
"""Where the object is, in joint space: the arm is "there" when these three are close."""
NEAR_DEG = 10.0
MOCK_CAM_HEIGHT_M = 0.3
MOCK_OBJECT_R = 0.03


class LeRobotMock(MockTransport):
    name = "mock"
    mobility = "none"
    camera_available = True
    policy_available = True

    def __init__(
        self,
        *,
        object_bearing_deg: float | None = 30.0,
        object_distance_m: float = 0.35,
        frame_size: int = 128,
        fail_heartbeat_after: int | None = None,
        refuse_kinds: set[str] | None = None,
    ) -> None:
        super().__init__(
            states=[DuckState(policy="idle", posture="unknown", battery_percent=None)],
            fail_heartbeat_after=fail_heartbeat_after,
            refuse_kinds=refuse_kinds,
            frame_size=(frame_size, frame_size),
        )
        self.joints: dict[str, float] = dict(REST)
        self.holding = False
        self.torque = True
        self.policy = "idle"
        self.object_bearing_deg = object_bearing_deg
        self.object_distance_m = object_distance_m
        self.actions: list[dict[str, float]] = []
        self.policy_runs: list[str] = []

    # ── state and camera ────────────────────────────────────────────────────────────

    def _near_object(self) -> bool:
        return all(abs(self.joints[k] - v) <= NEAR_DEG for k, v in OBJECT_AT.items())

    async def get_state(self) -> DuckState:
        state = await super().get_state()
        return state.model_copy(
            update={
                "policy": self.policy,
                "holding": self.holding,
                "extras": {
                    "joints": {k: round(v, 1) for k, v in self.joints.items()},
                    "torque": self.torque,
                    "near_object": self._near_object(),
                },
            }
        )

    async def get_frame(self) -> Image.Image | None:
        size = self._frame_size[0]
        img = Image.new("RGB", (size, size), SKY)
        draw = ImageDraw.Draw(img)
        horizon = int(size * HORIZON)
        draw.rectangle([0, horizon, size, size], fill=FLOOR)
        if self.object_bearing_deg is None or self.holding:
            return img  # nothing on the table, or it is in the gripper
        rel = math.radians(self.object_bearing_deg - self.joints["shoulder_pan"])
        if abs(rel) > math.radians(45):
            return img
        f = focal_px(size)
        cx = size / 2 - math.tan(rel) * f
        ground_y = horizon + f * MOCK_CAM_HEIGHT_M / self.object_distance_m
        r = f * MOCK_OBJECT_R / self.object_distance_m
        draw.ellipse([cx - r, ground_y - 2 * r, cx + r, ground_y], fill=BALL)
        return img

    # ── intents ─────────────────────────────────────────────────────────────────────

    def _goto(self, goals: dict[str, float]) -> None:
        for joint, goal in goals.items():
            if joint in JOINTS:
                lo, hi = (0.0, 100.0) if joint == "gripper" else (-180.0, 180.0)
                self.joints[joint] = min(hi, max(lo, float(goal)))
        self.actions.append(dict(goals))

    def _set_gripper(self, open_: bool) -> None:
        self._goto({"gripper": GRIPPER_OPEN if open_ else GRIPPER_CLOSED})
        if open_:
            self.holding = False
        elif self._near_object():
            self.holding = True

    async def send_intent(self, intent: Intent) -> Ack:
        ack = await super().send_intent(intent)
        if not ack.accepted:
            return ack
        p = intent.params
        match intent.kind:
            case "joint":
                if not self.torque:
                    return Ack(accepted=False, reason="torque is off")
                self._goto({str(k): float(v) for k, v in dict(p.get("positions", {})).items()})
            case "gripper":
                self._set_gripper(bool(p.get("open", True)))
            case "do":
                kind, _, rest = str(p.get("skill")).partition(":")
                if kind != "policy":
                    return Ack(accepted=False, reason=f"unknown skill {p.get('skill')!r}")
                name, _, task = rest.partition(":")
                if name != "pick":
                    return Ack(accepted=False, reason=f"no policy named {name!r}")
                # the scripted policy: go to the object and close on it
                self.policy = f"policy:pick:{task}"
                self.policy_runs.append(task)
                self._goto(dict(OBJECT_AT))
                self._set_gripper(False)
                self.policy = "idle"
            case "stop":
                self.policy = "idle"
            case "move":
                return Ack(accepted=False, reason="an arm cannot drive")
            case "enable":
                if not p.get("on", True):
                    return Ack(accepted=False, reason="quackd never limps a robot")
            case _:
                return Ack(accepted=False, reason=f"an arm cannot {intent.kind}")
        return ack

    async def stop(self) -> None:
        await super().stop()
        self.policy = "idle"
