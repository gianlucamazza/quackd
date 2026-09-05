"""Run a bounded live OpenAI benchmark against the quackd simulator.

This is deliberately manual: it performs real API calls, runs only the safe sim2d transport,
and writes only an explicitly requested artifact. The model catalog is checked before any
generation.
"""

from __future__ import annotations

import argparse
import json
import os
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
TARGETED_SCENARIOS = ("fetch", "follow-me", "patrol-and-quack")
ALL_SCENARIOS = SCENARIOS + TARGETED_SCENARIOS
DEFAULT_MODELS = ("gpt-5.6-sol",)
PROVIDER_DEFAULTS = {
    "openai": ("gpt-5.6-sol", "OPENAI_API_KEY", None),
    "deepseek": ("deepseek-v4-pro", "DEEPSEEK_API_KEY", "https://api.deepseek.com"),
}


def _failure_class(returncode: int, stderr: str, outcome: object) -> str | None:
    if returncode == 0 and outcome == "success":
        return None
    if "insufficient_quota" in stderr or "credit_balance_exhausted" in stderr:
        return "quota"
    if "TimeoutExpired" in stderr or "APITimeoutError" in stderr:
        return "timeout"
    if "APIConnectionError" in stderr or "RateLimitError" in stderr:
        return "transient_provider"
    if "ProviderError" in stderr:
        return "provider"
    return "run"


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
    provider: str,
    scenario: str,
    seed: int,
    affective_context: bool,
    repeat: int,
    run_retries: int,
    run_timeout: int,
    full_task_budget: bool,
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
            provider,
            "--model",
            model,
            "--seed",
            str(seed),
            "--yes",
            "--no-gif",
            "--no-memory",
            "--runs-dir",
            str(root / "runs"),
        ]
        if not full_task_budget:
            command.extend(("--max-steps", "12"))
        if affective_context:
            command.extend(("--emotional-state", "--emotional-dir", str(root / "affective")))
            command.append("--emotional-context")
        started = time.perf_counter()
        completed = None
        attempts = 0
        for attempt in range(1, run_retries + 2):
            attempts = attempt
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=run_timeout,
                )
            except subprocess.TimeoutExpired as exc:
                completed = subprocess.CompletedProcess(
                    command,
                    124,
                    stdout=exc.stdout or "",
                    stderr=f"TimeoutExpired after {run_timeout}s",
                )
            transient = "insufficient_quota" not in completed.stderr and any(
                marker in completed.stderr
                for marker in (
                    "APIConnectionError",
                    "APITimeoutError",
                    "RateLimitError",
                    "TimeoutExpired",
                )
            )
            if completed.returncode == 0 or not transient:
                break
        assert completed is not None
        summaries = sorted((root / "runs").glob("*/summary.json"))
        summary = json.loads(summaries[-1].read_text(encoding="utf-8")) if summaries else {}
        input_tokens, output_tokens = _usage(summary)
        return {
            "provider": provider,
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
            "failure_class": _failure_class(
                completed.returncode, completed.stderr, summary.get("outcome")
            ),
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
    parser.add_argument("--provider", choices=tuple(PROVIDER_DEFAULTS), default="openai")
    parser.add_argument("--scenario", action="append", choices=ALL_SCENARIOS, default=None)
    parser.add_argument("--seed", action="append", type=int, dest="seeds", default=None)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--run-retries", type=int, default=2)
    parser.add_argument("--run-timeout", type=int, default=180)
    parser.add_argument("--resume", action="store_true", help="resume rows already in --output")
    parser.add_argument(
        "--full-task-budget",
        action="store_true",
        help="use each duck file's max_steps/max_minutes budget instead of the 12-step cap",
    )
    parser.add_argument("--output", type=Path, default=Path("/tmp/quackd-live-openai.json"))
    args = parser.parse_args()
    default_model, key_env, base_url = PROVIDER_DEFAULTS[args.provider]
    models = tuple(args.models or (default_model,))
    scenarios = tuple(args.scenario or SCENARIOS)
    seeds = tuple(args.seeds or range(10))
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    if args.run_retries < 0:
        parser.error("--run-retries must not be negative")
    if args.run_timeout < 1:
        parser.error("--run-timeout must be positive")

    load_dotenv()
    try:
        from openai import OpenAI

        catalog_client = OpenAI(
            api_key=os.environ.get(key_env),
            base_url=base_url,
            timeout=15,
            max_retries=0,
        )
        catalog = {model.id for model in catalog_client.models.list().data}
    except Exception as exc:
        print(f"preflight blocked: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    missing = sorted(set(models) - catalog)
    if missing:
        print(f"preflight blocked: models unavailable: {', '.join(missing)}", file=sys.stderr)
        raise SystemExit(2)

    rows: list[dict[str, object]] = []
    if args.resume and args.output.exists():
        saved = json.loads(args.output.read_text(encoding="utf-8"))
        if saved.get("kind") != "quackd-live-openai" or not isinstance(saved.get("rows"), list):
            parser.error("--resume requires a compatible live benchmark artifact")
        rows = [row for row in saved["rows"] if isinstance(row, dict)]
    completed_keys = {
        (
            row.get("model"),
            row.get("scenario"),
            row.get("seed"),
            row.get("repeat"),
            row.get("affective_context"),
        )
        for row in rows
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for model in models:
        for scenario in scenarios:
            for seed in seeds:
                for repeat in range(args.repeats):
                    for affective in (False, True):
                        key = (model, scenario, seed, repeat, affective)
                        if key in completed_keys:
                            continue
                        rows.append(
                            run_one(
                                model,
                                args.provider,
                                scenario,
                                seed,
                                affective,
                                repeat,
                                args.run_retries,
                                args.run_timeout,
                                args.full_task_budget,
                            )
                        )
                        completed_keys.add(key)
                        checkpoint = {
                            "kind": "quackd-live-openai",
                            "created_at": datetime.now(UTC).isoformat(),
                            "models": models,
                            "scenarios": scenarios,
                            "seeds": seeds,
                            "repeats": args.repeats,
                            "run_retries": args.run_retries,
                            "run_timeout": args.run_timeout,
                            "full_task_budget": args.full_task_budget,
                            "rows": rows,
                        }
                        args.output.write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")
    payload = {
        "kind": "quackd-live-openai",
        "created_at": datetime.now(UTC).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "models": models,
        "provider": args.provider,
        "scenarios": scenarios,
        "seeds": seeds,
        "repeats": args.repeats,
        "run_retries": args.run_retries,
        "run_timeout": args.run_timeout,
        "full_task_budget": args.full_task_budget,
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
    input_token_deltas = [
        ((int(pair[True]["input_tokens"]) / int(pair[False]["input_tokens"])) - 1) * 100
        for pair in pairs
        if isinstance(pair[False]["input_tokens"], int)
        and int(pair[False]["input_tokens"]) > 0
        and isinstance(pair[True]["input_tokens"], int)
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
        "input_token_overhead_median_pct": round(
            statistics.median(input_token_deltas),
            2,
        )
        if input_token_deltas
        else 0.0,
        "pairs_with_transient_retry": sum(
            pair[False]["attempts"] > 1 or pair[True]["attempts"] > 1 for pair in pairs
        ),
        "failure_classes": {
            failure_class: sum(row["failure_class"] == failure_class for row in rows)
            for failure_class in sorted(
                {row["failure_class"] for row in rows if row["failure_class"] is not None}
            )
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    failures = [row for row in rows if not row["success"]]
    print(f"wrote {args.output}: {len(rows) - len(failures)}/{len(rows)} successful")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
