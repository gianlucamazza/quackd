"""A Reachy Mini that does exactly what the test tells it to.

`ReachyMiniMock` records intents like `MockTransport`, refuses to walk, and serves a
synthetic frame with an orange disc at a configurable bearing that shifts as the head
turns, so `search_scan`'s gaze sweep and the colour detector can be exercised offline.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

from quackd.sim2d.render import BALL, FLOOR, HORIZON, SKY, focal_px
from quackd.transport.base import Ack, DuckState, Intent
from quackd.transport.mock import MockTransport

MOCK_CAM_HEIGHT_M = 0.25
MOCK_BALL_R = 0.05


class ReachyMiniMock(MockTransport):
    name = "mock"
    mobility = "none"

    def __init__(
        self,
        *,
        ball_bearing_deg: float | None = 30.0,
        ball_distance_m: float = 0.8,
        frame_size: int = 128,
        fail_heartbeat_after: int | None = None,
        refuse_kinds: set[str] | None = None,
    ) -> None:
        super().__init__(
            states=[
                DuckState(
                    policy="idle",
                    posture="standing",
                    battery_percent=None,
                    extras={"head_yaw_deg": 0.0, "motor_mode": "enabled"},
                )
            ],
            fail_heartbeat_after=fail_heartbeat_after,
            refuse_kinds=refuse_kinds,
            frame_size=(frame_size, frame_size),
        )
        self.head_yaw_deg = 0.0
        self.head_pitch_deg = 0.0
        self.ball_bearing_deg = ball_bearing_deg
        self.ball_distance_m = ball_distance_m
        self.expressions_played: list[str] = []
        self.sounds: list[str] = []
        self.speech: list[tuple[str, str]] = []

    async def get_state(self) -> DuckState:
        state = await super().get_state()
        return state.model_copy(
            update={
                "extras": {
                    **state.extras,
                    "head_yaw_deg": round(self.head_yaw_deg, 1),
                    "head_pitch_deg": round(self.head_pitch_deg, 1),
                    "expressions_played": len(self.expressions_played),
                }
            }
        )

    async def get_frame(self) -> Image.Image | None:
        size = self._frame_size[0]
        img = Image.new("RGB", (size, size), SKY)
        draw = ImageDraw.Draw(img)
        horizon = int(size * HORIZON)
        draw.rectangle([0, horizon, size, size], fill=FLOOR)
        if self.ball_bearing_deg is None:
            return img
        rel = math.radians(self.ball_bearing_deg - self.head_yaw_deg)
        rel = math.atan2(math.sin(rel), math.cos(rel))
        if abs(rel) > math.radians(45) + 0.2:
            return img
        f = focal_px(size)
        cx = size / 2 - math.tan(rel) * f
        ground_y = horizon + f * MOCK_CAM_HEIGHT_M / self.ball_distance_m
        r = f * MOCK_BALL_R / self.ball_distance_m
        draw.ellipse([cx - r, ground_y - 2 * r, cx + r, ground_y], fill=BALL)
        return img

    async def send_intent(self, intent: Intent) -> Ack:
        ack = await super().send_intent(intent)
        if not ack.accepted:
            return ack
        p = intent.params
        match intent.kind:
            case "look":
                self.head_yaw_deg = math.degrees(math.atan2(p.get("y", 0.0), p.get("x", 1.0)))
                self.head_pitch_deg = math.degrees(
                    math.atan2(p.get("z", 0.0), math.hypot(p.get("x", 1.0), p.get("y", 0.0)))
                )
            case "do":
                kind, _, arg = str(p.get("skill")).partition(":")
                if kind == "express":
                    self.expressions_played.append(arg)
                elif kind == "play_sound":
                    self.sounds.append(arg)
                elif kind != "wake_up":
                    return Ack(accepted=False, reason=f"unknown skill {p.get('skill')!r}")
            case "sound":
                self.speech.append((str(p.get("text")), str(p.get("tag"))))
            case "move":
                return Ack(accepted=False, reason="a stationary head cannot move")
            case "enable":
                if not p.get("on", True):
                    return Ack(accepted=False, reason="quackd never limps a robot")
        return ack
