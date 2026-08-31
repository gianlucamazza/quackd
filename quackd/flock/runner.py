"""Wires a flock run together: world, clock, bus, members, coordinator, recorder, summary.

The flock analogue of `agent.loop.run_duck`. Success comes from sim ground truth
(`ball_displacement_m`), so the summary cannot claim what the world did not see.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from quackd.agent.providers.base import LLMProvider, Usage
from quackd.agent.transcript import new_run_dir
from quackd.duckfile.schema import DuckFile, FlockSection
from quackd.flock.auction import AuctionPolicy
from quackd.flock.bus import InProcessBus
from quackd.flock.coordinator import FlockCoordinator, FlockOutcome
from quackd.flock.member import FlockMember
from quackd.flock.planner import plan_flock_task
from quackd.flock.transcript import FlockTranscript
from quackd.perception.color_blob import ColorBlobDetector
from quackd.transport.sim2d import make_flock


@dataclass
class FlockResult:
    outcome: FlockOutcome
    reason: str
    kicker: str | None
    auctions: int
    bids: int
    ball_displacement_m: float
    sim_elapsed_s: float
    run_dir: Path
    per_duck: dict[str, dict[str, Any]] = field(default_factory=dict)
    gif_path: Path | None = None
    usage: Usage = field(default_factory=Usage)

    @property
    def ok(self) -> bool:
        return self.outcome == "success"


async def run_flock(
    duck: DuckFile,
    *,
    provider: LLMProvider,
    seed: int = 0,
    runs_dir: str | Path = "runs",
    n_override: int | None = None,
    dry_run: bool = False,
    live: bool = False,
    gif_size: int = 256,
    on_recorder: Any = None,
    log: Any = lambda *_: None,
) -> FlockResult:
    flock: FlockSection = duck.frontmatter.flock or FlockSection()
    if n_override is not None:
        flock = flock.model_copy(update={"members": n_override})
    members = flock.member_names
    policy = AuctionPolicy.from_flock(flock)

    run_name = duck.name if duck.name.startswith("flock") else f"flock-{duck.name}"
    run_dir = new_run_dir(runs_dir, run_name)
    transports = make_flock(len(members), seed=seed, live=live)
    clock = transports[0].clock
    transcript = FlockTranscript(run_dir, now=clock.now)
    bus = InProcessBus(tap=transcript.on_bus)

    task_id = uuid.uuid4().hex[:8]
    task, wedges, usage, llm_calls, fallback = await plan_flock_task(
        duck, members, provider, task_id, log=log
    )
    task = task.model_copy(update={"success_moved_m": max(task.success_moved_m, 0.3)})
    transcript.write(
        "plan",
        task=task.model_dump(),
        wedges={k: w.model_dump() for k, w in wedges.items()},
        provider=provider.name,
        model=provider.model,
        llm_calls=llm_calls,
        fallback=fallback,
        usage=usage.model_dump(),
    )

    detectors = [ColorBlobDetector() for _ in members]
    flock_members: dict[str, FlockMember] = {}
    ordered = sorted(members)
    for i, name in enumerate(ordered):
        flock_members[name] = FlockMember(
            name,
            duck.frontmatter,
            transports[i],
            detectors[i],
            bus,
            transcript,
            task,
            hb_period_s=flock.safety.per_duck_heartbeat_s,
            dry_run=dry_run,
        )

    coordinator = FlockCoordinator(
        task=task,
        members=flock_members,
        wedges=wedges,
        bus=bus,
        clock=clock,
        transcript=transcript,
        policy=policy,
        success_moved_m=task.success_moved_m,
        log=log,
    )
    if on_recorder is not None:
        on_recorder(transports[0], coordinator)

    transcript.write(
        "flock_start",
        duck=duck.name,
        members=ordered,
        seed=seed,
        dry_run=dry_run,
        contract=duck.frontmatter.model_dump(),
    )
    wall0 = time.perf_counter()
    outcome, reason = await coordinator.run()

    world = transports[0].world
    truth = world.ball_displacement_m
    if outcome == "success" and truth < task.success_moved_m and not dry_run:
        # a member claimed a kick the world did not record: the world wins
        outcome, reason = (
            "failure",
            (f"claimed kick not confirmed by telemetry (ball moved {truth:.2f} m)"),
        )
    kicker = coordinator.kicker if coordinator.kicker is not None else coordinator.prev_kicker
    per_duck = {
        name: {
            "final_status": m.final_status,
            "steps": m.steps,
            "verbs_failed": m.verbs_failed,
            "kicks_connected": world.ducks[ordered.index(name)].kicks_connected,
        }
        for name, m in flock_members.items()
    }
    summary = {
        "duck": duck.name,
        "outcome": outcome,
        "reason": reason,
        "flock": {"members": ordered, "method": flock.allocation.method},
        "kicker": kicker,
        "auctions": coordinator.auctions,
        "bids": coordinator.bids,
        "bus_messages": bus.published,
        "ball_displacement_m": round(truth, 3),
        "planner": {
            "provider": provider.name,
            "model": provider.model,
            "llm_calls": llm_calls,
            "fallback": fallback,
            "usage": usage.model_dump(),
        },
        "policy": policy.__dict__,
        "per_duck": per_duck,
        "sim_elapsed_s": round(clock.now(), 2),
        "wall_elapsed_s": round(time.perf_counter() - wall0, 2),
        "seed": seed,
        "transport": "sim2d",
        "dry_run": dry_run,
    }
    transcript.write("flock_end", **{k: v for k, v in summary.items() if k != "per_duck"})
    transcript.write_summary(summary)
    transcript.close()
    return FlockResult(
        outcome=outcome,
        reason=reason,
        kicker=kicker,
        auctions=coordinator.auctions,
        bids=coordinator.bids,
        ball_displacement_m=truth,
        sim_elapsed_s=clock.now(),
        run_dir=run_dir,
        per_duck=per_duck,
        gif_path=None,
        usage=usage,
    )
