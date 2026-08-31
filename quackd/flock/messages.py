"""What ducks and the coordinator say to each other, typed and transcript-ready.

Six message kinds mirror the research report's wire sketches (TASK, BID, CLAIM, ROLE, HB,
RESULT). Timestamps are sim time from the shared clock, so a transcript replay lines up
with the world, not with wall-clock noise.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class Wedge(BaseModel):
    """A heading sector one duck owns during SEARCH, in absolute degrees."""

    model_config = ConfigDict(extra="forbid")

    start_deg: float
    end_deg: float

    @property
    def width_deg(self) -> float:
        return (self.end_deg - self.start_deg) % 360 or 360.0


class FlockTask(BaseModel):
    """The planner's output: the knobs the coordinator and the role FSMs run on."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    name: str
    goal: str
    target: str = Field(default="ball", description="Detector label to hunt.")
    kick_leg: Literal["left", "right"] = "right"
    stop_distance: float = Field(default=0.22, ge=0.1, le=1.0)
    step_deg: float = Field(default=45.0, ge=15, le=120)
    restart_s: float = Field(default=8.0, gt=0, le=120, description="Re-scan cadence.")
    timeout_s: float = Field(default=90.0, gt=0, le=600, description="Global cap, sim seconds.")
    max_search_rounds: int = Field(default=2, ge=1, le=10)
    success_moved_m: float = Field(default=0.3, gt=0, le=2.0)


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")

    t: float = Field(description="Sim time at publish, from the shared clock.")
    src: str = Field(description="Member name or 'coordinator'.")
    task_id: str


class TaskMsg(_Base):
    kind: Literal["TASK"] = "TASK"
    task: FlockTask
    members: list[str]


class BidMsg(_Base):
    kind: Literal["BID"] = "BID"
    ball_dist_m: float = Field(description="The bidder's OWN camera estimate.")
    bearing_deg: float = 0.0
    confidence: float = 1.0


class ClaimMsg(_Base):
    kind: Literal["CLAIM"] = "CLAIM"
    kicker: str
    lease_s: float = 6.0


class RoleMsg(_Base):
    kind: Literal["ROLE"] = "ROLE"
    duck: str
    role: Literal["SEARCH", "KICK", "YIELD", "STOP"]
    wedge: Wedge | None = None
    min_sep_m: float = 0.4
    retreat: bool = Field(
        default=False,
        description="YIELD only: the coordinator measured you inside the separation ring "
        "(ground truth), back away now.",
    )


class HbMsg(_Base):
    kind: Literal["HB"] = "HB"
    role: str
    posture: str = "standing"
    fallen: bool = False
    battery_percent: float | None = None
    x: float | None = None
    y: float | None = None
    steps: int = 0


class ResultMsg(_Base):
    kind: Literal["RESULT"] = "RESULT"
    status: Literal["kicked", "miss", "fell", "search_empty", "budget", "aborted"]
    detail: str = ""
    ball_moved_m: float | None = None


FlockMessage = Annotated[
    TaskMsg | BidMsg | ClaimMsg | RoleMsg | HbMsg | ResultMsg, Field(discriminator="kind")
]
