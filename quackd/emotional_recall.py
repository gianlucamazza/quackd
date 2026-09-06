"""Derived emotional-memory index for quackd's human-readable JSONL memory."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from filelock import FileLock, Timeout

from quackd.memory import MemoryEntry, RobotMemory, robot_slug

EmbeddingBackend = Literal["local", "openai-compatible"]
RankingMode = Literal["semantic", "affective"]


class Embedder(Protocol):
    def embed(self, text: str) -> list[float]: ...

    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class EmotionalRecallConfig:
    directory: str | Path = "~/.quackd/emotional-memory"
    backend: EmbeddingBackend = "local"
    model: str | None = None
    base_url: str | None = None
    api_key_env: str = "OPENAI_API_KEY"
    ranking: RankingMode = "affective"
    top_k: int = 5
    embedding_batch_size: int = 64
    lock_timeout_s: float = 30.0
    allow_remote: bool = False

    def __post_init__(self) -> None:
        if self.backend not in {"local", "openai-compatible"}:
            raise ValueError("embedding backend must be local or openai-compatible")
        if self.ranking not in {"semantic", "affective"}:
            raise ValueError("ranking must be semantic or affective")
        if self.top_k < 1:
            raise ValueError("top_k must be positive")
        if self.embedding_batch_size < 1:
            raise ValueError("embedding batch size must be positive")
        if self.lock_timeout_s <= 0:
            raise ValueError("index lock timeout must be positive")
        if self.backend == "openai-compatible" and not self.model:
            raise ValueError("remote emotional embeddings require an explicit model")
        if self.backend == "openai-compatible" and not self.allow_remote:
            raise ValueError("remote emotional embeddings require explicit data consent")

    @property
    def resolved_model(self) -> str:
        return self.model or "all-MiniLM-L6-v2"

    def identity(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "backend": self.backend,
            "model": self.resolved_model,
            "base_url_digest": (
                hashlib.sha256(self.base_url.encode()).hexdigest() if self.base_url else None
            ),
            "ranking": self.ranking,
        }


class OpenAICompatibleEmbedder:
    """Small adapter around the OpenAI-compatible embeddings endpoint."""

    def __init__(self, *, model: str, base_url: str | None, api_key: str) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("remote emotional embeddings need quackd[emotional-remote]") from exc
        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    def embed(self, text: str) -> list[float]:
        return list(self._client.embeddings.create(model=self._model, input=text).data[0].embedding)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        response = self._client.embeddings.create(model=self._model, input=texts)
        return [list(row.embedding) for row in sorted(response.data, key=lambda row: row.index)]


class _CachedBatchEmbedder:
    """Prefetch new vectors in bounded batches while preserving sequential PAD encoding."""

    def __init__(
        self, delegate: Embedder, *, cache: dict[str, list[float]], batch_size: int
    ) -> None:
        self.delegate = delegate
        self.cache = cache
        self.batch_size = batch_size

    def prime(self, texts: list[str]) -> None:
        missing = list(dict.fromkeys(text for text in texts if text not in self.cache))
        for offset in range(0, len(missing), self.batch_size):
            batch = missing[offset : offset + self.batch_size]
            vectors = self.delegate.embed_batch(batch)
            if len(vectors) != len(batch):
                raise RuntimeError("embedding backend returned the wrong batch size")
            self.cache.update(zip(batch, vectors, strict=True))

    def embed(self, text: str) -> list[float]:
        if text not in self.cache:
            self.cache[text] = self.delegate.embed(text)
        return list(self.cache[text])

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.prime(texts)
        return [list(self.cache[text]) for text in texts]


@dataclass(frozen=True)
class RecalledMemory:
    source_id: str
    text: str
    kind: str
    score: float
    breakdown: dict[str, Any]


@dataclass(frozen=True)
class EmotionalRecall:
    text: str = ""
    items: list[RecalledMemory] = field(default_factory=list)
    source_digest: str = ""
    backend: str = ""
    model: str = ""
    ranking: str = ""


class EmotionalMemoryIndex:
    """A rebuildable emotional index; ``RobotMemory`` remains authoritative."""

    def __init__(
        self,
        memory: RobotMemory,
        config: EmotionalRecallConfig,
        *,
        ephemeral: bool = False,
        embedder_factory: Callable[[], Embedder] | None = None,
        store_factory: Callable[[str | Path], Any] | None = None,
    ) -> None:
        self.memory = memory
        self.config = config
        self.ephemeral = ephemeral
        self._embedder_factory = embedder_factory
        self._store_factory = store_factory
        self._engine: Any | None = None
        self._source_digest = ""

        identity = json.dumps(config.identity(), sort_keys=True, separators=(",", ":"))
        suffix = hashlib.sha256(identity.encode()).hexdigest()[:12]
        root = Path(config.directory).expanduser()
        self.path = root / f"{robot_slug(memory.robot_key)}-{suffix}.sqlite"
        self.manifest_path = self.path.with_suffix(".manifest.json")
        self.lock_path = self.path.with_suffix(".sqlite.lock")

    def _make_embedder(self) -> Embedder:
        if self._embedder_factory is not None:
            return self._embedder_factory()
        if self.config.backend == "local":
            try:
                from emotional_memory.embedders import SentenceTransformerEmbedder
            except ImportError as exc:
                raise RuntimeError(
                    "local emotional embeddings need quackd[emotional-local]"
                ) from exc
            return SentenceTransformerEmbedder(self.config.resolved_model)
        api_key = os.environ.get(self.config.api_key_env)
        if not api_key:
            raise RuntimeError(
                f"remote emotional embeddings need {self.config.api_key_env} in the environment"
            )
        return OpenAICompatibleEmbedder(
            model=self.config.resolved_model,
            base_url=self.config.base_url,
            api_key=api_key,
        )

    def _make_store(self, path: str | Path) -> Any:
        if self._store_factory is not None:
            return self._store_factory(path)
        if self.ephemeral:
            from emotional_memory import InMemoryStore

            return InMemoryStore()
        try:
            from emotional_memory import SQLiteStore
        except ImportError as exc:
            raise RuntimeError(
                "persistent emotional recall needs emotional-memory[sqlite]"
            ) from exc
        return SQLiteStore(path)

    def _make_engine(self, store: Any, embedder: Embedder) -> Any:
        from emotional_memory import EmotionalMemory, EmotionalMemoryConfig, RetrievalConfig

        if self.config.ranking == "semantic":
            config = EmotionalMemoryConfig(
                retrieval=RetrievalConfig(base_weights=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
                enable_appraisal=False,
                enable_mood_signal=False,
                enable_momentum=False,
                enable_resonance=False,
                enable_reconsolidation=False,
            )
        else:
            config = EmotionalMemoryConfig(enable_appraisal=False)
        return EmotionalMemory(store=store, embedder=embedder, config=config)

    def _digest(self, entries: list[MemoryEntry]) -> str:
        payload = [entry.to_json() for entry in entries]
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def _state(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
        if snapshot is None:
            return None
        return {key: value for key, value in snapshot.items() if key != "schema_version"}

    def _populate(self, engine: Any, store: Any, entries: list[MemoryEntry]) -> None:
        for entry in entries:
            state = self._state(entry.affective)
            if state is not None:
                engine.load_state(state)
            else:
                engine.reset_state()
            memory = engine.encode(
                entry.text,
                metadata={
                    "source_id": entry.id,
                    "kind": entry.kind,
                    "duck": entry.duck,
                    "tags": entry.tags,
                    "outcome": entry.outcome,
                },
            )
            timestamp = datetime.fromtimestamp(entry.ts, tz=UTC)
            memory = memory.model_copy(
                update={"tag": memory.tag.model_copy(update={"timestamp": timestamp})}
            )
            store.update(memory)

    def _manifest(self, source_digest: str) -> dict[str, Any]:
        return {**self.config.identity(), "source_digest": source_digest}

    def _manifest_matches(self, source_digest: str) -> bool:
        if self.ephemeral or not self.path.exists() or not self.manifest_path.exists():
            return False
        try:
            current = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return current == self._manifest(source_digest)

    def _cached_embeddings(self) -> dict[str, list[float]]:
        if not self.path.exists() or not self.manifest_path.exists():
            return {}
        try:
            manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        identity = self.config.identity()
        if any(manifest.get(key) != value for key, value in identity.items()):
            return {}
        store = self._make_store(self.path)
        try:
            return {
                memory.content: list(memory.embedding)
                for memory in store.list_all()
                if memory.embedding is not None
            }
        finally:
            store.close()

    def sync(self) -> None:
        entries = self.memory.entries()
        source_digest = self._digest(entries)
        if self._engine is not None and source_digest == self._source_digest:
            return
        self.close()
        raw_embedder = self._make_embedder()
        if self.ephemeral:
            embedder = _CachedBatchEmbedder(
                raw_embedder, cache={}, batch_size=self.config.embedding_batch_size
            )
            embedder.prime([entry.text for entry in entries])
            store = self._make_store(":memory:")
            self._engine = self._make_engine(store, embedder)
            self._populate(self._engine, store, entries)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with FileLock(self.lock_path, timeout=self.config.lock_timeout_s):
                    entries = self.memory.entries()
                    source_digest = self._digest(entries)
                    cache = self._cached_embeddings()
                    embedder = _CachedBatchEmbedder(
                        raw_embedder,
                        cache=cache,
                        batch_size=self.config.embedding_batch_size,
                    )
                    if self._manifest_matches(source_digest):
                        self._engine = self._make_engine(self._make_store(self.path), embedder)
                    else:
                        embedder.prime([entry.text for entry in entries])
                        safe_model = re.sub(r"[^a-zA-Z0-9_.-]+", "-", self.config.resolved_model)
                        tmp = self.path.with_name(f".{self.path.name}.{safe_model}.tmp")
                        tmp.unlink(missing_ok=True)
                        store = self._make_store(tmp)
                        engine = self._make_engine(store, embedder)
                        try:
                            self._populate(engine, store, entries)
                        finally:
                            engine.close()
                        tmp.replace(self.path)
                        manifest_tmp = self.manifest_path.with_suffix(".json.tmp")
                        manifest_tmp.write_text(
                            json.dumps(self._manifest(source_digest), indent=2, sort_keys=True)
                            + "\n",
                            encoding="utf-8",
                        )
                        manifest_tmp.replace(self.manifest_path)
                        self._engine = self._make_engine(self._make_store(self.path), embedder)
            except Timeout as exc:
                raise RuntimeError(f"emotional-memory index is busy: {self.path}") from exc
        self._source_digest = source_digest

    def recall(self, query: str, *, affective: dict[str, Any] | None = None) -> EmotionalRecall:
        self.sync()
        assert self._engine is not None
        state = self._state(affective)
        if state is not None:
            self._engine.load_state(state)
        explanations = self._engine.retrieve_with_explanations(query, top_k=self.config.top_k)
        items = [
            RecalledMemory(
                source_id=str(item.memory.metadata.get("source_id", item.memory.id)),
                text=item.memory.content,
                kind=str(item.memory.metadata.get("kind", "memory")),
                score=round(float(item.score), 6),
                breakdown=item.breakdown.model_dump(mode="json"),
            )
            for item in explanations
        ]
        text = ""
        if items:
            lines = ["Relevant memories selected for this task:"]
            lines.extend(f"- [{item.kind}] {item.text}" for item in items)
            text = "\n".join(lines)
        return EmotionalRecall(
            text=text,
            items=items,
            source_digest=self._source_digest,
            backend=self.config.backend,
            model=self.config.resolved_model,
            ranking=self.config.ranking,
        )

    def close(self) -> None:
        if self._engine is not None:
            self._engine.close()
            self._engine = None
