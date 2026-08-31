"""The one place an LLM appears in a flock run, and the proof it stayed there.

Wedges are ALWAYS computed deterministically (an equal partition of the circle over the
sorted member names — the model does not get to draw geometry). A real provider gets one
forced `plan_flock_task` call to tune the task knobs; anything invalid falls back to the
deterministic defaults with a logged `planner_fallback`. The fake provider makes zero
calls. `summary.json` records `llm_calls` (0 or 1).
"""

from __future__ import annotations

from typing import Any

from quackd.agent.providers.base import Exchange, LLMProvider, Observation, Usage
from quackd.duckfile.schema import DuckFile
from quackd.flock.messages import FlockTask, Wedge

PLAN_TOOL = {
    "name": "plan_flock_task",
    "description": (
        "Plan the flock task. Choose the detector target and the approach parameters. "
        "Call this tool exactly once."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "target": {"type": "string", "description": "Detector label to hunt (e.g. ball)."},
            "kick_leg": {"type": "string", "enum": ["left", "right"]},
            "stop_distance": {"type": "number", "minimum": 0.1, "maximum": 1.0},
            "step_deg": {"type": "number", "minimum": 15, "maximum": 120},
            "timeout_s": {"type": "number", "minimum": 10, "maximum": 600},
        },
        "required": [],
        "additionalProperties": False,
    },
}

TUNABLE = ("target", "kick_leg", "stop_distance", "step_deg", "timeout_s")
CLAMPS = {"stop_distance": (0.1, 1.0), "step_deg": (15.0, 120.0), "timeout_s": (10.0, 600.0)}


def equal_wedges(members: list[str]) -> dict[str, Wedge]:
    """Deterministic search partition: the circle split equally over sorted names."""
    ordered = sorted(members)
    width = 360.0 / len(ordered)
    return {
        name: Wedge(start_deg=i * width, end_deg=(i + 1) * width) for i, name in enumerate(ordered)
    }


def default_task(duck: DuckFile, task_id: str) -> FlockTask:
    goal = duck.body.strip()
    target = "person" if "person" in duck.name else "ball"
    flock = duck.frontmatter.flock
    restart_s = flock.search.restart_s if flock is not None else 8.0
    return FlockTask(task_id=task_id, name=duck.name, goal=goal, target=target, restart_s=restart_s)


async def plan_flock_task(
    duck: DuckFile,
    members: list[str],
    provider: LLMProvider,
    task_id: str,
    log: Any = lambda *_: None,
) -> tuple[FlockTask, dict[str, Wedge], Usage, int, bool]:
    """Returns (task, wedges, usage, llm_calls, fallback_used)."""
    wedges = equal_wedges(members)
    task = default_task(duck, task_id)
    if provider.name == "fake":
        return task, wedges, Usage(), 0, False
    prompt = (
        "You are planning a task for a flock of small duck robots in a 2 m square arena. "
        f"Members: {', '.join(sorted(members))}. Each will search its own heading sector, "
        "the closest sighting wins an auction, and the winner approaches and kicks.\n\n"
        f"Task file '{duck.name}':\n{duck.body}\n\n"
        "Call plan_flock_task once with your chosen parameters (omit any you would keep "
        "at the defaults)."
    )
    fallback = False
    usage = Usage()
    try:
        turn = await provider.step(
            "You plan tasks for cooperating duck robots. Answer with one tool call.",
            [Exchange(observation=Observation(text=prompt))],
            [PLAN_TOOL],
        )
        usage = turn.usage
        call = next((c for c in turn.tool_calls if c.name == "plan_flock_task"), None)
        if call is None:
            raise ValueError("no plan_flock_task call in the reply")
        # per-field: numeric arguments clamp into range, the rest validate individually,
        # so one bad argument never discards the model's valid choices
        dropped: dict[str, Any] = {}
        for k, v in call.arguments.items():
            if k not in TUNABLE:
                continue
            if k in CLAMPS and isinstance(v, int | float) and not isinstance(v, bool):
                lo, hi = CLAMPS[k]
                v = min(max(float(v), lo), hi)
            try:
                task = FlockTask(**{**task.model_dump(), k: v})
            except Exception:
                dropped[k] = v
        if dropped:
            log(f"planner dropped invalid arguments: {dropped}")
    except Exception as e:  # planner trouble (refusal, no call, network) -> defaults
        fallback = True
        log(f"planner fallback: {type(e).__name__}: {e}")
        task = default_task(duck, task_id)
    return task, wedges, usage, 1, fallback
