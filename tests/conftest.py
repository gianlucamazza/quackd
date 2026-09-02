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
def _fresh_deprecation_warnings() -> None:
    # the CLI prints a deprecation line once per process; every test is its own process
    from quackd.adapters.factory import reset_warnings

    reset_warnings()


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
