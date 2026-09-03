"""What a robot keeps between runs: the memory file, the `remember` tool, the prompt."""

from __future__ import annotations

from pathlib import Path

import pytest

from quackd.agent.loop import RunConfig, run_duck
from quackd.agent.prompts import REMEMBER_NAME, build_system_prompt
from quackd.agent.providers.base import ToolCall
from quackd.agent.providers.fake import FakeProvider
from quackd.agent.transcript import Transcript
from quackd.duckfile.schema import DuckFile
from quackd.memory import MAX_ENTRIES, RobotMemory, memory_dir, robot_slug
from quackd.transport.mock import MockTransport
from quackd.verbs.registry import default_registry

# ── the file ────────────────────────────────────────────────────────────────────────────


def test_slug_and_dir_resolution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert robot_slug("microduck:sim2d") == "microduck-sim2d"
    assert robot_slug("Open Duck::bridge") == "open-duck-bridge"
    monkeypatch.setenv("QUACKD_MEMORY_DIR", str(tmp_path / "env"))
    assert memory_dir() == tmp_path / "env"
    assert memory_dir(tmp_path / "explicit") == tmp_path / "explicit"
    mem = RobotMemory("microduck:sim2d", tmp_path)
    assert mem.path == tmp_path / "microduck-sim2d.jsonl"


def test_remember_round_trip_and_dedup(tmp_path: Path) -> None:
    mem = RobotMemory("microduck:sim2d", tmp_path)
    assert mem.recall() == ""
    a = mem.remember("  the ball is usually near   the left wall ", tags=["place"], now=1.0)
    assert a.text == "the ball is usually near the left wall"
    mem.remember("The ball is usually near the left wall", tags=["ball"], now=2.0)
    notes = mem.notes()
    assert len(notes) == 1, "same sentence twice must refresh, not duplicate"
    assert notes[0].ts == 2.0 and notes[0].tags == ["ball", "place"]
    with pytest.raises(ValueError):
        mem.remember("   ")
    assert "the ball is usually near the left wall" in mem.recall()


def test_episode_and_recall_order(tmp_path: Path) -> None:
    mem = RobotMemory("microduck:sim2d", tmp_path)
    mem.record_episode(duck="find-and-kick", outcome="failure", reason="no ball", steps=6, now=1.0)
    mem.record_episode(
        duck="find-and-kick",
        outcome="success",
        reason="ball displaced",
        steps=4,
        highlights=["search_scan: ball found at 18° left", "kick: ball moved 0.5 m"],
        now=2.0,
    )
    mem.remember("kick with the right leg works", now=3.0)
    text = mem.recall()
    assert text.index("kick with the right leg works") < text.index("Your most recent runs")
    # newest first
    assert text.index("success — ball displaced") < text.index("failure — no ball")
    assert "kick: ball moved 0.5 m" in text
    assert mem.summary() == {
        "robot": "microduck:sim2d",
        "path": str(mem.path),
        "notes": 1,
        "episodes": 2,
    }
    assert mem.clear() == 3 and not mem.path.exists() and mem.recall() == ""


def test_cap_drops_old_episodes_before_notes(tmp_path: Path) -> None:
    mem = RobotMemory("microduck:sim2d", tmp_path)
    mem.remember("keep me", now=0.0)
    for i in range(MAX_ENTRIES + 5):
        mem.record_episode(duck="d", outcome="success", reason=str(i), steps=1, now=float(i))
    entries = mem.entries()
    assert len(entries) == MAX_ENTRIES
    assert entries[0].kind == "note" and entries[0].text == "keep me"


def test_garbage_lines_are_skipped(tmp_path: Path) -> None:
    mem = RobotMemory("microduck:sim2d", tmp_path)
    mem.remember("real", now=1.0)
    with mem.path.open("a", encoding="utf-8") as f:
        f.write("not json at all\n")
    assert [e.text for e in mem.entries()] == ["real"]


# ── the prompt ──────────────────────────────────────────────────────────────────────────


def test_prompt_mentions_memory_only_when_on(hello_duck: DuckFile) -> None:
    reg = default_registry()
    verbs = [reg.view(n) for n in hello_duck.frontmatter.verbs.allow]
    off = build_system_prompt(hello_duck, verbs, "mock")
    assert "remember" not in off.lower()
    empty = build_system_prompt(hello_duck, verbs, "mock", memory_text="")
    assert "first run on this robot" in empty and "`remember`" in empty
    full = build_system_prompt(hello_duck, verbs, "mock", memory_text="- [2026-09-03] ball by sofa")
    assert "ball by sofa" in full and "first run" not in full


