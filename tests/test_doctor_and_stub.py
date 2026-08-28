"""`quackd doctor` runs without crashing anywhere; the WebSocket stub refuses honestly."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from quackd.cli import app
from quackd.transport.base import TransportError
from quackd.transport.websocket_stub import WebSocketTransport


def test_doctor_runs() -> None:
    result = CliRunner().invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    for needle in ("providers", "transports", "upstream assumptions", "sim2d", "jsonrpc"):
        assert needle in result.output


async def test_websocket_stub_points_at_upstream() -> None:
    t = WebSocketTransport()
    with pytest.raises(TransportError, match=r"architecture\.md"):
        await t.connect()
    await t.stop()  # never raises: a stop must always be safe
