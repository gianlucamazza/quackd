"""The MCP server, driven in-process by the SDK's own client over memory streams.

Proves the tool list, image content, and — the point — that the same executor rules apply
to an MCP session: no contract → safe verbs; contract loaded → allowlist and budgets.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any

import pytest
from mcp.client.session import ClientSession
from mcp.shared.memory import create_client_server_memory_streams

from quackd.mcp_server import DuckSession, build_server
from quackd.transport.sim2d import Sim2DTransport

TOOLS = {
    # 0.4: six fleet tools
    "robot_list",
    "robot_list_verbs",
    "robot_run_verb",
    "robot_observe",
    "robot_say",
    "robot_load_duckfile",
    # 0.3: eight duck_* tools, kept as aliases of the default robot
    "duck_list_verbs",
    "duck_run_verb",
    "duck_get_frame",
    "duck_get_state",
    "duck_set_velocity",
    "duck_stop",
    "duck_quack",
    "duck_load_duckfile",
}


@contextlib.asynccontextmanager
async def connected(
    **kwargs: Any,
) -> AsyncIterator[tuple[ClientSession, DuckSession, Sim2DTransport]]:
    transport = Sim2DTransport(seed=1)
    server, session = build_server(transport, heartbeat_period_s=0.05, **kwargs)
    async with create_client_server_memory_streams() as (client_streams, server_streams):
        low = server._lowlevel_server
        task = asyncio.create_task(
            low.run(server_streams[0], server_streams[1], low.create_initialization_options())
        )
        try:
            async with ClientSession(client_streams[0], client_streams[1]) as client:
                await client.initialize()
                yield client, session, transport
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task


def _data(result: Any) -> dict[str, Any]:
    assert not result.is_error, result
    assert result.structured_content is not None
    return result.structured_content


async def test_tools_and_basic_calls() -> None:
    async with connected() as (client, session, transport):
        tools = await client.list_tools()
        assert {t.name for t in tools.tools} == TOOLS
        from quackd.mcp_server import TOOL_NAMES

        assert set(TOOL_NAMES) == TOOLS  # the docs test reads the same constant
        notes = {t.name: t.description or "" for t in tools.tools}
        assert all("alias" in notes[n] for n in TOOLS if n.startswith("duck_"))
        verbs = _data(await client.call_tool("duck_list_verbs", {}))
        names = {v["name"] for v in verbs["verbs"]}
        assert {"move", "kick", "go_to", "quack"} <= names
        aliases = {v["name"]: v["aliases"] for v in verbs["verbs"]}
        assert aliases["move"] == ["walk"] and aliases["go_to"] == ["walk_to"]
        assert verbs["contract"] is None

        quack = _data(await client.call_tool("duck_quack", {"text": "hello there"}))
        assert quack["ok"] and "greet" in quack["summary"]
        assert transport.world.quacks

        frame = await client.call_tool("duck_get_frame", {})
        kinds = [c.type for c in frame.content]
        assert "image" in kinds and "text" in kinds
        image = next(c for c in frame.content if c.type == "image")
        assert image.mime_type == "image/png" and len(image.data) > 100  # v2: snake_case

        state = _data(await client.call_tool("duck_get_state", {}))
        assert state["transport"] == "sim2d" and state["posture"] == "standing"

        before = (transport.world.duck.x, transport.world.duck.y)
        moved = _data(await client.call_tool("duck_set_velocity", {"vx": 0.2, "duration_s": 1.0}))
        assert moved["ok"]
        assert (transport.world.duck.x, transport.world.duck.y) != before
        assert _data(await client.call_tool("duck_stop", {}))["ok"]
        assert session.calls == 3  # quack, set_velocity, stop go through the executor


async def test_contract_is_enforced_after_loading_a_duck() -> None:
    async with connected() as (client, _session, _transport):
        assert _data(await client.call_tool("duck_run_verb", {"name": "kick"}))["ok"] is True
        loaded = _data(await client.call_tool("duck_load_duckfile", {"path": "hello-world"}))
        assert loaded["ok"] and loaded["name"] == "hello-world"
        assert "Task" in loaded["instructions"]
        refused = _data(await client.call_tool("duck_run_verb", {"name": "kick"}))
        assert refused["ok"] is False and "allowlist" in refused["summary"]
        verbs = _data(await client.call_tool("duck_list_verbs", {}))
        allowed = {v["name"] for v in verbs["verbs"] if v["allowed"]}
        assert allowed == {"quack", "walk", "stop"}
        # budgets: hello-world allows 5 steps; the refused kick did not count, quacks do
        results = [_data(await client.call_tool("duck_quack", {})) for _ in range(6)]
        assert all(r["ok"] for r in results[:5])
        assert results[5]["ok"] is False and "budget" in results[5]["summary"]
        bad = _data(await client.call_tool("duck_load_duckfile", {"path": "nope.duck"}))
        assert bad["ok"] is False


async def test_load_duckfile_refuses_flock_ducks() -> None:
    # regression: only serve() guarded flock ducks; the load tool adopted them silently
    async with connected() as (client, session, _transport):
        res = _data(await client.call_tool("duck_load_duckfile", {"path": "flock-kick"}))
        assert res["ok"] is False and "flock" in res["error"]
        assert session.duck is None  # nothing was adopted


async def test_dry_run_sends_nothing() -> None:
    async with connected(dry_run=True) as (client, _session, transport):
        res = _data(await client.call_tool("duck_set_velocity", {"vx": 0.2}))
        assert res["ok"] and res["data"].get("dry_run") is True
        assert not transport.world.moving and transport.world.steps == 0


async def test_confirm_gated_verbs_need_yes() -> None:
    from quackd.verbs.learned import LearnedVerbSpec, register_learned_verb
    from quackd.verbs.registry import default_registry

    registry = default_registry()
    register_learned_verb(
        registry, LearnedVerbSpec(name="moonwalk", description="d", policy_path="m.onnx")
    )
    async with connected(registry=registry) as (client, _session, _transport):
        res = _data(await client.call_tool("duck_run_verb", {"name": "moonwalk"}))
        assert res["ok"] is False and "--yes" in res["summary"]
    async with connected(registry=registry, yes=True) as (client, _session, _transport):
        res = _data(await client.call_tool("duck_run_verb", {"name": "moonwalk"}))
        assert res["ok"] is False and "v2" in res["summary"]  # allowed through; no runner yet


@pytest.mark.parametrize("path", ["hello-world", "find-and-kick"])
async def test_bundled_ducks_load_by_name(path: str) -> None:
    async with connected() as (client, _session, _transport):
        assert _data(await client.call_tool("duck_load_duckfile", {"path": path}))["ok"]
