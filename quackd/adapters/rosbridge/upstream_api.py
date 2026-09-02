"""The only file in quackd allowed to spell a roslibpy or rosbridge name (ADR-0022).

Every constant is tagged VERIFIED (read from upstream source, link given) or UNVERIFIED
(an assumption of ours, with what quackd does about it). `docs/adapters/rosbridge.md` is
the human-readable version; `tests/test_upstream_api.py` proves UNVERIFIED names are only
reachable from the experimental `ws` backend.

Three upstreams, each pinned and read on 2026-09-02: roslibpy (the client library, PyPI
2.1.0, Python >= 3.9), rosbridge_suite (the protocol the server speaks, ros2 branch) and
ros2/common_interfaces (the message definitions). Nothing here has been run against a
bridge, and roslibpy is never imported outside the `ws` backend.
"""

from __future__ import annotations

from quackd.transport.upstream_api import UpstreamRef

REPO = "https://github.com/gramaziokohler/roslibpy"
PIN = "f5793dbc28578275b0ac93ae84b736dad822db4b"
REPO_ROSBRIDGE = "https://github.com/RobotWebTools/rosbridge_suite"
PIN_ROSBRIDGE = "aa9a7a33ddb3b1b45ddd6d2eead4c3d5eb800b14"
REPO_INTERFACES = "https://github.com/ros2/common_interfaces"
PIN_INTERFACES = "d54aa9b96dfed4922775652414e0e8fa4ee2ae40"
READ_ON = "2026-09-02"
PYPI_VERSION_READ = "2.1.0"


def src(path: str, line: int | None = None) -> str:
    return f"{REPO}/blob/{PIN}/{path}" + (f"#L{line}" if line else "")


def bridge(path: str, line: int | None = None) -> str:
    return f"{REPO_ROSBRIDGE}/blob/{PIN_ROSBRIDGE}/{path}" + (f"#L{line}" if line else "")


def msg(path: str, line: int | None = None) -> str:
    return f"{REPO_INTERFACES}/blob/{PIN_INTERFACES}/{path}" + (f"#L{line}" if line else "")


_ROS = "src/roslibpy/ros.py"
_CORE = "src/roslibpy/core.py"
_COMM = "src/roslibpy/comm/comm.py"
_PROTO = "ROSBRIDGE_PROTOCOL.md"
_LOADER = "rosbridge_library/src/rosbridge_library/internal/ros_loader.py"
_CONV = "rosbridge_library/src/rosbridge_library/internal/message_conversion.py"

# ── roslibpy, the client ────────────────────────────────────────────────────────────────

PACKAGE = UpstreamRef(
    "roslibpy", "VERIFIED", src("src/roslibpy/__version__.py", 7), "2.1.0 at the pin and on PyPI"
)
ROS_CLIENT = UpstreamRef(
    "roslibpy.Ros(host, port=None, is_secure=False, headers=None, transport=None)",
    "VERIFIED",
    src(_ROS, 38),
    "the constructor already calls connect() (line 58); run() then waits for it",
)
ROS_RUN = UpstreamRef(
    "Ros.run(timeout)",
    "VERIFIED",
    src(_ROS, 109),
    "starts the non-blocking event loop and waits until connected or raises RosTimeoutError",
)
ROS_CLOSE = UpstreamRef("Ros.close(timeout)", "VERIFIED", src(_ROS, 93))
ROS_TERMINATE = UpstreamRef(
    "Ros.terminate()", "VERIFIED", src(_ROS, 154), "closes if connected, then stops the loop"
)
ROS_IS_CONNECTED = UpstreamRef("Ros.is_connected", "VERIFIED", src(_ROS, 71))
ROS_ON_READY = UpstreamRef("Ros.on_ready(callback, run_in_thread=True)", "VERIFIED", src(_ROS, 187))
ROS_GET_TOPICS = UpstreamRef("Ros.get_topics(callback, errback)", "VERIFIED", src(_ROS, 333))
ROS_GET_TOPIC_TYPE = UpstreamRef(
    "Ros.get_topic_type(topic, callback, errback)", "VERIFIED", src(_ROS, 352)
)
TOPIC = UpstreamRef(
    "roslibpy.Topic(ros, name, message_type, compression=None, latch=False, throttle_rate=0, "
    "queue_size=100, queue_length=0, reconnect_on_close=True)",
    "VERIFIED",
    src(_CORE, 210),
)
TOPIC_PUBLISH = UpstreamRef(
    "Topic.publish(message)",
    "VERIFIED",
    src(_CORE, 303),
    "advertises on first use (line 309) and sends dict(message), so a plain dict works",
)
TOPIC_SUBSCRIBE = UpstreamRef(
    "Topic.subscribe(callback)", "VERIFIED", src(_CORE, 260), "callback(message: dict)"
)
TOPIC_UNSUBSCRIBE = UpstreamRef("Topic.unsubscribe()", "VERIFIED", src(_CORE, 290))
TOPIC_ADVERTISE = UpstreamRef("Topic.advertise()", "VERIFIED", src(_CORE, 324))
TOPIC_UNADVERTISE = UpstreamRef("Topic.unadvertise()", "VERIFIED", src(_CORE, 363))
TOPIC_COMPRESSION = UpstreamRef(
    "compression: png or none", "VERIFIED", src(_CORE, 208), "quackd subscribes with none"
)
MESSAGE = UpstreamRef("roslibpy.Message(values)", "VERIFIED", src(_CORE, 45), "a UserDict")
WIRE_JSON = UpstreamRef(
    "JSON text frames", "VERIFIED", src(_COMM, 44), "json.loads on every frame, keyed by op"
)

