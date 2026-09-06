from __future__ import annotations

from pathlib import Path

import pytest
from filelock import FileLock

pytest.importorskip("emotional_memory")

from emotional_memory import AffectiveState, InMemoryStore

from quackd.emotional_recall import EmotionalMemoryIndex, EmotionalRecallConfig
from quackd.memory import RobotMemory


class WordEmbedder:
    def embed(self, text: str) -> list[float]:
        words = text.lower().split()
        return [float(words.count("ball")), float(words.count("charger")), 1.0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


class CountingEmbedder(WordEmbedder):
    def __init__(self) -> None:
        self.batches: list[list[str]] = []

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.batches.append(list(texts))
        return [self.embed(text) for text in texts]


def _index(
    memory: RobotMemory, tmp_path: Path, *, ranking: str = "semantic"
) -> EmotionalMemoryIndex:
    return EmotionalMemoryIndex(
        memory,
        EmotionalRecallConfig(directory=tmp_path, ranking=ranking),  # type: ignore[arg-type]
        ephemeral=True,
        embedder_factory=WordEmbedder,
        store_factory=lambda _path: InMemoryStore(),
    )


def test_semantic_recall_uses_jsonl_as_source(tmp_path: Path) -> None:
    memory = RobotMemory("microduck:sim2d", tmp_path / "memory")
    ball = memory.remember("the ball is behind the sofa", now=1.0)
    memory.remember("the charger is under the desk", now=2.0)
    index = _index(memory, tmp_path / "index")

    result = index.recall("find the ball")

    assert result.items[0].source_id == ball.id
    assert "ball is behind the sofa" in result.text
    assert result.ranking == "semantic"


def test_changed_jsonl_invalidates_the_live_index(tmp_path: Path) -> None:
    memory = RobotMemory("microduck:sim2d", tmp_path / "memory")
    memory.remember("the charger is under the desk", now=1.0)
    index = _index(memory, tmp_path / "index")
    first = index.recall("find the ball")

    ball = memory.remember("the ball is behind the sofa", now=2.0)
    second = index.recall("find the ball")

    assert first.source_digest != second.source_digest
    assert second.items[0].source_id == ball.id


def test_persistent_index_reopens_and_rebuilds_from_jsonl(tmp_path: Path) -> None:
    memory = RobotMemory("microduck:sim2d", tmp_path / "memory")
    memory.remember("the charger is under the desk", now=1.0)
    config = EmotionalRecallConfig(directory=tmp_path / "index", ranking="semantic")
    first = EmotionalMemoryIndex(memory, config, embedder_factory=WordEmbedder)
    original = first.recall("find the charger")
    path = first.path
    first.close()

    reopened = EmotionalMemoryIndex(memory, config, embedder_factory=WordEmbedder)
    assert reopened.recall("find the charger").source_digest == original.source_digest
    ball = memory.remember("the ball is behind the sofa", now=2.0)
    rebuilt = reopened.recall("find the ball")

    assert path.exists() and reopened.manifest_path.exists()
    assert rebuilt.source_digest != original.source_digest
    assert rebuilt.items[0].source_id == ball.id


def test_rebuild_batches_only_new_embeddings(tmp_path: Path) -> None:
    memory = RobotMemory("microduck:sim2d", tmp_path / "memory")
    memory.remember("the charger is under the desk", now=1.0)
    embedder = CountingEmbedder()
    index = EmotionalMemoryIndex(
        memory,
        EmotionalRecallConfig(directory=tmp_path / "index", ranking="semantic"),
        embedder_factory=lambda: embedder,
    )
    index.sync()
    memory.remember("the ball is behind the sofa", now=2.0)
    index.sync()

    assert embedder.batches == [
        ["the charger is under the desk"],
        ["the ball is behind the sofa"],
    ]


def test_batch_prefetch_preserves_per_entry_affect(tmp_path: Path) -> None:
    memory = RobotMemory("microduck:sim2d", tmp_path / "memory")
    positive = AffectiveState.initial().snapshot()
    positive["core_affect"]["valence"] = 0.8
    negative = AffectiveState.initial().snapshot()
    negative["core_affect"]["valence"] = -0.8
    memory.remember("ball success", now=1.0, affective=positive)
    memory.remember("ball failure", now=2.0, affective=negative)
    index = _index(memory, tmp_path / "index", ranking="affective")

    index.sync()
    assert index._engine is not None
    values = {item.content: item.tag.core_affect.valence for item in index._engine.list_all()}
    assert values == {"ball success": 0.8, "ball failure": -0.8}


def test_index_lock_timeout_is_actionable(tmp_path: Path) -> None:
    memory = RobotMemory("microduck:sim2d", tmp_path / "memory")
    memory.remember("the ball is behind the sofa", now=1.0)
    index = EmotionalMemoryIndex(
        memory,
        EmotionalRecallConfig(
            directory=tmp_path / "index", ranking="semantic", lock_timeout_s=0.01
        ),
        embedder_factory=WordEmbedder,
    )
    index.path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(index.lock_path), pytest.raises(RuntimeError, match="index is busy"):
        index.sync()


def test_remote_backend_requires_model_and_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ValueError, match="explicit model"):
        EmotionalRecallConfig(backend="openai-compatible")
    with pytest.raises(ValueError, match="explicit data consent"):
        EmotionalRecallConfig(backend="openai-compatible", model="embedding-model")
    config = EmotionalRecallConfig(
        backend="openai-compatible", model="embedding-model", allow_remote=True
    )
    monkeypatch.delenv(config.api_key_env, raising=False)
    index = EmotionalMemoryIndex(RobotMemory("microduck:sim2d", tmp_path), config)
    with pytest.raises(RuntimeError, match=config.api_key_env):
        index.sync()
