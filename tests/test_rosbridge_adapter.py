"""The rosbridge adapter: a wheeled base that takes a Twist, and the messages it speaks."""

from __future__ import annotations

import base64
import importlib.util
import io
import math
from typing import Any

import pytest
from PIL import Image

from quackd.adapters.base import AdapterNotInstalled
from quackd.adapters.factory import describe, make_adapter, parse_robot_spec
from quackd.adapters.microduck import microduck_manifest
from quackd.adapters.rosbridge import RosbridgeAdapter, rosbridge_manifest
from quackd.adapters.rosbridge.mock import RosbridgeMock
from quackd.adapters.rosbridge.ws import (
    RosbridgeWs,
    decode_compressed_image,
    parse_address,
    twist_message,
    yaw_from_quaternion,
)
from quackd.perception.color_blob import ColorBlobDetector
from quackd.safety import Executor
from quackd.transport.base import HeartbeatError, Intent, TransportError
from quackd.verbs.core import speed_limits
from quackd.verbs.registry import registry_from_manifest

MOCK_VERBS = {"observe", "report_state", "stop", "move", "go_to", "search_scan", "approach_and"}
NO_ROSLIBPY = importlib.util.find_spec("roslibpy") is None


def test_the_address_carries_the_topics() -> None:
    default = parse_address(None)
    assert (default.host, default.port, default.secure) == ("localhost", 9090, False)
    assert (default.cmd_vel, default.odom, default.image) == ("/cmd_vel", "/odom", None)
    full = parse_address("wss://robot.local:9443?cmd_vel=/base/cmd_vel&image=/cam/compressed")
    assert full.secure and full.url == "wss://robot.local:9443"
    assert full.cmd_vel == "/base/cmd_vel" and full.image == "/cam/compressed"
    assert full.odom == "/odom"
    with pytest.raises(TransportError, match="ws://"):
        parse_address("http://robot.local:9090")
    with pytest.raises(TransportError, match="must start with /"):
        parse_address("ws://robot.local:9090?cmd_vel=cmd_vel")


def test_manifest_is_a_wheeled_base_with_twist_only() -> None:
    m = rosbridge_manifest("mock", camera=True)
    assert m.embodiment == "wheeled" and m.mobility == "wheeled" and m.intents == ["twist"]
    assert set(m.verb_names()) == MOCK_VERBS
    assert not any(m.provides(v) for v in ("say", "gaze", "kick", "sit", "express"))
    assert m.provides("walk_to") and m.provides("walk")  # the aliases of go_to and move
    assert m.safety_authority.native == "none" and not m.safety_authority.deadman
    assert m.limits == {"max_vx": 0.3, "max_vy": 0.0, "max_wz": 1.0}
    assert describe(parse_robot_spec("rosbridge:mock")) == m
    blind = describe(parse_robot_spec("rosbridge:ws"))
    assert set(blind.verb_names()) == {"report_state", "stop", "move"}
    assert blind.sensors == ["odometry"] and blind.extras["image"] is None


async def test_mock_base_drives_coasts_on_silence_and_reaches_the_ball() -> None:
    adapter = RosbridgeAdapter(RosbridgeMock())
    manifest = await adapter.connect()
    ex = Executor(
        registry_from_manifest(manifest, adapter),
        adapter,
        detector=ColorBlobDetector(),
        manifest=manifest,
    )
    mock = adapter.transport
    assert isinstance(mock, RosbridgeMock)
    assert (await ex.run_verb("move", {"vx": 0.2, "duration_s": 1.0})).ok
    assert abs(mock.x - 0.2) < 0.03 and mock.twists[-1] == {"vx": 0.0, "vy": 0.0, "wz": 0.0}
    # a raw Twist with nobody re-sending it: the deadman coasts the base to zero
    x0 = mock.x
    assert (await adapter.send_intent(Intent.move(0.2, 0.0, 0.0))).accepted
    await adapter.sleep(2.0)
    assert 0.09 < mock.x - x0 < 0.13
    assert not (await adapter.send_intent(Intent.look(1.0, 0.0, 0.0))).accepted
    found = await ex.run_verb("search_scan", {"target": "ball"})
    assert found.ok and found.data["steps"] == 0  # 18 degrees off the nose: in view already
    reached = await ex.run_verb("go_to", {"target": "ball"})
    assert reached.ok, reached.summary
    rel = mock.ball_relative()
    assert rel is not None and rel[0] < 0.4
    state = await ex.run_verb("report_state")
    assert state.ok and state.data["state"]["extras"]["odom"]["x"] > 0.8
    assert (await adapter.health()).ok


async def test_speed_limits_come_from_the_manifest() -> None:
    assert speed_limits(None) == (0.3, 0.2, 1.5)
    assert speed_limits(microduck_manifest("sim2d")) == (0.3, 0.2, 1.5)  # the old schema bounds
    adapter = RosbridgeAdapter(RosbridgeMock())
    await adapter.connect()
    slow = rosbridge_manifest("mock", camera=True, max_vx=0.1, max_wz=0.5)
    ex = Executor(registry_from_manifest(slow, adapter), adapter, manifest=slow)
    res = await ex.run_verb("move", {"vx": 0.3, "wz": 1.0, "duration_s": 0.5})
    assert res.ok and "clamped" in res.summary
    mock = adapter.transport
    assert isinstance(mock, RosbridgeMock)
    assert mock.twists[0] == {"vx": 0.1, "vy": 0.0, "wz": 0.5}


