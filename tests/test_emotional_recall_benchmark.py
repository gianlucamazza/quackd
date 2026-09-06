from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("emotional_memory")

from benchmarks.emotional_recall import ARTIFACT_KIND, run_benchmark


def test_deterministic_emotional_recall_benchmark_is_complete(tmp_path: Path) -> None:
    output = tmp_path / "result.json"
    payload = run_benchmark(output)

    assert payload["kind"] == ARTIFACT_KIND
    assert payload["status"] == "complete"
    assert len(payload["rows"]) == 4
    assert {row["ranking"] for row in payload["rows"]} == {"semantic", "affective"}
    assert all(len(row["results"]) == 3 for row in payload["rows"])
    assert output.exists()
