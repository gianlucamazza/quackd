"""The only file in quackd allowed to spell a Reachy Mini SDK name (ADR-0022).

Every constant is tagged VERIFIED (read from upstream source, link given) or UNVERIFIED
(an assumption of ours, with what quackd does about it). `docs/adapters/reachy_mini.md` is
the human-readable version; `tests/test_upstream_api.py` proves UNVERIFIED names are only
reachable from the experimental `sdk` backend.

Source of truth: https://github.com/pollen-robotics/reachy_mini at commit
da0097361c1567f0daf61310e940616171028fd2 (main, 2026-08-26; read 2026-09-01). Every
line number below was confirmed against the installed `reachy-mini` 1.10.0 wheel on
2026-09-02 (the two agree). Nothing here has been run against a robot.
"""

from __future__ import annotations

from quackd.transport.upstream_api import UpstreamRef

REPO = "https://github.com/pollen-robotics/reachy_mini"
PIN = "da0097361c1567f0daf61310e940616171028fd2"
READ_ON = "2026-09-01"
SDK_VERSION_READ = "1.10.0"
HF_DATASETS = "https://huggingface.co/datasets/pollen-robotics/"


def src(path: str, line: int | None = None) -> str:
    return f"{REPO}/blob/{PIN}/{path}" + (f"#L{line}" if line else "")


_SDK = "src/reachy_mini/reachy_mini.py"
_MEDIA = "src/reachy_mini/media/media_manager.py"
_PROTOCOL = "src/reachy_mini/io/protocol.py"
_WS = "src/reachy_mini/io/ws_client.py"
_MOVES = "src/reachy_mini/motion/recorded_move.py"

# ── package and connection ──────────────────────────────────────────────────────────────

PACKAGE = UpstreamRef(
    "reachy-mini", "VERIFIED", src("pyproject.toml"), "PyPI name; the import name is reachy_mini"
)
PYTHON = UpstreamRef(">=3.11", "VERIFIED", src("pyproject.toml"), "requires-python")
CLIENT = UpstreamRef(
    "ReachyMini",
    "VERIFIED",
    src(_SDK, 104),
    "ReachyMini(robot_name='reachy_mini', host='reachy-mini.local', port=8000, "
    "connection_mode='auto'|'localhost_only'|'network', spawn_daemon=False, use_sim=False, "
    "timeout=5.0, automatic_body_yaw=True, log_level='INFO', media_backend='default'). "
    "A WebSocket client to a daemon; raises without one (no offline construction).",
)
WS_PATH = UpstreamRef("/ws/sdk", "VERIFIED", src(_WS, 85), "ws://{host}:{port}/ws/sdk")
DEFAULT_HOST = UpstreamRef("reachy-mini.local", "VERIFIED", src(_SDK, 104))
DEFAULT_PORT = UpstreamRef("8000", "VERIFIED", src(_SDK, 104))
MDNS_SERVICE = UpstreamRef(
    "_reachy-mini._tcp.local.", "VERIFIED", src("src/reachy_mini/utils/discovery.py", 22)
)
FIND_ROBOTS = UpstreamRef(
    "reachy_mini.utils.discovery.find_robots",
    "VERIFIED",
    src("src/reachy_mini/utils/discovery.py", 219),
    "find_robots(timeout=5.0) -> list[DiscoveredRobot]",
)
CONTEXT_EXIT = UpstreamRef(
    "ReachyMini.__exit__",
    "VERIFIED",
    src(_SDK, 186),
    "closes the media manager and calls client.disconnect(); ReachyMini has no close() or "
    "disconnect() of its own",
)
CLIENT_DISCONNECT = UpstreamRef("client.disconnect", "VERIFIED", src(_WS, 135))
GET_STATUS = UpstreamRef(
    "client.get_status",
    "VERIFIED",
    src(_WS, 228),
    "mini.client.get_status(wait=True, timeout=5.0) -> DaemonStatus. On the WS client, "
    "not on ReachyMini (the research draft had it wrong).",
)
DAEMON_STATUS = UpstreamRef(
    "DaemonStatus",
    "VERIFIED",
    src(_PROTOCOL, 147),
    "robot_name, state, wireless_version, simulation_enabled, mockup_sim_enabled, no_media, "
    "media_released, camera_specs_name, backend_status, error, wlan_ip, version, "
    "hardware_id, face_target",
)
DAEMON_STATE = UpstreamRef(
    "DaemonState: not_initialized, starting, running, stopping, stopped, error",
    "VERIFIED",
    src(_PROTOCOL, 51),
    "the daemon state enum; quackd's heartbeat needs 'running'",
)
STATE_SNAPSHOT = UpstreamRef(
    "StateSnapshot",
    "VERIFIED",
    src(_PROTOCOL, 111),
    "head_pose, antennas, head_joint_positions, body_yaw, motor_mode, is_recording, "
    "is_move_running, face_target, doa; a stable wire contract",
)
MOTOR_MODE_ENABLED = UpstreamRef(
    "enabled", "VERIFIED", src(_PROTOCOL, 46), "MotorControlMode.Enabled; quackd's 'motors_enabled'"
)
VERSION_MISMATCH = UpstreamRef(
    "SDK/daemon version warning",
    "VERIFIED",
    src(_SDK, 343),
    "_warn_if_daemon_version_mismatch: the SDK warns when the daemon's version differs",
)
SPAWN_DAEMON_KILLS = UpstreamRef(
    "spawn_daemon=True kills a mismatched daemon",
    "VERIFIED",
    src("src/reachy_mini/daemon/utils.py", 129),
    "SIGKILL on a config mismatch; quackd never passes spawn_daemon=True",
)
DAEMON_CMD = UpstreamRef(
    "reachy-mini-daemon",
    "VERIFIED",
    src("pyproject.toml"),
    "--sim (MuJoCo, extra reachy-mini[mujoco]) or --mockup-sim (no physics): how to exercise "
    "the sdk backend without hardware",
)

