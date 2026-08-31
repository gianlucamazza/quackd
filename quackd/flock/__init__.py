"""The flock: several simulated Microducks cooperating on one task.

This package exists so that cooperation is *inspectable*: every message between ducks
travels over a tiny in-process bus and lands in a transcript, the kicker is chosen by a
deterministic auction rather than model vibes, and the LLM contributes at most one
planning call per run. Simulator only in v0.3; the bus is a protocol so a LAN bus can
slot in later.
"""

from quackd.flock.runner import FlockResult, run_flock

__all__ = ["FlockResult", "run_flock"]