# ── the loop ────────────────────────────────────────────────────────────────────────────


async def test_remember_tool_saves_a_note_without_spending_a_step(
    hello_duck: DuckFile, tmp_path: Path
) -> None:
    mem = RobotMemory("microduck:mock", tmp_path / "mem")
    script = [
        ToolCall(name="quack", arguments={"text": "hi"}),
        ToolCall(name=REMEMBER_NAME, arguments={"text": "quacking first works", "tags": ["how"]}),
        ToolCall(name="declare_success", arguments={"reason": "quacked"}),
    ]
    result = await run_duck(
        RunConfig(
            duck=hello_duck,
            provider=FakeProvider(script=script),
            transport=MockTransport(),
            runs_dir=tmp_path / "runs",
            memory=mem,
        )
    )
    assert result.outcome == "success"
    assert result.steps == 1 and result.llm_calls == 3, "remember costs an LLM call, not a step"
    events = Transcript.read(result.run_dir / "transcript.jsonl")
    assert events[0]["memory"] == {
        "robot": "microduck:mock",
        "path": str(mem.path),
        "notes": 0,
        "episodes": 0,
    }
    assert REMEMBER_NAME in events[0]["tools"]
    kinds = [e["kind"] for e in events]
    assert "memory" in kinds
    mem_event = next(e for e in events if e["kind"] == "memory")
    assert mem_event["ok"] and mem_event["text"] == "quacking first works"
    # the model heard back about it on the next observation
    obs_after = [e for e in events if e["kind"] == "observation"][-1]
    assert "remembered for future runs: quacking first works" in obs_after["text"]
    # and the file now has the note plus the episode quackd wrote at the end
    assert [e.text for e in mem.notes()] == ["quacking first works"]
    episodes = mem.episodes()
    assert len(episodes) == 1 and episodes[0].outcome == "success"
    assert episodes[0].text.startswith("hello-world: success — quacked (1 steps)")
    assert episodes[0].highlights == ["quack: quacked [hi]"] or episodes[0].highlights[
        0
    ].startswith("quack:")


async def test_second_run_starts_with_what_the_first_learned(
    hello_duck: DuckFile, tmp_path: Path
) -> None:
    mem = RobotMemory("microduck:mock", tmp_path / "mem")
    first = await run_duck(
        RunConfig(
            duck=hello_duck,
            provider=FakeProvider(
                script=[
                    ToolCall(name=REMEMBER_NAME, arguments={"text": "the sofa is on the left"}),
                    ToolCall(name="declare_failure", arguments={"reason": "just testing"}),
                ]
            ),
            transport=MockTransport(),
            runs_dir=tmp_path / "runs",
            memory=mem,
        )
    )
    assert first.outcome == "failure"
    second = await run_duck(
        RunConfig(
            duck=hello_duck,
            provider=FakeProvider.for_duck("hello-world"),
            transport=MockTransport(),
            runs_dir=tmp_path / "runs",
            memory=mem,
        )
    )
    assert second.outcome == "success"
    start = Transcript.read(second.run_dir / "transcript.jsonl")[0]
    prompt = start["system_prompt"]
    assert "the sofa is on the left" in prompt
    assert "hello-world: failure — just testing" in prompt
    assert start["memory"]["notes"] == 1 and start["memory"]["episodes"] == 1
    assert len(mem.episodes()) == 2


async def test_memory_off_means_no_tool_no_episode(hello_duck: DuckFile, tmp_path: Path) -> None:
    result = await run_duck(
        RunConfig(
            duck=hello_duck,
            provider=FakeProvider.for_duck("hello-world"),
            transport=MockTransport(),
            runs_dir=tmp_path / "runs",
        )
    )
    start = Transcript.read(result.run_dir / "transcript.jsonl")[0]
    assert REMEMBER_NAME not in start["tools"] and start["memory"] is None
    assert "remember" not in start["system_prompt"].lower()


async def test_dry_run_writes_no_episode(hello_duck: DuckFile, tmp_path: Path) -> None:
    mem = RobotMemory("microduck:mock", tmp_path / "mem")
    await run_duck(
        RunConfig(
            duck=hello_duck,
            provider=FakeProvider.for_duck("hello-world"),
            transport=MockTransport(),
            runs_dir=tmp_path / "runs",
            memory=mem,
            dry_run=True,
        )
    )
    assert mem.entries() == []