# ── motion ──────────────────────────────────────────────────────────────────────────────

LOOK_AT_WORLD = UpstreamRef(
    "look_at_world",
    "VERIFIED",
    src(_SDK, 830),
    "look_at_world(x, y, z, duration=1.0, perform_movement=True) -> 4x4 pose. Metres in the "
    "neutral head frame: x forward, y left, z up (docstring, line 840). quackd's gaze.",
)
LOOK_AT_IMAGE = UpstreamRef(
    "look_at_image",
    "VERIFIED",
    src(_SDK, 772),
    "look_at_image(u, v, duration=1.0): u right, v down",
)
GOTO_TARGET = UpstreamRef(
    "goto_target",
    "VERIFIED",
    src(_SDK, 672),
    "goto_target(head=4x4, antennas=[right, left] rad, duration=0.5, "
    "method='minjerk'|'linear'|'ease_in_out'|'cartoon', body_yaw=0.0); blocks until done",
)
SET_TARGET = UpstreamRef(
    "set_target", "VERIFIED", src(_SDK, 610), "immediate target for high-rate loops; unused"
)
GET_CURRENT_HEAD_POSE = UpstreamRef(
    "get_current_head_pose", "VERIFIED", src(_SDK, 950), "-> 4x4 homogeneous matrix"
)
GET_CURRENT_JOINT_POSITIONS = UpstreamRef(
    "get_current_joint_positions",
    "VERIFIED",
    src(_SDK, 926),
    "-> (head[7] with body yaw at index 0, antennas[2] as [right, left]) in radians",
)
CREATE_HEAD_POSE = UpstreamRef(
    "reachy_mini.utils.create_head_pose",
    "VERIFIED",
    src("src/reachy_mini/utils/__init__.py", 13),
    "create_head_pose(x, y, z, roll, pitch, yaw, mm=False, degrees=True) -> 4x4",
)
LIMITS = UpstreamRef(
    "head pitch/roll ±40°, head yaw ±180°, body yaw ±160°, head-body yaw delta ≤ 65°",
    "VERIFIED",
    src("docs/source/SDK/core-concept.md", 33),
    "the daemon clamps to the closest valid pose",
)
MOTOR_NAMES = UpstreamRef(
    "body_rotation, stewart_1..stewart_6, right_antenna, left_antenna",
    "VERIFIED",
    src(_SDK, 1063),
    "the nine motors, from the enable_motors docstring",
)

# ── expression, wake and sleep, torque ──────────────────────────────────────────────────

PLAY_MOVE = UpstreamRef(
    "play_move",
    "VERIFIED",
    src(_SDK, 1171),
    "play_move = async_to_sync(async_play_move); play_move(move, play_frequency=100.0, "
    "initial_goto_duration=0.0, sound=True): a client-side wall-clock loop",
)
ASYNC_PLAY_MOVE = UpstreamRef("async_play_move", "VERIFIED", src(_SDK, 1115))
CANCEL_MOVE = UpstreamRef(
    "cancel_move",
    "VERIFIED",
    src(_SDK, 1105),
    "stops a playing move and its sound. This is quackd's stop; it is not limp.",
)
RECORDED_MOVES = UpstreamRef(
    "RecordedMoves",
    "VERIFIED",
    src(_MOVES, 176),
    "RecordedMoves(hf_dataset_name); .list_moves() -> list[str] (line 233); "
    ".get(name) -> RecordedMove (line 224)",
)
EMOTIONS_DATASET = UpstreamRef(
    "pollen-robotics/reachy-mini-emotions-library",
    "VERIFIED",
    src(_MOVES),
    "DEFAULT_EMOTIONS_DATASET, a Hugging Face Hub dataset with sidecar sounds",
)
WAKE_UP = UpstreamRef(
    "wake_up", "VERIFIED", src(_SDK, 724), "the official wake choreography; moves every joint"
)
GOTO_SLEEP = UpstreamRef("goto_sleep", "VERIFIED", src(_SDK, 740), "never sent by quackd")
ENABLE_MOTORS = UpstreamRef(
    "enable_motors", "VERIFIED", src(_SDK, 1063), "enable_motors(ids=None); torque on"
)
DISABLE_MOTORS = UpstreamRef(
    "disable_motors",
    "VERIFIED",
    src(_SDK, 1074),
    "torque off: the head goes limp. quackd NEVER sends this (ADR-0023).",
)

