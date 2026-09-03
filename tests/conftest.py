"""Shared fixtures. Nothing here touches the network or needs an API key."""

from __future__ import annotations

from pathlib import Path

import pytest

from quackd.duckfile.parser import load_duck
from quackd.duckfile.schema import DuckFile
from quackd.transport.mock import MockTransport
from quackd.verbs.registry import VerbRegistry, default_registry

REPO = Path(__file__).resolve().parents[1]
DUCKS = REPO / "ducks"


@pytest.fixture(autouse=True)
def _memory_in_tmp(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A test run must never write the developer's real `~/.quackd/memory`: every test that
    runs the CLI with memory on (the default) gets a throwaway directory instead. Not inside
    `tmp_path`: tests count the run directories they make there."""
    monkeypatch.setenv("QUACKD_MEMORY_DIR", str(tmp_path_factory.mktemp("quackd-memory")))


@pytest.fixture
def registry() -> VerbRegistry:
    return default_registry()


@pytest.fixture
def mock_transport() -> MockTransport:
    return MockTransport()


@pytest.fixture
def hello_duck() -> DuckFile:
    return load_duck(str(DUCKS / "hello-world.duck"))


@pytest.fixture
def kick_duck() -> DuckFile:
    return load_duck(str(DUCKS / "find-and-kick.duck"))
