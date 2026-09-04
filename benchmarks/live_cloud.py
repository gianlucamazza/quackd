"""Run a bounded live OpenAI benchmark against the quackd simulator.

This is deliberately manual: it performs real API calls, runs only the safe sim2d transport,
and writes only an explicitly requested artifact. The model catalog is checked before any
generation.
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

from dotenv import load_dotenv

SCENARIOS = ("hello-world", "find-and-kick", "open-duck-scout", "reachy-spotter")
DEFAULT_MODELS = ("gpt-5.6-luna", "gpt-5.6-terra")


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


def run_one(model: str, scenario: str, seed: int, affective: bool) -> dict[str, object]:
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
        if affective:
            command.extend(("--emotional-state", "--emotional-dir", str(root / "affective")))
        started = time.perf_counter()
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        summaries = sorted((root / "runs").glob("*/summary.json"))
        summary = json.loads(summaries[-1].read_text(encoding="utf-8")) if summaries else {}
        input_tokens, output_tokens = _usage(summary)
        return {
            "model": model,
            "scenario": scenario,
            "seed": seed,
            "affective": affective,
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
    parser.add_argument("--output", type=Path, default=Path("/tmp/quackd-live-openai.json"))
    args = parser.parse_args()
    models = tuple(args.models or DEFAULT_MODELS)
    scenarios = tuple(args.scenario or SCENARIOS)
    seeds = tuple(args.seeds or (0, 1, 2))

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
        run_one(model, scenario, seed, affective)
        for model in models
        for scenario in scenarios
        for seed in seeds
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
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    failures = [row for row in rows if not row["success"]]
    print(f"wrote {args.output}: {len(rows) - len(failures)}/{len(rows)} successful")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