# ── media ───────────────────────────────────────────────────────────────────────────────

MEDIA = UpstreamRef("media", "VERIFIED", src(_SDK, 194), "mini.media -> MediaManager (property)")
MEDIA_GET_FRAME = UpstreamRef(
    "media.get_frame", "VERIFIED", src(_MEDIA, 243), "-> BGR uint8 (H, W, 3) or None"
)
MEDIA_GET_FRAME_JPEG = UpstreamRef("media.get_frame_jpeg", "VERIFIED", src(_MEDIA, 257), "-> bytes")
MEDIA_PLAY_SOUND = UpstreamRef(
    "media.play_sound",
    "VERIFIED",
    src(_MEDIA, 264),
    "play_sound(sound_file: str): an absolute path or a bundled asset name. There is no TTS "
    "anywhere in the SDK.",
)
MEDIA_PUSH_AUDIO = UpstreamRef(
    "media.push_audio_sample", "VERIFIED", src(_MEDIA, 341), "raw float32 PCM"
)
MEDIA_GET_DOA = UpstreamRef(
    "media.get_DoA",
    "VERIFIED",
    src(_MEDIA, 418),
    "-> (angle_rad, speech_detected) or None; 0 = left, pi/2 = front, pi = right",
)
MEDIA_BACKEND_NO_MEDIA = UpstreamRef(
    "no_media",
    "VERIFIED",
    src(_MEDIA, 38),
    "MediaBackend.NO_MEDIA: skips the GStreamer import chain. quackd's default unless a "
    "camera or sound verb is in the contract.",
)
NO_TTS = UpstreamRef(
    "no say / speak / tts method",
    "VERIFIED",
    src("examples/sound_tts.py", 1),
    "the only TTS example calls an external Hugging Face Space (gradio_client). quackd's say "
    "on Reachy is a mood-mapped emotion sound (ADR-0023).",
)
NO_BATTERY = UpstreamRef(
    "no battery field",
    "VERIFIED",
    src(_PROTOCOL, 147),
    "neither DaemonStatus nor StateSnapshot carries a battery; battery_percent is always None "
    "and a 'Battery below N%' abort cannot be enforced",
)
MOTOR_WATCHDOG = UpstreamRef(
    "motor liveness watchdog",
    "VERIFIED",
    src("src/reachy_mini/daemon/backend/robot/backend.py", 287),
    "more than 1 s without motor responses flags an error status; it protects the motors, "
    "not a dead client",
)

# ── assumptions of ours ─────────────────────────────────────────────────────────────────

NO_CLIENT_DEADMAN = UpstreamRef(
    "no client-disconnect deadman",
    "UNVERIFIED",
    src(_SDK),
    "Nothing found that stops motion when the SDK client vanishes: a goto finishes its "
    "duration, a play_move dies with our process. quackd keeps gaze moves short (0.3 s) and "
    "runs its own 2 Hz heartbeat.",
)
NO_ESTOP = UpstreamRef(
    "no e-stop primitive",
    "UNVERIFIED",
    src(_SDK),
    "No global emergency stop was found beyond disable_motors (limp). stop = cancel_move; a "
    "human uses the daemon or the power switch.",
)
CAMERA_YAW_COMPOSITION = UpstreamRef(
    "camera heading = body_yaw + head-pose yaw",
    "UNVERIFIED",
    src(_SDK, 926),
    "how quackd derives head_yaw_deg from get_current_joint_positions and "
    "get_current_head_pose; listed in extras.assumptions like jsonrpc's posture inference",
)
CAMERA_INTRINSICS = UpstreamRef(
    "camera field of view",
    "UNVERIFIED",
    src(_SDK, 809),
    "K and D exist (used by look_at_image) but the accessor was not read: fallback FOV 90° "
    "and extras.camera_calibrated = false, so distance estimates are uncalibrated",
)
THREAD_SAFETY = UpstreamRef(
    "concurrent SDK calls from several threads",
    "UNVERIFIED",
    src(_WS, 50),
    "a background receive thread and threading.Events; quackd serialises every call under "
    "one lock with a per-call timeout",
)
LOOK_AT_WORLD_BLOCKS = UpstreamRef(
    "look_at_world blocks for its duration",
    "UNVERIFIED",
    src(_SDK, 830),
    "goto_target waits for task completion; we assume look_at_world(duration) does too",
)
EXPRESSION_NAMES = UpstreamRef(
    "emotion move names (cheerful1, curious1, ...)",
    "UNVERIFIED",
    HF_DATASETS + "reachy-mini-emotions-library",
    "a Hub dataset, not pinned to a commit. The sdk backend reads the names from the local "
    "cache at connect and never downloads; express is omitted when the library is absent. "
    "Sim and mock use a fixed tuple.",
)


def all_refs() -> list[UpstreamRef]:
    return [v for v in globals().values() if isinstance(v, UpstreamRef)]


def refs_by_status(status: str) -> list[UpstreamRef]:
    return [r for r in all_refs() if r.status == status]
