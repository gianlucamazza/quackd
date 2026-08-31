"""`quackd serve-mcp`: the duck as MCP tools over stdio, for Claude Code / Claude Desktop.

This is the second wow-demo — "I asked Claude to make the duck patrol my desk" — and it
goes through the *same* `Executor` as `.duck` runs, so allowlists, confirm gates, budgets
and the heartbeat apply to an interactive session too. stdout is the wire; every log line
goes to stderr.
"""

from __future__ import annotations

import contextlib
import logging
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver import Image

from quackd import __version__
from quackd.agent.transcript import png_bytes
from quackd.duckfile.parser import DuckParseError, load_duck
from quackd.duckfile.schema import DuckFile
from quackd.perception.base import Detector, summarize_detections
from quackd.safety import (
    Aborted,
    Budget,
    BudgetExceeded,
    ConfirmDenied,
    Executor,
    Heartbeat,
    VerbNotAllowed,
    allow_all,
    deny_all,
)
from quackd.transport.base import DuckTransport
from quackd.verbs.registry import VerbRegistry, VerbResult, default_registry

log = logging.getLogger("quackd.mcp")

INSTRUCTIONS = """You are piloting a small biped duck robot (25 cm, 800 g) through quackd.
Call duck_list_verbs first. Every action is a *verb*; the executor enforces an allowlist,
budgets and confirmation gates, so a refused call is a rule, not a bug. Prefer composite
verbs (search_scan, walk_to) over micro-managing velocities. Load a .duck file with
duck_load_duckfile to adopt a task contract; then follow its body as your instructions.
Call duck_stop if anything looks wrong."""


@dataclass
class DuckSession:
    transport: DuckTransport
    registry: VerbRegistry
    executor: Executor
    heartbeat: Heartbeat
    detector: Detector | None = None
    duck: DuckFile | None = None
    frames: int = 0
    calls: int = 0
    log_lines: list[str] = field(default_factory=list)

    def adopt(self, duck: DuckFile) -> None:
        self.duck = duck
        self.executor.contract = duck.frontmatter
        self.executor.budget = Budget(duck.frontmatter.budgets, now=self.transport.now)
        self.executor.budget.start()
        self.executor.consecutive_failures.clear()

    async def run(self, name: str, params: dict[str, Any] | None) -> dict[str, Any]:
        self.calls += 1
        if self.executor.abort.is_set():
            return _result(
                VerbResult.fail("session aborted (heartbeat failed or kill switch); restart quackd")
            )
        try:
            result = await self.executor.run_verb(name, params or {}, source="mcp")
        except VerbNotAllowed as e:
            result = VerbResult.fail(str(e))
        except ConfirmDenied as e:
            result = VerbResult.fail(
                f"{e}: this verb needs human confirmation; "
                "start `quackd serve-mcp --yes` to allow it"
            )
        except BudgetExceeded as e:
            result = VerbResult.fail(f"budget exhausted: {e}")
        except Aborted as e:
            result = VerbResult.fail(f"aborted: {e}")
        return _result(result)


def _result(r: VerbResult) -> dict[str, Any]:
    return {"ok": r.ok, "summary": r.summary, "data": r.data}


