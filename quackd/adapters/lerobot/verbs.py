"""An arm's own verbs: joints, a gripper, place, and pick as a LeRobot policy.

The thesis holds here too: `pick` is one skill intent, and the robot's own controller (a
LeRobot policy) moves the arm; quackd never writes a grasp control law. `place` is the
one thing that needs no policy: open the gripper where it is. Joint names are the SO-101
follower's six motors, verified upstream (`upstream_api.SO_MOTORS`).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from quackd.transport.base import DuckState, Intent
from quackd.verbs.core import send_or_fail
from quackd.verbs.registry import NoParams, Precondition, Verb, VerbContext, VerbResult

JOINTS: tuple[str, ...] = (
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
    "gripper",
)
"""The SO-101 follower's motors, in bus order (upstream_api.SO_MOTORS)."""
GRIPPER_OPEN = 100.0
GRIPPER_CLOSED = 0.0
GRIPPER_S = 0.8
PICK_POLL_S = 0.5


class MoveJointsParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    positions: dict[str, float] = Field(
        ...,
        description="Joint -> goal in degrees (the gripper in 0..100). Only the joints given move.",
    )
    duration_s: float = Field(
        default=1.0, ge=0.2, le=10, description="How long to give the motion before reporting."
    )

    @field_validator("positions")
    @classmethod
    def _known_joints(cls, value: dict[str, float]) -> dict[str, float]:
        if not value:
            raise ValueError("give at least one joint")
        unknown = sorted(set(value) - set(JOINTS))
        if unknown:
            raise ValueError(f"unknown joints {unknown}; this arm has {', '.join(JOINTS)}")
        for joint, goal in value.items():
            lo, hi = (0.0, 100.0) if joint == "gripper" else (-180.0, 180.0)
            if not lo <= goal <= hi:
                raise ValueError(f"{joint}={goal} is outside {lo}..{hi}")
        return value


class GripperParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    open: bool = Field(default=True, description="True opens the gripper, False closes it.")


class PickParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str = Field(default="object", description="What to pick, as the policy's task text.")
    max_s: float = Field(default=20.0, ge=1, le=60, description="Give up after this long.")


# ── preconditions the manifest references by name ───────────────────────────────────────


def _torque_on(state: DuckState) -> str | None:
    if state.extras.get("torque", True):
        return None
    return "the arm's torque is off; enable it from LeRobot first (quackd never toggles torque)"


def _holding(state: DuckState) -> str | None:
    return None if state.holding else "nothing is held: pick something first"


def lerobot_conditions() -> dict[str, Precondition]:
    return {"torque_on": _torque_on, "holding": _holding}


# ── the verbs ───────────────────────────────────────────────────────────────────────────


async def move_joints(ctx: VerbContext, p: MoveJointsParams) -> VerbResult:
    intent = Intent.joint(dict(p.positions), p.duration_s)
    if (fail := await send_or_fail(ctx, intent)) is not None:
        return fail
    await ctx.transport.sleep(p.duration_s)
    state = await ctx.transport.get_state()
    joints: dict[str, Any] = state.extras.get("joints", {})
    return VerbResult.success(
        "moved " + ", ".join(f"{k}={v:.0f}" for k, v in p.positions.items()),
        goal=dict(p.positions),
        joints=joints,
    )


async def gripper(ctx: VerbContext, p: GripperParams) -> VerbResult:
    if (fail := await send_or_fail(ctx, Intent.gripper(p.open))) is not None:
        return fail
    await ctx.transport.sleep(GRIPPER_S)
    state = await ctx.transport.get_state()
    return VerbResult.success(
        "gripper open" if p.open else "gripper closed", open=p.open, holding=state.holding
    )


async def pick(ctx: VerbContext, p: PickParams) -> VerbResult:
    """One skill intent; the policy drives. quackd only watches the clock and `holding`."""
    if (fail := await send_or_fail(ctx, Intent.do(f"policy:pick:{p.target}"))) is not None:
        return fail
    t0 = ctx.transport.now()
    while ctx.transport.now() - t0 < p.max_s:
        await ctx.transport.sleep(PICK_POLL_S)
        state = await ctx.transport.get_state()
        if state.holding:
            return VerbResult.success(
                f"picked {p.target}", target=p.target, seconds=round(ctx.transport.now() - t0, 1)
            )
        if not str(state.policy).startswith("policy:"):
            break  # the policy finished without a grasp
    await ctx.transport.stop()
    return VerbResult.fail(f"pick {p.target!r} did not end with something held", target=p.target)


async def place(ctx: VerbContext, _: NoParams) -> VerbResult:
    if (fail := await send_or_fail(ctx, Intent.gripper(True))) is not None:
        return fail
    await ctx.transport.sleep(GRIPPER_S)
    return VerbResult.success("placed: gripper opened where the arm is")


def lerobot_verbs(*, policy: bool) -> dict[str, Verb]:
    verbs = [
        Verb(
            "move_joints",
            "Move one or more joints to goal angles in degrees (gripper 0..100). "
            "The arm's own controller does the motion.",
            move_joints,
            MoveJointsParams,
            timeout_s=15,
        ),
        Verb("gripper", "Open or close the gripper.", gripper, GripperParams, timeout_s=5),
        Verb(
            "place",
            "Release what is held by opening the gripper where the arm is.",
            place,
            NoParams,
            timeout_s=5,
        ),
    ]
    if policy:
        verbs.append(
            Verb(
                "pick",
                "Pick the target with the arm's own learned policy. Ends when something is "
                "held or the time is up.",
                pick,
                PickParams,
                timeout_s=70,
                safety_class="confirm",
            )
        )
    return {v.name: v for v in verbs}


__all__ = [
    "GRIPPER_CLOSED",
    "GRIPPER_OPEN",
    "JOINTS",
    "GripperParams",
    "MoveJointsParams",
    "PickParams",
    "lerobot_conditions",
    "lerobot_verbs",
]
