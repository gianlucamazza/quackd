"""The default transport: the built-in 2D simulator behind the `DuckTransport` protocol.

Its job is to make the north-star demo need no hardware and no GPU. Time is simulated:
`sleep()` advances the world at 20 Hz as fast as the CPU allows (or in real time with a
live window), so a whole `find-and-kick` run takes seconds of wall-clock.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable
from typing import Any

from PIL import Image

from quackd.sim2d.render import render_duckcam
from quackd.sim2d.world import DT, World
from quackd.transport.base import Ack, DuckState, HeartbeatError, Intent

BATTERY_DRAIN_PER_S = 0.02  # percent per sim second: a 5-minute run costs ~6 %


class Sim2DTransport:
    name = "sim2d"

    def __init__(
        self,
        seed: int = 0,
        *,
        live: bool = False,
        realtime: bool | None = None,
        person: bool = True,
        frame_size: int = 256,
        battery_start: float = 100.0,
    ) -> None:
        self.world = World(seed=seed, person=person)
        self.seed = seed
        self.live = live
        self.realtime = live if realtime is None else realtime
        self.frame_size = frame_size
        self.battery_start = battery_start
        self._tick_hooks: list[Callable[[World], None]] = []
        self._closed = False
        self._window: Any = None
        self._steps_since_yield = 0

    # ── hooks (recorder, live window) ───────────────────────────────────────────────

    def add_tick_hook(self, hook: Callable[[World], None]) -> None:
        self._tick_hooks.append(hook)

    # ── protocol ────────────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        self._closed = False
        if self.live:
            from quackd.sim2d.live import LiveWindow  # optional pygame dependency

            self._window = LiveWindow(self.frame_size)
            self.add_tick_hook(self._window.draw)

    async def close(self) -> None:
        self._closed = True
        if self._window is not None:
            with contextlib.suppress(Exception):
                self._window.close()
            self._window = None

    async def get_frame(self) -> Image.Image | None:
        return render_duckcam(self.world, self.frame_size)

    async def get_state(self) -> DuckState:
        w = self.world
        d = w.duck
        battery = max(0.0, self.battery_start - BATTERY_DRAIN_PER_S * w.t)
        policy = "sit" if d.posture == "sitting" else ("walk" if w.moving else "stand")
        return DuckState(
            t=w.t,
            x=d.x,
            y=d.y,
            theta=d.theta,
            policy=policy,
            posture="fallen" if d.posture == "fallen" else d.posture,
            fallen=d.posture == "fallen",
            battery_percent=battery,
            holding=d.holding,
            extras=w.snapshot(),
        )

    async def send_intent(self, intent: Intent) -> Ack:
        w = self.world
        p = intent.params
        match intent.kind:
            case "move":
                w.set_velocity(p.get("vx", 0.0), p.get("vy", 0.0), p.get("wz", 0.0))
            case "stop":
                w.stop()
            case "do":
                return self._do(str(p.get("skill")))
            case "look":
                clamped = w.look(p.get("x", 1.0), p.get("y", 0.0), p.get("z", 0.0))
                return Ack(accepted=True, reason="clamped to head limits" if clamped else None)
            case "sound":
                w.sound(str(p.get("tag", "chirp")), p.get("text"))
            case "enable":
                if p.get("on", True):
                    w.enable()
            case "pose":
                pass
            case _:
                return Ack(accepted=False, reason=f"sim2d: unknown intent {intent.kind}")
        return Ack()

    def _do(self, skill: str) -> Ack:
        w = self.world
        if w.duck.posture == "fallen":
            return Ack(accepted=False, reason="the duck has fallen")
        match skill:
            case "kick_left" | "kick_right":
                if w.duck.posture != "standing":
                    return Ack(accepted=False, reason="cannot kick while sitting")
                w.kick("left" if skill == "kick_left" else "right")
                return Ack()  # the kick *ran*; whether it connected shows in ball telemetry
            case "ground_pick":
                w.ground_pick()
                return Ack()
            case "sit_toggle":
                w.sit_toggle()
                return Ack()
            case "roulade":
                return Ack(accepted=True, reason="roulade is a no-op in sim2d")
            case _:
                return Ack(accepted=False, reason=f"unknown skill {skill!r}")

    async def subscribe(self, topic: str) -> AsyncIterator[dict[str, Any]]:  # type: ignore[override]
        while not self._closed:
            await self.sleep(DT)
            yield {"topic": topic, **(await self.get_state()).model_dump()}

    async def heartbeat(self) -> None:
        if self._closed:
            raise HeartbeatError("sim2d transport is closed")

    async def stop(self) -> None:
        self.world.stop()

    def now(self) -> float:
        return self.world.t

    async def sleep(self, seconds: float) -> None:
        steps = max(1, round(seconds / DT))
        for _ in range(steps):
            self.world.step(DT)
            for hook in self._tick_hooks:
                hook(self.world)
            if self.realtime:
                await asyncio.sleep(DT)
            else:
                self._steps_since_yield += 1
                if self._steps_since_yield >= 4:
                    self._steps_since_yield = 0
                    await asyncio.sleep(0)
