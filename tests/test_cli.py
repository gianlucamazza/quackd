"""The CLI wires things together; these tests prove the wiring, not the parts."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from quackd.cli import app

from .conftest import DUCKS

runner = CliRunner()


def test_validate_starter_ducks() -> None:
    result = runner.invoke(app, ["validate", *[str(p) for p in sorted(DUCKS.glob("*.duck"))]])
    assert result.exit_code == 0, result.output
    assert "7 file(s) valid" in result.output


def test_run_a_reachy_duck_by_its_own_default_robot(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["run", "reachy-spotter", "--provider", "fake", "--seed", "1", "--runs-dir", str(tmp_path)],
    )
    assert result.exit_code == 0, result.output
    assert "robot=reachy_mini:sim2d" in result.output and "SUCCESS" in result.output
    run_dir = next(tmp_path.iterdir())
    assert (run_dir / "run.gif").exists()  # the head cam pane, from the duck's own default robot


def test_validate_expands_globs_itself() -> None:
    result = runner.invoke(app, ["validate", str(DUCKS / "*.duck")])
    assert result.exit_code == 0, result.output


def test_validate_fails_fast(tmp_path: Path) -> None:
    bad = tmp_path / "bad.duck"
    bad.write_text("---\nduck: 0\nname: bad\n---\nbody\n", encoding="utf-8")
    unknown = tmp_path / "unknown.duck"
    unknown.write_text(
        "---\nduck: 0\nname: unknown\ndescription: d\nverbs:\n  allow: [fly]\n"
        "success: [x]\n---\n# Task\nx\n",
        encoding="utf-8",
    )
    result = runner.invoke(
        app, ["validate", str(bad), str(unknown), str(DUCKS / "hello-world.duck")]
    )
    assert result.exit_code == 1
    assert "unknown verbs: fly" in result.output
    assert "✗" in result.output and "✓" in result.output


def test_list_verbs() -> None:
    result = runner.invoke(app, ["list-verbs"])
    assert result.exit_code == 0
    for name in ("walk", "kick", "walk_to", "quack"):
        assert name in result.output


def test_run_hello_world_on_mock(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "run",
            "hello-world",
            "--provider",
            "fake",
            "--transport",
            "mock",
            "--runs-dir",
            str(tmp_path),
            "--no-gif",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "SUCCESS" in result.output
    run_dirs = list(tmp_path.iterdir())
    assert len(run_dirs) == 1 and (run_dirs[0] / "transcript.jsonl").exists()


def test_missing_extra_hint_survives_rich_markup(tmp_path: Path, monkeypatch) -> None:
    from quackd.agent.providers import factory
    from quackd.agent.providers.base import ProviderNotInstalled

    def missing(name: str, **_: object) -> None:
        raise ProviderNotInstalled(name, "anthropic")

    monkeypatch.setattr(factory, "make_provider", missing)
    result = runner.invoke(
        app,
        [
            "run",
            "hello-world",
            "--provider",
            "anthropic",
            "--transport",
            "mock",
            "--runs-dir",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 1
    assert "quackd[anthropic]" in result.output  # Rich must not eat the [anthropic] "tag"


def test_run_goal_builds_an_ad_hoc_duck(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "run",
            "--goal",
            "say hello and stop",
            "--provider",
            "fake",
            "--transport",
            "mock",
            "--runs-dir",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "goal" in result.output
    transcript = next(tmp_path.rglob("transcript.jsonl")).read_text(encoding="utf-8")
    assert "say hello and stop" in transcript  # the goal is the task body
    assert '"kick"' in transcript  # safe verbs are allowed
    assert "SUCCESS" in result.output


def test_goal_picks_a_matching_scripted_strategy(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "run",
            "--goal",
            "find the ball and kick it",
            "--provider",
            "fake",
            "--seed",
            "4",
            "--runs-dir",
            str(tmp_path),
            "--no-gif",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "scripted:goal:find-and-kick" in result.output
    transcript = next(tmp_path.rglob("transcript.jsonl")).read_text(encoding="utf-8")
    assert '"name": "kick"' in transcript  # it really kicked, not just "nothing more to do"


def test_run_needs_exactly_one_of_duck_or_goal(tmp_path: Path) -> None:
    both = runner.invoke(
        app,
        ["run", "hello-world", "--goal", "x", "--transport", "mock", "--runs-dir", str(tmp_path)],
    )
    neither = runner.invoke(app, ["run", "--transport", "mock", "--runs-dir", str(tmp_path)])
    assert both.exit_code == 1 and neither.exit_code == 1
    assert "either" in both.output and "either" in neither.output


def _run_hello(tmp_path: Path, *flags: str) -> object:
    return runner.invoke(
        app,
        [
            "run",
            "hello-world",
            "--provider",
            "fake",
            "--runs-dir",
            str(tmp_path),
            "--no-gif",
            *flags,
        ],
    )


def test_transport_flag_is_a_deprecated_alias_that_warns_once(tmp_path: Path) -> None:
    old = _run_hello(tmp_path, "--transport", "mock")
    assert old.exit_code == 0, old.output  # type: ignore[attr-defined]
    assert old.output.count("deprecated") == 1 and "--robot microduck:mock" in old.output  # type: ignore[attr-defined]
    new = _run_hello(tmp_path, "--robot", "microduck:mock")
    assert new.exit_code == 0 and "deprecated" not in new.output  # type: ignore[attr-defined]
    assert "robot=microduck:mock" in new.output  # type: ignore[attr-defined]


def test_robot_flag_errors_are_clean(tmp_path: Path) -> None:
    unknown = _run_hello(tmp_path, "--robot", "hal9000:mock")
    assert unknown.exit_code == 1 and "unknown adapter" in unknown.output  # type: ignore[attr-defined]
    both = _run_hello(tmp_path, "--robot", "microduck:mock", "--transport", "sim2d")
    assert both.exit_code == 1 and "choose one" in both.output  # type: ignore[attr-defined]


def test_list_adapters() -> None:
    result = runner.invoke(app, ["list-adapters"])
    assert result.exit_code == 0, result.output
    for needle in ("microduck", "sim2d", "mock", "jsonrpc", "--transport"):
        assert needle in result.output


def test_list_verbs_for_a_robot() -> None:
    result = runner.invoke(app, ["list-verbs", "--robot", "microduck:mock"])
    assert result.exit_code == 0 and "move" in result.output and "walk" in result.output
    bad = runner.invoke(app, ["list-verbs", "--robot", "nope"])
    assert bad.exit_code == 1 and "unknown adapter" in bad.output


def test_validate_against_a_robot(tmp_path: Path) -> None:
    ok = runner.invoke(app, ["validate", "hello-world", "--robot", "microduck:mock"])
    assert ok.exit_code == 0 and "for microduck" in ok.output
    duck = tmp_path / "needs-express.duck"
    duck.write_text(
        "---\nduck: 1\nname: needs-express\ndescription: d\nrequires: [express]\n"
        "robots: microduck:mock\nverbs:\n  allow: [quack, express, stop]\nsuccess: [x]\n"
        "---\n# Task\nx\n",
        encoding="utf-8",
    )
    bad = runner.invoke(app, ["validate", str(duck)])  # the duck's own robots: default applies
    assert bad.exit_code == 1
    # printed as a plain line under the table, so it survives any terminal width
    assert "requires express, but microduck (microduck) does not provide it" in bad.output
    with_robot = runner.invoke(app, ["validate", str(duck), "--robot", "bogus:x"])
    assert with_robot.exit_code == 1 and "unknown adapter" in with_robot.output


def test_run_unknown_provider_is_a_clean_error(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "run",
            "hello-world",
            "--provider",
            "hal9000",
            "--transport",
            "mock",
            "--runs-dir",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 1
    assert "unknown provider" in result.output
