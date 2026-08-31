"""The referee: opens auctions, grants the one claim, watches heartbeats, judges outcome.

The coordinator is deterministic code on the same lockstep clock as the ducks (participant
"coordinator", 0.05 s sim ticks), so bid windows, leases and the watchdog are measured in
sim time and a slow LLM cannot warp them. Success is judged from sim ground truth
(`ball_displacement_m`), never from a model's claim.
"""

from __future__ import annotations

import asyncio
import contextlib
import math
from dataclasses import dataclass, field
from typing import Any, Literal

from quackd.flock.auction import Auction, AuctionPolicy
from quackd.flock.bus import Bus
from quackd.flock.member import FlockMember
from quackd.flock.messages import (
    BidMsg,
    ClaimMsg,
    FlockTask,
    HbMsg,
    ResultMsg,
    RoleMsg,
    TaskMsg,
    Wedge,
)
from quackd.flock.transcript import FlockTranscript
from quackd.sim2d.clock import FlockClock

FlockOutcome = Literal["success", "failure", "budget", "aborted", "error"]
COORD_TICK_S = 0.05
COORD_PID = "coordinator"


@dataclass
class FlockCoordinator:
    task: FlockTask
    members: dict[str, FlockMember]
    wedges: dict[str, Wedge]
    bus: Bus
    clock: FlockClock
    transcript: FlockTranscript
    policy: AuctionPolicy = field(default_factory=AuctionPolicy)
    success_moved_m: float = 0.3
    log: Any = lambda *_: None
    on_event: Any = None
    """Optional callback (kind: str, data: dict) for a recorder or a live view."""

    def __post_init__(self) -> None:
        self.abort = asyncio.Event()  # the kill switch binds here
        self.sub = self.bus.subscribe(COORD_PID)
        self.auction = Auction(self.policy, self.clock.now)
        self.kicker: str | None = None
        self.prev_kicker: str | None = None
        self.lease_deadline: float | None = None
        self.last_hb: dict[str, float] = {}
        self.excluded_until: dict[str, float] = {}
        self.auctions = 0
        self.bids = 0
        self.search_rounds = 0
        self.searching_empty: set[str] = set()
        self.outcome: FlockOutcome = "error"
        self.reason = "coordinator exited unexpectedly"

    # ── helpers ─────────────────────────────────────────────────────────────────────

    def _now(self) -> float:
        return self.clock.now()

    def _publish(self, msg: Any) -> None:
        self.bus.publish(msg)

    def _event(self, kind: str, **data: Any) -> None:
        if self.on_event is not None:
            self.on_event(kind, data)

    def _role(self, duck: str, role: str, wedge: Wedge | None = None) -> None:
        self._publish(
            RoleMsg(
                t=self._now(),
                src=COORD_PID,
                task_id=self.task.task_id,
                duck=duck,
                role=role,  # type: ignore[arg-type]
                wedge=wedge,
                min_sep_m=self.policy.min_sep_m,
            )
        )

    def _excluded_now(self) -> set[str]:
        now = self._now()
        return {d for d, until in self.excluded_until.items() if until > now}

    def _live(self) -> set[str]:
        return {name for name in self.members if self.excluded_until.get(name, 0.0) != math.inf}

    def _exclude(self, duck: str, seconds: float) -> None:
        self.excluded_until[duck] = self._now() + seconds if seconds != math.inf else math.inf

    # ── dispatch ────────────────────────────────────────────────────────────────────

    def _dispatch(self, msg: Any) -> None:
        if isinstance(msg, BidMsg):
            self.bids += 1
            if self.kicker is not None:
                return  # standby sighting while a claim is live
            if not self.auction.is_open:
                self.auction.open(msg)
                self.transcript.write("auction_open", first_bid=msg.src, dist=msg.ball_dist_m)
                self._event("auction", first_bid=msg.src, dist=msg.ball_dist_m)
            else:
                self.auction.add(msg)
        elif isinstance(msg, HbMsg):
            self.last_hb[msg.src] = msg.t
        elif isinstance(msg, ResultMsg):
            self._on_result(msg)

    def _on_result(self, msg: ResultMsg) -> None:
        if msg.status == "kicked":
            self.outcome = "success"
            moved = msg.ball_moved_m if msg.ball_moved_m is not None else 0.0
            self.reason = f"{msg.src} kicked the ball {moved:.2f} m (auction {self.auctions})"
        elif msg.status in ("miss", "fell"):
            cooldown = math.inf if msg.status == "fell" else self.policy.cooldown_s
            self._miss(msg.src, f"{msg.status}: {msg.detail}", cooldown)
        elif msg.status == "search_empty":
            self.searching_empty.add(msg.src)
        elif msg.status in ("budget", "aborted"):
            self._exclude(msg.src, math.inf)
            self.transcript.write("member_excluded", duck=msg.src, why=msg.status)
            if msg.src == self.kicker:
                self._miss(msg.src, msg.status, math.inf)

    def _miss(self, duck: str, detail: str, cooldown: float) -> None:
        self.transcript.write("miss", duck=duck, detail=detail)
        self._event("miss", duck=duck, detail=detail)
        self._exclude(duck, cooldown)
        if duck == self.kicker:
            self.prev_kicker = self.kicker
            self.kicker = None
            self.lease_deadline = None
        self.searching_empty.clear()
        # the ball moved: wedges are stale, so every live duck re-scans the full circle
        # (cooldown exclusion gates the AUCTION, not the searching)
        for name in self._live():
            self._role(name, "SEARCH", None)

    # ── phases ──────────────────────────────────────────────────────────────────────

    def _decide_if_due(self) -> None:
        if self.kicker is not None or not self.auction.due():
            return
        decision = self.auction.decide(self.prev_kicker, self._excluded_now())
        self.auctions += 1
        if decision is None:
            self.transcript.write("auction_void", auctions=self.auctions)
            return
        self.transcript.write(
            "auction_decision",
            kicker=decision.kicker,
            winning_dist=decision.winning_dist,
            bids=decision.bids,
            tie=decision.tie,
            hysteresis_applied=decision.hysteresis_applied,
        )
        self.kicker = decision.kicker
        self._event("claim", kicker=decision.kicker, dist=decision.winning_dist)
        self.lease_deadline = self._now() + self.policy.lease_s
        self._publish(
            ClaimMsg(
                t=self._now(),
                src=COORD_PID,
                task_id=self.task.task_id,
                kicker=decision.kicker,
                lease_s=self.policy.lease_s,
            )
        )
        self._role(decision.kicker, "KICK")
        for name in self.members:
            if name != decision.kicker:
                self._role(name, "YIELD")

    def _watchdog(self) -> None:
        now = self._now()
        for name in list(self._live()):
            seen = self.last_hb.get(name)
            if seen is not None and now - seen > self.policy.hb_timeout_s:
                self._exclude(name, math.inf)
                self.transcript.write("member_dead", duck=name, last_hb=seen)
                if name == self.kicker:
                    self._miss(name, "heartbeat lost while holding the claim", math.inf)

    def _rotate_wedges_if_empty(self) -> bool:
        """All live searchers came up empty: rotate the partition and try again."""
        live = self._live() - self._excluded_now()
        if self.kicker is not None or not live or not live <= self.searching_empty:
            return True
        self.search_rounds += 1
        if self.search_rounds >= self.task.max_search_rounds:
            self.outcome = "failure"
            self.reason = (
                f"no {self.task.target} found by any duck after {self.search_rounds} search rounds"
            )
            return False
        half = next(iter(self.wedges.values())).width_deg / 2
        self.wedges = {
            name: Wedge(start_deg=w.start_deg + half, end_deg=w.end_deg + half)
            for name, w in self.wedges.items()
        }
        self.searching_empty.clear()
        self.transcript.write("wedges_rotated", round=self.search_rounds, by_deg=half)
        for name in live:
            self._role(name, "SEARCH", self.wedges[name])
        return True

    # ── the run ─────────────────────────────────────────────────────────────────────

    async def run(self) -> tuple[FlockOutcome, str]:
        self.clock.register(COORD_PID)
        member_tasks = [
            asyncio.create_task(m.run(), name=f"flock-{name}") for name, m in self.members.items()
        ]
        self._publish(
            TaskMsg(
                t=self._now(),
                src=COORD_PID,
                task_id=self.task.task_id,
                task=self.task,
                members=sorted(self.members),
            )
        )
        for name in self.members:
            self._role(name, "SEARCH", self.wedges[name])
        t0 = self._now()
        self.outcome = "error"
        try:
            while True:
                for msg in self.sub.drain():
                    self._dispatch(msg)
                if self.outcome == "success":
                    break
                self._watchdog()
                self._decide_if_due()
                if (
                    self.kicker is not None
                    and self.lease_deadline is not None
                    and self._now() > self.lease_deadline
                ):
                    self._miss(self.kicker, "claim lease expired", self.policy.cooldown_s)
                if not self._rotate_wedges_if_empty():
                    break
                if self.abort.is_set():
                    self.outcome = "aborted"
                    self.reason = "kill switch"
                    for m in self.members.values():
                        m.executor.abort.set()
                    break
                if not self._live():
                    self.outcome = "failure"
                    self.reason = "every duck is excluded (dead, fallen or out of budget)"
                    break
                if self._now() - t0 > self.task.timeout_s:
                    self.outcome = "failure"
                    self.reason = f"global timeout after {self.task.timeout_s:g}s of sim time"
                    break
                await self.clock.sleep(COORD_PID, COORD_TICK_S)
        finally:
            for name in self.members:
                self._role(name, "STOP")
            # let members wind down on sim time, then hard-abort stragglers
            for _ in range(40):
                if all(t.done() for t in member_tasks):
                    break
                with contextlib.suppress(Exception):
                    await self.clock.sleep(COORD_PID, COORD_TICK_S)
            for m in self.members.values():
                m.executor.abort.set()
            self.clock.unregister(COORD_PID)
            await asyncio.gather(*member_tasks, return_exceptions=True)
            await self.clock.stop()
        return self.outcome, self.reason