def build_server(
    transport: DuckTransport,
    *,
    duckfile: str | None = None,
    dry_run: bool = False,
    yes: bool = False,
    registry: VerbRegistry | None = None,
    detector: Detector | None = None,
    heartbeat_period_s: float = 0.5,
) -> tuple[MCPServer, DuckSession]:
    registry = registry or default_registry()
    if detector is None and transport.name == "sim2d":
        from quackd.perception.color_blob import ColorBlobDetector

        detector = ColorBlobDetector()
    executor = Executor(
        registry=registry,
        transport=transport,
        contract=None,
        detector=detector,
        dry_run=dry_run,
        confirm=allow_all if yes else deny_all,
        log=lambda m: log.info(m),
    )
    heartbeat = Heartbeat(
        transport, executor.abort, period_s=heartbeat_period_s, log=lambda m: log.warning(m)
    )
    session = DuckSession(
        transport=transport,
        registry=registry,
        executor=executor,
        heartbeat=heartbeat,
        detector=detector,
    )
    if duckfile:
        session.adopt(load_duck(duckfile))

    @contextlib.asynccontextmanager
    async def lifespan(_server: MCPServer) -> AsyncIterator[DuckSession]:
        await transport.connect()
        session.heartbeat.start()
        log.info("quackd MCP server up: transport=%s dry_run=%s", transport.name, dry_run)
        try:
            yield session
        finally:
            await session.heartbeat.stop()
            with contextlib.suppress(Exception):
                await transport.stop()
            with contextlib.suppress(Exception):
                await transport.close()

    mcp = MCPServer("quackd", instructions=INSTRUCTIONS, version=__version__, lifespan=lifespan)

    @mcp.tool(description="List every verb: params, safety class, and whether it is allowed now.")
    async def duck_list_verbs() -> dict[str, Any]:
        allowed = set(session.executor.allowed)
        return {
            "contract": session.duck.name if session.duck else None,
            "verbs": [
                {
                    "name": v.name,
                    "kind": v.kind,
                    "safety_class": v.safety_class,
                    "allowed": v.name in allowed or v.name == "stop",
                    "description": v.description,
                    "params": v.tool_schema()["input_schema"],
                }
                for v in registry.verbs()
            ],
        }

    @mcp.tool(description="Run a verb by name with JSON params. Refusals come back as ok=false.")
    async def duck_run_verb(name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return await session.run(name, params)

    @mcp.tool(
        description="Capture the duck's camera frame (PNG) plus a detection summary.",
        structured_output=False,
    )
    async def duck_get_frame() -> list[str | Image]:
        img = await transport.get_frame()
        if img is None:
            return ["this transport has no camera"]
        session.frames += 1
        dets = detector.detect(img) if detector else []
        return [f"camera: {summarize_detections(dets)}", Image(data=png_bytes(img), format="png")]

    @mcp.tool(description="The duck's state: posture, policy, battery, pose (sim), budget status.")
    async def duck_get_state() -> dict[str, Any]:
        state = (await transport.get_state()).model_dump()
        state["budget"] = session.executor.budget.status() if session.executor.budget else None
        state["transport"] = transport.name
        state["dry_run"] = dry_run
        return state

    @mcp.tool(description="Walk for a duration: vx forward m/s, vy left m/s, wz rad/s (+ = left).")
    async def duck_set_velocity(
        vx: float = 0.15, vy: float = 0.0, wz: float = 0.0, duration_s: float = 1.0
    ) -> dict[str, Any]:
        return await session.run("walk", {"vx": vx, "vy": vy, "wz": wz, "duration_s": duration_s})

    @mcp.tool(description="Stop the duck immediately. Always allowed.")
    async def duck_stop() -> dict[str, Any]:
        return await session.run("stop", {})

    @mcp.tool(
        description="Make a duck sound; optional text is mapped to one of the robot's seven tones."
    )
    async def duck_quack(text: str | None = None) -> dict[str, Any]:
        return await session.run("quack", {"text": text})

    @mcp.tool(
        description="Load a .duck file: adopt its allowlist and budgets; get its instructions."
    )
    async def duck_load_duckfile(path: str) -> dict[str, Any]:
        try:
            duck = load_duck(path)
        except DuckParseError as e:
            return {"ok": False, "error": str(e)}
        session.adopt(duck)
        return {
            "ok": True,
            "name": duck.name,
            "contract": duck.frontmatter.model_dump(),
            "instructions": duck.body,
            "note": "The executor now enforces this contract for every duck_* tool call.",
        }

    return mcp, session


def serve(
    transport: str = "sim2d",
    duckfile: str | None = None,
    seed: int | None = None,
    address: str | None = None,
    dry_run: bool = False,
    yes: bool = False,
) -> None:
    from quackd.transport.factory import make_transport

    if duckfile:
        probe = load_duck(duckfile)
        if probe.frontmatter.flock is not None:
            raise SystemExit(
                "flock ducks are not available over MCP yet (the MCP client is one pilot, "
                "a flock needs a coordinator). Run it with: quackd run " + duckfile
            )
    logging.basicConfig(
        stream=sys.stderr, level=logging.INFO, format="quackd-mcp %(levelname)s %(message)s"
    )
    duck_transport = make_transport(
        transport, seed=seed if seed is not None else 0, address=address
    )
    mcp, _session = build_server(duck_transport, duckfile=duckfile, dry_run=dry_run, yes=yes)
    mcp.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    serve()


__all__ = ["DuckSession", "build_server", "serve"]
