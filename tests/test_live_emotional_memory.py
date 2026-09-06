from __future__ import annotations

from typing import Any

from benchmarks.live_emotional_memory import MODES, _memory_fixture, _selection_gate


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
