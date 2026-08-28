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
    assert "5 file(s) valid" in result.output


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


def test_run_needs_exactly_one_of_duck_or_goal(tmp_path: Path) -> None:
    both = runner.invoke(
        app,
        ["run", "hello-world", "--goal", "x", "--transport", "mock", "--runs-dir", str(tmp_path)],
    )
    neither = runner.invoke(app, ["run", "--transport", "mock", "--runs-dir", str(tmp_path)])
    assert both.exit_code == 1 and neither.exit_code == 1
    assert "either" in both.output and "either" in neither.output


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
