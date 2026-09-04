"""Optional runtime affect for a robot.

This module deliberately keeps affect outside the executor and safety contract.  It turns
structured quackd events into an ``emotional-memory`` ``AffectiveState`` and exposes a
small, serialisable snapshot for prompts and transcripts.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol


class Appraisal(Protocol):
    def appraise(self, event_text: str, context: dict[str, Any] | None = None) -> Any: ...


@dataclass(frozen=True)
class AffectiveConfig:
    """Runtime policy for affect; it never changes the robot safety contract."""

    enabled: bool = False
    directory: str | Path = "~/.quackd/affective"
    appraisal: str = "deterministic"
    appraisal_timeout_s: float = 5.0
    max_appraisals: int = 8
    mood_alpha: float = 0.2

    def __post_init__(self) -> None:
        if self.appraisal not in {"deterministic", "optional"}:
            raise ValueError("appraisal must be 'deterministic' or 'optional'")
        if self.appraisal_timeout_s <= 0:
            raise ValueError("appraisal_timeout_s must be positive")
        if self.max_appraisals < 0:
            raise ValueError("max_appraisals must not be negative")
        if not 0 < self.mood_alpha <= 1:
            raise ValueError("mood_alpha must be in (0, 1]")

    def state_path(self, robot_key: str, *, ephemeral: bool = False) -> str | Path:
        if ephemeral or not self.enabled:
            return ":memory:"
        root = Path(self.directory).expanduser()
        slug = "-".join(part for part in robot_key.lower().split(":") if part)
        return root / f"{slug or 'robot'}.sqlite"


def state_path_for(
    robot_key: str, directory: str | Path = "~/.quackd/affective", *, ephemeral: bool = False
) -> str | Path:
    """Return the canonical per-robot SQLite path used by CLI and MCP."""
    return AffectiveConfig(enabled=True, directory=directory).state_path(
        robot_key, ephemeral=ephemeral
    )


def _load_emotional_memory() -> tuple[Any, Any, Any, Any]:
    try:
        from emotional_memory import (  # type: ignore[import-not-found]
            AffectiveState,
            CoreAffect,
            MoodDecayConfig,
            SQLiteAffectiveStateStore,
        )
    except ImportError as exc:
        raise RuntimeError(
            "affective state needs the optional extra quackd[emotional]; "
            'install it with: uv pip install "quackd[emotional]"'
        ) from exc
    return AffectiveState, CoreAffect, MoodDecayConfig, SQLiteAffectiveStateStore


def affect_for_event(kind: str, ok: bool | None = None) -> tuple[float, float, float]:
    """Return a conservative PAD target for a quackd event."""
    if kind in {"safety_stop", "abort"}:
        return -0.8, 1.0, 0.1
    if kind in {"failure", "verb_failure"} or ok is False:
        return -0.45, 0.7, 0.3
    if kind in {"success", "verb_success"} or ok is True:
        return 0.65, 0.35, 0.7
    if kind == "observation":
        return 0.0, 0.15, 0.5
    return 0.0, 0.1, 0.5


class AffectiveRuntime:
    """Per-robot affective state backed by emotional-memory.

    ``appraisal`` is optional and runs outside the event loop thread.  If it fails, the
    deterministic event mapping remains authoritative for this update.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        appraisal: Appraisal | None = None,
        mood_alpha: float = 0.2,
        config: AffectiveConfig | None = None,
    ) -> None:
        if config is not None:
            mood_alpha = config.mood_alpha
        self._appraisal_timeout_s = config.appraisal_timeout_s if config else 5.0
        self._max_appraisals = config.max_appraisals if config else 8
        self._appraisal_count = 0
        if path != ":memory:":
            Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        AffectiveState, _CoreAffect, MoodDecayConfig, Store = _load_emotional_memory()
        self._core_affect = _CoreAffect
        self._decay = MoodDecayConfig()
        self._store = Store(path)
        self._state = self._store.load() or AffectiveState.initial()
        self._appraisal = appraisal
        self._mood_alpha = mood_alpha

    @classmethod
    def for_robot(
        cls,
        robot_key: str,
        config: AffectiveConfig,
        *,
        ephemeral: bool = False,
        appraisal: Appraisal | None = None,
    ) -> AffectiveRuntime:
        """Build the canonical per-robot runtime from one policy object."""
        return cls(
            config.state_path(robot_key, ephemeral=ephemeral),
            appraisal=appraisal,
            config=config,
        )

    def snapshot(self) -> dict[str, Any]:
        return self._state.snapshot()

    def summary(self) -> dict[str, Any]:
        state = self._state
        return {
            "valence": round(state.core_affect.valence, 3),
            "arousal": round(state.core_affect.arousal, 3),
            "dominance": round(state.core_affect.dominance, 3),
            "mood": {
                "valence": round(state.mood.valence, 3),
                "arousal": round(state.mood.arousal, 3),
                "dominance": round(state.mood.dominance, 3),
            },
        }

    async def observe(
        self,
        kind: str,
        *,
        text: str = "",
        ok: bool | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        valence, arousal, dominance = affect_for_event(kind, ok)
        appraisal_used = False
        appraisal_status = "disabled"
        if self._appraisal is not None and text and kind != "observation":
            if self._appraisal_count >= self._max_appraisals:
                appraisal_status = "cap_reached"
            else:
                self._appraisal_count += 1
                appraisal_status = "fallback"
                try:
                    result = await asyncio.wait_for(
                        asyncio.to_thread(self._appraisal.appraise, text, context),
                        timeout=self._appraisal_timeout_s,
                    )
                    candidate = result.to_core_affect()
                    valence, arousal, dominance = (
                        candidate.valence,
                        candidate.arousal,
                        candidate.dominance,
                    )
                    appraisal_used = True
                    appraisal_status = "used"
                except Exception:
                    # Appraisal must never turn a robot run into an error.
                    pass
        now = datetime.now(tz=UTC)
        affect = self._core_affect(
            valence=valence,
            arousal=arousal,
            dominance=dominance,
        )
        self._state = self._state.update(
            affect,
            now=now,
            mood_alpha=self._mood_alpha,
            mood_decay=self._decay,
        )
        self._store.save(self._state)
        return {
            "event": kind,
            "appraisal": appraisal_used,
            "appraisal_status": appraisal_status,
            **self.summary(),
        }

    def close(self) -> None:
        self._store.close()
