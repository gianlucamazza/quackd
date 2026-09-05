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
import random
import statistics
import subprocess
import sys
import tempfile
import time
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

if __package__:
    from .verification import verify
else:
    from verification import verify

SCENARIOS = ("hello-world", "find-and-kick", "open-duck-scout", "reachy-spotter")
TARGETED_SCENARIOS = ("fetch", "follow-me", "patrol-and-quack")
ALL_SCENARIOS = SCENARIOS + TARGETED_SCENARIOS
ARTIFACT_KIND = "quackd-live-v2"
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


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)


def _config(
    args: argparse.Namespace,
    models: tuple[str, ...],
    scenarios: tuple[str, ...],
    seeds: tuple[int, ...],
) -> dict[str, object]:
    return {
        "provider": args.provider,
        "models": list(models),
        "scenarios": list(scenarios),
        "seeds": list(seeds),
        "repeats": args.repeats,
        "full_task_budget": args.full_task_budget,
        "run_timeout": args.run_timeout,
        "run_retries": args.run_retries,
        "verifier_version": 1,
    }


def _success_delta_ci(pairs: list[dict[bool, dict[str, object]]]) -> tuple[float, float]:
    """Deterministic paired bootstrap CI for context minus baseline success."""
    if not pairs:
        return 0.0, 0.0
    deltas = [int(pair[True]["success"]) - int(pair[False]["success"]) for pair in pairs]
    rng = random.Random(0)
    samples = [statistics.mean(rng.choice(deltas) for _ in deltas) for _ in range(10_000)]
    samples.sort()
    return round(samples[250], 3), round(samples[9749], 3)


