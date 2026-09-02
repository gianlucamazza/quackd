"""EXPERIMENTAL: a real Reachy Mini through its SDK. Verified names, never run on a robot.

Every SDK name comes from `upstream_api.py` (ADR-0022). The SDK is synchronous with its
own background threads, so every call runs in a worker thread under one lock with a
timeout. `stop` is `cancel_move`; `disable_motors` (limp) is never sent (ADR-0023). The
SDK is imported inside `connect()` only: `quackd[reachy]` is an extra, and a machine
without it still validates, lists and simulates this robot.
"""

from __future__ import annotations

import asyncio
import contextlib
import math
import os
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

import numpy as np
from PIL import Image

from quackd.adapters.base import AdapterNotInstalled
from quackd.adapters.reachy_mini import upstream_api as up
from quackd.transport.base import Ack, DuckState, HeartbeatError, Intent, TransportError

STATUS = "EXPERIMENTAL: SDK names verified at a pinned commit, never run against a robot"
DEFAULT_ADDRESS = f"{up.DEFAULT_HOST.name}:{up.DEFAULT_PORT.name}"


def parse_address(address: str | None) -> tuple[str, int]:
    text = (address or DEFAULT_ADDRESS).strip()
    host, _, port = text.rpartition(":")
    if not host:
        host, port = text, up.DEFAULT_PORT.name
    return host, int(port)


