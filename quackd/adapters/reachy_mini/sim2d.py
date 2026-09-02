"""A Reachy Mini in the cartoon world: one `StationaryHead`, seen through the same
`DuckTransport` shape the executor, the heartbeat and the flock clock already speak.

One transport is one head's view of a (possibly shared) world. Solo, it owns a head-only
world; in a heterogeneous flock, `make_head_transports` hands out views of the arena the
ducks live in, on the same lockstep clock.
"""

from __future__ import annotations

import contextlib
import math
from collections.abc import AsyncIterator, Callable
from typing import Any

from PIL import Image

from quackd.sim2d.clock import FlockClock, HookInterrupt
from quackd.sim2d.render import render_headcam
from quackd.sim2d.world import DT, World
from quackd.transport.base import Ack, DuckState, HeartbeatError, Intent


class ReachyMiniSim2D:
    name = "sim2d"
    mobility = "none"

    def __init__(
        self,
        seed: int = 0,
        *,
        live: bool = False,
        realtime: bool | None = None,
        person: bool = True,
        frame_size: int = 256,
        world: World | None = None,
        clock: FlockClock | None = None,
        head_index: int = 0,
    ) -> None:
        self.realtime = live if realtime is None else realtime
        self.world = (
            world if world is not None else World(seed=seed, person=person, n_ducks=0, n_heads=1)
        )
        self.clock = clock if clock is not None else FlockClock(self.world, realtime=self.realtime)
        self.head_index = head_index
        self.pid = f"head-{head_index}"
        self.camera = ("head", head_index)
        self.seed = seed
        self.live = live
        self.frame_size = frame_size
        self._closed = False
        self._window: Any = None
        self.post_sleep: Callable[[], None] | None = None
        """Called after every sim sleep. The flock uses it to preempt an in-flight verb."""

    def add_tick_hook(self, hook: Callable[[World], None]) -> None:
        self.clock.add_tick_hook(hook)

    # ── protocol ────────────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        self._closed = False
        if self.live:
            from quackd.sim2d.live import LiveWindow  # optional pygame dependency

            self._window = LiveWindow(self.frame_size)
            self.add_tick_hook(self._window.draw)
        self.clock.register(self.pid)

    async def close(self) -> None:
        self._closed = True
        self.clock.unregister(self.pid)
        if self._window is not None:
            self.clock.remove_tick_hook(self._window.draw)
            with contextlib.suppress(Exception):
                self._window.close()
            self._window = None

    async def get_frame(self) -> Image.Image | None:
        return render_headcam(self.world, self.frame_size, head_index=self.head_index)

    async def get_state(self) -> DuckState:
        w = self.world
        h = w.heads[self.head_index]
        return DuckState(
            t=w.t,
            x=h.x,
            y=h.y,
            theta=h.theta,
            policy="express" if w.t < h.busy_until else "idle",
            posture="standing",
            fallen=False,
            battery_percent=None,  # a Reachy Mini reports no battery
            holding=False,
            extras={**w.head_snapshot(self.head_index), "motor_mode": "enabled"},
        )

    async def send_intent(self, intent: Intent) -> Ack:
        w = self.world
        i = self.head_index
        p = intent.params
        match intent.kind:
            case "look":
                clamped = w.head_look(p.get("x", 1.0), p.get("y", 0.0), p.get("z", 0.0), i)
                return Ack(accepted=True, reason="clamped to head limits" if clamped else None)
            case "do":
                return self._do(str(p.get("skill")))
            case "sound":
                w.head_say(str(p.get("text") or p.get("tag")), str(p.get("tag", "attentive1")), i)
                w.express(str(p.get("tag", "attentive1")), i)
            case "stop":
                w.head_stop(i)
            case "move":
                return Ack(accepted=False, reason="a stationary head cannot move")
            case "enable":
                if not p.get("on", True):
                    return Ack(accepted=False, reason="quackd never limps a robot")
            case _:
                return Ack(accepted=False, reason=f"sim2d head: unknown intent {intent.kind}")
        return Ack()

    def _do(self, skill: str) -> Ack:
        w = self.world
        i = self.head_index
        kind, _, arg = skill.partition(":")
        match kind:
            case "express":
                w.express(arg, i)
                return Ack()
            case "play_sound":
                w.head_say(f"<{arg}>", "play_sound", i)
                return Ack()
            case "wake_up":
                w.head_look(1.0, 0.0, 0.0, i)
                return Ack()
            case _:
                return Ack(accepted=False, reason=f"unknown skill {skill!r}")

    async def subscribe(self, topic: str) -> AsyncIterator[dict[str, Any]]:  # type: ignore[override]
        while not self._closed:
            await self.sleep(DT)
            yield {"topic": topic, **(await self.get_state()).model_dump()}

    async def heartbeat(self) -> None:
        if self._closed:
            raise HeartbeatError("sim2d head transport is closed")

    async def stop(self) -> None:
        self.world.head_stop(self.head_index)

    def now(self) -> float:
        return self.world.t

    async def sleep(self, seconds: float) -> None:
        try:
            await self.clock.sleep(self.pid, seconds)
        except HookInterrupt as e:
            from quackd.safety import Aborted  # local import: safety must stay clock-free

            raise Aborted(str(e)) from None
        if self.post_sleep is not None:
            self.post_sleep()


def make_head_transports(
    world: World, clock: FlockClock, n: int, *, frame_size: int = 256
) -> list[ReachyMiniSim2D]:
    """N head views of a shared arena, on the ducks' clock (a heterogeneous flock)."""
    if n > len(world.heads):
        raise ValueError(f"the world has {len(world.heads)} heads, {n} requested")
    return [
        ReachyMiniSim2D(world=world, clock=clock, head_index=i, frame_size=frame_size)
        for i in range(n)
    ]


def bearing_to_head_frame(bearing_deg: float, head_yaw_deg: float) -> float:
    """A camera-relative bearing as a body-frame bearing (documented frame limitation)."""
    return math.degrees(
        math.atan2(
            math.sin(math.radians(bearing_deg + head_yaw_deg)),
            math.cos(math.radians(bearing_deg + head_yaw_deg)),
        )
    )