def _compatible_artifact(saved: object, expected_config: dict[str, object]) -> bool:
    compatible = (
        isinstance(saved, dict)
        and saved.get("kind") == ARTIFACT_KIND
        and isinstance(saved.get("rows"), list)
        and saved.get("config") == expected_config
    )
    if not compatible:
        return False
    seen = set()
    for row in saved["rows"]:
        if not isinstance(row, dict):
            return False
        key = tuple(
            row.get(k) for k in ("model", "scenario", "seed", "repeat", "affective_context")
        )
        if (
            row.get("provider") != expected_config["provider"]
            or row.get("model") not in expected_config["models"]
            or row.get("scenario") not in expected_config["scenarios"]
            or row.get("seed") not in expected_config["seeds"]
            or type(row.get("repeat")) is not int
            or not 0 <= row["repeat"] < expected_config["repeats"]
            or type(row.get("affective_context")) is not bool
        ):
            return False
        if key in seen:
            return False
        seen.add(key)
    return True


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
    evidence_dir: Path | None = None,
) -> dict[str, object]:
    if evidence_dir is not None:
        evidence_dir.mkdir(parents=True, exist_ok=True)
    directory = (
        nullcontext(tempfile.mkdtemp(prefix="run-", dir=evidence_dir))
        if evidence_dir is not None
        else tempfile.TemporaryDirectory(prefix="quackd-live-")
    )
    with directory as tmp:
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
            attempt_root = root / f"attempt-{attempt}"
            command[command.index("--runs-dir") + 1] = str(attempt_root / "runs")
            if affective_context:
                command[command.index("--emotional-dir") + 1] = str(attempt_root / "affective")
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
        summaries = sorted((attempt_root / "runs").glob("*/summary.json"))
        summary = json.loads(summaries[-1].read_text(encoding="utf-8")) if summaries else {}
        events = (
            [
                json.loads(line)
                for line in (summaries[-1].parent / "transcript.jsonl").read_text().splitlines()
            ]
            if summaries
            else []
        )
        verification = verify(scenario, summary, events)
        input_tokens, output_tokens = _usage(summary)
        final_state = summary.get("final_state")
        extras = final_state.get("extras", {}) if isinstance(final_state, dict) else {}
        ground_truth_success: bool | None = None
        if scenario == "find-and-kick" and isinstance(extras, dict):
            displacement = extras.get("ball_displacement_m")
            if isinstance(displacement, (int, float)):
                ground_truth_success = float(displacement) >= 0.3
        return {
            "provider": provider,
            "evidence_dir": str(root) if evidence_dir is not None else None,
            "verified_success": verification["success"],
            "verification": verification,
            "model": model,
            "scenario": scenario,
            "seed": seed,
            "repeat": repeat,
            "attempts": attempts,
            "affective": affective_context,
            "affective_context": affective_context,
            "returncode": completed.returncode,
            "success": completed.returncode == 0 and summary.get("outcome") == "success",
            "model_claim_success": (
                completed.returncode == 0 and summary.get("outcome") == "success"
            ),
            "ground_truth_success": ground_truth_success,
            "success_basis": "model_claim" if ground_truth_success is None else "model_claim+sim2d",
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
        expected_config = _config(args, models, scenarios, seeds)
        if not _compatible_artifact(saved, expected_config):
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
                    for affective in (False, True) if (seed + repeat) % 2 == 0 else (True, False):
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
                                args.output.with_suffix(".runs"),
                            )
                        )
                        completed_keys.add(key)
                        checkpoint = {
                            "kind": ARTIFACT_KIND,
                            "created_at": datetime.now(UTC).isoformat(),
                            "provider": args.provider,
                            "models": models,
                            "scenarios": scenarios,
                            "seeds": seeds,
                            "repeats": args.repeats,
                            "run_retries": args.run_retries,
                            "run_timeout": args.run_timeout,
                            "full_task_budget": args.full_task_budget,
                            "config": _config(args, models, scenarios, seeds),
                            "status": "partial",
                            "rows": rows,
                        }
                        _write_json_atomic(args.output, checkpoint)
    payload = {
        "kind": ARTIFACT_KIND,
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
        "config": _config(args, models, scenarios, seeds),
        "status": "complete",
        "rows": rows,
    }
    grouped: dict[tuple[object, ...], dict[bool, dict[str, object]]] = {}
    for row in rows:
        key = (row["model"], row["scenario"], row["seed"], row["repeat"])
        grouped.setdefault(key, {})[bool(row["affective_context"])] = row
    pairs = [pair for pair in grouped.values() if False in pair and True in pair]
    success_delta_ci_low, success_delta_ci_high = _success_delta_ci(pairs)
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
    output_token_deltas = [
        ((int(pair[True]["output_tokens"]) / int(pair[False]["output_tokens"])) - 1) * 100
        for pair in pairs
        if isinstance(pair[False]["output_tokens"], int)
        and int(pair[False]["output_tokens"]) > 0
        and isinstance(pair[True]["output_tokens"], int)
    ]
    verified_pairs = [
        pair
        for pair in pairs
        if pair[False].get("ground_truth_success") is not None
        and pair[True].get("ground_truth_success") is not None
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
        "success_delta_context_minus_disabled": round(
            statistics.mean(
                int(pair[True]["success"]) - int(pair[False]["success"]) for pair in pairs
            ),
            3,
        )
        if pairs
        else 0.0,
        "success_delta_ci95": {
            "low": success_delta_ci_low,
            "high": success_delta_ci_high,
            "method": "paired_bootstrap",
            "resamples": 10000,
            "seed": 0,
        },
        "verified_success_pairs": len(verified_pairs),
        "verified_success_rate_disabled": round(
            statistics.mean(bool(pair[False]["ground_truth_success"]) for pair in verified_pairs),
            3,
        )
        if verified_pairs
        else None,
        "verified_success_rate_context": round(
            statistics.mean(bool(pair[True]["ground_truth_success"]) for pair in verified_pairs),
            3,
        )
        if verified_pairs
        else None,
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
        "output_token_overhead_median_pct": round(statistics.median(output_token_deltas), 2)
        if output_token_deltas
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
    payload["scenario_metrics"] = {
        scenario: {
            str(context).lower(): {
                "runs": len(
                    selected := [
                        r
                        for r in rows
                        if r["scenario"] == scenario and r["affective_context"] == context
                    ]
                ),
                "verified_successes": sum(r.get("verified_success") is True for r in selected),
                "unknown": sum(r.get("verified_success") is None for r in selected),
                "false_claims": sum(
                    r["model_claim_success"] and r.get("verified_success") is False
                    for r in selected
                ),
                "input_tokens": sum(r["input_tokens"] or 0 for r in selected),
                "output_tokens": sum(r["output_tokens"] or 0 for r in selected),
            }
            for context in (False, True)
        }
        for scenario in scenarios
    }
    payload["paired_metrics"]["success_delta_ci95"]["limitation"] = (
        "Claim-based exploratory interval; repeated seeds are correlated. "
        "A degenerate interval does not establish equivalence."
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(args.output, payload)
    failures = [row for row in rows if not row["success"]]
    print(f"wrote {args.output}: {len(rows) - len(failures)}/{len(rows)} successful")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
