"""The Reachy Mini adapter: a stationary head with a camera, antennas and a speaker.

Three backends behind one manifest: `sim2d` (a `StationaryHead` in the cartoon world),
`mock` (scripted, for tests) and `sdk` (the real robot through `reachy-mini`,
EXPERIMENTAL and never run on hardware by us). Everything the SDK is asked for is a
VERIFIED or UNVERIFIED ref in `upstream_api.py` (ADR-0022, ADR-0023).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any

from PIL import Image

from quackd.adapters.manifest import Frame, Health, RobotManifest, SafetyAuthority, verb_spec
from quackd.adapters.reachy_mini.verbs import EXPRESSIONS, reachy_conditions, reachy_verbs
from quackd.transport.base import Ack, DuckState, DuckTransport, HeartbeatError, Intent
from quackd.verbs.core import CORE
from quackd.verbs.registry import Precondition, Verb

BACKENDS = ("sim2d", "mock", "sdk")
DEFAULT_ID = "reachy-01"
BLURB = "a small stationary robot head with a camera, two antennas and a speaker (a Reachy Mini)"
_SEARCH_SCAN_DESCRIPTION = (
    "Sweep the head in steps, looking for a target. Returns where it was seen (the bearing "
    "is camera-relative; the result also carries the head yaw)."
)


def reachy_manifest(
    backend: str,
    robot_id: str | None = None,
    *,
    expressions: Sequence[str] = EXPRESSIONS,
    microphone: bool = False,
    imu: bool = False,
    calibrated: bool = False,
    sdk_version: str | None = None,
) -> RobotManifest:
    """The Reachy Mini as data. Static for validate and announce; `connect()` enriches it
    with what the live robot reports (its expression library, a microphone, an IMU)."""
    own = reachy_verbs(expressions)
    verbs = [
        verb_spec(CORE["observe"], core=True),
        verb_spec(CORE["report_state"], core=True),
        verb_spec(CORE["stop"], core=True),
        verb_spec(own["say"], core=True),
        verb_spec(CORE["search_scan"], core=True, description=_SEARCH_SCAN_DESCRIPTION),
        verb_spec(own["gaze"], core=False),
        verb_spec(own["play_sound"], core=False),
        verb_spec(own["wake_up"], core=False, safety_class="confirm"),
    ]
    preconditions = {"gaze": ["motors_enabled"]}
    if "express" in own:
        verbs.append(verb_spec(own["express"], core=False))
        preconditions["express"] = ["motors_enabled"]
    sensors: list[Any] = ["camera"]
    if microphone:
        sensors.append("microphone")
    if imu:
        sensors.append("imu")
    return RobotManifest(
        id=robot_id or DEFAULT_ID,
        vendor="pollen-robotics",
        model="reachy-mini",
        embodiment="stationary_head",
        mobility="none",
        intents=["gaze", "sound", "skill"],
        sensors=sensors,
        verbs=verbs,
        preconditions=preconditions,
        # no client deadman and no e-stop were verified: quackd's heartbeat is the authority
        safety_authority=SafetyAuthority(native="none", deadman=False, heartbeat_hz=2.0),
        frame=Frame(
            reference="head",
            note="bearings are camera-relative; body bearing = gaze_yaw_deg + bearing_deg",
        ),
        limits={"gaze_yaw_deg": 180.0, "gaze_pitch_deg": 40.0},
        backend=backend,
        blurb=BLURB,
        extras={
            "speech": "tones",  # no TTS: say(text) is voiced as an expression (ADR-0023)
            "camera_calibrated": calibrated,
            "expressions": list(expressions),
            "sdk_version": sdk_version,
        },
    )


class ReachyMiniAdapter:
    """A `RobotAdapter` over one of the three Reachy Mini backends."""

    name = "reachy_mini"

    def __init__(self, transport: DuckTransport, *, robot_id: str | None = None) -> None:
        self.transport = transport
        self.backend = transport.name
        self.robot_id = robot_id or DEFAULT_ID
        self.manifest: RobotManifest | None = None
        self._expressions: tuple[str, ...] = tuple(EXPRESSIONS)

    async def connect(self) -> RobotManifest:
        await self.transport.connect()
        live = getattr(self.transport, "expressions", None)
        if live is not None:  # the sdk backend read the library (or found none)
            self._expressions = tuple(live)
        self.manifest = reachy_manifest(
            self.backend,
            self.robot_id,
            expressions=self._expressions,
            microphone=bool(getattr(self.transport, "microphone", False)),
            imu=bool(getattr(self.transport, "imu", False)),
            calibrated=bool(getattr(self.transport, "calibrated", False)),
            sdk_version=getattr(self.transport, "sdk_version", None),
        )
        return self.manifest

    async def disconnect(self) -> None:
        await self.transport.close()

    async def close(self) -> None:
        await self.disconnect()

    async def get_state(self) -> DuckState:
        return await self.transport.get_state()

    async def get_frame(self) -> Image.Image | None:
        return await self.transport.get_frame()

    async def send_intent(self, intent: Intent) -> Ack:
        return await self.transport.send_intent(intent)

    async def health(self) -> Health:
        try:
            await self.transport.heartbeat()
        except HeartbeatError as e:
            return Health(ok=False, reason=str(e))
        state = await self.transport.get_state()
        return Health(
            ok=True,
            battery_percent=None,
            extras={"motor_mode": state.extras.get("motor_mode"), "policy": state.policy},
        )

    async def heartbeat(self) -> None:
        await self.transport.heartbeat()

    async def stop(self) -> None:
        await self.transport.stop()

    def subscribe(self, topic: str) -> AsyncIterator[dict[str, Any]]:
        return self.transport.subscribe(topic)

    def now(self) -> float:
        return self.transport.now()

    async def sleep(self, seconds: float) -> None:
        await self.transport.sleep(seconds)

    def preconditions(self) -> dict[str, Precondition]:
        return reachy_conditions()

    def implementations(self) -> dict[str, Verb]:
        return reachy_verbs(self._expressions)

    # ── sim-only passthroughs (recorder, flock) ─────────────────────────────────────

    @property
    def mobility(self) -> str:
        return "none"

    @property
    def world(self) -> Any:
        return self.transport.world  # type: ignore[attr-defined]

    @property
    def clock(self) -> Any:
        return self.transport.clock  # type: ignore[attr-defined]

    @property
    def head_index(self) -> int:
        return int(self.transport.head_index)  # type: ignore[attr-defined]

    @property
    def camera(self) -> tuple[str, int]:
        return ("head", self.head_index)

    def add_tick_hook(self, hook: Callable[[Any], None]) -> None:
        self.transport.add_tick_hook(hook)  # type: ignore[attr-defined]

    @property
    def post_sleep(self) -> Callable[[], None] | None:
        return getattr(self.transport, "post_sleep", None)

    @post_sleep.setter
    def post_sleep(self, hook: Callable[[], None] | None) -> None:
        self.transport.post_sleep = hook  # type: ignore[attr-defined]


# ── what the factory calls ──────────────────────────────────────────────────────────────


def describe(backend: str, robot_id: str | None = None) -> RobotManifest:
    return reachy_manifest(backend, robot_id)


def implementations() -> dict[str, Verb]:
    return reachy_verbs(EXPRESSIONS)


def conditions() -> dict[str, Precondition]:
    return reachy_conditions()


def make(
    backend: str,
    *,
    robot_id: str | None = None,
    seed: int | None = None,
    address: str | None = None,
    live: bool = False,
    camera_url: str | None = None,
    token: str | None = None,
) -> ReachyMiniAdapter:
    if backend == "sim2d":
        from quackd.adapters.reachy_mini.sim2d import ReachyMiniSim2D

        return ReachyMiniAdapter(
            ReachyMiniSim2D(seed=seed if seed is not None else 0, live=live), robot_id=robot_id
        )
    if backend == "mock":
        from quackd.adapters.reachy_mini.mock import ReachyMiniMock

        return ReachyMiniAdapter(ReachyMiniMock(), robot_id=robot_id)
    if backend == "sdk":
        from quackd.adapters.reachy_mini.sdk import ReachyMiniSdk

        return ReachyMiniAdapter(ReachyMiniSdk(address=address), robot_id=robot_id)
    raise ValueError(f"unknown reachy_mini backend {backend!r}; choose one of {BACKENDS}")


__all__ = [
    "BACKENDS",
    "DEFAULT_ID",
    "EXPRESSIONS",
    "ReachyMiniAdapter",
    "conditions",
    "describe",
    "implementations",
    "make",
    "reachy_manifest",
]
