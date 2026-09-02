"""The heterogeneous flock: a head spots and judges, a duck kicks, seeds 0..9, ground truth."""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from quackd.agent.providers.base import ProviderTurn, ToolCall, Usage
from quackd.agent.providers.fake import FakeProvider
from quackd.cli import app
from quackd.duckfile.parser import load_duck
from quackd.flock.runner import member_specs, run_flock

DUCK = load_duck("reachy-spots-duck-kicks")
MIN_SUCCESSES = 10 if os.environ.get("QUACKD_STRICT_SEEDS") == "1" else 8


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _bus(events: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [e["msg"] for e in events if e["kind"] == "bus" and e["msg"]["kind"] == kind]


async def _run(seed: int, tmp_path: Path, **kw: Any) -> Any:
    return await asyncio.wait_for(
        run_flock(
            DUCK,
            provider=FakeProvider.for_duck("reachy-spots-duck-kicks"),
            seed=seed,
            runs_dir=tmp_path,
            **kw,
        ),
        timeout=120,
    )


def test_member_specs_come_from_the_duck() -> None:
    specs = member_specs(["reachy-01", "duck-01"], None, DUCK.frontmatter.robots)
    assert specs["reachy-01"].key == "reachy_mini:sim2d" and specs["reachy-01"].name == "reachy-01"
    assert specs["duck-01"].key == "microduck:sim2d"
    override = member_specs(["a", "b"], {"a": "microduck:mock"}, None)
    assert override["a"].backend == "mock" and override["b"].key == "microduck:sim2d"


async def test_reachy_spots_duck_kicks_seeds(tmp_path: Path) -> None:
    successes = 0
    report = []
    for seed in range(10):
        t0 = time.perf_counter()
        result = await _run(seed, tmp_path)
        wall = time.perf_counter() - t0
        ok = result.outcome == "success" and result.ball_displacement_m >= 0.3
        successes += ok
        report.append(
            f"seed {seed}: {result.outcome} truth={result.ball_displacement_m:.2f} "
            f"verdicts={len(result.verdicts)} {wall:.1f}s ({result.reason})"
        )
        assert wall < 90, report[-1]
        events = read_jsonl(result.run_dir / "flock.jsonl")
        summary = json.loads((result.run_dir / "summary.json").read_text(encoding="utf-8"))
        assert summary["planner"]["llm_calls"] == 0
        assert summary["robots"] == {"reachy-01": "reachy_mini:sim2d", "duck-01": "microduck:sim2d"}
        assert len(events) == len([e for e in events]) and summary["bus_messages"] == len(
            [e for e in events if e["kind"] == "bus"]
        )
        # the head never moves, kicks or approaches; every kick is the duck's
        head_verbs = {e["name"] for e in events if e["kind"] == "verb" and e["duck"] == "reachy-01"}
        assert not head_verbs & {"move", "walk", "go_to", "walk_to", "kick"}
        for e in events:
            if e["kind"] == "verb" and e.get("canonical", e["name"]) in ("go_to", "kick"):
                assert e["duck"] == "duck-01"
        # no actor ever claimed success on the bus
        assert not [r for r in _bus(events, "RESULT") if r["status"] == "kicked"]
        if ok:
            assert summary["assignments"] == {"spotter": "reachy-01", "kicker": "duck-01"}
            assert summary["spotter"] == "reachy-01" and summary["kicker"] == "duck-01"
            verdicts = _bus(events, "VERDICT")
            assert verdicts and verdicts[-1]["verdict"] == "moved"
            assert verdicts[-1]["src"] == "reachy-01" and verdicts[-1]["kicker"] == "duck-01"
            kicked = [e for e in events if e["kind"] == "kick_done"]
            assert (
                kicked
                and kicked[-1]["sim_t"]
                <= [e for e in events if e["kind"] == "verdict"][-1]["sim_t"]
            )
            assert any(b["role"] == "spotter" for b in _bus(events, "BID"))
        for name in ("reachy-01", "duck-01"):
            assert (result.run_dir / "ducks" / name / "transcript.jsonl").exists()
    assert successes >= MIN_SUCCESSES, "\n".join(report)


async def test_a_lying_kicker_is_caught_by_the_spotter_and_the_world(tmp_path: Path) -> None:
    # dry run: nothing moves, so the spotter can never see a displacement
    result = await _run(2, tmp_path, dry_run=True)
    assert result.outcome != "success" and result.ball_displacement_m == 0.0


async def test_a_muted_spotter_fails_the_run_honestly(tmp_path: Path) -> None:
    def on_ready(_transport: Any, coordinator: Any) -> None:
        victim = coordinator.members["reachy-01"]
        victim._publish = lambda _msg: None  # never bids, never judges, never heartbeats
        victim.executor.abort.set()

    result = await _run(0, tmp_path, on_recorder=on_ready)
    assert result.outcome == "failure"
    events = read_jsonl(result.run_dir / "flock.jsonl")
    assert any(e["kind"] == "member_dead" and e["duck"] == "reachy-01" for e in events)
    assert not any(r["status"] == "kicked" for r in _bus(events, "RESULT"))


class _OnePlanCall:
    name = "stub"
    model = "stub-1"
    supports_vision = False

    def __init__(self) -> None:
        self.calls = 0

    async def step(self, system: str, history: Any, tools: Any) -> ProviderTurn:
        self.calls += 1
        return ProviderTurn(
            tool_calls=[ToolCall(name="plan_flock_task", arguments={"step_deg": 30})],
            usage=Usage(input_tokens=5, output_tokens=2),
        )


async def test_a_real_provider_makes_at_most_one_call(tmp_path: Path) -> None:
    stub = _OnePlanCall()
    result = await asyncio.wait_for(
        run_flock(DUCK, provider=stub, seed=3, runs_dir=tmp_path), timeout=120
    )
    summary = json.loads((result.run_dir / "summary.json").read_text(encoding="utf-8"))
    assert stub.calls == 1 and summary["planner"]["llm_calls"] == 1
    assert result.assignments.get("spotter") == "reachy-01"  # roles were never the model's to set


def test_cli_hetero_run_and_guards(tmp_path: Path) -> None:
    runner = CliRunner()
    ok = runner.invoke(
        app,
        [
            "run",
            "reachy-spots-duck-kicks",
            "--provider",
            "fake",
            "--seed",
            "3",
            "--runs-dir",
            str(tmp_path),
        ],
    )
    assert ok.exit_code == 0, ok.output
    assert "spotter=reachy-01" in ok.output and "kicker=duck-01" in ok.output
    run_dir = next(tmp_path.iterdir())
    assert (run_dir / "flock.jsonl").exists() and (run_dir / "run.gif").exists()

    mock = runner.invoke(
        app,
        [
            "run",
            "reachy-spots-duck-kicks",
            "--robots",
            "reachy-01=reachy_mini:mock,duck-01=microduck:sim2d",
            "--runs-dir",
            str(tmp_path),
        ],
    )
    assert mock.exit_code == 1 and "simulator only" in mock.output

    n = runner.invoke(
        app, ["run", "reachy-spots-duck-kicks", "--flock", "3", "--runs-dir", str(tmp_path)]
    )
    assert n.exit_code == 1 and "cannot be combined" in n.output
