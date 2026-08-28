"""A top-down toy world with a duck, a ball, a person, and walls.

This is a cartoon on purpose. It exists to test the agent loop — search, approach, act,
verify — not physics. What it *does* take seriously: determinism under a seed, a deadman
that zeroes velocity when `move` intents stop (mirroring upstream `robotd`), and enough
geometry that a kick only connects when the ball is actually in front of the duck.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

DT = 0.05  # 20 Hz
ARENA_HALF = 1.0  # metres; the arena is [-1, 1]²
DUCK_R = 0.08
BALL_R = 0.05
PERSON_R = 0.12
MAX_VX = 0.3
MAX_VY = 0.2
MAX_WZ = 1.5
DEADMAN_S = 0.3
KICK_RANGE_M = 0.30
KICK_CONE_DEG = 35.0
KICK_SPEED = 1.2
BALL_FRICTION = 1.0  # m/s² deceleration
GRAB_RANGE_M = 0.18
GRAB_CONE_DEG = 30.0
GRAB_SUCCESS_P = 0.6  # open-loop scoop: deliberately unreliable (fetch is experimental)
HEAD_YAW_LIMIT = math.radians(60)

Posture = Literal["standing", "sitting", "fallen"]


@dataclass
class Duck:
    x: float = 0.0
    y: float = 0.0
    theta: float = 0.0
    head_yaw: float = 0.0
    posture: Posture = "standing"
    holding: bool = False
    r: float = DUCK_R


@dataclass
class Ball:
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    r: float = BALL_R
    start_x: float = 0.0
    start_y: float = 0.0
    present: bool = True


@dataclass
class Person:
    x: float
    y: float
    r: float = PERSON_R
    label: str = "person"


@dataclass
class World:
    seed: int = 0
    person: bool = True
    t: float = 0.0
    duck: Duck = field(default_factory=Duck)
    ball: Ball = field(default_factory=lambda: Ball(0.5, 0.5))
    people: list[Person] = field(default_factory=list)
    cmd: tuple[float, float, float] = (0.0, 0.0, 0.0)
    cmd_age: float = 0.0
    kick_origin: tuple[float, float] | None = None
    kicks: int = 0
    kicks_connected: int = 0
    quacks: list[tuple[float, str, str | None]] = field(default_factory=list)
    steps: int = 0

    def __post_init__(self) -> None:
        self.rng = np.random.default_rng(self.seed)
        self.duck = Duck(
            x=float(self.rng.uniform(-0.3, 0.3)),
            y=float(self.rng.uniform(-0.3, 0.3)),
            theta=float(self.rng.uniform(-math.pi, math.pi)),
        )
        for _ in range(1000):
            bx, by = self.rng.uniform(-0.75, 0.75, size=2)
            if math.hypot(bx - self.duck.x, by - self.duck.y) >= 0.5:
                break
        self.ball = Ball(float(bx), float(by), start_x=float(bx), start_y=float(by))
        self.people = []
        if self.person:
            for _ in range(1000):
                px, py = self.rng.uniform(-0.8, 0.8, size=2)
                if (
                    math.hypot(px - self.duck.x, py - self.duck.y) >= 0.6
                    and math.hypot(px - self.ball.x, py - self.ball.y) >= 0.4
                ):
                    break
            self.people.append(Person(float(px), float(py)))

    # ── geometry ────────────────────────────────────────────────────────────────────

    def relative(self, x: float, y: float, *, camera: bool = False) -> tuple[float, float]:
        """(distance, bearing_rad) of a point in the duck's body frame (or camera frame)."""
        dx, dy = x - self.duck.x, y - self.duck.y
        heading = self.duck.theta + (self.duck.head_yaw if camera else 0.0)
        dist = math.hypot(dx, dy)
        bearing = math.atan2(dy, dx) - heading
        return dist, math.atan2(math.sin(bearing), math.cos(bearing))

    @property
    def ball_displacement_m(self) -> float:
        return math.hypot(self.ball.x - self.ball.start_x, self.ball.y - self.ball.start_y)

    @property
    def last_kick_ball_moved_m(self) -> float | None:
        if self.kick_origin is None:
            return None
        return math.hypot(self.ball.x - self.kick_origin[0], self.ball.y - self.kick_origin[1])

    @property
    def moving(self) -> bool:
        return any(abs(c) > 1e-6 for c in self.cmd)

    # ── intents ─────────────────────────────────────────────────────────────────────

    def set_velocity(self, vx: float, vy: float, wz: float) -> None:
        self.cmd = (
            float(np.clip(vx, -MAX_VX, MAX_VX)),
            float(np.clip(vy, -MAX_VY, MAX_VY)),
            float(np.clip(wz, -MAX_WZ, MAX_WZ)),
        )
        self.cmd_age = 0.0

    def stop(self) -> None:
        self.cmd = (0.0, 0.0, 0.0)
        self.cmd_age = 0.0

    def look(self, x: float, y: float, _z: float = 0.0) -> bool:
        """Point the camera at a trunk-frame point. Returns True if clamped."""
        yaw = math.atan2(y, x)
        clamped = abs(yaw) > HEAD_YAW_LIMIT
        self.duck.head_yaw = float(np.clip(yaw, -HEAD_YAW_LIMIT, HEAD_YAW_LIMIT))
        return clamped

    def kick(self, leg: str = "right") -> bool:
        """Kick along the heading. Connects only if the ball is close and roughly ahead."""
        self.kicks += 1
        if not self.ball.present or self.duck.posture != "standing":
            return False
        dist, bearing = self.relative(self.ball.x, self.ball.y)
        if dist > KICK_RANGE_M or abs(math.degrees(bearing)) > KICK_CONE_DEG:
            self.kick_origin = (self.ball.x, self.ball.y)  # a miss moves nothing
            return False
        self.kick_origin = (self.ball.x, self.ball.y)
        self.kicks_connected += 1
        skew = math.radians(self.rng.normal(0.0, 6.0)) + (0.05 if leg == "left" else -0.05)
        ang = self.duck.theta + skew
        self.ball.vx = KICK_SPEED * math.cos(ang)
        self.ball.vy = KICK_SPEED * math.sin(ang)
        return True

    def ground_pick(self) -> bool:
        if self.duck.holding or not self.ball.present or self.duck.posture != "standing":
            return False
        dist, bearing = self.relative(self.ball.x, self.ball.y)
        if dist > GRAB_RANGE_M or abs(math.degrees(bearing)) > GRAB_CONE_DEG:
            return False
        if self.rng.random() > GRAB_SUCCESS_P:
            # the scoop nudges the ball away — realistic and annoying
            self.ball.vx = 0.2 * math.cos(self.duck.theta + 0.6)
            self.ball.vy = 0.2 * math.sin(self.duck.theta + 0.6)
            return False
        self.duck.holding = True
        self.ball.present = False
        return True

    def sit_toggle(self) -> Posture:
        if self.duck.posture == "fallen":
            return self.duck.posture
        self.duck.posture = "sitting" if self.duck.posture == "standing" else "standing"
        self.stop()
        return self.duck.posture

    def enable(self) -> None:
        if self.duck.posture == "fallen":
            self.duck.posture = "standing"

    def sound(self, tag: str, text: str | None) -> None:
        self.quacks.append((self.t, tag, text))

    # ── physics ─────────────────────────────────────────────────────────────────────

    def step(self, dt: float = DT) -> None:
        self.cmd_age += dt
        vx, vy, wz = self.cmd
        if self.cmd_age > DEADMAN_S and self.moving:
            self.cmd = (0.0, 0.0, 0.0)  # upstream's deadman: stop is not limp
            vx = vy = wz = 0.0
        if self.duck.posture != "standing":
            vx = vy = wz = 0.0
        d = self.duck
        if vx or vy or wz:
            noise = self.rng.normal(0.0, 0.02, size=3)
            vx *= 1 + noise[0]
            vy *= 1 + noise[1]
            wz *= 1 + noise[2]
            d.theta = math.atan2(math.sin(d.theta + wz * dt), math.cos(d.theta + wz * dt))
            d.x += (vx * math.cos(d.theta) - vy * math.sin(d.theta)) * dt
            d.y += (vx * math.sin(d.theta) + vy * math.cos(d.theta)) * dt
            lim = ARENA_HALF - d.r
            d.x = float(np.clip(d.x, -lim, lim))
            d.y = float(np.clip(d.y, -lim, lim))

        b = self.ball
        if b.present:
            speed = math.hypot(b.vx, b.vy)
            if speed > 0:
                decel = min(speed, BALL_FRICTION * dt)
                b.vx *= (speed - decel) / speed
                b.vy *= (speed - decel) / speed
                b.x += b.vx * dt
                b.y += b.vy * dt
                lim = ARENA_HALF - b.r
                if abs(b.x) > lim:
                    b.x = float(np.clip(b.x, -lim, lim))
                    b.vx = -0.5 * b.vx
                if abs(b.y) > lim:
                    b.y = float(np.clip(b.y, -lim, lim))
                    b.vy = -0.5 * b.vy
            # contact push: the duck's body shoves the ball
            dx, dy = b.x - d.x, b.y - d.y
            dist = math.hypot(dx, dy)
            min_dist = d.r + b.r
            if dist < min_dist:
                if dist < 1e-6:
                    dx, dy, dist = math.cos(d.theta), math.sin(d.theta), 1.0
                nx, ny = dx / dist, dy / dist
                b.x = d.x + nx * min_dist
                b.y = d.y + ny * min_dist
                b.vx, b.vy = 0.3 * nx, 0.3 * ny
        self.t += dt
        self.steps += 1

    # ── telemetry ───────────────────────────────────────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        return {
            "sim_time": round(self.t, 3),
            "ball": (
                {"x": round(self.ball.x, 3), "y": round(self.ball.y, 3), "present": True}
                if self.ball.present
                else {"present": False}
            ),
            "ball_displacement_m": round(self.ball_displacement_m, 3),
            "last_kick_ball_moved_m": (
                None
                if self.last_kick_ball_moved_m is None
                else round(self.last_kick_ball_moved_m, 3)
            ),
            "kicks": self.kicks,
            "quacks": len(self.quacks),
            "head_yaw_deg": round(math.degrees(self.duck.head_yaw), 1),
            "people": [{"x": round(p.x, 3), "y": round(p.y, 3)} for p in self.people],
        }
