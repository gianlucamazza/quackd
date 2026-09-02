"""The Reachy Mini's own verbs: a head that looks, expresses and voices, and never walks.

`gaze` is Reachy's own (a full 180 degrees either way, explicit pitch, no fall
precondition), registered under the same name as the Microduck's so a `.duck` that
requires `gaze` is satisfied by both. `say(text)` follows the owner's call (ADR-0023): the
SDK has no text-to-speech, so the text is logged and its mood is mapped to a recorded
emotion move with its own sound, the way the Microduck maps text to one of seven tones.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

from quackd.transport.base import DuckState, Intent
from quackd.verbs.core import SayParams, send_or_fail
from quackd.verbs.registry import NoParams, Precondition, Verb, VerbContext, VerbResult

# A curated subset of the emotion library the sim and mock know. The sdk backend reads the
# real list from the local Hugging Face cache at connect (never downloads).
EXPRESSIONS: tuple[str, ...] = (
    "amazed1",
    "attentive1",
    "cheerful1",
    "confused1",
    "curious1",
    "laughing1",
    "no1",
    "proud1",
    "sad1",
    "surprised1",
    "thoughtful1",
    "welcoming1",
    "yes1",
)
EXPRESS_S = 1.5
WAKE_UP_S = 2.0
GAZE_DIRECTIONS = {"center": 0.0, "left": 45.0, "right": -45.0, "up": 0.0, "down": 0.0}
GAZE_PITCH = {"up": 20.0, "down": -15.0}


class ReachyGazeParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    direction: Literal["center", "left", "right", "up", "down"] = Field(
        default="center", description="Where to point the head."
    )
    bearing_deg: float | None = Field(
        default=None, ge=-180, le=180, description="Exact yaw (+ = left). Overrides direction."
    )
    pitch_deg: float | None = Field(
        default=None, ge=-40, le=40, description="Exact pitch (+ = up). Overrides direction."
    )


class PlaySoundParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        ...,
        pattern=r"^[A-Za-z0-9_.-]+\.wav$",
        description="A bundled sound asset name such as wake_up.wav (no paths).",
    )


def express_params(expressions: Sequence[str]) -> type[BaseModel]:
    """An `ExpressParams` whose `name` is an enum of what THIS robot can play, so the tool
    schema the LLM sees lists the real choices."""
    literal = Literal[tuple(expressions)]  # type: ignore[valid-type]
    return create_model(  # type: ignore[call-overload, no-any-return]
        "ExpressParams",
        __config__=ConfigDict(extra="forbid"),
        name=(literal, Field(..., description="Which expression to play.")),
    )


def mood_for(text: str) -> str:
    """The Reachy analogue of the Microduck's `quack_tag_for`: a mood per phrase."""
    t = text.lower()
    if any(w in t for w in ("hello", "hi ", "hi!", "hey", "welcome", "greet")):
        return "welcoming1"
    if "?" in t:
        return "curious1"
    if any(w in t for w in ("yay", "success", "did it", "got it", "found", "well done")):
        return "cheerful1"
    if any(w in t for w in ("sad", "sorry", "oh no", "lost", "missed")):
        return "sad1"
    if any(w in t for w in ("no ", "no!", "nope", "not ")):
        return "no1"
    if "!" in t:
        return "surprised1"
    return "attentive1"


# ── preconditions the manifest references by name ───────────────────────────────────────


def _motors_enabled(state: DuckState) -> str | None:
    mode = state.extras.get("motor_mode")
    if mode in (None, "enabled"):
        return None
    return f"motors are {mode}; run wake_up (confirm-gated) or enable them from the daemon"


def reachy_conditions() -> dict[str, Precondition]:
    return {"motors_enabled": _motors_enabled}


# ── the verbs ───────────────────────────────────────────────────────────────────────────


async def gaze(ctx: VerbContext, p: ReachyGazeParams) -> VerbResult:
    bearing = p.bearing_deg if p.bearing_deg is not None else GAZE_DIRECTIONS[p.direction]
    pitch = p.pitch_deg if p.pitch_deg is not None else GAZE_PITCH.get(p.direction, 0.0)
    yaw = math.radians(bearing)
    # a unit vector in the head frame: the backends recover yaw and pitch from it
    point = (math.cos(yaw), math.sin(yaw), math.tan(math.radians(pitch)))
    ack = await ctx.transport.send_intent(Intent.look(*point))
    if not ack.accepted:
        return VerbResult.fail(f"look refused: {ack.reason or 'no reason given'}")
    shown = p.direction if p.bearing_deg is None and p.pitch_deg is None else f"{bearing:+.0f}°"
    return VerbResult.success(
        f"looking {shown}" + (" (clamped)" if ack.reason else ""),
        head_yaw_deg=bearing,
        head_pitch_deg=pitch,
        clamped=bool(ack.reason),
    )


async def express(ctx: VerbContext, p: BaseModel) -> VerbResult:
    name = str(p.name)  # type: ignore[attr-defined]
    if (fail := await send_or_fail(ctx, Intent.do(f"express:{name}"))) is not None:
        return fail
    await ctx.transport.sleep(EXPRESS_S)
    return VerbResult.success(f"played {name}", name=name, duration_s=EXPRESS_S)


async def play_sound(ctx: VerbContext, p: PlaySoundParams) -> VerbResult:
    if (fail := await send_or_fail(ctx, Intent.do(f"play_sound:{p.name}"))) is not None:
        return fail
    return VerbResult.success(f"played {p.name}", name=p.name)


async def wake_up(ctx: VerbContext, _: NoParams) -> VerbResult:
    if (fail := await send_or_fail(ctx, Intent.do("wake_up"))) is not None:
        return fail
    await ctx.transport.sleep(WAKE_UP_S)
    return VerbResult.success("awake: motors on, head at neutral")


async def say(ctx: VerbContext, p: SayParams) -> VerbResult:
    """No TTS on this robot: the text is logged and voiced as the closest emotion sound."""
    mood = mood_for(p.text)
    if (fail := await send_or_fail(ctx, Intent.sound(mood, p.text))) is not None:
        return fail
    await ctx.transport.sleep(EXPRESS_S)
    return VerbResult.success(f"said {p.text!r} as [{mood}]", text=p.text, voiced_as=mood)


def reachy_verbs(expressions: Sequence[str] = EXPRESSIONS) -> dict[str, Verb]:
    verbs = [
        Verb(
            "gaze",
            "Point the head: a direction, or an exact yaw (±180°) and pitch (±40°).",
            gaze,
            ReachyGazeParams,
            timeout_s=5,
        ),
        Verb(
            "play_sound",
            "Play one of the robot's bundled sounds by file name.",
            play_sound,
            PlaySoundParams,
            timeout_s=10,
        ),
        Verb(
            "wake_up",
            "Wake the robot: motors on and the official wake choreography. Moves every joint.",
            wake_up,
            NoParams,
            timeout_s=15,
            safety_class="confirm",
        ),
        Verb(
            "say",
            "Say something. This robot has no voice, so the text is voiced as the closest "
            "expressive sound and logged verbatim.",
            say,
            SayParams,
            timeout_s=10,
            core=True,
        ),
    ]
    if expressions:
        verbs.append(
            Verb(
                "express",
                "Play a recorded expression with its sound (antennas, head, a chirp).",
                express,
                express_params(expressions),
                timeout_s=10,
            )
        )
    return {v.name: v for v in verbs}
