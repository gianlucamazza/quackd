"""The only file in quackd allowed to spell a LeRobot name (ADR-0022).

Every constant is tagged VERIFIED (read from upstream source, link given) or UNVERIFIED
(an assumption of ours, with what quackd does about it). `docs/adapters/lerobot.md` is the
human-readable version; `tests/test_upstream_api.py` proves UNVERIFIED names are only
reachable from the experimental `real` backend.

Source of truth: https://github.com/huggingface/lerobot at commit
fbb811fca92504439792b97d216f0d00c2268382 (main, 2026-09-01; read 2026-09-02). PyPI had
0.6.1 that day (requires Python >= 3.12); the pinned tree calls itself 0.6.2. Nothing here
has been run against an arm, and LeRobot is never imported outside the `real` backend.
"""

from __future__ import annotations

from quackd.transport.upstream_api import UpstreamRef

REPO = "https://github.com/huggingface/lerobot"
PIN = "fbb811fca92504439792b97d216f0d00c2268382"
READ_ON = "2026-09-02"
PYPI_VERSION_READ = "0.6.1"


def src(path: str, line: int | None = None) -> str:
    return f"{REPO}/blob/{PIN}/{path}" + (f"#L{line}" if line else "")


_ROBOT = "src/lerobot/robots/robot.py"
_UTILS = "src/lerobot/robots/utils.py"
_SO = "src/lerobot/robots/so_follower/so_follower.py"
_SO_CFG = "src/lerobot/robots/so_follower/config_so_follower.py"
_TYPES = "src/lerobot/lerobot_types.py"
_BUS = "src/lerobot/motors/motors_bus.py"
_POLICY = "src/lerobot/policies/pretrained.py"
_FACTORY = "src/lerobot/policies/factory.py"
_CAMERA = "src/lerobot/cameras/camera.py"
_OPENCV = "src/lerobot/cameras/opencv/camera_opencv.py"

# ── package ─────────────────────────────────────────────────────────────────────────────

PACKAGE = UpstreamRef("lerobot", "VERIFIED", src("pyproject.toml", 27), "PyPI and import name")
PYTHON = UpstreamRef(
    ">=3.12",
    "VERIFIED",
    src("pyproject.toml", 32),
    "requires-python; quackd's floor is 3.11, so the extra carries a python_version marker",
)
VERSION_AT_PIN = UpstreamRef("0.6.2", "VERIFIED", src("pyproject.toml", 28), "PyPI had 0.6.1")

# ── the Robot interface ─────────────────────────────────────────────────────────────────

ROBOT_BASE = UpstreamRef(
    "lerobot.robots.Robot", "VERIFIED", src(_ROBOT, 30), "the abstract base every robot implements"
)
ROBOT_CONNECT = UpstreamRef(
    "Robot.connect(calibrate=True)",
    "VERIFIED",
    src(_ROBOT, 125),
    "quackd passes calibrate=False: calibration is interactive (see ROBOT_CALIBRATE)",
)
ROBOT_DISCONNECT = UpstreamRef("Robot.disconnect()", "VERIFIED", src(_ROBOT, 209))
ROBOT_GET_OBSERVATION = UpstreamRef(
    "Robot.get_observation() -> dict",
    "VERIFIED",
    src(_ROBOT, 182),
    "a flat dict: '<motor>.pos' floats plus one array per camera, keyed by camera name",
)
ROBOT_SEND_ACTION = UpstreamRef(
    "Robot.send_action(action: dict) -> dict",
    "VERIFIED",
    src(_ROBOT, 194),
    "'<motor>.pos' -> goal; returns what was actually sent, possibly clipped",
)
ROBOT_OBSERVATION_FEATURES = UpstreamRef(
    "Robot.observation_features",
    "VERIFIED",
    src(_ROBOT, 90),
    "key -> float, or a (h, w, c) shape tuple for a camera; usable before connect()",
)
ROBOT_ACTION_FEATURES = UpstreamRef("Robot.action_features", "VERIFIED", src(_ROBOT, 104))
ROBOT_IS_CONNECTED = UpstreamRef("Robot.is_connected", "VERIFIED", src(_ROBOT, 117))
ROBOT_IS_CALIBRATED = UpstreamRef("Robot.is_calibrated", "VERIFIED", src(_ROBOT, 137))
ROBOT_CALIBRATE = UpstreamRef(
    "Robot.calibrate() is interactive",
    "VERIFIED",
    src(_SO, 118),
    "the SO follower's calibrate() calls input() (also line 131); quackd never triggers it "
    "and refuses to drive an uncalibrated arm",
)
ROBOT_CONFIGURE = UpstreamRef("Robot.configure()", "VERIFIED", src(_ROBOT, 174))
ROBOT_CONTEXT = UpstreamRef(
    "Robot.__enter__/__exit__", "VERIFIED", src(_ROBOT, 61), "connect on enter, disconnect on exit"
)
TYPES = UpstreamRef(
    "RobotAction = dict[str, Any]; RobotObservation = dict[str, Any]",
    "VERIFIED",
    src(_TYPES, 40),
)