class ReachyMiniSdk:
    name = "sdk"
    mobility = "none"

    def __init__(
        self,
        address: str | None = None,
        *,
        media: str = "default",
        robot_name: str | None = None,
        timeout_s: float = 5.0,
        gaze_s: float = 0.3,
        client: Any = None,
    ) -> None:
        self.host, self.port = parse_address(address)
        self.media = media
        self.robot_name = robot_name
        self.timeout_s = timeout_s
        self.gaze_s = gaze_s
        self._mini: Any = client  # injected in tests; built in connect() otherwise
        self._lock = asyncio.Lock()
        self._closed = False
        self.status: Any = None
        self.moves: Any = None
        self.expressions: tuple[str, ...] = ()
        self.microphone = True
        self.imu = False
        self.sdk_version: str | None = None
        self.calibrated = False
        self.post_sleep: Callable[[], None] | None = None

    # ── plumbing ────────────────────────────────────────────────────────────────────

    async def _call(
        self, fn: Callable[..., Any], *args: Any, deadline_s: float | None = None
    ) -> Any:
        """One SDK call at a time (thread safety is UNVERIFIED), each with a deadline."""
        async with self._lock:
            return await asyncio.wait_for(
                asyncio.to_thread(fn, *args), timeout=deadline_s or self.timeout_s
            )

    def _build_client(self) -> Any:
        try:
            import reachy_mini
        except ImportError as e:
            raise AdapterNotInstalled("reachy_mini", "quackd[reachy]") from e
        self.sdk_version = getattr(reachy_mini, "__version__", None)
        local = self.host in ("localhost", "127.0.0.1")
        kwargs: dict[str, Any] = {
            "host": self.host,
            "port": self.port,
            "connection_mode": "localhost_only" if local else "network",
            "spawn_daemon": False,  # up.SPAWN_DAEMON_KILLS: never
            "use_sim": False,
            "timeout": self.timeout_s,
            "media_backend": self.media,
        }
        if self.robot_name:
            kwargs["robot_name"] = self.robot_name
        return reachy_mini.ReachyMini(**kwargs)

    def _load_moves(self) -> Any:
        """The emotion library from the LOCAL Hugging Face cache only: no cloud (ADR-0023)."""
        from reachy_mini.motion.recorded_move import RecordedMoves

        previous = os.environ.get("HF_HUB_OFFLINE")
        os.environ["HF_HUB_OFFLINE"] = "1"
        try:
            return RecordedMoves(up.EMOTIONS_DATASET.name)
        finally:
            if previous is None:
                os.environ.pop("HF_HUB_OFFLINE", None)
            else:
                os.environ["HF_HUB_OFFLINE"] = previous

    # ── protocol ────────────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        self._closed = False
        if self._mini is None:
            self._mini = await asyncio.to_thread(self._build_client)
        try:
            self.status = await self._call(self._mini.client.get_status)
        except Exception as e:
            raise TransportError(f"reachy_mini sdk: cannot read the daemon status: {e}") from e
        self.imu = bool(getattr(self.status, "wireless_version", False))
        with contextlib.suppress(Exception):
            self.moves = await self._call(self._load_moves, deadline_s=30.0)
            self.expressions = tuple(sorted(self.moves.list_moves()))

    async def close(self) -> None:
        self._closed = True
        if self._mini is not None:
            with contextlib.suppress(Exception):
                await self._call(self._mini.__exit__, None, None, None)  # up.CONTEXT_EXIT

    async def get_frame(self) -> Image.Image | None:
        frame = await self._call(self._mini.media.get_frame)
        if frame is None:
            return None
        return Image.fromarray(np.asarray(frame)[:, :, ::-1])  # BGR -> RGB

    async def get_state(self) -> DuckState:
        head, _antennas = await self._call(self._mini.get_current_joint_positions)
        pose = np.asarray(await self._call(self._mini.get_current_head_pose))
        body_yaw = float(head[0])
        pose_yaw = float(math.atan2(pose[1, 0], pose[0, 0]))
        backend = getattr(self.status, "backend_status", None)
        motor_mode = getattr(backend, "motor_control_mode", None)
        mode = str(getattr(motor_mode, "value", motor_mode) or "unknown")
        return DuckState(
            t=self.now(),
            policy="idle",
            posture="standing" if mode == up.MOTOR_MODE_ENABLED.name else "unknown",
            fallen=False,
            battery_percent=None,  # up.NO_BATTERY
            extras={
                "head_yaw_deg": round(math.degrees(body_yaw + pose_yaw), 1),
                "body_yaw_deg": round(math.degrees(body_yaw), 1),
                "motor_mode": mode,
                "assumptions": [up.CAMERA_YAW_COMPOSITION.name],
            },
        )

    async def send_intent(self, intent: Intent) -> Ack:
        p = intent.params
        try:
            match intent.kind:
                case "look":
                    await self._call(
                        self._mini.look_at_world,
                        float(p.get("x", 1.0)),
                        float(p.get("y", 0.0)),
                        float(p.get("z", 0.0)),
                        self.gaze_s,
                        deadline_s=self.gaze_s + self.timeout_s,
                    )
                case "do":
                    return await self._do(str(p.get("skill")))
                case "sound":
                    return await self._voice(str(p.get("tag", "attentive1")))
                case "stop":
                    await self._call(self._mini.cancel_move)
                case "enable":
                    if not p.get("on", True):
                        return Ack(accepted=False, reason="quackd never limps a robot")
                    await self._call(self._mini.enable_motors)
                case _:
                    return Ack(accepted=False, reason=f"reachy_mini cannot {intent.kind}")
        except TimeoutError:
            return Ack(accepted=False, reason=f"{intent.kind} timed out on the SDK")
        except Exception as e:  # the SDK's own errors are feedback, not a crash
            return Ack(accepted=False, reason=f"{intent.kind} failed: {type(e).__name__}: {e}")
        return Ack()

    async def _do(self, skill: str) -> Ack:
        kind, _, arg = skill.partition(":")
        if kind == "express":
            return await self._play(arg)
        if kind == "play_sound":
            await self._call(self._mini.media.play_sound, arg)
            return Ack()
        if kind == "wake_up":
            await self._call(self._mini.wake_up, deadline_s=20.0)
            return Ack()
        return Ack(accepted=False, reason=f"unknown skill {skill!r}")

    async def _voice(self, mood: str) -> Ack:
        if self.moves is None:
            return Ack(
                accepted=False, reason="no emotion library in the local cache: nothing to voice"
            )
        return await self._play(mood)

    async def _play(self, name: str) -> Ack:
        if self.moves is None or name not in self.expressions:
            return Ack(accepted=False, reason=f"expression {name!r} is not available")
        move = self.moves.get(name)
        duration = float(getattr(move, "duration", 2.0))
        await self._call(self._mini.play_move, move, deadline_s=duration + 2.0)
        return Ack()

    async def subscribe(self, topic: str) -> AsyncIterator[dict[str, Any]]:  # type: ignore[override]
        while not self._closed:
            await self.sleep(0.5)
            yield {"topic": topic, **(await self.get_state()).model_dump()}

    async def heartbeat(self) -> None:
        if self._closed:
            raise HeartbeatError("reachy_mini sdk transport is closed")
        try:
            status = await self._call(self._mini.client.get_status)
        except Exception as e:
            raise HeartbeatError(f"daemon unreachable: {e}") from e
        state = getattr(status, "state", None)
        state = str(getattr(state, "value", state))
        error = getattr(getattr(status, "backend_status", None), "error", None)
        if state != "running" or error:
            raise HeartbeatError(f"daemon state {state!r}" + (f": {error}" if error else ""))
        self.status = status

    async def stop(self) -> None:
        with contextlib.suppress(Exception):
            await self._call(self._mini.cancel_move)

    def now(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)
        if self.post_sleep is not None:
            self.post_sleep()