# ── the rosbridge protocol, the server side ─────────────────────────────────────────────

OP_ADVERTISE = UpstreamRef(
    "op=advertise {id, topic, type, latch, queue_size}",
    "VERIFIED",
    bridge(_PROTO, 299),
    "what roslibpy sends (core.py line 334)",
)
OP_PUBLISH = UpstreamRef(
    "op=publish {id, topic, msg, latch}", "VERIFIED", bridge(_PROTO, 339), "core.py line 315"
)
OP_SUBSCRIBE = UpstreamRef(
    "op=subscribe {id, topic, type, compression, throttle_rate, queue_length}",
    "VERIFIED",
    bridge(_PROTO, 379),
    "core.py line 279",
)
BINARY_BASE64 = UpstreamRef(
    "uint8[] fields arrive base64-encoded",
    "VERIFIED",
    bridge(_PROTO, 140),
    "message_conversion.py line 96 lists the binary types; a CompressedImage's data is one",
)
TYPE_STRING_FORMS = UpstreamRef(
    "pkg/Type and pkg/msg/Type both resolve",
    "VERIFIED",
    bridge(_LOADER, 254),
    "_splittype accepts two or three parts; quackd sends the ROS 2 three-part form",
)

# ── the messages quackd speaks ──────────────────────────────────────────────────────────

MSG_TWIST = UpstreamRef(
    "geometry_msgs/msg/Twist",
    "VERIFIED",
    msg("geometry_msgs/msg/Twist.msg", 3),
    "{linear: Vector3, angular: Vector3}",
)
MSG_VECTOR3 = UpstreamRef(
    "geometry_msgs/msg/Vector3", "VERIFIED", msg("geometry_msgs/msg/Vector3.msg", 7), "{x, y, z}"
)
MSG_COMPRESSED_IMAGE = UpstreamRef(
    "sensor_msgs/msg/CompressedImage",
    "VERIFIED",
    msg("sensor_msgs/msg/CompressedImage.msg", 44),
    "{header, format, data: uint8[]}; format names the codec (jpeg, png) and pixel format",
)
MSG_ODOMETRY = UpstreamRef(
    "nav_msgs/msg/Odometry",
    "VERIFIED",
    msg("nav_msgs/msg/Odometry.msg", 12),
    "{header, child_frame_id, pose: PoseWithCovariance, twist: TwistWithCovariance}",
)
MSG_POSE = UpstreamRef(
    "geometry_msgs/msg/Pose",
    "VERIFIED",
    msg("geometry_msgs/msg/Pose.msg", 3),
    "{position: Point, orientation: Quaternion}; PoseWithCovariance wraps it as pose",
)
MSG_QUATERNION = UpstreamRef(
    "geometry_msgs/msg/Quaternion",
    "VERIFIED",
    msg("geometry_msgs/msg/Quaternion.msg", 3),
    "{x, y, z, w}",
)

# ── UNVERIFIED: our assumptions, and what quackd does about each ────────────────────────

NO_DEADMAN = UpstreamRef(
    "NO_DEADMAN",
    "UNVERIFIED",
    bridge(_PROTO),
    "neither rosbridge nor a base's driver has a deadman we verified; quackd re-sends the "
    "Twist at 10 Hz while a verb runs and publishes a zero Twist on stop, and that is the "
    "only stop authority (manifest: native none, deadman false)",
)
TOPIC_NAMES = UpstreamRef(
    "TOPIC_NAMES",
    "UNVERIFIED",
    bridge(_PROTO, 339),
    "/cmd_vel, /odom and an image topic are conventions, not a contract; each is set in "
    "the address query (?cmd_vel=&odom=&image=)",
)
TWIST_UNITS = UpstreamRef(
    "TWIST_UNITS",
    "UNVERIFIED",
    msg("geometry_msgs/msg/Twist.msg", 1),
    "m/s and rad/s in the base frame with angular z positive to the left, as ROS convention "
    "says; the limits in the manifest are what quackd clamps to, not what the base can do",
)
IMAGE_FORMAT = UpstreamRef(
    "IMAGE_FORMAT",
    "UNVERIFIED",
    msg("sensor_msgs/msg/CompressedImage.msg", 10),
    "the format string names jpeg or png and bgr8 or rgb8; quackd decodes with PIL and "
    "swaps channels when the format says bgr8, otherwise assumes rgb; anything else is refused",
)
ODOM_YAW = UpstreamRef(
    "ODOM_YAW",
    "UNVERIFIED",
    msg("nav_msgs/msg/Odometry.msg", 12),
    "yaw is taken from the quaternion's z and w, assuming a planar base",
)
THREAD_SAFETY = UpstreamRef(
    "THREAD_SAFETY",
    "UNVERIFIED",
    src(_CORE, 260),
    "subscription callbacks arrive on roslibpy's transport thread; quackd stores only the "
    "latest message under a lock and never calls back into the event loop from there",
)
ROS1_BRIDGE = UpstreamRef(
    "ROS1_BRIDGE",
    "UNVERIFIED",
    bridge(_LOADER, 254),
    "a ROS 1 rosbridge should accept the three-part type strings too; not tried",
)


def all_refs() -> list[UpstreamRef]:
    return [v for v in globals().values() if isinstance(v, UpstreamRef)]


def refs_by_status(status: str) -> list[UpstreamRef]:
    return [r for r in all_refs() if r.status == status]
