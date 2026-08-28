"""Built-in verbs: one per behaviour the robot actually ships.

Each maps to an intent the transport understands (and, on hardware, to a VERIFIED upstream
method — see `transport/upstream_api.py`). The `walk` verb re-sends its velocity every
100 ms because upstream's deadman zeroes a velocity that stops arriving; that is a feature
we keep, not a quirk we hide.
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from quackd.perception.base import summarize_detections
from quackd.transport.base import DuckState, Intent
from quackd.verbs.registry import NoParams, Verb, VerbContext, VerbRegistry, VerbResult

MOVE_RESEND_S = 0.1
MAX_VX = 0.3
MAX_WZ = 1.5


class WalkParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vx: float = Field(
        default=0.15, ge=-MAX_VX, le=MAX_VX, description="Forward m/s (negative = back)."
    )
    vy: float = Field(default=0.0, ge=-0.2, le=0.2, description="Left m/s (negative = right).")
    wz: float = Field(default=0.0, ge=-MAX_WZ, le=MAX_WZ, description="Turn rate rad/s (+ = left).")
    duration_s: float = Field(
        default=1.0, gt=0, le=10, description="How long to hold this velocity."
    )


class KickParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    leg: Literal["left", "right"] = Field(default="right", description="Which leg kicks.")


class QuackParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str | None = Field(
        default=None,
        max_length=200,
        description="What to say. The robot only has duck sounds; text is mapped to a tone.",
    )


GazeDirection = Literal["center", "left", "right", "up", "down"]


class GazeParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    direction: GazeDirection = Field(default="center", description="Where to point the head.")
    bearing_deg: float | None = Field(
        default=None,
        ge=-90,
        le=90,
        description="Optional exact bearing (+ = left). Overrides direction.",
    )


def _not_fallen(state: DuckState) -> str | None:
    return "the duck has fallen; run stand_up first" if state.fallen else None


def _standing(state: DuckState) -> str | None:
    if state.fallen:
        return "the duck has fallen; run stand_up first"
    if state.posture == "sitting":
        return "the duck is sitting; run stand first"
    return None


async def _send(ctx: VerbContext, intent: Intent) -> VerbResult | None:
    """Send an intent; return a failure result if the duck refused it."""
    ack = await ctx.transport.send_intent(intent)
    if not ack.accepted:
        return VerbResult.fail(f"{intent.kind} refused: {ack.reason or 'no reason given'}")
    return None


async def walk(ctx: VerbContext, p: WalkParams) -> VerbResult:
    slices = max(1, round(p.duration_s / MOVE_RESEND_S))
    step = p.duration_s / slices
    for _ in range(slices):
        if (fail := await _send(ctx, Intent.move(p.vx, p.vy, p.wz))) is not None:
            await ctx.transport.stop()
            return fail
        await ctx.transport.sleep(step)
    await ctx.transport.stop()
    return VerbResult.success(
        f"walked vx={p.vx:.2f} vy={p.vy:.2f} wz={p.wz:.2f} for {p.duration_s:.1f}s",
        duration_s=p.duration_s,
    )


async def stop(ctx: VerbContext, _: NoParams) -> VerbResult:
    await ctx.transport.stop()
    return VerbResult.success("stopped (velocity zeroed)")


async def _sit_toggle(ctx: VerbContext, want: Literal["sitting", "standing"]) -> VerbResult:
    state = await ctx.transport.get_state()
    if state.posture == want:
        return VerbResult.success(f"already {want}")
    if (fail := await _send(ctx, Intent.do("sit_toggle"))) is not None:
        return fail
    await ctx.transport.sleep(2.0)
    state = await ctx.transport.get_state()
    if state.posture in (want, "unknown"):
        return VerbResult.success(f"now {want}" if state.posture == want else f"asked to be {want}")
    return VerbResult.fail(f"asked to be {want} but posture is {state.posture}")


async def sit(ctx: VerbContext, _: NoParams) -> VerbResult:
    return await _sit_toggle(ctx, "sitting")


async def stand(ctx: VerbContext, _: NoParams) -> VerbResult:
    return await _sit_toggle(ctx, "standing")


async def kick(ctx: VerbContext, p: KickParams) -> VerbResult:
    skill: Literal["kick_left", "kick_right"] = "kick_left" if p.leg == "left" else "kick_right"
    ack = await ctx.transport.send_intent(Intent.do(skill))
    if not ack.accepted:
        return VerbResult.fail(f"kick missed or refused: {ack.reason or 'no reason given'}")
    await ctx.transport.sleep(1.5)
    state = await ctx.transport.get_state()
    moved = state.extras.get("last_kick_ball_moved_m")
    if moved is not None:
        return VerbResult.success(
            f"kicked with {p.leg} leg; ball moved {moved:.2f} m", ball_moved_m=moved
        )
    return VerbResult.success(f"kicked with {p.leg} leg", ball_moved_m=None)


async def grab(ctx: VerbContext, _: NoParams) -> VerbResult:
    if (fail := await _send(ctx, Intent.do("ground_pick"))) is not None:
        return fail
    await ctx.transport.sleep(3.0)
    state = await ctx.transport.get_state()
    if state.holding:
        return VerbResult.success("scooped something up — it is in the beak", holding=True)
    return VerbResult.fail(
        "scooped at the floor but the beak is empty; reposition and retry", holding=False
    )


async def stand_up(ctx: VerbContext, _: NoParams) -> VerbResult:
    if (fail := await _send(ctx, Intent.enable(True))) is not None:
        return fail
    await ctx.transport.sleep(3.0)
    state = await ctx.transport.get_state()
    if state.fallen:
        return VerbResult.fail("still down; the onboard recovery has not finished")
    return VerbResult.success("upright")


def quack_tag_for(text: str | None) -> str:
    """Upstream has seven duck sounds and no TTS. Pick the one that fits the mood."""
    if not text:
        return "chirp"
    t = text.lower()
    if any(w in t for w in ("hello", "hi ", "hi!", "hey", "greet")):
        return "greet"
    if "?" in t:
        return "inquire"
    if any(w in t for w in ("alarm", "intruder", "stop!", "warning", "alert")):
        return "alarm"
    if any(w in t for w in ("yay", "whee", "wooo", "success", "did it", "got it")):
        return "wheee"
    if any(w in t for w in ("hmm", "sad", "sorry", "oh no")):
        return "coo"
    if "!" in t:
        return "peck"
    return "chirp"


async def quack(ctx: VerbContext, p: QuackParams) -> VerbResult:
    tag = quack_tag_for(p.text)
    if (fail := await _send(ctx, Intent.sound(tag, p.text))) is not None:
        return fail
    shown = f" ({p.text!r})" if p.text else ""
    return VerbResult.success(f"quacked [{tag}]{shown}", tag=tag, text=p.text)


async def gaze(ctx: VerbContext, p: GazeParams) -> VerbResult:
    bearing = p.bearing_deg
    pitch = 0.0
    if bearing is None:
        bearing = {"center": 0.0, "left": 45.0, "right": -45.0, "up": 0.0, "down": 0.0}[p.direction]
        pitch = {"up": 0.25, "down": -0.15}.get(p.direction, 0.0)
    rad = math.radians(bearing)
    point = (math.cos(rad), math.sin(rad), pitch)
    if (fail := await _send(ctx, Intent.look(*point))) is not None:
        return fail
    return VerbResult.success(
        f"looking {p.direction if p.bearing_deg is None else f'{bearing:+.0f}°'}"
    )


async def get_frame(ctx: VerbContext, _: NoParams) -> VerbResult:
    img = await ctx.transport.get_frame()
    if img is None:
        return VerbResult.fail("this transport has no camera")
    ctx.on_frame(img, "get_frame")
    detections = ctx.detector.detect(img) if ctx.detector else []
    return VerbResult.success(
        f"frame captured; {summarize_detections(detections)}",
        detections=[d.model_dump() for d in detections],
    )


def register_builtins(registry: VerbRegistry) -> None:
    registry.register(
        Verb(
            "walk",
            "Walk with a velocity for a duration. Use small values; the robot is 25 cm tall.",
            walk,
            WalkParams,
            timeout_s=15,
            preconditions=[_standing],
            done_condition="the duration has elapsed and the duck has stopped.",
        )
    )
    registry.register(
        Verb(
            "stop",
            "Stop moving immediately (zero velocity). Always allowed.",
            stop,
            NoParams,
            timeout_s=5,
        )
    )
    registry.register(
        Verb("sit", "Sit down.", sit, NoParams, timeout_s=10, preconditions=[_not_fallen])
    )
    registry.register(
        Verb(
            "stand",
            "Stand up from sitting.",
            stand,
            NoParams,
            timeout_s=10,
            preconditions=[_not_fallen],
        )
    )
    registry.register(
        Verb(
            "kick",
            "Kick forward with one leg. Only connects if the ball is < 0.3 m away and "
            "roughly ahead.",
            kick,
            KickParams,
            timeout_s=10,
            preconditions=[_standing],
            done_condition="the kick animation finished; the result says whether the ball moved.",
        )
    )
    registry.register(
        Verb(
            "grab",
            "Scoop at the floor with the beak (open-loop). Works only with the object right "
            "under the beak.",
            grab,
            NoParams,
            timeout_s=10,
            preconditions=[_standing],
            done_condition="the scoop finished; the result says whether the beak holds something.",
        )
    )
    registry.register(
        Verb("stand_up", "Recover to standing after a fall.", stand_up, NoParams, timeout_s=15)
    )
    registry.register(
        Verb(
            "quack",
            "Make a duck sound, optionally with text (mapped to a tone).",
            quack,
            QuackParams,
            timeout_s=5,
        )
    )
    registry.register(
        Verb(
            "gaze",
            "Point the head in a direction or at a bearing.",
            gaze,
            GazeParams,
            timeout_s=5,
            preconditions=[_not_fallen],
        )
    )
    registry.register(
        Verb(
            "get_frame",
            "Capture a camera frame and report what is detected in it.",
            get_frame,
            NoParams,
            timeout_s=10,
            read_only=True,
        )
    )
