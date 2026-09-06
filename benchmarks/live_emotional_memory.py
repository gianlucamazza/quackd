"""Paid cross-run evaluation of chronological, semantic and emotional recall.

This runner only targets ``microduck:sim2d`` with retained evidence. It does not run in CI
and must not be started without an explicit provider and embedding budget.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from benchmarks.live_cloud import PROVIDER_DEFAULTS, run_one

ARTIFACT_KIND = "quackd-live-emotional-memory-v1"
MODES = ("chronological", "semantic", "affective", "affective-context")
SCENARIO_NOTES = {
    "fetch": (
        "For fetch, remember the starting pose and return while still holding the ball.",
        "Do not declare success until the ball has moved at least 0.5 m back toward start.",
    ),
    "follow-me": (
        "A moving person must be observed again before each approach.",
        "Follow for at least three translating approaches and keep at least 0.4 m away.",
    ),
    "patrol-and-quack": (
        "A patrol needs three moving legs and two quacks after every new encounter.",
        "Repeated frames of the same visible person are one encounter, not several.",
    ),
}


def _source_digest() -> str:
    digest = hashlib.sha256()
    root = Path(__file__).resolve().parents[1]
    for relative in (
        "benchmarks/live_cloud.py",
        "benchmarks/live_emotional_memory.py",
        "benchmarks/verification.py",
        "quackd/emotional_recall.py",
        "quackd/agent/loop.py",
        "quackd/memory.py",
    ):
        digest.update(relative.encode())
        digest.update((root / relative).read_bytes())
    return digest.hexdigest()


def _config(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "provider": args.provider,
        "model": args.model,
        "embedding_backend": args.embedding_backend,
        "embedding_model": args.embedding_model,
        "embedding_base_url_digest": (
            hashlib.sha256(args.embedding_base_url.encode()).hexdigest()
            if args.embedding_base_url
            else None
        ),
        "embedding_api_key_env": args.embedding_api_key_env,
        "scenarios": args.scenarios,
        "seeds": args.seeds,
        "repeats": args.repeats,
        "run_retries": args.run_retries,
        "run_timeout": args.run_timeout,
        "source_digest": _source_digest(),
    }


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    report: dict[str, Any] = {}
    for mode in MODES:
        selected = [row for row in rows if row["memory_mode"] == mode]
        verified = [row for row in selected if row["verified_success"] is not None]
        report[mode] = {
            "runs": len(selected),
            "verified_runs": len(verified),
            "verified_successes": sum(row["verified_success"] is True for row in verified),
            "model_claim_successes": sum(row["model_claim_success"] is True for row in selected),
            "usage_complete": all(row["usage_complete"] for row in selected),
            "input_tokens": sum(row["total_observed_input_tokens"] for row in selected),
            "output_tokens": sum(row["total_observed_output_tokens"] for row in selected),
        }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=tuple(PROVIDER_DEFAULTS), default="deepseek")
    parser.add_argument("--model")
    parser.add_argument(
        "--embedding-backend", choices=("local", "openai-compatible"), required=True
    )
    parser.add_argument("--embedding-model")
    parser.add_argument("--embedding-base-url")
    parser.add_argument("--embedding-api-key-env", default="OPENAI_API_KEY")
    parser.add_argument(
        "--scenario",
        action="append",
        choices=tuple(SCENARIO_NOTES),
        dest="scenarios",
    )
    parser.add_argument("--seed", action="append", type=int, dest="seeds")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--run-retries", type=int, default=2)
    parser.add_argument("--run-timeout", type=int, default=180)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.model = args.model or PROVIDER_DEFAULTS[args.provider][0]
    args.scenarios = args.scenarios or list(SCENARIO_NOTES)
    args.seeds = args.seeds or list(range(10))
    if args.embedding_backend == "openai-compatible" and not args.embedding_model:
        parser.error("--embedding-model is required for openai-compatible embeddings")
    if args.repeats < 1 or args.run_retries < 0 or args.run_timeout < 1:
        parser.error("repeats/timeout must be positive and retries non-negative")

    config = _config(args)
    rows: list[dict[str, Any]] = []
    if args.resume:
        if not args.output.exists():
            parser.error("--resume artifact does not exist")
        saved = json.loads(args.output.read_text(encoding="utf-8"))
        if saved.get("kind") != ARTIFACT_KIND or saved.get("config") != config:
            parser.error("--resume requires an identical v1 configuration")
        rows = list(saved.get("rows", []))
    elif args.output.exists():
        parser.error("output already exists; use --resume or a new path")

    completed = {(row["scenario"], row["seed"], row["repeat"], row["memory_mode"]) for row in rows}
    for scenario in args.scenarios:
        for seed in args.seeds:
            for repeat in range(args.repeats):
                offset = (seed + repeat) % len(MODES)
                order = MODES[offset:] + MODES[:offset]
                for mode in order:
                    key = (scenario, seed, repeat, mode)
                    if key in completed:
                        continue
                    row = run_one(
                        args.model,
                        args.provider,
                        scenario,
                        seed,
                        False,
                        repeat,
                        args.run_retries,
                        args.run_timeout,
                        True,
                        args.output.with_suffix(".runs"),
                        "targeted-v1",
                        memory_mode=mode,
                        memory_notes=SCENARIO_NOTES[scenario],
                        emotional_embedding=args.embedding_backend,
                        emotional_embedding_model=args.embedding_model,
                        emotional_embedding_base_url=args.embedding_base_url,
                        emotional_embedding_api_key_env=args.embedding_api_key_env,
                    )
                    rows.append(row)
                    completed.add(key)
                    payload = {
                        "kind": ARTIFACT_KIND,
                        "status": "partial",
                        "created_at": datetime.now(UTC).isoformat(),
                        "config": config,
                        "rows": rows,
                        "summary": _summary(rows),
                    }
                    _atomic_write(args.output, payload)
                    if row["failure_class"] == "quota":
                        raise SystemExit("quota exhausted; partial checkpoint retained")

    payload = {
        "kind": ARTIFACT_KIND,
        "status": "complete",
        "created_at": datetime.now(UTC).isoformat(),
        "config": config,
        "rows": rows,
        "summary": _summary(rows),
    }
    _atomic_write(args.output, payload)
    print(json.dumps(payload["summary"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
