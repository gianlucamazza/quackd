"""Run the deterministic quackd affective benchmark matrix.

Usage: ``uv run --extra emotional python benchmarks/affective_runtime.py``.
The output is a JSON artifact and never calls a provider or writes to the repository.
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

SCENARIOS = ("hello-world", "find-and-kick", "open-duck-scout", "reachy-spotter")
SEEDS = range(10)


def run_one(scenario: str, seed: int, affective: bool) -> dict[str, object]:
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
        if summaries:
            summary = json.loads(summaries[-1].read_text(encoding="utf-8"))
        return {
            "scenario": scenario,
            "seed": seed,
            "affective": affective,
            "returncode": completed.returncode,
            "success": completed.returncode == 0,
            "wall_s": round(wall, 4),
            "outcome": summary.get("outcome"),
            "steps": summary.get("steps"),
            "llm_calls": summary.get("llm_calls"),
            "affective_state": summary.get("affective_state"),
            "stdout_tail": completed.stdout[-500:],
            "stderr_tail": completed.stderr[-500:],
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("/tmp/quackd-affective-benchmark.json"))
    args = parser.parse_args()
    rows = [
        run_one(scenario, seed, affective)
        for scenario in SCENARIOS
        for seed in SEEDS
        for affective in (False, True)
    ]
    payload = {
        "kind": "quackd-affective-runtime",
        "created_at": datetime.now(UTC).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "scenarios": SCENARIOS,
        "seeds": list(SEEDS),
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    failures = [row for row in rows if not row["success"]]
    print(f"wrote {args.output}: {len(rows) - len(failures)}/{len(rows)} successful")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
