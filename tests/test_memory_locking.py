from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from filelock import FileLock

from quackd.memory import RobotMemory


def test_concurrent_writers_do_not_lose_notes(tmp_path: Path) -> None:
    def write(i: int) -> None:
        RobotMemory("microduck:sim2d", tmp_path).remember(f"note {i}", now=float(i))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write, range(24)))

    entries = RobotMemory("microduck:sim2d", tmp_path).entries()
    assert {entry.text for entry in entries} == {f"note {i}" for i in range(24)}


def test_write_lock_timeout_is_actionable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    memory = RobotMemory("microduck:sim2d", tmp_path)
    monkeypatch.setattr("quackd.memory.MEMORY_LOCK_TIMEOUT_S", 0.01)
    with FileLock(memory.lock_path), pytest.raises(OSError, match="memory file is busy"):
        memory.remember("blocked")
