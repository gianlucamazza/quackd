"""Whole flock runs: the seed sweep, the one-claimant invariant, and the failure paths."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from quackd.agent.providers.fake import FakeProvider
from quackd.cli import app
from quackd.duckfile.parser import load_duck
from quackd.flock.runner import run_flock

runner = CliRunner()
DUCK = load_duck("flock-kick")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def assert_one_claimant(events: list[dict[str, Any]]) -> None:
    """Replay flock.jsonl: at most one live claim, and only the claimant approaches."""
    claimant: str | None = None
    for ev in events:
        if ev["kind"] == "auction_decision":
            assert claimant is None, "a claim was granted while another was live"
            claimant = ev["kicker"]
        elif ev["kind"] == "miss":
            if ev["duck"] == claimant:
                claimant = None
        elif ev["kind"] == "verb" and ev["name"] in ("walk_to", "kick"):
            assert ev["duck"] == claimant, f"{ev['duck']} moved on the ball without the claim"


async def test_flock_acceptance_seeds(tmp_path: Path) -> None:
    successes = 0
    report = []
    for seed in range(10):
        t0 = time.perf_counter()
        result = await run_flock(
            DUCK, provider=FakeProvider.for_duck("flock-kick"), seed=seed, runs_dir=tmp_path
        )
        wall = time.perf_counter() - t0
        ok = result.outcome == "success" and result.ball_displacement_m >= 0.3
        successes += ok
        report.append(f"seed {seed}: {result.outcome} truth={result.ball_displacement_m:.2f}")
        assert wall < 60, report[-1]
        events = read_jsonl(result.run_dir / "flock.jsonl")
        assert_one_claimant(events)
        kinds = {e["kind"] for e in events}
        assert {"plan", "bus", "flock_start", "flock_end"} <= kinds
        summary = json.loads((result.run_dir / "summary.json").read_text(encoding="utf-8"))
        assert summary["planner"]["llm_calls"] == 0  # fake provider: zero model calls
        assert summary["kicker"] in summary["flock"]["members"] or summary["kicker"] is None
        for name in summary["flock"]["members"]:
            assert (result.run_dir / "ducks" / name / "transcript.jsonl").exists()
            assert not (result.run_dir / "ducks" / name / "summary.json").exists()
    assert successes >= 8, "\n".join(report)


async def test_flock_dry_run_moves_nothing(tmp_path: Path) -> None:
    result = await run_flock(
        DUCK,
        provider=FakeProvider.for_duck("flock-kick"),
        seed=1,
        runs_dir=tmp_path,
        dry_run=True,
    )
    assert result.outcome != "success"
    assert result.ball_displacement_m == 0.0
    assert all(d["kicks_connected"] == 0 for d in result.per_duck.values())


async def test_flock_kill_switch_stops_every_duck(tmp_path: Path) -> None:
    def on_ready(_transport: Any, coordinator: Any) -> None:
        async def pull() -> None:
            await asyncio.sleep(0.2)  # wall time, mid-run
            coordinator.abort.set()

        asyncio.get_running_loop().create_task(pull())

    result = await run_flock(
        DUCK,
        provider=FakeProvider.for_duck("flock-kick"),
        seed=4,  # a seed that needs several auctions, so the pull lands mid-run
        runs_dir=tmp_path,
        on_recorder=on_ready,
    )
    assert result.outcome in ("aborted", "success")  # success only if it finished in <0.2 s
    if result.outcome == "aborted":
        assert "kill switch" in result.reason


async def test_flock_survives_a_dead_member(tmp_path: Path) -> None:
    def on_ready(_transport: Any, coordinator: Any) -> None:
        async def kill_one() -> None:
            await asyncio.sleep(0.1)
            victim = coordinator.members["duck-2"]
            await victim.transport.close()  # heartbeat dies; clock unregisters

        asyncio.get_running_loop().create_task(kill_one())

    result = await run_flock(
        DUCK,
        provider=FakeProvider.for_duck("flock-kick"),
        seed=0,
        runs_dir=tmp_path,
        on_recorder=on_ready,
    )
    # the run must END (no clock wedge) with the survivors either winning or failing
    assert result.outcome in ("success", "failure", "aborted")


def test_cli_flock_run_and_guards(tmp_path: Path) -> None:
    ok = runner.invoke(
        app,
        ["run", "flock-kick", "--provider", "fake", "--seed", "3", "--runs-dir", str(tmp_path)],
    )
    assert ok.exit_code == 0, ok.output
    assert "flock" in ok.output and "kicker=" in ok.output
    run_dir = next(tmp_path.iterdir())
    assert (run_dir / "flock.jsonl").exists() and (run_dir / "run.gif").exists()

    one = runner.invoke(app, ["run", "hello-world", "--flock", "1", "--runs-dir", str(tmp_path)])
    assert one.exit_code == 1 and "2 to 4" in one.output

    wrong_transport = runner.invoke(
        app,
        ["run", "flock-kick", "--transport", "mock", "--runs-dir", str(tmp_path)],
    )
    assert wrong_transport.exit_code == 1 and "simulator only" in wrong_transport.output


def test_cli_flock_flag_on_a_solo_duck(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "run",
            "find-and-kick",
            "--flock",
            "2",
            "--provider",
            "fake",
            "--seed",
            "1",
            "--no-gif",
            "--runs-dir",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    summary = json.loads((next(tmp_path.iterdir()) / "summary.json").read_text(encoding="utf-8"))
    assert summary["flock"]["members"] == ["duck-0", "duck-1"]


def test_validate_rejects_flock_with_confirm(tmp_path: Path) -> None:
    bad = tmp_path / "bad-flock.duck"
    bad.write_text(
        "---\nduck: 0\nname: bad-flock\ndescription: d\nverbs:\n  allow: [kick, stop]\n"
        "  confirm: [kick]\nsuccess: [x]\nflock:\n  members: 2\n---\n# T\nx\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["validate", str(bad)])
    assert result.exit_code == 1 and "y/N" in result.output


def test_serve_mcp_refuses_flock_ducks() -> None:
    from quackd.mcp_server import serve

    try:
        serve(duckfile="flock-kick")
        raise AssertionError("expected SystemExit")
    except SystemExit as e:
        assert "flock" in str(e)
