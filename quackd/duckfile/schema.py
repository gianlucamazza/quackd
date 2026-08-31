"""The machine-enforced half of a `.duck` file.

Everything in the YAML frontmatter is validated here, strictly (unknown keys are errors),
because the executor trusts this model and nothing else. The Markdown body is free text
for the LLM and is deliberately not modelled beyond "it is a string".
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DUCK_SPEC_VERSION = 0

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

# The two `abort_when` phrasings the executor enforces itself. Anything else in the list is
# passed to the LLM as an instruction, which is honest about what is and is not policed.
BATTERY_ABORT_RE = re.compile(r"battery\s+(?:below|under|<)\s*(\d+(?:\.\d+)?)\s*%", re.I)
REPEAT_FAIL_ABORT_RE = re.compile(r"same\s+verb\s+fails\s+(\d+)\s+times?\s+in\s+a\s+row", re.I)


class VerbsSection(BaseModel):
    """Which verbs the LLM may call, and which need a human to say yes first."""

    model_config = ConfigDict(extra="forbid")

    allow: list[str] = Field(
        default=..., min_length=1, description="Verbs the LLM may call. Anything else is refused."
    )
    confirm: list[str] = Field(
        default_factory=list,
        description="Verbs (subset of `allow`) that prompt a human y/N before executing.",
    )

    @field_validator("allow", "confirm")
    @classmethod
    def _unique_names(cls, names: list[str]) -> list[str]:
        seen: set[str] = set()
        for name in names:
            if not _NAME_RE.match(name.replace("_", "-")):
                raise ValueError(f"{name!r} is not a valid verb name")
            if name in seen:
                raise ValueError(f"duplicate verb {name!r}")
            seen.add(name)
        return names

    @model_validator(mode="after")
    def _confirm_subset_of_allow(self) -> VerbsSection:
        extra = [v for v in self.confirm if v not in self.allow]
        if extra:
            raise ValueError(f"confirm lists verbs that are not allowed: {extra}")
        return self


class Budgets(BaseModel):
    """Hard stops. The loop ends when any of these is hit, whatever the LLM thinks."""

    model_config = ConfigDict(extra="forbid")

    max_steps: int = Field(
        default=40, ge=1, le=1000, description="Maximum number of LLM decisions."
    )
    max_minutes: float = Field(
        default=5.0, gt=0, le=180, description="Wall-clock (or sim-clock) cap."
    )
    max_llm_calls: int = Field(default=40, ge=1, le=2000, description="Maximum provider calls.")


class LearnedVerbRef(BaseModel):
    """Reserved for v2. The shape a `.duck` will use to pull in a learned (ONNX) verb.

    See `docs/learned-verbs.md`. Parsed and validated today; nothing executes it.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Verb name it registers as.")
    policy: str = Field(..., description="Path or URL of the ONNX policy.")
    description: str = Field(default="", description="LLM-facing description.")
    metadata: dict[str, Any] = Field(default_factory=dict)


class FlockAllocation(BaseModel):
    """How a flock decides who kicks. Deterministic; the LLM never runs the auction."""

    model_config = ConfigDict(extra="forbid")

    method: Literal["auction"] = "auction"  # Contract Net; the only method in v0.3
    bid: Literal["ball_distance"] = "ball_distance"  # lower bid wins
    tie_break: Literal["duck_id"] = "duck_id"  # lexicographic member name
    hysteresis_pct: float = Field(
        default=20.0,
        ge=0,
        le=100,
        description="A challenger must bid this much lower to unseat the current claimant.",
    )
    claim_lease_s: float = Field(
        default=6.0,
        gt=0,
        le=60,
        description="Longest a claim may be held before re-auction (sim clock). A fixed "
        "fuse from the moment the claim is granted, not a progress timer.",
    )


