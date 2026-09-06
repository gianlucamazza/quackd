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
SCENARIO_GUIDANCE = {
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

HARD_NEGATIVES = {
    "fetch": (
        "Declare fetch success as soon as the ball is visible.",
        "Drop the ball before returning to the starting pose.",
        "A few centimetres of ball movement is enough for fetch success.",
        "Never re-observe the ball after approaching it.",
        "Walk away from the starting pose while holding the ball.",
        "Kick the ball instead of carrying it back.",
    ),
    "follow-me": (
        "One approach is enough to declare follow-me success.",
        "Approach the person's original position without observing again.",
        "Move closer than 0.2 m while following a person.",
        "A stationary person proves that following is complete.",
        "Do not require three translating approaches.",
        "Ignore whether the person moved between observations.",
    ),
    "patrol-and-quack": (
        "Repeated frames of one person count as new encounters.",
        "One quack is enough after an encounter.",
        "Patrol success needs only one movement leg.",
        "Declare success before completing three patrol legs.",
        "Quack before observing whether an encounter is new.",
        "Remain still and count camera frames as patrol progress.",
    ),
}


def _affect(valence: float, arousal: float, dominance: float) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "core_affect": {
            "valence": valence,
            "arousal": arousal,
            "dominance": dominance,
        },
        "momentum": {
            "d_valence": 0.0,
            "d_arousal": 0.0,
            "d_dominance": 0.0,
            "dd_valence": 0.0,
            "dd_arousal": 0.0,
            "dd_dominance": 0.0,
        },
        "mood": {
            "valence": valence,
            "arousal": arousal,
            "dominance": dominance,
            "inertia": 0.5,
            "timestamp": "2026-01-01T00:00:00Z",
        },
        "_history": [],
    }


def _memory_fixture(scenario: str) -> tuple[dict[str, object], ...]:
    entries: list[dict[str, object]] = []
    for text in SCENARIO_GUIDANCE[scenario]:
        entries.append({"text": text, "tags": ["target"], "affective": _affect(0.7, 0.4, 0.8)})
    entries.append(
        {
            "text": f"Previous {scenario} recovery succeeded after observing before retrying.",
            "tags": ["target", "recovery"],
            "affective": _affect(-0.4, 0.7, 0.3),
        }
    )
    for text in HARD_NEGATIVES[scenario]:
        entries.append(
            {"text": text, "tags": ["hard-negative"], "affective": _affect(-0.8, 0.9, 0.1)}
        )
    for index in range(21):
        entries.append(
            {
                "text": f"Unrelated maintenance note {index}: inspect battery and joints.",
                "tags": ["distractor"],
                "affective": _affect(0.0, 0.1, 0.5),
            }
        )
    return tuple(entries)


def _start_selection(row: dict[str, Any]) -> list[str]:
    for event in row.get("recall_evidence", []):
        if event.get("phase") == "run_start":
            return [str(item["source_id"]) for item in event.get("items", [])]
    return []


def _selection_gate(rows: list[dict[str, Any]]) -> tuple[bool, str]:
    by_mode = {str(row["memory_mode"]): row for row in rows}
    if set(by_mode) != set(MODES):
        return False, "quartet_incomplete"
    seeded = by_mode["chronological"]["seeded_memories"]
    targets = {str(item["source_id"]) for item in seeded if "target" in item.get("tags", [])}
    chronological = [str(item["source_id"]) for item in seeded[-5:]]
    semantic = _start_selection(by_mode["semantic"])
    affective = _start_selection(by_mode["affective"])
    affective_context = _start_selection(by_mode["affective-context"])
    if targets & set(chronological):
        return False, "chronological_contains_target"
    if not targets & set(semantic):
        return False, "semantic_missed_target"
    if not targets & set(affective):
        return False, "affective_missed_target"
    if semantic == affective:
        return False, "semantic_and_affective_are_identical"
    if affective != affective_context:
        return False, "context_changed_retrieval"
    return True, "discriminating"


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
        "allow_remote_memory": args.allow_remote_memory,
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
    parser.add_argument("--allow-remote-memory", action="store_true")
    parser.add_argument(
        "--scenario",
        action="append",
        choices=tuple(SCENARIO_GUIDANCE),
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
    args.scenarios = args.scenarios or list(SCENARIO_GUIDANCE)
    args.seeds = args.seeds or list(range(10))
    if any(
        len(_memory_fixture(scenario)) != 30
        or any("distractor" not in entry["tags"] for entry in _memory_fixture(scenario)[-5:])
        for scenario in args.scenarios
    ):
        parser.error("memory fixture must contain 30 entries with recent distractors")
    if args.embedding_backend == "openai-compatible" and not args.embedding_model:
        parser.error("--embedding-model is required for openai-compatible embeddings")
    if args.embedding_backend == "openai-compatible" and not args.allow_remote_memory:
        parser.error("remote embeddings require --allow-remote-memory")
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
                        memory_entries=_memory_fixture(scenario),
                        emotional_embedding=args.embedding_backend,
                        emotional_embedding_model=args.embedding_model,
                        emotional_embedding_base_url=args.embedding_base_url,
                        emotional_embedding_api_key_env=args.embedding_api_key_env,
                        allow_remote_memory=args.allow_remote_memory,
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
                    quartet = [
                        candidate
                        for candidate in rows
                        if candidate["scenario"] == scenario
                        and candidate["seed"] == seed
                        and candidate["repeat"] == repeat
                    ]
                    if len(quartet) == len(MODES) and all(
                        candidate["returncode"] == 0 for candidate in quartet
                    ):
                        valid, reason = _selection_gate(quartet)
                        if not valid:
                            payload["status"] = "non_discriminating_fixture"
                            payload["fixture_error"] = reason
                            _atomic_write(args.output, payload)
                            raise SystemExit(f"non-discriminating memory fixture: {reason}")

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
