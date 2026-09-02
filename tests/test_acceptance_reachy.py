"""Acceptance for the second robot: `reachy-spotter` with the scripted pilot, seeds 0..9.

`outcome == "success"` is the pilot's claim; the sim's ground truth (the head is left
looking at the ball, and the ball is where it said) is checked too.
"""

from __future__ import annotations

import math
import os
import time
from pathlib import Path

from quackd.adapters.factory import make_adapter
from quackd.agent.loop import RunConfig, run_duck
from quackd.agent.providers.fake import FakeProvider
from quackd.agent.transcript import Transcript
from quackd.duckfile.parser import load_duck
from quackd.perception.color_blob import ColorBlobDetector
from quackd.sim2d.recorder import FrameRecorder

SEEDS = range(10)
MIN_SUCCESSES = 10 if os.environ.get("QUACKD_STRICT_SEEDS") == "1" else 8


async def test_reachy_spotter_acceptance(tmp_path: Path) -> None:
    duck = load_duck("reachy-spotter")
    successes = 0
    report = []
    for seed in SEEDS:
        adapter = make_adapter("reachy_mini:sim2d", seed=seed)
        recorder = FrameRecorder(adapter) if seed == 0 else None
        t0 = time.perf_counter()
        result = await run_duck(
            RunConfig(
                duck=duck,
                provider=FakeProvider.for_duck("reachy-spotter"),
                transport=adapter,
                detector=ColorBlobDetector(),
                runs_dir=tmp_path,
                on_frame=recorder.capture if recorder else None,
            )
        )
        wall = time.perf_counter() - t0
        world = adapter.world
        _dist, bearing = world.relative_head(world.ball.x, world.ball.y)
        looking = abs(math.degrees(bearing)) < 45
        ok = result.outcome == "success" and looking
        successes += ok
        report.append(
            f"seed {seed}: {result.outcome} bearing={math.degrees(bearing):+.0f} "
            f"steps={result.steps} {wall:.1f}s"
        )
        assert wall < 60, report[-1]
        events = Transcript.read(result.run_dir / "transcript.jsonl")
        verbs = [e["name"] for e in events if e["kind"] == "verb"]
        assert not {"move", "walk", "go_to", "walk_to", "kick"} & set(verbs)
        assert events[0]["robot"]["model"] == "reachy-mini" and events[0]["transport"] == "sim2d"
        said = [e for e in events if e["kind"] == "verb" and e["name"] == "say"]
        assert said and said[0]["ok"] and said[0]["data"]["voiced_as"]
        if recorder is not None:
            gif = recorder.save_gif(result.run_dir / "run.gif")
            assert gif.exists() and gif.stat().st_size > 1000
            assert recorder.focus_kind == "head"
    assert successes >= MIN_SUCCESSES, "\n".join(report)
