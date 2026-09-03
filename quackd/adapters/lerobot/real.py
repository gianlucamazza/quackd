"""EXPERIMENTAL: a real arm through LeRobot. Verified names, never run on an arm.

Every LeRobot name comes from `upstream_api.py` (ADR-0022). LeRobot is synchronous, so
every call runs in a worker thread under one lock with a deadline. `stop` re-sends the
present position as the goal (hold); torque is never disabled by quackd (LeRobot's own
`disconnect()` does, by its default, and that is documented). `pick` runs an injected
policy object; building one from a Hub checkpoint (`load_policy`) uses verified names but
has never been exercised (`upstream_api.POLICY_PIPELINE`). LeRobot is imported inside
`connect()` and `load_policy()` only: `quackd[lerobot]` is an extra.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator, Callable
from typing import Any, Protocol

import numpy as np
from PIL import Image

from quackd.adapters.base import AdapterNotInstalled
from quackd.adapters.lerobot import upstream_api as up
from quackd.adapters.lerobot.verbs import GRIPPER_CLOSED, GRIPPER_OPEN, JOINTS
from quackd.transport.base import Ack, DuckState, HeartbeatError, Intent, TransportError

STATUS = "EXPERIMENTAL: LeRobot names verified at a pinned commit, never run against an arm"
POLICY_HZ = 10.0


class PolicyLike(Protocol):
    """What `pick` needs from a policy: one observation in, one joint goal out (or None
    when it considers the task done). The `real` backend never builds one on its own."""

    def act(self, observation: dict[str, Any], *, task: str) -> dict[str, float] | None: ...


class LeRobotReal:
    name = "real"
    mobility = "none"

    def __init__(
        self,
        address: str | None = None,
        *,
        robot: Any = None,
        policy: PolicyLike | None = None,
        robot_type: str = up.ROBOT_TYPE_SO101.name,
        robot_id: str = "arm-01",
        timeout_s: float = 5.0,
    ) -> None:
        self.port = address or ""
        self.robot_type = robot_type
        self.robot_id = robot_id
        self.timeout_s = timeout_s
        self._robot: Any = robot  # injected in tests; built in connect() otherwise
        self._policy = policy
        self._lock = asyncio.Lock()
        self._closed = False
        self._policy_task: asyncio.Task[None] | None = None
        self._policy_name = "idle"
        self._holding_commanded = False
        self.camera_keys: tuple[str, ...] = ()
        self.lerobot_version: str | None = None
        self.post_sleep: Callable[[], None] | None = None

    @property
    def camera_available(self) -> bool:
        return bool(self.camera_keys)

    @property
    def policy_available(self) -> bool:
        return self._policy is not None

    # ── plumbing ────────────────────────────────────────────────────────────────────

    async def _call(
        self, fn: Callable[..., Any], *args: Any, deadline_s: float | None = None
    ) -> Any:
        """One LeRobot call at a time (thread safety is UNVERIFIED), each with a deadline."""
        async with self._lock:
            return await asyncio.wait_for(
                asyncio.to_thread(fn, *args), timeout=deadline_s or self.timeout_s
            )

    def _build_robot(self) -> Any:
        try:
            import lerobot
            from lerobot.robots import make_robot_from_config
            from lerobot.robots.so_follower import SO101FollowerConfig
        except ImportError as e:
            raise AdapterNotInstalled("lerobot", "quackd[lerobot]") from e
        self.lerobot_version = getattr(lerobot, "__version__", None)
        if not self.port:
            raise TransportError("lerobot real: --address must be the arm's serial port")
        if self.robot_type != up.ROBOT_TYPE_SO101.name:
            raise TransportError(f"lerobot real: only {up.ROBOT_TYPE_SO101.name} is wired")
        config = SO101FollowerConfig(port=self.port, id=self.robot_id)
        return make_robot_from_config(config)

    # ── protocol ────────────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        self._closed = False
        if self._robot is None:
            self._robot = await asyncio.to_thread(self._build_robot)
        try:
            await self._call(self._robot.connect, False, deadline_s=30.0)  # never calibrate
        except Exception as e:
            raise TransportError(f"lerobot real: connect failed: {e}") from e
        if not bool(self._robot.is_calibrated):
            with contextlib.suppress(Exception):
                await self._call(self._robot.disconnect)
            raise TransportError(
                "lerobot real: the arm is not calibrated; run LeRobot's calibration first "
                "(it is interactive, quackd never triggers it)"
            )
        features = dict(self._robot.observation_features)
        self.camera_keys = tuple(k for k, v in features.items() if isinstance(v, tuple))

    async def close(self) -> None:
        self._closed = True
        await self._cancel_policy()
        if self._robot is not None:
            with contextlib.suppress(Exception):
                await self._call(self._robot.disconnect)  # up.SO_DISCONNECT_TORQUE applies

    async def _observe(self) -> dict[str, Any]:
        obs: dict[str, Any] = await self._call(self._robot.get_observation)
        return obs

    @staticmethod
    def _joints(obs: dict[str, Any]) -> dict[str, float]:
        return {k.removesuffix(".pos"): float(v) for k, v in obs.items() if k.endswith(".pos")}

    async def get_frame(self) -> Image.Image | None:
        if not self.camera_keys:
            return None
        obs = await self._observe()
        frame = obs.get(self.camera_keys[0])
        if frame is None:
            return None
        return Image.fromarray(np.asarray(frame))  # up.CAMERA_COLOR_ORDER: assumed RGB

    async def get_state(self) -> DuckState:
        joints = self._joints(await self._observe())
        return DuckState(
            t=self.now(),
            policy=self._policy_name,
            posture="unknown",
            fallen=False,
            battery_percent=None,
            holding=self._holding_commanded,  # up.GRIPPER_OPEN_VALUE: commanded, not sensed
            extras={
                "joints": {k: round(v, 1) for k, v in joints.items()},
                "torque": True,  # quackd never disables it
                "assumptions": [
                    up.GRIPPER_OPEN_VALUE.name,
                    up.CAMERA_COLOR_ORDER.name,
                    up.NO_CLIENT_DEADMAN.name,
                ],
            },
        )

    async def _send(self, goals: dict[str, float]) -> None:
        action = {f"{k}.pos": float(v) for k, v in goals.items() if k in JOINTS}
        await self._call(self._robot.send_action, action)

    async def send_intent(self, intent: Intent) -> Ack:
        p = intent.params
        try:
            match intent.kind:
                case "joint":
                    goals = {str(k): float(v) for k, v in dict(p.get("positions", {})).items()}
                    await self._send(goals)
                case "gripper":
                    open_ = bool(p.get("open", True))
                    await self._send({"gripper": GRIPPER_OPEN if open_ else GRIPPER_CLOSED})
                    self._holding_commanded = not open_
                case "do":
                    return await self._do(str(p.get("skill")))
                case "stop":
                    await self._hold()
                case "enable":
                    if not p.get("on", True):
                        return Ack(accepted=False, reason="quackd never limps a robot")
                case _:
                    return Ack(accepted=False, reason=f"an arm cannot {intent.kind}")
        except TimeoutError:
            return Ack(accepted=False, reason=f"{intent.kind} timed out on LeRobot")
        except Exception as e:  # LeRobot's own errors are feedback, not a crash
            return Ack(accepted=False, reason=f"{intent.kind} failed: {type(e).__name__}: {e}")
        return Ack()

    async def _do(self, skill: str) -> Ack:
        kind, _, rest = skill.partition(":")
        name, _, task = rest.partition(":")
        if kind != "policy" or name != "pick":
            return Ack(accepted=False, reason=f"unknown skill {skill!r}")
        if self._policy is None:
            return Ack(accepted=False, reason="no policy was given to this backend")
        await self._cancel_policy()
        self._policy_name = f"policy:pick:{task}"
        self._policy_task = asyncio.create_task(self._run_policy(task))
        return Ack()

    async def _run_policy(self, task: str) -> None:
        """The policy's own observe/act loop at its own rate; quackd only says 'pick'."""
        assert self._policy is not None
        try:
            while not self._closed:
                obs = await self._observe()
                action = await asyncio.to_thread(self._policy.act, obs, task=task)
                if action is None:
                    self._holding_commanded = True  # the policy declared the grasp done
                    break
                await self._send(action)
                await asyncio.sleep(1.0 / POLICY_HZ)
        finally:
            self._policy_name = "idle"

    async def _cancel_policy(self) -> None:
        task, self._policy_task = self._policy_task, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._policy_name = "idle"

    async def _hold(self) -> None:
        """Stop is 'stay where you are': the present position becomes the goal."""
        await self._cancel_policy()
        joints = self._joints(await self._observe())
        if joints:
            await self._send(joints)

    async def subscribe(self, topic: str) -> AsyncIterator[dict[str, Any]]:  # type: ignore[override]
        while not self._closed:
            await self.sleep(0.5)
            yield {"topic": topic, **(await self.get_state()).model_dump()}

    async def heartbeat(self) -> None:
        if self._closed:
            raise HeartbeatError("lerobot real transport is closed")
        if self._robot is None or not bool(self._robot.is_connected):
            raise HeartbeatError("the arm is not connected")

    async def stop(self) -> None:
        with contextlib.suppress(Exception):
            await self._hold()

    def now(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)
        if self.post_sleep is not None:
            self.post_sleep()


def load_policy(path: str, *, device: str = "cpu") -> PolicyLike:
    """A `PolicyLike` from a LeRobot checkpoint, from verified names. UNTESTED end to end
    (`upstream_api.POLICY_PIPELINE`); inject your own `policy=` to bypass this."""
    try:
        import torch
        from lerobot.configs.policies import PreTrainedConfig
        from lerobot.policies.factory import get_policy_class, make_pre_post_processors
    except ImportError as e:
        raise AdapterNotInstalled("lerobot", "quackd[lerobot]") from e

    config = PreTrainedConfig.from_pretrained(path)
    config.device = device
    policy = get_policy_class(config.type).from_pretrained(path, config=config)
    preprocess, postprocess = make_pre_post_processors(config, pretrained_path=path)

    class _HubPolicy:
        def act(self, observation: dict[str, Any], *, task: str) -> dict[str, float] | None:
            batch = preprocess({**observation, "task": task})
            with torch.no_grad():
                action = policy.select_action(batch)
            out = postprocess(action)
            return {str(k): float(v) for k, v in dict(out).items()}

    return _HubPolicy()