class FakeTopic:
    def __init__(self, ros: Any, name: str, message_type: str) -> None:
        self.name = name
        self.message_type = message_type
        self.published: list[dict[str, Any]] = []
        self.callback: Any = None
        self.unsubscribed = False
        self.unadvertised = False

    def publish(self, message: Any) -> None:
        self.published.append(dict(message))

    def subscribe(self, callback: Any) -> None:
        self.callback = callback

    def unsubscribe(self) -> None:
        self.unsubscribed = True

    def unadvertise(self) -> None:
        self.unadvertised = True


class FakeRos:
    def __init__(self) -> None:
        self.is_connected = False
        self.runs = 0
        self.terminated = False

    def run(self, timeout: float = 5.0) -> None:
        self.runs += 1
        self.is_connected = True

    def close(self, timeout: float = 5.0) -> None:
        self.is_connected = False

    def terminate(self) -> None:
        self.terminated = True
        self.is_connected = False


def _png(color: tuple[int, int, int], size: tuple[int, int] = (8, 6), fmt: str = "PNG") -> str:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format=fmt, quality=95)
    return base64.b64encode(buf.getvalue()).decode("ascii")


async def test_ws_backend_speaks_verified_topics_and_messages() -> None:
    ros = FakeRos()
    topics: dict[str, FakeTopic] = {}

    def factory(client: Any, name: str, message_type: str) -> FakeTopic:
        return topics.setdefault(name, FakeTopic(client, name, message_type))

    ws = RosbridgeWs(
        "ws://robot.local:9090?image=/cam/compressed&cmd_vel=/base/cmd_vel",
        ros=ros,
        topic_factory=factory,
    )
    adapter = RosbridgeAdapter(ws)
    manifest = await adapter.connect()
    assert ros.runs == 1 and set(topics) == {"/base/cmd_vel", "/odom", "/cam/compressed"}
    assert topics["/base/cmd_vel"].message_type == "geometry_msgs/msg/Twist"
    assert topics["/odom"].message_type == "nav_msgs/msg/Odometry"
    assert topics["/cam/compressed"].message_type == "sensor_msgs/msg/CompressedImage"
    assert manifest.provides("observe") and manifest.extras["image"] == "/cam/compressed"
    assert manifest.extras["cmd_vel"] == "/base/cmd_vel"

    assert (await adapter.send_intent(Intent.move(0.2, 0.0, 0.5))).accepted
    assert topics["/base/cmd_vel"].published == [twist_message(0.2, 0.0, 0.5)]
    assert twist_message(0.2, 0.0, 0.5) == {
        "linear": {"x": 0.2, "y": 0.0, "z": 0.0},
        "angular": {"x": 0.0, "y": 0.0, "z": 0.5},
    }
    before = await adapter.get_state()
    assert before.x is None and before.extras["odom_seen"] is False
    topics["/odom"].callback(
        {
            "pose": {
                "pose": {
                    "position": {"x": 1.0, "y": 2.0, "z": 0.0},
                    "orientation": {
                        "x": 0.0,
                        "y": 0.0,
                        "z": math.sin(math.pi / 4),
                        "w": math.cos(math.pi / 4),
                    },
                }
            }
        }
    )
    after = await adapter.get_state()
    assert after.x == 1.0 and after.y == 2.0 and after.theta is not None
    assert abs(after.theta - math.pi / 2) < 1e-6
    assert await adapter.get_frame() is None  # nothing published on the image topic yet
    topics["/cam/compressed"].callback(
        {"format": "rgb8; png compressed rgb8", "data": _png((255, 0, 0))}
    )
    frame = await adapter.get_frame()
    assert frame is not None and frame.size == (8, 6) and frame.getpixel((1, 1)) == (255, 0, 0)
    topics["/cam/compressed"].callback(
        {"format": "bgr8; jpeg compressed bgr8", "data": _png((255, 0, 0), fmt="JPEG")}
    )
    swapped = await adapter.get_frame()
    assert swapped is not None
    r, _g, b = swapped.getpixel((1, 1))
    assert b > 200 and r < 50  # the format said bgr8, so the channels were swapped
    await adapter.stop()
    assert topics["/base/cmd_vel"].published[-1] == twist_message(0.0, 0.0, 0.0)
    await adapter.heartbeat()
    ros.is_connected = False
    with pytest.raises(HeartbeatError):
        await adapter.heartbeat()
    ros.is_connected = True
    await adapter.close()
    assert topics["/odom"].unsubscribed and topics["/cam/compressed"].unsubscribed
    assert topics["/base/cmd_vel"].unadvertised and ros.terminated
    assert topics["/base/cmd_vel"].published[-1] == twist_message(0.0, 0.0, 0.0)


def test_message_helpers() -> None:
    assert abs(yaw_from_quaternion({"x": 0, "y": 0, "z": 0, "w": 1})) < 1e-9
    with pytest.raises(ValueError, match="jpeg or png"):
        decode_compressed_image({"format": "rgb8; tiff compressed", "data": _png((1, 2, 3))})
    plain = decode_compressed_image({"format": "", "data": _png((0, 255, 0))})
    assert plain.getpixel((0, 0)) == (0, 255, 0)


@pytest.mark.skipif(not NO_ROSLIBPY, reason="roslibpy is installed here")
async def test_ws_backend_without_the_extra_names_it() -> None:
    adapter = make_adapter("rosbridge:ws", address="ws://robot.local:9090")
    with pytest.raises(AdapterNotInstalled, match=r"quackd\[rosbridge\]"):
        await adapter.connect()
