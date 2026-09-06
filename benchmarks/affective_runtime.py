"""Run the deterministic quackd affective benchmark matrix.

Usage: ``uv run --extra emotional python benchmarks/affective_runtime.py``.
The output is a JSON artifact and never calls a provider or writes to the repository.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

SCENARIOS = ("hello-world", "find-and-kick", "open-duck-scout", "reachy-spotter")
SEEDS = range(10)


def run_one(scenario: str, seed: int, affective: bool, repeat: int) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="quackd-bench-") as tmp:
        root = Path(tmp)
        command = [
            sys.executable,
            "-m",
            "quackd.cli",
            "run",
            scenario,
            "--provider",
            "fake",
            "--seed",
            str(seed),
            "--no-gif",
            "--runs-dir",
            str(root / "runs"),
            "--memory-dir",
            str(root / "memory"),
        ]
        if affective:
            command.extend(("--emotional-state", "--emotional-dir", str(root / "affective")))
        start = time.perf_counter()
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        wall = time.perf_counter() - start
        summaries = sorted((root / "runs").glob("*/summary.json"))
        summary: dict[str, object] = {}
        observation_chars = 0
        feature_chars = 0
        affective_events = 0
        if summaries:
            summary = json.loads(summaries[-1].read_text(encoding="utf-8"))
            transcript = summaries[-1].parent / "transcript.jsonl"
            for line in transcript.read_text(encoding="utf-8").splitlines():
                event = json.loads(line)
                if event.get("kind") == "observation":
                    observation_chars += len(str(event.get("text", "")))
                    feature_chars += len(json.dumps(event.get("features", {}), sort_keys=True))
                if event.get("kind") == "affective":
                    affective_events += 1
        return {
            "scenario": scenario,
            "seed": seed,
            "repeat": repeat,
            "affective": affective,
            "returncode": completed.returncode,
            "success": completed.returncode == 0,
            "wall_s": round(wall, 4),
            "outcome": summary.get("outcome"),
            "steps": summary.get("steps"),
            "llm_calls": summary.get("llm_calls"),
            "affective_state": summary.get("affective_state"),
            "observation_chars": observation_chars,
            "feature_chars": feature_chars,
            "affective_events": affective_events,
            "stdout_tail": completed.stdout[-500:],
            "stderr_tail": completed.stderr[-500:],
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--output", type=Path, default=Path("/tmp/quackd-affective-benchmark.json"))
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    rows = [
        run_one(scenario, seed, affective, repeat)
        for scenario in SCENARIOS
        for seed in SEEDS
        for repeat in range(args.repeats)
        for affective in (False, True)
    ]
    payload = {
        "kind": "quackd-affective-runtime",
        "created_at": datetime.now(UTC).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "scenarios": SCENARIOS,
        "seeds": list(SEEDS),
        "repeats": args.repeats,
        "rows": rows,
    }
    metrics: dict[str, dict[str, float]] = {}
    for affective in (False, True):
        selected = [row for row in rows if row["affective"] == affective]
        walls = sorted(float(row["wall_s"]) for row in selected)
        metrics[str(affective).lower()] = {
            "wall_median_s": round(statistics.median(walls), 4),
            "wall_p95_s": round(walls[max(0, int(len(walls) * 0.95) - 1)], 4),
            "observation_chars_avg": round(
                statistics.mean(float(row["observation_chars"]) for row in selected), 2
            ),
            "feature_chars_avg": round(
                statistics.mean(float(row["feature_chars"]) for row in selected), 2
            ),
        }
    baseline = metrics["false"]["wall_median_s"]
    enabled = metrics["true"]["wall_median_s"]
    metrics["true"]["wall_overhead_pct_vs_disabled"] = round(
        ((enabled / baseline) - 1) * 100 if baseline else 0.0,
        2,
    )
    paired = {}
    for row in rows:
        key = (row["scenario"], row["seed"], row["repeat"])
        paired.setdefault(key, {})[row["affective"]] = row
    pairs = [pair for pair in paired.values() if False in pair and True in pair]
    wall_deltas = [
        ((float(pair[True]["wall_s"]) / float(pair[False]["wall_s"])) - 1) * 100
        for pair in pairs
        if float(pair[False]["wall_s"]) > 0
    ]
    payload["paired_metrics"] = {
        "pairs": len(pairs),
        "outcome_mismatches": sum(
            pair[True]["outcome"] != pair[False]["outcome"] for pair in pairs
        ),
        "step_mismatches": sum(pair[True]["steps"] != pair[False]["steps"] for pair in pairs),
        "llm_call_mismatches": sum(
            pair[True]["llm_calls"] != pair[False]["llm_calls"] for pair in pairs
        ),
        "wall_overhead_median_pct": round(statistics.median(wall_deltas), 2)
        if wall_deltas
        else 0.0,
    }
    payload["metrics"] = metrics
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    failures = [row for row in rows if not row["success"]]
    print(f"wrote {args.output}: {len(rows) - len(failures)}/{len(rows)} successful")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
