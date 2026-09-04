"""Run a bounded live OpenAI benchmark against the quackd simulator.

This is deliberately manual: it performs real API calls, runs only the safe sim2d transport,
and writes only an explicitly requested artifact. The model catalog is checked before any
generation.
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

from dotenv import load_dotenv

SCENARIOS = ("hello-world", "find-and-kick", "open-duck-scout", "reachy-spotter")
DEFAULT_MODELS = ("gpt-5.6-sol",)


def _usage(summary: dict[str, object]) -> tuple[int | None, int | None]:
    usage = summary.get("usage")
    if not isinstance(usage, dict):
        return None, None
    input_tokens = usage.get("prompt_tokens", usage.get("input_tokens"))
    output_tokens = usage.get("completion_tokens", usage.get("output_tokens"))
    return (
        input_tokens if isinstance(input_tokens, int) else None,
        output_tokens if isinstance(output_tokens, int) else None,
    )


def run_one(
    model: str,
    scenario: str,
    seed: int,
    affective_context: bool,
    repeat: int,
    run_retries: int,
) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="quackd-live-") as tmp:
        root = Path(tmp)
        command = [
            sys.executable,
            "-m",
            "quackd.cli",
            "run",
            scenario,
            "--provider",
            "openai",
            "--model",
            model,
            "--seed",
            str(seed),
            "--max-steps",
            "12",
            "--yes",
            "--no-gif",
            "--no-memory",
            "--runs-dir",
            str(root / "runs"),
        ]
        if affective_context:
            command.extend(("--emotional-state", "--emotional-dir", str(root / "affective")))
            command.append("--emotional-context")
        started = time.perf_counter()
        completed = None
        attempts = 0
        for attempt in range(1, run_retries + 2):
            attempts = attempt
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
            transient = any(
                marker in completed.stderr
                for marker in ("APIConnectionError", "APITimeoutError", "RateLimitError")
            )
            if completed.returncode == 0 or not transient:
                break
        assert completed is not None
        summaries = sorted((root / "runs").glob("*/summary.json"))
        summary = json.loads(summaries[-1].read_text(encoding="utf-8")) if summaries else {}
        input_tokens, output_tokens = _usage(summary)
        return {
            "model": model,
            "scenario": scenario,
            "seed": seed,
            "repeat": repeat,
            "attempts": attempts,
            "affective": affective_context,
            "affective_context": affective_context,
            "returncode": completed.returncode,
            "success": completed.returncode == 0 and summary.get("outcome") == "success",
            "outcome": summary.get("outcome"),
            "reason": summary.get("reason"),
            "wall_s": round(time.perf_counter() - started, 3),
            "steps": summary.get("steps"),
            "llm_calls": summary.get("llm_calls"),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "affective_state_present": summary.get("affective_state") is not None,
            "stdout_tail": completed.stdout[-500:],
            "stderr_tail": completed.stderr[-500:],
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", action="append", dest="models", default=None)
    parser.add_argument("--scenario", action="append", choices=SCENARIOS, default=None)
    parser.add_argument("--seed", action="append", type=int, dest="seeds", default=None)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--run-retries", type=int, default=2)
    parser.add_argument("--output", type=Path, default=Path("/tmp/quackd-live-openai.json"))
    args = parser.parse_args()
    models = tuple(args.models or DEFAULT_MODELS)
    scenarios = tuple(args.scenario or SCENARIOS)
    seeds = tuple(args.seeds or range(10))
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    if args.run_retries < 0:
        parser.error("--run-retries must not be negative")

    load_dotenv()
    try:
        from openai import OpenAI

        catalog = {model.id for model in OpenAI(timeout=15, max_retries=0).models.list().data}
    except Exception as exc:
        print(f"preflight blocked: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    missing = sorted(set(models) - catalog)
    if missing:
        print(f"preflight blocked: models unavailable: {', '.join(missing)}", file=sys.stderr)
        raise SystemExit(2)

    rows = [
        run_one(model, scenario, seed, affective, repeat, args.run_retries)
        for model in models
        for scenario in scenarios
        for seed in seeds
        for repeat in range(args.repeats)
        for affective in (False, True)
    ]
    payload = {
        "kind": "quackd-live-openai",
        "created_at": datetime.now(UTC).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "models": models,
        "scenarios": scenarios,
        "seeds": seeds,
        "repeats": args.repeats,
        "run_retries": args.run_retries,
        "rows": rows,
    }
    grouped: dict[tuple[object, ...], dict[bool, dict[str, object]]] = {}
    for row in rows:
        key = (row["model"], row["scenario"], row["seed"], row["repeat"])
        grouped.setdefault(key, {})[bool(row["affective_context"])] = row
    pairs = [pair for pair in grouped.values() if False in pair and True in pair]
    latency_deltas = [
        ((float(pair[True]["wall_s"]) / float(pair[False]["wall_s"])) - 1) * 100
        for pair in pairs
        if float(pair[False]["wall_s"]) > 0
    ]
    payload["paired_metrics"] = {
        "pairs": len(pairs),
        "success_rate_disabled": round(
            statistics.mean(bool(pair[False]["success"]) for pair in pairs), 3
        )
        if pairs
        else 0.0,
        "success_rate_context": round(
            statistics.mean(bool(pair[True]["success"]) for pair in pairs), 3
        )
        if pairs
        else 0.0,
        "outcome_mismatches": sum(
            pair[True]["outcome"] != pair[False]["outcome"] for pair in pairs
        ),
        "step_mismatches": sum(pair[True]["steps"] != pair[False]["steps"] for pair in pairs),
        "llm_call_mismatches": sum(
            pair[True]["llm_calls"] != pair[False]["llm_calls"] for pair in pairs
        ),
        "wall_overhead_median_pct": round(statistics.median(latency_deltas), 2)
        if latency_deltas
        else 0.0,
        "pairs_with_transient_retry": sum(
            pair[False]["attempts"] > 1 or pair[True]["attempts"] > 1 for pair in pairs
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    failures = [row for row in rows if not row["success"]]
    print(f"wrote {args.output}: {len(rows) - len(failures)}/{len(rows)} successful")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
