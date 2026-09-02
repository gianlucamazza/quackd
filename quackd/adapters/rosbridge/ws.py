"""EXPERIMENTAL: a wheeled base over rosbridge through roslibpy. Verified names, never run.

Every roslibpy and rosbridge name comes from `upstream_api.py` (ADR-0022). The address
carries everything: `ws://host:9090?cmd_vel=/cmd_vel&odom=/odom&image=/camera/compressed`.
quackd publishes `geometry_msgs/msg/Twist` on the command topic, re-sent at 10 Hz by the
core `move` verb, and a zero Twist on stop, which is the only stop authority there is
(`upstream_api.NO_DEADMAN`). Odometry and the optional compressed image are subscribed,
and only the latest of each is kept, under a lock, because callbacks arrive on roslibpy's
own thread. roslibpy is imported inside `connect()` only: `quackd[rosbridge]` is an extra.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import io
import math
import threading
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import parse_qs, urlsplit

from PIL import Image

from quackd.adapters.base import AdapterNotInstalled
from quackd.adapters.rosbridge import upstream_api as up
from quackd.transport.base import Ack, DuckState, HeartbeatError, Intent, TransportError

STATUS = "EXPERIMENTAL: roslibpy and rosbridge names verified at pinned commits, never run"
DEFAULT_ADDRESS = "ws://localhost:9090"
DEFAULT_CMD_VEL = "/cmd_vel"
DEFAULT_ODOM = "/odom"


@dataclass(frozen=True)
class Endpoint:
    host: str
    port: int
    secure: bool
    cmd_vel: str
    odom: str
    image: str | None

    @property
    def url(self) -> str:
        return f"{'wss' if self.secure else 'ws'}://{self.host}:{self.port}"


def parse_address(address: str | None) -> Endpoint:
    """`ws://host:9090?cmd_vel=/cmd_vel&odom=/odom&image=/camera/image/compressed`."""
    parts = urlsplit(address or DEFAULT_ADDRESS)
    if parts.scheme not in ("ws", "wss"):
        raise TransportError(f"rosbridge address must start with ws:// or wss://, not {address!r}")
    query = {k: v[-1] for k, v in parse_qs(parts.query).items()}
    for key in ("cmd_vel", "odom", "image"):
        if key in query and not query[key].startswith("/"):
            raise TransportError(f"rosbridge topic {key}={query[key]!r} must start with /")
    return Endpoint(
        host=parts.hostname or "localhost",
        port=parts.port or 9090,
        secure=parts.scheme == "wss",
        cmd_vel=query.get("cmd_vel", DEFAULT_CMD_VEL),
        odom=query.get("odom", DEFAULT_ODOM),
        image=query.get("image"),
    )


class TopicLike(Protocol):
    """The slice of `roslibpy.Topic` the backend uses."""

    def publish(self, message: Any) -> Any: ...

    def subscribe(self, callback: Callable[[dict[str, Any]], None]) -> Any: ...

    def unsubscribe(self) -> Any: ...

    def unadvertise(self) -> Any: ...


class RosLike(Protocol):
    """The slice of `roslibpy.Ros` the backend uses."""

    @property
    def is_connected(self) -> bool: ...

    def run(self, timeout: float = ...) -> Any: ...

    def close(self, timeout: float = ...) -> Any: ...

    def terminate(self) -> Any: ...


TopicFactory = Callable[[Any, str, str], TopicLike]


def twist_message(vx: float, vy: float, wz: float) -> dict[str, Any]:
    """`geometry_msgs/msg/Twist` as a dict (roslibpy sends dict(message))."""
    return {
        "linear": {"x": float(vx), "y": float(vy), "z": 0.0},
        "angular": {"x": 0.0, "y": 0.0, "z": float(wz)},
    }


def yaw_from_quaternion(q: dict[str, Any]) -> float:
    """Planar yaw from (x, y, z, w); `upstream_api.ODOM_YAW`."""
    x, y, z, w = (float(q.get(k, 0.0)) for k in ("x", "y", "z", "w"))
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def decode_compressed_image(message: dict[str, Any]) -> Image.Image:
    """A `sensor_msgs/msg/CompressedImage` (data base64 over rosbridge) to RGB."""
    fmt = str(message.get("format", "")).lower()
    data = message.get("data", "")
    raw = base64.b64decode(data) if isinstance(data, str) else bytes(data)
    if not any(codec in fmt for codec in ("jpeg", "jpg", "png")) and fmt:
        raise ValueError(f"unsupported CompressedImage format {fmt!r} (jpeg or png only)")
    img: Image.Image = Image.open(io.BytesIO(raw))
    img.load()
    if img.mode != "RGB":
        img = img.convert("RGB")
    if "bgr8" in fmt:
        r, g, b = img.split()
        img = Image.merge("RGB", (b, g, r))
    return img


class RosbridgeWs:
    name = "ws"
    mobility = "wheeled"

    def __init__(
        self,
        address: str | None = None,
        *,
        ros: RosLike | None = None,
        topic_factory: TopicFactory | None = None,
        timeout_s: float = 5.0,
    ) -> None:
        self.endpoint = parse_address(address)
        self.timeout_s = timeout_s
        self._ros: Any = ros  # injected in tests; built in connect() otherwise
        self._topic_factory = topic_factory
        self._cmd: TopicLike | None = None
        self._odom: TopicLike | None = None
        self._image: TopicLike | None = None
        self._lock = threading.Lock()
        self._latest_odom: dict[str, Any] | None = None
        self._latest_image: dict[str, Any] | None = None
        self._closed = False
        self._t0 = time.monotonic()
        self.last_twist = (0.0, 0.0, 0.0)
        self.published = 0
        self.roslibpy_version: str | None = None
        self.post_sleep: Callable[[], None] | None = None

    @property
    def camera_available(self) -> bool:
        return self.endpoint.image is not None

    # ── plumbing ────────────────────────────────────────────────────────────────────

    def _build(self) -> tuple[Any, TopicFactory]:
        try:
            import roslibpy
        except ImportError as e:
            raise AdapterNotInstalled("rosbridge", "quackd[rosbridge]") from e
        self.roslibpy_version = getattr(roslibpy, "__version__", None)
        ros = roslibpy.Ros(self.endpoint.host, self.endpoint.port, is_secure=self.endpoint.secure)

        def factory(client: Any, name: str, message_type: str) -> TopicLike:
            topic: TopicLike = roslibpy.Topic(client, name, message_type, compression="none")
            return topic

        return ros, factory

    def _on_odom(self, message: dict[str, Any]) -> None:  # roslibpy's thread
        with self._lock:
            self._latest_odom = dict(message)

    def _on_image(self, message: dict[str, Any]) -> None:  # roslibpy's thread
        with self._lock:
            self._latest_image = dict(message)

    # ── protocol ────────────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        self._closed = False
        if self._ros is None or self._topic_factory is None:
            ros, factory = await asyncio.to_thread(self._build)
            self._ros = self._ros or ros
            self._topic_factory = self._topic_factory or factory
        try:
            await asyncio.wait_for(
                asyncio.to_thread(self._ros.run, self.timeout_s), timeout=self.timeout_s + 1.0
            )
        except Exception as e:
            raise TransportError(f"rosbridge ws: cannot reach {self.endpoint.url}: {e}") from e
        make = self._topic_factory
        self._cmd = make(self._ros, self.endpoint.cmd_vel, up.MSG_TWIST.name)
        self._odom = make(self._ros, self.endpoint.odom, up.MSG_ODOMETRY.name)
        self._odom.subscribe(self._on_odom)
        if self.endpoint.image is not None:
            self._image = make(self._ros, self.endpoint.image, up.MSG_COMPRESSED_IMAGE.name)
            self._image.subscribe(self._on_image)

    async def close(self) -> None:
        self._closed = True
        with contextlib.suppress(Exception):
            self._publish_twist(0.0, 0.0, 0.0)
        for topic in (self._odom, self._image):
            if topic is not None:
                with contextlib.suppress(Exception):
                    topic.unsubscribe()
        if self._cmd is not None:
            with contextlib.suppress(Exception):
                self._cmd.unadvertise()
        if self._ros is not None:
            with contextlib.suppress(Exception):
                await asyncio.to_thread(self._ros.terminate)

    def _publish_twist(self, vx: float, vy: float, wz: float) -> None:
        if self._cmd is None:
            raise TransportError("rosbridge ws: not connected")
        self.last_twist = (vx, vy, wz)
        self.published += 1
        self._cmd.publish(twist_message(vx, vy, wz))

    async def get_frame(self) -> Image.Image | None:
        if self._image is None:
            return None
        with self._lock:
            message = self._latest_image
        if message is None:
            return None
        return decode_compressed_image(message)

    async def get_state(self) -> DuckState:
        with self._lock:
            odom = self._latest_odom
        x = y = theta = None
        if odom is not None:
            pose = dict(odom.get("pose", {})).get("pose", {})
            position = dict(pose.get("position", {}))
            x, y = float(position.get("x", 0.0)), float(position.get("y", 0.0))
            theta = yaw_from_quaternion(dict(pose.get("orientation", {})))
        vx, vy, wz = self.last_twist
        return DuckState(
            t=self.now(),
            policy="idle",
            posture="unknown",
            fallen=False,
            battery_percent=None,
            x=x,
            y=y,
            theta=theta,
            extras={
                "odom_seen": odom is not None,
                "twist": {"vx": vx, "vy": vy, "wz": wz},
                "assumptions": [up.NO_DEADMAN.name, up.TWIST_UNITS.name, up.ODOM_YAW.name],
            },
        )

    async def send_intent(self, intent: Intent) -> Ack:
        p = intent.params
        try:
            match intent.kind:
                case "move":
                    self._publish_twist(
                        float(p.get("vx", 0.0)), float(p.get("vy", 0.0)), float(p.get("wz", 0.0))
                    )
                case "stop":
                    self._publish_twist(0.0, 0.0, 0.0)
                case _:
                    return Ack(accepted=False, reason=f"a base over rosbridge cannot {intent.kind}")
        except Exception as e:
            return Ack(accepted=False, reason=f"{intent.kind} failed: {type(e).__name__}: {e}")
        return Ack()

    async def subscribe(self, topic: str) -> AsyncIterator[dict[str, Any]]:  # type: ignore[override]
        while not self._closed:
            await self.sleep(0.5)
            yield {"topic": topic, **(await self.get_state()).model_dump()}

    async def heartbeat(self) -> None:
        if self._closed:
            raise HeartbeatError("rosbridge ws transport is closed")
        if self._ros is None or not bool(self._ros.is_connected):
            raise HeartbeatError(f"rosbridge at {self.endpoint.url} is not connected")

    async def stop(self) -> None:
        with contextlib.suppress(Exception):
            self._publish_twist(0.0, 0.0, 0.0)

    def now(self) -> float:
        return time.monotonic() - self._t0

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)
        if self.post_sleep is not None:
            self.post_sleep()
