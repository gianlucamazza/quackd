"""The optional emotional-memory runtime stays outside the safety contract."""

from __future__ import annotations

import pytest

emotional_memory = pytest.importorskip("emotional_memory")

from quackd.affective import (  # noqa: E402
    AffectiveConfig,
    AffectiveRuntime,
    affect_for_event,
    state_path_for,
)


def test_event_mapping_prioritises_safety() -> None:
    assert affect_for_event("safety_stop") == (-0.8, 1.0, 0.1)
    assert affect_for_event("verb_success", ok=True)[0] > 0
    assert affect_for_event("verb_failure", ok=False)[0] < 0


def test_paths_are_canonical_and_ephemeral() -> None:
    assert str(state_path_for("Reachy_Mini:SDK", "/tmp/a")) == "/tmp/a/reachy_mini-sdk.sqlite"
    assert AffectiveConfig(enabled=True).state_path("microduck:sim2d", ephemeral=True) == ":memory:"


@pytest.mark.asyncio
async def test_runtime_updates_and_persists_state(tmp_path) -> None:
    path = tmp_path / "robot.sqlite"
    runtime = AffectiveRuntime(path)
    initial = runtime.summary()
    updated = await runtime.observe("success", text="the target was found", ok=True)
    assert initial["valence"] == 0.0
    assert updated["valence"] > 0.0
    runtime.close()

    restored = AffectiveRuntime(path)
    assert restored.summary()["valence"] > 0.0
    restored.close()


def test_for_robot_uses_canonical_configured_path(tmp_path) -> None:
    config = AffectiveConfig(enabled=True, directory=tmp_path)
    runtime = AffectiveRuntime.for_robot("microduck:sim2d", config)
    runtime.close()
    assert (tmp_path / "microduck-sim2d.sqlite").exists()


@pytest.mark.asyncio
async def test_appraisal_failure_falls_back_to_deterministic_mapping(tmp_path) -> None:
    class BrokenAppraisal:
        def appraise(self, _text, _context=None):
            raise RuntimeError("provider unavailable")

    runtime = AffectiveRuntime(tmp_path / "robot.sqlite", appraisal=BrokenAppraisal())
    state = await runtime.observe("verb_failure", text="failed to reach the target", ok=False)
    assert state["valence"] < 0
    assert state["appraisal_status"] == "fallback"
    runtime.close()


@pytest.mark.asyncio
async def test_appraisal_is_capped_and_observations_do_not_call_it(tmp_path) -> None:
    class Appraisal:
        calls = 0

        def appraise(self, _text, _context=None):
            self.calls += 1
            return emotional_memory.CoreAffect(valence=0.9, arousal=0.2, dominance=0.8)

    appraisal = Appraisal()
    config = AffectiveConfig(enabled=True, max_appraisals=1)
    runtime = AffectiveRuntime(tmp_path / "robot.sqlite", appraisal=appraisal, config=config)
    await runtime.observe("observation", text="camera frame")
    await runtime.observe("success", text="first")
    capped = await runtime.observe("failure", text="second")
    assert appraisal.calls == 1
    assert capped["appraisal_status"] == "cap_reached"
    runtime.close()


@pytest.mark.asyncio
async def test_ephemeral_runtime_does_not_persist_to_disk(tmp_path) -> None:
    config = AffectiveConfig(enabled=True, directory=tmp_path)
    runtime = AffectiveRuntime.for_robot("microduck:sim2d", config, ephemeral=True)
    await runtime.observe("success", text="ephemeral run", ok=True)
    runtime.close()
    assert not list(tmp_path.glob("*.sqlite"))