# ── the SO-101 follower (the arm the adapter targets by default) ────────────────────────

MAKE_ROBOT = UpstreamRef(
    "lerobot.robots.make_robot_from_config(config)", "VERIFIED", src(_UTILS, 27)
)
ROBOT_TYPE_SO101 = UpstreamRef(
    "so101_follower",
    "VERIFIED",
    src(_SO_CFG, 56),
    "the registered config type; make_robot_from_config dispatches on it (utils.py line 41)",
)
SO_FOLLOWER = UpstreamRef(
    "lerobot.robots.so_follower.SO101Follower",
    "VERIFIED",
    src(_SO, 242),
    "an alias of SOFollower (SO100Follower too); exported by the package __init__",
)
SO_CONFIG = UpstreamRef(
    "SO101FollowerConfig(port, disable_torque_on_disconnect=True, max_relative_target=None, "
    "cameras={}, use_degrees=True)",
    "VERIFIED",
    src(_SO_CFG, 29),
    "an alias of SOFollowerRobotConfig; id and calibration_dir come from RobotConfig",
)
SO_MOTORS = UpstreamRef(
    "shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper",
    "VERIFIED",
    src(_SO, 54),
    "six Feetech sts3215 motors, ids 1..6",
)
SO_OBSERVATION_KEYS = UpstreamRef(
    "'<motor>.pos'", "VERIFIED", src(_SO, 184), "joint positions; the same keys are the action"
)
SO_CAMERA_KEYS = UpstreamRef(
    "camera name -> array",
    "VERIFIED",
    src(_SO, 192),
    "get_observation() adds cam.read_latest() under each configured camera's name",
)
SO_ACTION_CLAMP = UpstreamRef(
    "max_relative_target caps each step",
    "VERIFIED",
    src(_SO, 223),
    "ensure_safe_goal_position (utils.py line 93) clips a goal to present +/- the cap; "
    "None (the default) means no cap",
)
SO_DEGREES = UpstreamRef(
    "use_degrees=True -> body joints in degrees",
    "VERIFIED",
    src(_SO, 50),
    "MotorNormMode.DEGREES; False means a -100..100 range",
)
SO_GRIPPER_RANGE = UpstreamRef(
    "gripper is 0..100", "VERIFIED", src(_SO, 59), "MotorNormMode.RANGE_0_100 whatever use_degrees"
)
SO_DISCONNECT_TORQUE = UpstreamRef(
    "disconnect() disables torque by default",
    "VERIFIED",
    src(_SO, 234),
    "disable_torque_on_disconnect defaults to True (config line 31): LeRobot lets the arm go "
    "limp when the session ends; quackd keeps that default and says so",
)
SO_GRIPPER_TORQUE_LIMIT = UpstreamRef(
    "Max_Torque_Limit 500 on the gripper",
    "VERIFIED",
    src(_SO, 169),
    "configure() caps the gripper at 50 % torque and current: the native safety authority",
)
BUS_DISABLE_TORQUE = UpstreamRef(
    "MotorsBus.disable_torque()", "VERIFIED", src(_BUS, 118), "NEVER called by quackd (limp)"
)
BUS_ENABLE_TORQUE = UpstreamRef("MotorsBus.enable_torque()", "VERIFIED", src(_BUS, 113))
BUS_DISCONNECT = UpstreamRef("MotorsBus.disconnect(disable_torque=True)", "VERIFIED", src(_BUS, 82))

# ── policies (pick is a LeRobot policy, never a quackd control law) ─────────────────────

