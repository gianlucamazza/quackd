"""The affective module remains importable when its optional dependency is absent."""

from __future__ import annotations

import pytest

import quackd.affective as affective


def test_missing_emotional_memory_has_actionable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing_dependency() -> tuple[object, object, object, object]:
        raise RuntimeError("affective state needs the optional extra quackd[emotional]")

    monkeypatch.setattr(affective, "_load_emotional_memory", missing_dependency)
    with pytest.raises(RuntimeError, match=r"quackd\[emotional\]"):
        affective.AffectiveRuntime(":memory:")
