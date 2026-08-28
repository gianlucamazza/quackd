"""Composite verbs: the steering loop, written as ordinary Python.

`walk_to` is the whole argument for the three-loop design: it closes the approach loop on
detections at ~10 Hz, so the LLM decides *that* the duck should go to the ball and never
has to decide *how*. Composites call built-ins through `ctx.run_verb` so the executor's
allowlist and budgets still apply.

Bodies land in M2 (they need the sim and the detector). Until then they register, so
`.duck` files that allow them validate, and explain themselves when called.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from quackd.verbs.registry import Verb, VerbContext, VerbRegistry, VerbResult


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


async def _not_yet(ctx: VerbContext, _p: BaseModel) -> VerbResult:
    return VerbResult.fail("composite verbs need a camera and a detector (M2)")


def register_composites(registry: VerbRegistry) -> None:
    registry.register(
        Verb(
            "search_scan",
            "Rotate in steps, looking for a target. Returns where it was seen.",
            _not_yet,
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
            _not_yet,
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
            _not_yet,
            ApproachAndParams,
            timeout_s=90,
            kind="composite",
        )
    )
