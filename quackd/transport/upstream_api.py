"""The only file in quackd allowed to spell an upstream Microduck method name.

Every constant is tagged VERIFIED (read from upstream source, link given) or UNVERIFIED
(designed upstream but not shipped, or an assumption of ours). `docs/transport-status.md`
is the human-readable version of this file; `tests/test_upstream_api.py` proves that
UNVERIFIED names are only reachable from the experimental and stub transports.

Source of truth: https://github.com/pollen-robotics/microduck/blob/main/duck-ipc-proto/src/lib.rs
(API_VERSION 16, read 2026-08-28). Architecture context:
https://github.com/pollen-robotics/microduck/blob/main/docs/design/architecture.md (draft, 2026-07-22)
https://github.com/pollen-robotics/microduck/blob/main/docs/design/robotd-design.md
https://github.com/pollen-robotics/microduck/blob/main/docs/project/roadmap.md (2026-08-26)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Status = Literal["VERIFIED", "UNVERIFIED"]

IPC_PROTO = "https://github.com/pollen-robotics/microduck/blob/main/duck-ipc-proto/src/lib.rs"
ARCH_DOC = "https://github.com/pollen-robotics/microduck/blob/main/docs/design/architecture.md"
ROBOTD_DOC = "https://github.com/pollen-robotics/microduck/blob/main/docs/design/robotd-design.md"
ROADMAP = "https://github.com/pollen-robotics/microduck/blob/main/docs/project/roadmap.md"
WEBRTC_DOC = "https://github.com/pollen-robotics/microduck/blob/main/docs/design/remote-webrtc.md"


@dataclass(frozen=True)
class UpstreamRef:
    """A named upstream thing and how sure we are that it exists as described."""

    name: str
    status: Status
    source: str
    note: str = ""

    def __str__(self) -> str:
        return self.name


# ── protocol ────────────────────────────────────────────────────────────────────────────

JSONRPC_VERSION = "2.0"
API_VERSION = UpstreamRef("16", "VERIFIED", IPC_PROTO, "duck-ipc-proto API_VERSION at read time")
FRAMING = UpstreamRef("NDJSON: one JSON-RPC 2.0 object per line", "VERIFIED", ARCH_DOC)
RUNTIME_DIR_ENV = UpstreamRef("DUCK_RUNTIME_DIR", "VERIFIED", IPC_PROTO, "overrides /run")

SOCKET_ROBOTD = UpstreamRef("/run/robotd.sock", "VERIFIED", IPC_PROTO)
SOCKET_CONFIGD = UpstreamRef("/run/configd.sock", "VERIFIED", IPC_PROTO)
SOCKET_UPDATERD = UpstreamRef("/run/updaterd.sock", "VERIFIED", IPC_PROTO)
SOCKET_PADD = UpstreamRef("/run/padd/pad.sock", "VERIFIED", IPC_PROTO, "pad.input only")
SOCKET_TOFD = UpstreamRef("/run/tofd/tof.sock", "VERIFIED", IPC_PROTO, "tof.stream only")

# ── methods we use ──────────────────────────────────────────────────────────────────────

HELLO = UpstreamRef(
    "hello",
    "VERIFIED",
    IPC_PROTO,
    "params {api_version}; result {api_version, daemon_version?, revision?}",
)
ROBOT_MOVE = UpstreamRef(
    "robot.move",
    "VERIFIED",
    IPC_PROTO,
    "NOTIFICATION (no id). params {vx, vy, vyaw} m/s, rad/s, trunk frame; x fwd, y left, +vyaw left. "
    "Continuous: robotd's deadman zeroes velocity when these stop arriving.",
)
ROBOT_STOP = UpstreamRef("robot.stop", "VERIFIED", IPC_PROTO, "request; zero velocity, NOT limp")
ROBOT_HEAD = UpstreamRef(
    "robot.head",
    "VERIFIED",
    IPC_PROTO,
    "NOTIFICATION {neck_pitch, head_pitch, head_yaw, head_roll} rad",
)
ROBOT_LOOK = UpstreamRef(
    "robot.look",
    "VERIFIED",
    IPC_PROTO,
    "request {x, y, z, neck_pitch} trunk-frame point -> {head, clamped}",
)
ROBOT_DO = UpstreamRef("robot.do", "VERIFIED", IPC_PROTO, "request {skill} -> {accepted, reason?}")
ROBOT_POSE = UpstreamRef(
    "robot.pose",
    "VERIFIED",
    IPC_PROTO,
    "NOTIFICATION {z, roll, pitch, active} standing body pose offsets",
)
ROBOT_ENABLE = UpstreamRef(
    "robot.enable", "VERIFIED", IPC_PROTO, "request {on, toggle?}; enables the policy"
)
ROBOT_INIT = UpstreamRef(
    "robot.init", "VERIFIED", IPC_PROTO, "torque on + ramp to home pose; MOVES EVERY JOINT"
)
ROBOT_RELAX = UpstreamRef(
    "robot.relax",
    "VERIFIED",
    IPC_PROTO,
    "torque off — the robot collapses. quackd never sends this.",
)
ROBOT_SOUND = UpstreamRef(
    "robot.sound", "VERIFIED", IPC_PROTO, "request {tag, hold?}; tags only, no TTS"
)
ROBOT_SUBSCRIBE = UpstreamRef(
    "robot.subscribe", "VERIFIED", IPC_PROTO, "request {hz?} -> stream of robot.state notifications"
)
ROBOT_STATE = UpstreamRef(
    "robot.state",
    "VERIFIED",
    IPC_PROTO,
    "notification {t, move{requested,applied,limited_by}, head[4], policy, safety{fallen,limp,gravity,gain?}, loop{hz,..}, joints[15], targets, odom, ...}",
)
ROBOT_HEALTH = UpstreamRef(
    "robot.health",
    "VERIFIED",
    IPC_PROTO,
    "request -> {healthy, degraded?, reason?, battery{volts,percent}?, motors?}",
)
ROBOT_MODE = UpstreamRef("robot.mode", "VERIFIED", IPC_PROTO, "request -> {mode}")
ROBOT_SET_MODE = UpstreamRef(
    "robot.setMode", "VERIFIED", IPC_PROTO, "request {mode: 'walk'|'roller'}"
)
TOF_STREAM = UpstreamRef(
    "tof.stream", "VERIFIED", IPC_PROTO, "on tofd socket; then tof.frame notifications (8x8)"
)
TOF_FRAME = UpstreamRef("tof.frame", "VERIFIED", IPC_PROTO)
PAD_INPUT = UpstreamRef(
    "pad.input", "VERIFIED", IPC_PROTO, "gamepad raw tap; the pad is the authority, not us"
)

SKILLS = UpstreamRef(
    "ground_pick | kick_left | kick_right | sit_toggle | roulade",
    "VERIFIED",
    IPC_PROTO,
    "duck-ipc-proto Skill enum, snake_case on the wire",
)
SOUND_TAGS = UpstreamRef(
    "alarm | greet | inquire | peck | chirp | coo | wheee", "VERIFIED", IPC_PROTO, "SoundTag enum"
)
SOUND_TAG_LIST = ("alarm", "greet", "inquire", "peck", "chirp", "coo", "wheee")

ERR_METHOD_NOT_FOUND = -32601
ERR_INVALID_PARAMS = -32602
ERR_BUSY = 1
ERR_PROTOCOL_MISMATCH = 3
ERR_PERMISSION_DENIED = 14

DEADMAN = UpstreamRef(
    "robotd intent deadman",
    "VERIFIED",
    ROBOTD_DOC,
    "if intents stop arriving the velocity goes to zero; 'stop is not limp'. Our walk verb re-sends robot.move at 10 Hz.",
)

# ── assumptions and things upstream has designed but not shipped ────────────────────────

POSTURE_FROM_POLICY = UpstreamRef(
    "robot.state.policy == 'sit' means sitting",
    "UNVERIFIED",
    ROBOTD_DOC,
    "The state frame names the active policy ('walk', 'stand', ...). We assume a sitting robot reports something containing 'sit'.",
)
WEBSOCKET_GATEWAY = UpstreamRef(
    "WebSocket agent gateway",
    "UNVERIFIED",
    ARCH_DOC,
    "architecture.md §5.3 designs 'open a WebSocket, poll a frame, send intents'. Roadmap M5 (2026-08-26): in progress, not shipped.",
)
GET_FRAME = UpstreamRef(
    "get_frame",
    "UNVERIFIED",
    ARCH_DOC,
    "§5.3: 'get_frame -> JPEG on demand, or 1-2 fps push'. Method name and params not in duck-ipc-proto yet.",
)
CAMERA_SNAPSHOT = UpstreamRef(
    "camera snapshot over a unix socket",
    "UNVERIFIED",
    WEBRTC_DOC,
    "Today the camera reaches clients only through mediad's WebRTC track. No socket-level frame method exists.",
)
FEATURE_STREAM = UpstreamRef(
    "mediad feature events ('ball at (x,y)', 'person detected')",
    "UNVERIFIED",
    ARCH_DOC,
    "Designed ('features, not frames'); not built. quackd's Detector protocol is the stand-in.",
)
STAND_UP_RPC = UpstreamRef(
    "stand_up",
    "UNVERIFIED",
    ROBOTD_DOC,
    "No such RPC. robotd recovers from falls itself (limp -> settle -> ramp -> standing policy). Our stand_up verb sends robot.enable.",
)


def all_refs() -> list[UpstreamRef]:
    return [v for v in globals().values() if isinstance(v, UpstreamRef)]


def refs_by_status(status: Status) -> list[UpstreamRef]:
    return [r for r in all_refs() if r.status == status]
