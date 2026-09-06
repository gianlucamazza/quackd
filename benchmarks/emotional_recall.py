"""Paired retrieval benchmark for quackd's full emotional-memory integration.

The deterministic backend is offline and suitable for CI. ``local`` and
``openai-compatible`` exercise the two real embedding adapters without involving a chat
provider or robot hardware.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from emotional_memory import AffectiveState, CoreAffect, InMemoryStore

from quackd.emotional_recall import EmotionalMemoryIndex, EmotionalRecallConfig
from quackd.memory import RobotMemory

ARTIFACT_KIND = "quackd-emotional-recall-v1"


class DeterministicEmbedder:
    """Small feature-hash embedder for plumbing tests, never a quality baseline."""

    dimensions = 64

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in text.lower().split():
            digest = hashlib.sha256(token.strip(".,:;!?()[]").encode()).digest()
            vector[int.from_bytes(digest[:2], "big") % self.dimensions] += 1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


def _snapshot(valence: float, arousal: float, dominance: float) -> dict[str, Any]:
    state = AffectiveState.initial().update(
        CoreAffect(valence=valence, arousal=arousal, dominance=dominance)
    )
    return {"schema_version": 1, **state.snapshot()}


CASES = (
    {
        "name": "learned-location",
        "query": "find the ball behind the blue sofa",
        "memories": (
            ("the ball is behind the blue sofa", "target", (0.7, 0.4, 0.7)),
            ("the charger is under the desk", "distractor", (0.1, 0.1, 0.5)),
            ("the ball was once near the red door", "obsolete", (-0.4, 0.7, 0.3)),
        ),
    },
    {
        "name": "recovery-strategy",
        "query": "recover after approach failed because the target disappeared",
        "memories": (
            ("after approach fails, search left before retrying", "target", (0.6, 0.5, 0.7)),
            ("quack after completing a patrol", "distractor", (0.4, 0.2, 0.6)),
            ("repeat the same approach without observing", "unsafe", (-0.7, 0.9, 0.2)),
        ),
    },
)


def run_benchmark(
    output: Path,
    *,
    backend: str = "deterministic",
    model: str | None = None,
    base_url: str | None = None,
    api_key_env: str = "OPENAI_API_KEY",
) -> dict[str, Any]:
    if backend not in {"deterministic", "local", "openai-compatible"}:
        raise ValueError("backend must be deterministic, local or openai-compatible")
    root = Path(tempfile.mkdtemp(prefix="quackd-emotional-recall-"))
    rows: list[dict[str, Any]] = []
    try:
        for case_index, case in enumerate(CASES):
            memory = RobotMemory(f"benchmark:{case['name']}", root / "memory")
            target_id = ""
            for index, (text, label, affect) in enumerate(case["memories"]):
                entry = memory.remember(
                    text,
                    tags=[label],
                    now=float(case_index * 100 + index + 1),
                    affective=_snapshot(*affect),
                )
                if label == "target":
                    target_id = entry.id
            for ranking in ("semantic", "affective"):
                actual_backend = "local" if backend == "deterministic" else backend
                config = EmotionalRecallConfig(
                    directory=root / "indexes",
                    backend=actual_backend,  # type: ignore[arg-type]
                    model=model,
                    base_url=base_url,
                    api_key_env=api_key_env,
                    ranking=ranking,  # type: ignore[arg-type]
                    top_k=3,
                )
                kwargs: dict[str, Any] = {}
                if backend == "deterministic":
                    kwargs = {
                        "ephemeral": True,
                        "embedder_factory": DeterministicEmbedder,
                        "store_factory": lambda _path: InMemoryStore(),
                    }
                index = EmotionalMemoryIndex(memory, config, **kwargs)
                started = time.perf_counter()
                recalled = index.recall(str(case["query"]), affective=_snapshot(0.5, 0.4, 0.7))
                elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
                index.close()
                rows.append(
                    {
                        "case": case["name"],
                        "query": case["query"],
                        "ranking": ranking,
                        "target_source_id": target_id,
                        "top1_correct": bool(
                            recalled.items and recalled.items[0].source_id == target_id
                        ),
                        "elapsed_ms": elapsed_ms,
                        "source_digest": recalled.source_digest,
                        "results": [
                            {
                                "source_id": item.source_id,
                                "kind": item.kind,
                                "text": item.text,
                                "score": item.score,
                                "breakdown": item.breakdown,
                            }
                            for item in recalled.items
                        ],
                    }
                )
        payload = {
            "kind": ARTIFACT_KIND,
            "status": "complete",
            "created_at": datetime.now(UTC).isoformat(),
            "backend": backend,
            "model": model or ("feature-hash-64" if backend == "deterministic" else None),
            "rows": rows,
            "summary": {
                ranking: {
                    "cases": sum(row["ranking"] == ranking for row in rows),
                    "top1_correct": sum(
                        row["ranking"] == ranking and row["top1_correct"] for row in rows
                    ),
                }
                for ranking in ("semantic", "affective")
            },
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        tmp = output.with_suffix(output.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(output)
        return payload
    finally:
        import shutil

        shutil.rmtree(root, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backend",
        choices=("deterministic", "local", "openai-compatible"),
        default="deterministic",
    )
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.backend == "openai-compatible" and not args.model:
        parser.error("--model is required for openai-compatible embeddings")
    payload = run_benchmark(
        args.output,
        backend=args.backend,
        model=args.model,
        base_url=args.base_url,
        api_key_env=args.api_key_env,
    )
    print(json.dumps(payload["summary"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
