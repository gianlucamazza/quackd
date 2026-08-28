"""Composite verbs: the steering loop, written as ordinary Python.

`walk_to` is the whole argument for the three-loop design: it closes the approach loop on
detections at ~10 Hz, so the LLM decides *that* the duck should go to the ball and never
has to decide *how*. Composites call built-ins through `ctx.run_verb` where a human-visible
verb exists, and send intents directly for the tight inner loop — either way the executor's
allowlist has already admitted the composite itself.
"""

from __future__ import annotations

import math

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from quackd.perception.base import Detection
from quackd.transport.base import Intent
from quackd.verbs.registry import Verb, VerbContext, VerbRegistry, VerbResult

TICK_S = 0.1
TURN_RATE = 1.0  # rad/s used for scanning


class SearchScanParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str = Field(default="ball", description="Label to look for (e.g. ball, person).")
    step_deg: float = Field(default=45.0, ge=15, le=120, description="Rotation per step.")
    max_steps: int = Field(
        default=8, ge=1, le=16, description="Steps before giving up (8 x 45° = full turn)."
    )


class WalkToParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str = Field(default="ball", description="Label to approach.")
    stop_distance: float = Field(
        default=0.25, ge=0.1, le=1.5, description="Stop this far away (m)."
    )
    timeout_s: float = Field(default=20.0, gt=0, le=60)


class ApproachAndParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str = Field(default="ball")
    stop_distance: float = Field(default=0.25, ge=0.1, le=1.5)
    then: str = Field(..., description="Verb to run once close (e.g. kick, grab).")


async def _look_ahead(ctx: VerbContext) -> None:
    await ctx.transport.send_intent(Intent.look(1.0, 0.0, 0.0))


async def _see(
    ctx: VerbContext, label: str, caption: str
) -> tuple[Image.Image | None, list[Detection]]:
    img = await ctx.transport.get_frame()
    if img is None:
        return None, []
    ctx.on_frame(img, caption)
    dets = ctx.detector.detect(img) if ctx.detector else []
    return img, [d for d in dets if d.label == label]


async def _turn(ctx: VerbContext, radians: float) -> None:
    """Rotate in place by `radians`, feeding the deadman every tick."""
    wz = TURN_RATE if radians >= 0 else -TURN_RATE
    duration = abs(radians) / TURN_RATE
    ticks = max(1, round(duration / TICK_S))
    for _ in range(ticks):
        await ctx.transport.send_intent(Intent.move(0.0, 0.0, wz))
        await ctx.transport.sleep(duration / ticks)
    await ctx.transport.stop()


async def search_scan(ctx: VerbContext, p: SearchScanParams) -> VerbResult:
    if ctx.detector is None:
        return VerbResult.fail("search_scan needs a detector (none configured)")
    await _look_ahead(ctx)
    for i in range(p.max_steps + 1):
        img, hits = await _see(ctx, p.target, f"search_scan {i}")
        if img is None:
            return VerbResult.fail("this transport has no camera")
        if hits:
            best = hits[0]
            return VerbResult.success(
                f"{p.target} found: {best.summary()} (after {i} turn steps)",
                detections=[d.model_dump() for d in hits],
                steps=i,
            )
        if i == p.max_steps:
            break
        await _turn(ctx, math.radians(p.step_deg))
        await ctx.transport.sleep(TICK_S)  # let the view settle
    return VerbResult.fail(
        f"{p.target} not found after {p.max_steps} steps ({p.max_steps * p.step_deg:.0f}°)"
    )


async def walk_to(ctx: VerbContext, p: WalkToParams) -> VerbResult:
    if ctx.detector is None:
        return VerbResult.fail("walk_to needs a detector (none configured)")
    await _look_ahead(ctx)
    t0 = ctx.transport.now()
    lost = 0
    last_bearing = 0.0
    tick = 0
    while ctx.transport.now() - t0 < p.timeout_s:
        tick += 1
        img, hits = await _see(ctx, p.target, f"walk_to {p.target}")
        if img is None:
            return VerbResult.fail("this transport has no camera")
        if not hits:
            lost += 1
            if lost > 30:
                await ctx.transport.stop()
                return VerbResult.fail(f"lost the {p.target}; try search_scan")
            # turn toward where it was last seen
            wz = 0.8 if last_bearing >= 0 else -0.8
            await ctx.transport.send_intent(Intent.move(0.0, 0.0, wz))
            await ctx.transport.sleep(TICK_S)
            continue
        lost = 0
        d = hits[0]
        bearing = d.bearing_deg or 0.0
        dist = d.est_distance_m
        last_bearing = bearing
        if dist is not None and dist <= p.stop_distance:
            await ctx.transport.stop()
            await ctx.transport.sleep(TICK_S)
            return VerbResult.success(
                f"reached the {p.target}: ~{dist:.2f} m away, bearing {bearing:+.0f}°",
                distance_m=dist,
                bearing_deg=bearing,
                ticks=tick,
            )
        wz = max(-1.0, min(1.0, bearing * 0.05))
        vx = 0.2 if abs(bearing) < 25 else 0.05
        if dist is not None and dist < p.stop_distance + 0.15:
            vx = min(vx, 0.1)  # creep in
        await ctx.transport.send_intent(Intent.move(vx, 0.0, wz))
        await ctx.transport.sleep(TICK_S)
    await ctx.transport.stop()
    return VerbResult.fail(
        f"walk_to timed out after {p.timeout_s:g}s without reaching the {p.target}"
    )


async def approach_and(ctx: VerbContext, p: ApproachAndParams) -> VerbResult:
    if ctx.run_verb is None:
        return VerbResult.fail("approach_and needs an executor")
    first = await ctx.run_verb("walk_to", {"target": p.target, "stop_distance": p.stop_distance})
    if not first.ok:
        return first
    second = await ctx.run_verb(p.then, {})
    return VerbResult(
        ok=second.ok,
        summary=f"{first.summary}; then {p.then}: {second.summary}",
        data={"walk_to": first.data, p.then: second.data},
    )


def register_composites(registry: VerbRegistry) -> None:
    registry.register(
        Verb(
            "search_scan",
            "Rotate in steps, looking for a target. Returns where it was seen.",
            search_scan,
            SearchScanParams,
            timeout_s=60,
            kind="composite",
            done_condition="the target was detected, or a full turn found nothing.",
        )
    )
    registry.register(
        Verb(
            "walk_to",
            "Walk toward a detected target and stop at a distance. Closes the loop on the "
            "camera itself.",
            walk_to,
            WalkToParams,
            timeout_s=70,
            kind="composite",
            done_condition="within stop_distance of the target, the target was lost, or timed out.",
        )
    )
    registry.register(
        Verb(
            "approach_and",
            "walk_to a target, then run another verb (kick, grab).",
            approach_and,
            ApproachAndParams,
            timeout_s=90,
            kind="composite",
        )
    )
