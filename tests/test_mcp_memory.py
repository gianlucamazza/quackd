"""`robot_recall` / `robot_remember` over MCP: one memory per robot, keyed adapter:backend."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from quackd.mcp_server import TOOL_NAMES
from quackd.memory import RobotMemory
from tests.test_mcp_fleet import _data, connected, two_robots


def test_memory_tools_are_registered() -> None:
    assert "robot_recall" in TOOL_NAMES and "robot_remember" in TOOL_NAMES


async def test_remember_then_recall_per_robot(tmp_path: Path) -> None:
    async with connected(two_robots(), memory_dir=tmp_path) as (client, fleet):
        tools = {t.name for t in (await client.list_tools()).tools}
        assert {"robot_recall", "robot_remember"} <= tools
        empty = _data(await client.call_tool("robot_recall", {}))
        assert empty["ok"] and "nothing remembered yet" in empty["summary"]
        saved = _data(
            await client.call_tool(
                "robot_remember", {"text": "the ball hides behind the sofa", "tags": ["place"]}
            )
        )
        assert saved["ok"] and saved["notes"] == 1 and saved["robot"] == "duck"
        again = _data(
            await client.call_tool("robot_remember", {"text": "The ball hides behind the sofa"})
        )
        assert again["notes"] == 1, "same sentence twice is one note"
        recalled = _data(await client.call_tool("robot_recall", {}))
        assert recalled["notes"] == ["the ball hides behind the sofa"]
        # the other body has its own file
        other = _data(await client.call_tool("robot_recall", {"robot": "reachy"}))
        assert other["ok"] and other["notes"] == []
        assert fleet.sessions["duck"].memory is not None
        assert fleet.sessions["duck"].memory.path == tmp_path / "microduck-sim2d.jsonl"
        assert fleet.sessions["reachy"].memory is not None
        assert fleet.sessions["reachy"].memory.path == tmp_path / "reachy-mini-mock.jsonl"
    # and it survives the server: a CLI run on the same robot would read the same file
    assert [e.text for e in RobotMemory("microduck:sim2d", tmp_path).notes()] == [
        "the ball hides behind the sofa"
    ]


async def test_memory_off(tmp_path: Path) -> None:
    async with connected(two_robots(), memory=False, memory_dir=tmp_path) as (client, fleet):
        off = _data(await client.call_tool("robot_recall", {}))
        assert not off["ok"] and "off" in off["summary"]
        saved: dict[str, Any] = _data(await client.call_tool("robot_remember", {"text": "x"}))
        assert not saved["ok"]
        assert fleet.sessions["duck"].memory is None
    assert os.listdir(tmp_path) == []
