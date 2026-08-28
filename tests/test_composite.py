"""Composite verbs close their own loops on the camera — the steering tier, tested alone."""

from __future__ import annotations

from quackd.duckfile.parser import parse_duck_text
from quackd.perception.color_blob import ColorBlobDetector
from quackd.safety import Executor
from quackd.transport.sim2d import Sim2DTransport
from quackd.verbs.registry import VerbRegistry

DUCK = parse_duck_text(
    """---
duck: 0
name: t
description: d
verbs:
  allow: [search_scan, walk_to, kick, approach_and, grab]
success: [x]
---
# Task
x
"""
)


def _executor(registry: VerbRegistry, seed: int) -> tuple[Executor, Sim2DTransport]:
    transport = Sim2DTransport(seed=seed)
    ex = Executor(registry, transport, contract=DUCK.frontmatter, detector=ColorBlobDetector())
    return ex, transport


async def test_search_scan_finds_the_ball(registry: VerbRegistry) -> None:
    ex, transport = _executor(registry, seed=4)
    result = await ex.run_verb("search_scan", {"target": "ball"})
    assert result.ok, result.summary
    _dist, bearing = transport.world.relative(transport.world.ball.x, transport.world.ball.y)
    assert abs(bearing) < 0.9  # the ball is now in the 90° field of view


async def test_walk_to_reaches_the_ball(registry: VerbRegistry) -> None:
    ex, transport = _executor(registry, seed=2)
    assert (await ex.run_verb("search_scan", {"target": "ball"})).ok
    result = await ex.run_verb("walk_to", {"target": "ball", "stop_distance": 0.25})
    assert result.ok, result.summary
    true_dist, true_bearing = transport.world.relative(
        transport.world.ball.x, transport.world.ball.y
    )
    assert true_dist <= 0.36
    assert abs(true_bearing) < 0.6


async def test_approach_and_kick_moves_the_ball(registry: VerbRegistry) -> None:
    ex, transport = _executor(registry, seed=6)
    assert (await ex.run_verb("search_scan", {"target": "ball"})).ok
    result = await ex.run_verb(
        "approach_and", {"target": "ball", "stop_distance": 0.22, "then": "kick"}
    )
    assert result.ok, result.summary
    # the kick connected; how far the ball travels also depends on walls (seed 6 bounces)
    assert transport.world.kicks_connected == 1
    assert transport.world.last_kick_ball_moved_m is not None
    assert transport.world.last_kick_ball_moved_m > 0.1


async def test_walk_to_without_detector_explains(registry: VerbRegistry) -> None:
    transport = Sim2DTransport(seed=0)
    ex = Executor(registry, transport, contract=DUCK.frontmatter, detector=None)
    result = await ex.run_verb("walk_to")
    assert not result.ok and "detector" in result.summary
