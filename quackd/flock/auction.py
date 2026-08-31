"""Who kicks: a Contract Net auction, pure and synchronous so it is trivially testable.

Lowest camera-estimated ball distance wins. Ties break on the member name, so two bids in
the same instant are a non-event. A previous kicker keeps the claim unless a challenger
undercuts it by the hysteresis margin (RoboCup's anti-oscillation rule). Failed kickers
sit out a cooldown before bidding again.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from quackd.duckfile.schema import FlockSection
from quackd.flock.messages import BidMsg


@dataclass(frozen=True)
class AuctionPolicy:
    window_s: float = 0.4  # sim time collected after the FIRST bid
    hysteresis: float = 0.2  # challenger must be >= this fraction closer to unseat
    lease_s: float = 6.0
    min_sep_m: float = 0.4
    cooldown_s: float = 3.0  # a failed kicker sits out this long
    hb_timeout_s: float = 3.0  # watchdog: sim seconds without a bus HB -> presumed dead

    @classmethod
    def from_flock(cls, flock: FlockSection) -> AuctionPolicy:
        return cls(
            hysteresis=flock.allocation.hysteresis_pct / 100.0,
            lease_s=flock.allocation.claim_lease_s,
            min_sep_m=flock.safety.min_separation_m,
            hb_timeout_s=3.0 * flock.safety.per_duck_heartbeat_s,
        )


@dataclass
class AuctionDecision:
    kicker: str
    winning_dist: float
    bids: dict[str, float]
    tie: bool
    hysteresis_applied: bool


@dataclass
class Auction:
    policy: AuctionPolicy
    now: Callable[[], float]
    opened_at: float | None = None
    bids: dict[str, float] = field(default_factory=dict)

    @property
    def is_open(self) -> bool:
        return self.opened_at is not None

    def open(self, first: BidMsg) -> None:
        self.opened_at = self.now()
        self.bids = {}
        self.add(first)

    def add(self, bid: BidMsg) -> None:
        best = self.bids.get(bid.src)
        if best is None or bid.ball_dist_m < best:
            self.bids[bid.src] = bid.ball_dist_m

    def due(self) -> bool:
        return self.is_open and self.now() >= (self.opened_at or 0.0) + self.policy.window_s

    def decide(self, prev_kicker: str | None, excluded: set[str]) -> AuctionDecision | None:
        """Close the auction and pick a kicker, or None if every bidder is excluded."""
        candidates = {duck: d for duck, d in self.bids.items() if duck not in excluded}
        self.opened_at = None
        if not candidates:
            return None
        winner = min(candidates, key=lambda duck: (candidates[duck], duck))
        best = candidates[winner]
        tie = sum(1 for d in candidates.values() if d == best) > 1
        hysteresis_applied = False
        if prev_kicker is not None and prev_kicker in candidates and winner != prev_kicker:
            prev_dist = candidates[prev_kicker]
            if best >= (1.0 - self.policy.hysteresis) * prev_dist:
                winner, best = prev_kicker, prev_dist
                hysteresis_applied = True
        return AuctionDecision(
            kicker=winner,
            winning_dist=best,
            bids=dict(candidates),
            tie=tie,
            hysteresis_applied=hysteresis_applied,
        )