class FlockSafety(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_separation_m: float = Field(default=0.4, ge=0.1, le=2.0)
    one_claimant: bool = Field(
        default=True,
        description="At most one duck approaches the ball at a time. Always enforced in "
        "v0.3; false is rejected rather than silently ignored.",
    )
    per_duck_heartbeat_s: float = Field(default=1.0, gt=0, le=10)

    @field_validator("one_claimant")
    @classmethod
    def _one_claimant(cls, value: bool) -> bool:
        if not value:
            raise ValueError(
                "one_claimant: false is not supported in v0.3 "
                "(the coordinator always enforces a single claimant)"
            )
        return value


class FlockSearch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    partition: Literal["heading"] = "heading"  # each duck owns a heading sector
    restart_s: float = Field(
        default=8.0,
        gt=0,
        le=120,
        description="Re-scan the sector when nothing was found for this long.",
    )


class FlockSection(BaseModel):
    """Cooperating ducks (v0.3, simulator only). The coordinator enforces this block."""

    model_config = ConfigDict(extra="forbid")

    members: int | list[str] = Field(
        default=3,
        description="Count (2-4, named duck-0..) or a list of 2-4 unique slugs.",
    )
    allocation: FlockAllocation = Field(default_factory=FlockAllocation)
    safety: FlockSafety = Field(default_factory=FlockSafety)
    search: FlockSearch = Field(default_factory=FlockSearch)

    @field_validator("members")
    @classmethod
    def _members(cls, value: int | list[str]) -> int | list[str]:
        if isinstance(value, int):
            if not 2 <= value <= 4:
                raise ValueError("a flock needs 2 to 4 ducks")
            return value
        if not 2 <= len(value) <= 4:
            raise ValueError("a flock needs 2 to 4 named ducks")
        seen: set[str] = set()
        for name in value:
            if not _NAME_RE.match(name):
                raise ValueError(f"{name!r} is not a valid member name (slug)")
            if name in seen:
                raise ValueError(f"duplicate member {name!r}")
            seen.add(name)
        return value

    @property
    def member_names(self) -> list[str]:
        if isinstance(self.members, int):
            return [f"duck-{i}" for i in range(self.members)]
        return list(self.members)


class DuckFrontmatter(BaseModel):
    """The contract. This is what `schema.json` describes and what the executor enforces."""

    model_config = ConfigDict(extra="forbid", title="quackd .duck v0 frontmatter")

    duck: Literal[0] = Field(..., description="Spec version. Only 0 exists.")
    name: str = Field(..., description="Slug: lowercase letters, digits, hyphens.")
    description: str = Field(..., min_length=1, description="One line, human-facing.")
    author: str | None = None
    verbs: VerbsSection
    budgets: Budgets = Budgets()
    success: list[str] = Field(
        default=..., min_length=1, description="Success criteria the LLM must judge itself against."
    )
    abort_when: list[str] = Field(
        default_factory=list,
        description=(
            "Abort conditions. 'Battery below N%' and 'Same verb fails N times in a row' are "
            "enforced by the executor; other entries are passed to the LLM as instructions."
        ),
    )
    persona: str | None = Field(default=None, description="Tone for the LLM. Optional.")
    providers: list[str] = Field(
        default_factory=list, description="Providers this duck was tested with (not enforced)."
    )
    learned_verbs: list[LearnedVerbRef] = Field(
        default_factory=list, description="Reserved for v2 learned verbs. Must be empty in v0.1."
    )
    flock: FlockSection | None = Field(
        default=None,
        description="Cooperating ducks (v0.3, simulator only). Absent means a single duck.",
    )

    @field_validator("name")
    @classmethod
    def _slug(cls, value: str) -> str:
        if not _NAME_RE.match(value):
            raise ValueError("name must match ^[a-z0-9][a-z0-9-]{0,63}$")
        return value

    # ── derived, machine-enforced abort thresholds ──────────────────────────────────

    @property
    def battery_abort_percent(self) -> float | None:
        for line in self.abort_when:
            m = BATTERY_ABORT_RE.search(line)
            if m:
                return float(m.group(1))
        return None

    @property
    def repeat_failure_abort(self) -> int | None:
        for line in self.abort_when:
            m = REPEAT_FAIL_ABORT_RE.search(line)
            if m:
                return int(m.group(1))
        return None

    @property
    def advisory_abort_conditions(self) -> list[str]:
        """The `abort_when` entries we cannot enforce and therefore hand to the LLM."""
        return [
            line
            for line in self.abort_when
            if not BATTERY_ABORT_RE.search(line) and not REPEAT_FAIL_ABORT_RE.search(line)
        ]


class DuckFile(BaseModel):
    """A parsed `.duck`: the enforced contract plus the LLM-facing body."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    frontmatter: DuckFrontmatter
    body: str
    path: str | None = None

    @property
    def name(self) -> str:
        return self.frontmatter.name


def json_schema() -> dict[str, Any]:
    """The JSON Schema for the frontmatter, as exported to `schema.json`."""
    schema = DuckFrontmatter.model_json_schema()
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://github.com/rokbenko/quackd/blob/main/quackd/duckfile/schema.json",
        **schema,
    }
    return schema
