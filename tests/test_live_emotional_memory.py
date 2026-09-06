from __future__ import annotations

from typing import Any

import pytest
from emotional_memory import InMemoryStore

from benchmarks.emotional_recall import DeterministicEmbedder, _snapshot
from benchmarks.live_emotional_memory import MODES, _memory_fixture, _selection_gate
from quackd.emotional_recall import EmotionalMemoryIndex, EmotionalRecallConfig
from quackd.memory import RobotMemory


def _row(mode: str, seeded: list[dict[str, Any]], selected: list[str]) -> dict[str, Any]:
    return {
        "memory_mode": mode,
        "seeded_memories": seeded,
        "recall_evidence": (
            [{"phase": "run_start", "items": [{"source_id": item} for item in selected]}]
            if selected
            else []
        ),
    }


def test_memory_fixture_has_old_targets_and_recent_distractors() -> None:
    for scenario in ("fetch", "follow-me", "patrol-and-quack"):
        fixture = _memory_fixture(scenario)
        assert len(fixture) == 30
        assert all("target" in entry["tags"] for entry in fixture[:3])
        assert all("distractor" in entry["tags"] for entry in fixture[-5:])
        assert all(entry.get("affective") for entry in fixture)


def test_selection_gate_requires_distinct_rankings() -> None:
    seeded = [
        {"source_id": "target", "tags": ["target"], "text": "target"},
        *[
            {"source_id": f"distractor-{i}", "tags": ["distractor"], "text": str(i)}
            for i in range(29)
        ],
    ]
    rows = [
        _row("chronological", seeded, []),
        _row("semantic", seeded, ["target", "distractor-1"]),
        _row("affective", seeded, ["distractor-1", "target"]),
        _row("affective-context", seeded, ["distractor-1", "target"]),
    ]
    assert {row["memory_mode"] for row in rows} == set(MODES)
    assert _selection_gate(rows) == (True, "discriminating")

    rows[2]["recall_evidence"] = rows[1]["recall_evidence"]
    assert _selection_gate(rows) == (False, "semantic_and_affective_are_identical")


@pytest.mark.parametrize("scenario", ["fetch", "follow-me", "patrol-and-quack"])
def test_fixture_discriminates_with_offline_embeddings(tmp_path, scenario: str) -> None:
    memory = RobotMemory("microduck:sim2d", tmp_path / "memory")
    targets: set[str] = set()
    for offset, seeded in enumerate(_memory_fixture(scenario), 1):
        entry = memory.remember(
            str(seeded["text"]),
            tags=list(seeded["tags"]),
            now=float(offset),
            affective=seeded["affective"],
        )
        if "target" in seeded["tags"]:
            targets.add(entry.id)
    selected: dict[str, list[str]] = {}
    for ranking in ("semantic", "affective"):
        index = EmotionalMemoryIndex(
            memory,
            EmotionalRecallConfig(directory=tmp_path / "index", ranking=ranking, top_k=5),
            ephemeral=True,
            embedder_factory=DeterministicEmbedder,
            store_factory=lambda _path: InMemoryStore(),
        )
        recalled = index.recall(
            f"{scenario}: complete the task safely and recover from failures",
            affective=_snapshot(0.0, 0.0, 0.5),
        )
        selected[ranking] = [item.source_id for item in recalled.items]
    assert targets & set(selected["semantic"])
    assert targets & set(selected["affective"])
    assert selected["semantic"] != selected["affective"]