POLICY_BASE = UpstreamRef(
    "lerobot.policies.pretrained.PreTrainedPolicy", "VERIFIED", src(_POLICY, 61)
)
POLICY_FROM_PRETRAINED = UpstreamRef(
    "PreTrainedPolicy.from_pretrained(path, *, config=None, local_files_only=False, "
    "revision=None, strict=False)",
    "VERIFIED",
    src(_POLICY, 147),
    "a local directory or a Hub repo id; sets eval mode",
)
POLICY_SELECT_ACTION = UpstreamRef(
    "PreTrainedPolicy.select_action(batch: dict[str, Tensor]) -> Tensor",
    "VERIFIED",
    src(_POLICY, 292),
    "one action per call, the policy handles its own action-chunk cache",
)
POLICY_RESET = UpstreamRef("PreTrainedPolicy.reset()", "VERIFIED", src(_POLICY, 223))
GET_POLICY_CLASS = UpstreamRef(
    "lerobot.policies.factory.get_policy_class(name)", "VERIFIED", src(_FACTORY, 80)
)
MAKE_PRE_POST_PROCESSORS = UpstreamRef(
    "lerobot.policies.factory.make_pre_post_processors(policy_cfg, pretrained_path)",
    "VERIFIED",
    src(_FACTORY, 151),
    "a raw observation goes through the pre-processor and the action tensor through the "
    "post-processor before it is a RobotAction",
)
MAKE_POLICY = UpstreamRef(
    "lerobot.policies.factory.make_policy(cfg)", "VERIFIED", src(_FACTORY, 260)
)

# ── cameras ─────────────────────────────────────────────────────────────────────────────

CAMERA_ASYNC_READ = UpstreamRef(
    "Camera.async_read(timeout_ms)", "VERIFIED", src(_CAMERA, 122), "the most recent new frame"
)
CAMERA_READ = UpstreamRef("Camera.read()", "VERIFIED", src(_CAMERA, 111))
CAMERA_RGB_CONVERSION = UpstreamRef(
    "OpenCVCamera converts BGR to RGB when color_mode is RGB",
    "VERIFIED",
    src(_OPENCV, 446),
    "so a camera array's channel order is a config choice, not a constant",
)

# ── UNVERIFIED: our assumptions, and what quackd does about each ────────────────────────

NO_CLIENT_DEADMAN = UpstreamRef(
    "NO_CLIENT_DEADMAN",
    "UNVERIFIED",
    src(_ROBOT),
    "nothing in Robot stops an arm when the client goes silent; a position-controlled arm "
    "holds its last goal. quackd's stop re-sends the present position as the goal (hold) "
    "and never disables torque",
)
POLICY_PIPELINE = UpstreamRef(
    "POLICY_PIPELINE",
    "UNVERIFIED",
    src(_FACTORY, 151),
    "wiring a PreTrainedPolicy end to end (pre-processor, select_action, post-processor, "
    "device) has never been run by us. The real backend takes an injected policy with "
    "act(observation, task=...) -> action; load_policy() builds one from the verified "
    "names and is untested",
)
CAMERA_COLOR_ORDER = UpstreamRef(
    "CAMERA_COLOR_ORDER",
    "UNVERIFIED",
    src(_OPENCV, 108),
    "a camera array's channel order follows the camera config's color_mode, whose default "
    "was not read; quackd assumes RGB and records the assumption in extras",
)
GRIPPER_OPEN_VALUE = UpstreamRef(
    "GRIPPER_OPEN_VALUE",
    "UNVERIFIED",
    src(_SO, 59),
    "which end of the gripper's 0..100 range is open: quackd assumes 100 is open and 0 is "
    "closed, and cannot sense whether an object is actually held",
)
JOINT_RANGES = UpstreamRef(
    "JOINT_RANGES",
    "UNVERIFIED",
    src(_SO, 50),
    "the reachable range of each joint depends on the arm's calibration; move_joints "
    "accepts -180..180 degrees as a schema bound, the motors clip the rest",
)
SERIAL_PORT = UpstreamRef(
    "SERIAL_PORT",
    "UNVERIFIED",
    src(_SO_CFG, 29),
    "the arm's serial port (/dev/ttyACM0, COM5) comes from --address; nothing validates it "
    "before connect()",
)
THREAD_SAFETY = UpstreamRef(
    "THREAD_SAFETY",
    "UNVERIFIED",
    src(_ROBOT),
    "Robot is synchronous and not documented as thread-safe; quackd serialises every call "
    "under one lock in a worker thread with a deadline",
)


def all_refs() -> list[UpstreamRef]:
    return [v for v in globals().values() if isinstance(v, UpstreamRef)]


def refs_by_status(status: str) -> list[UpstreamRef]:
    return [r for r in all_refs() if r.status == status]
