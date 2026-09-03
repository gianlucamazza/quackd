"""`quackd serve-mcp`: a robot, or a fleet of them, as MCP tools over stdio.

This is the second wow-demo — "I asked Claude to make the duck patrol my desk" — and it
goes through the *same* `Executor` as `.duck` runs, so allowlists, confirm gates, budgets
and the heartbeat apply to an interactive session too. Since 0.4 one server can front
several robots (`--robots duck=microduck:sim2d,reachy=reachy_mini:mock`): six `robot_*`
tools take a robot name, every robot has its own executor, budget, heartbeat and
contract, and the eight 0.3 `duck_*` tools stay as aliases of the default robot. stdout
is the wire; every log line goes to stderr.
"""

from __future__ import annotations

import contextlib
import logging
import sys
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver import Image

from quackd import __version__
from quackd.adapters.base import adapter_name, backend_name
from quackd.adapters.manifest import RobotManifest
from quackd.agent.transcript import png_bytes
from quackd.duckfile.parser import DuckParseError, load_duck
from quackd.duckfile.schema import DuckFile
from quackd.duckfile.validate import validate_duck
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
from quackd.verbs.registry import (
    Verb,
    VerbRegistry,
    VerbResult,
    default_registry,
    registry_from_manifest,
)

log = logging.getLogger("quackd.mcp")

TOOL_NAMES = (
    "robot_list",
    "robot_list_verbs",
    "robot_run_verb",
    "robot_observe",
    "robot_say",
    "robot_load_duckfile",
    "duck_list_verbs",
    "duck_run_verb",
    "duck_get_frame",
    "duck_get_state",
    "duck_set_velocity",
    "duck_stop",
    "duck_quack",
    "duck_load_duckfile",
)
"""Every tool the server registers, in this order; `docs/mcp.md` must list each one."""

INSTRUCTIONS = """You are piloting a small biped duck robot (25 cm, 800 g) through quackd.
Call duck_list_verbs first. Every action is a *verb*; the executor enforces an allowlist,
budgets and confirmation gates, so a refused call is a rule, not a bug. Prefer composite
verbs (search_scan, walk_to) over micro-managing velocities. Load a .duck file with
duck_load_duckfile to adopt a task contract; then follow its body as your instructions.
Call duck_stop if anything looks wrong."""

FLEET_INSTRUCTIONS = """You are piloting {n} robot(s) through quackd: {names}.
Call robot_list first, then robot_list_verbs(robot) for each body you will use: verbs come
from each robot's own manifest, so they differ per robot. Every action is a *verb*; each
robot's executor enforces its own allowlist, budgets and confirmation gates, so a refused
call is a rule, not a bug. Prefer composite verbs (search_scan, go_to) over micro-managing
velocities. Load a .duck file with robot_load_duckfile(path, robot) to adopt a task
contract on one robot; then follow its body as your instructions. The duck_* tools are
deprecated aliases that target the default robot ({default}). Call
robot_run_verb(verb="stop", robot=...) if anything looks wrong."""


def _alias(of: str) -> str:
    return f" Deprecated 0.3 alias of {of} on the default robot; removed in 0.5."


def _prefixed(emit: Callable[..., None], name: str) -> Callable[[str], None]:
    """Log lines from a fleet say which robot they are about."""

    def log_line(message: str) -> None:
        emit("%s: %s", name, message)

    return log_line


def _stash_frames(session: RobotSession) -> Callable[[Any, str], None]:
    """The executor's `on_frame` hook: keep the frame `observe` captured for `robot_observe`."""

    def on_frame(img: Any, _cause: str) -> None:
        session.last_frame = img

    return on_frame


@dataclass
class RobotSession:
    """One robot behind the server: its own executor, budget, heartbeat and contract."""

    name: str
    transport: DuckTransport
    registry: VerbRegistry
    executor: Executor
    heartbeat: Heartbeat
    detector: Detector | None = None
    duck: DuckFile | None = None
    manifest: RobotManifest | None = None
    """Set on connect when the transport is an adapter that describes itself."""
    frames: int = 0
    calls: int = 0
    log_lines: list[str] = field(default_factory=list)
    last_frame: Any = None
    """The most recent frame an `observe` captured, so `robot_observe` can return it."""
    explicit_registry: bool = False
    """A caller-supplied registry is kept as is; otherwise the manifest builds one."""

    def shown_name(self, verb: Verb) -> str:
        """The name a client sees: the loaded contract's own spelling when it used an alias."""
        if self.duck is not None:
            for spelled in self.executor.allowed:
                if spelled != verb.name and self.registry.canonical(spelled) == verb.name:
                    return spelled
        return verb.name

    def adopt(self, duck: DuckFile) -> None:
        self.duck = duck
        self.executor.contract = duck.frontmatter
        self.executor.budget = Budget(duck.frontmatter.budgets, now=self.transport.now)
        self.executor.budget.start()
        self.executor.consecutive_failures.clear()

    async def connect(self) -> None:
        connected = await self.transport.connect()
        if isinstance(connected, RobotManifest):
            # an adapter: the vocabulary is the manifest's, not the Microduck default
            self.manifest = connected
            self.executor.manifest = connected
            if not self.explicit_registry:
                self.registry = registry_from_manifest(connected, self.transport)
                self.executor.registry = self.registry
        self.heartbeat.start()

    async def close(self) -> None:
        await self.heartbeat.stop()
        with contextlib.suppress(Exception):
            await self.transport.stop()
        with contextlib.suppress(Exception):
            await self.transport.close()

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

    async def info(self, *, default: bool) -> dict[str, Any]:
        m = self.manifest
        healthy: bool | None = None
        reason: str | None = None
        health = getattr(self.transport, "health", None)
        if health is not None:
            try:
                h = await health()
                healthy, reason = bool(h.ok), h.reason
            except Exception as e:  # informational: a sick robot is a row, not a crash
                healthy, reason = False, str(e)
        return {
            "name": self.name,
            "adapter": adapter_name(self.transport),
            "backend": backend_name(self.transport),
            "vendor": m.vendor if m else None,
            "model": m.model if m else None,
            "embodiment": m.embodiment if m else None,
            "mobility": m.mobility if m else None,
            "manifest_id": m.id if m else None,
            "digest": m.digest() if m else None,
            "contract": self.duck.name if self.duck else None,
            "healthy": healthy,
            "health_reason": reason,
            "aborted": self.executor.abort.is_set(),
            "default": default,
        }

    def verbs_payload(self) -> dict[str, Any]:
        reg = self.registry
        aliases = reg.aliases()
        return {
            "robot": self.name,
            "contract": self.duck.name if self.duck else None,
            "manifest_id": self.manifest.id if self.manifest else None,
            "verbs": [
                {
                    "name": self.shown_name(v),
                    "canonical": v.name,
                    "aliases": [a for a, c in aliases.items() if c == v.name],
                    "core": v.core,
                    "kind": v.kind,
                    "safety_class": v.safety_class,
                    "allowed": self.executor.is_allowed(v.name),
                    "description": v.description,
                    "params": v.tool_schema()["input_schema"],
                }
                for v in reg.verbs()
            ],
        }

    async def observe(self) -> list[str | Image]:
        """The `observe` verb through the executor, then the frame it captured."""
        self.last_frame = None
        result = await self.run("observe", {})
        if not result["ok"] or self.last_frame is None:
            # refused, no camera, or a dry run (nothing was captured): words only
            return [f"{self.name}: {result['summary']}"]
        self.frames += 1
        summary = str(result["summary"]).removeprefix("frame captured; ")
        return [
            f"{self.name} camera: {summary}",
            Image(data=png_bytes(self.last_frame), format="png"),
        ]

    async def say(self, text: str) -> dict[str, Any]:
        if self.manifest is not None and "sound" not in self.manifest.intents:
            return {
                "ok": False,
                "summary": f"{self.name} ({self.manifest.model}) has no sound intent",
                "data": {},
            }
        return await self.run("say", {"text": text})

    def load(self, path: str) -> dict[str, Any]:
        try:
            duck = load_duck(path)
        except DuckParseError as e:
            return {"ok": False, "error": str(e)}
        if duck.frontmatter.flock is not None:
            # same guard as serve(): one MCP pilot must not adopt a many-robot contract
            return {
                "ok": False,
                "error": (
                    "flock ducks are not available over MCP (this session is one pilot, "
                    f"a flock needs a coordinator). Run it with: quackd run {path}"
                ),
            }
        if self.manifest is not None:
            problems = validate_duck(duck, [self.manifest], registry=self.registry)
            if problems:
                return {
                    "ok": False,
                    "error": "; ".join(p.message for p in problems),
                    "problems": [p.message for p in problems],
                }
        self.adopt(duck)
        return {
            "ok": True,
            "robot": self.name,
            "name": duck.name,
            "contract": duck.frontmatter.model_dump(),
            "instructions": duck.body,
            "note": f"The executor now enforces this contract for every call to {self.name}.",
        }


DuckSession = RobotSession
"""The 0.3 name."""


def _result(r: VerbResult) -> dict[str, Any]:
    return {"ok": r.ok, "summary": r.summary, "data": r.data}


@dataclass
class Fleet:
    sessions: dict[str, RobotSession]
    default: str

    def get(self, name: str | None) -> RobotSession | None:
        return self.sessions.get(name or self.default)

    def unknown(self, name: str | None) -> dict[str, Any]:
        return {
            "ok": False,
            "error": f"unknown robot {name!r}; robots: {', '.join(self.sessions)}",
        }

    async def connect_all(self) -> None:
        """Sequential and fail-fast: a fleet with a hole in it is not served."""
        connected: list[RobotSession] = []
        for session in self.sessions.values():
            try:
                await session.connect()
            except BaseException:
                for done in connected:
                    with contextlib.suppress(Exception):
                        await done.close()
                raise
            connected.append(session)

    async def close_all(self) -> None:
        for session in self.sessions.values():
            with contextlib.suppress(Exception):
                await session.close()


def _pick_default(robots: Mapping[str, Any]) -> str:
    """The only robot; else the first Microduck (the `duck_*` aliases mean a duck); else
    the first declared."""
    names = list(robots)
    if len(names) == 1:
        return names[0]
    for name, transport in robots.items():
        if adapter_name(transport) in (None, "microduck"):
            return name
    return names[0]


def _instructions(fleet: Fleet) -> str:
    solo = fleet.sessions[fleet.default]
    if len(fleet.sessions) == 1 and adapter_name(solo.transport) in (None, "microduck"):
        return INSTRUCTIONS
    return FLEET_INSTRUCTIONS.format(
        n=len(fleet.sessions), names=", ".join(fleet.sessions), default=fleet.default
    )


def build_fleet_server(
    robots: Mapping[str, DuckTransport],
    *,
    duckfile: str | None = None,
    dry_run: bool = False,
    yes: bool = False,
    registry: VerbRegistry | None = None,
    detector: Detector | None = None,
    heartbeat_period_s: float = 0.5,
    default: str | None = None,
) -> tuple[MCPServer, Fleet]:
    """One MCP server over several robots, each behind its own executor.

    `--yes` and `--dry-run` are global; contracts, budgets and abort flags are per robot.
    A `.duck` given at startup is adopted by the default robot."""
    if not robots:
        raise ValueError("a fleet needs at least one robot")
    sessions: dict[str, RobotSession] = {}
    for name, transport in robots.items():
        reg = registry or default_registry()
        det = detector
        if det is None and backend_name(transport) == "sim2d":
            from quackd.perception.color_blob import ColorBlobDetector

            det = ColorBlobDetector()
        executor = Executor(
            registry=reg,
            transport=transport,
            contract=None,
            detector=det,
            dry_run=dry_run,
            confirm=allow_all if yes else deny_all,
            log=_prefixed(log.info, name),
        )
        heartbeat = Heartbeat(
            transport,
            executor.abort,
            period_s=heartbeat_period_s,
            log=_prefixed(log.warning, name),
        )
        session = RobotSession(
            name=name,
            transport=transport,
            registry=reg,
            executor=executor,
            heartbeat=heartbeat,
            detector=det,
            explicit_registry=registry is not None,
        )
        executor.on_frame = _stash_frames(session)
        sessions[name] = session
    fleet = Fleet(sessions, default or _pick_default(robots))
    if fleet.default not in sessions:
        raise ValueError(f"default robot {fleet.default!r} is not one of {list(sessions)}")
    if duckfile:
        sessions[fleet.default].adopt(load_duck(duckfile))

    @contextlib.asynccontextmanager
    async def lifespan(_server: MCPServer) -> AsyncIterator[Fleet]:
        await fleet.connect_all()
        for session in fleet.sessions.values():
            log.info(
                "quackd MCP server up: robot=%s transport=%s dry_run=%s",
                session.name,
                backend_name(session.transport),
                dry_run,
            )
        try:
            yield fleet
        finally:
            await fleet.close_all()

    mcp = MCPServer(
        "quackd", instructions=_instructions(fleet), version=__version__, lifespan=lifespan
    )

    def me() -> RobotSession:
        return fleet.sessions[fleet.default]

    # ── the fleet tools ─────────────────────────────────────────────────────────────

    @mcp.tool(
        description="Every robot this server fronts (adapter, body, manifest, contract, "
        "health) and which one is the default. Call this first."
    )
    async def robot_list() -> dict[str, Any]:
        return {
            "robots": [
                await s.info(default=(name == fleet.default)) for name, s in fleet.sessions.items()
            ],
            "default": fleet.default,
        }

    @mcp.tool(
        description="One robot's verbs from its own manifest: params, safety class, "
        "canonical name, aliases, and whether its contract allows each now."
    )
    async def robot_list_verbs(robot: str | None = None) -> dict[str, Any]:
        session = fleet.get(robot)
        return session.verbs_payload() if session else fleet.unknown(robot)

    @mcp.tool(
        description="Run a verb on one robot through its executor, with JSON params. "
        "Refusals come back as ok=false; a verb its manifest lacks is a refusal too."
    )
    async def robot_run_verb(
        verb: str, params: dict[str, Any] | None = None, robot: str | None = None
    ) -> dict[str, Any]:
        session = fleet.get(robot)
        return await session.run(verb, params) if session else fleet.unknown(robot)

    @mcp.tool(
        description="The observe verb on one robot, through its executor: the camera frame "
        "as a PNG plus a detection summary.",
        structured_output=False,
    )
    async def robot_observe(robot: str | None = None) -> list[str | Image]:
        session = fleet.get(robot)
        return await session.observe() if session else [str(fleet.unknown(robot)["error"])]

    @mcp.tool(
        description="Say something on one robot: tones on a Microduck, an expressive sound "
        "on a Reachy Mini. A robot without a sound intent refuses."
    )
    async def robot_say(text: str, robot: str | None = None) -> dict[str, Any]:
        session = fleet.get(robot)
        return await session.say(text) if session else fleet.unknown(robot)

    @mcp.tool(
        description="Load a .duck contract on one robot: its requires are checked against "
        "that robot's manifest, then its allowlist and budgets apply there; the body comes "
        "back as instructions."
    )
    async def robot_load_duckfile(path: str, robot: str | None = None) -> dict[str, Any]:
        session = fleet.get(robot)
        return session.load(path) if session else fleet.unknown(robot)

    # ── the 0.3 tools, aliases of the default robot ─────────────────────────────────

    @mcp.tool(
        description="List every verb: params, safety class, and whether it is allowed now."
        + _alias("robot_list_verbs")
    )
    async def duck_list_verbs() -> dict[str, Any]:
        return me().verbs_payload()

    @mcp.tool(
        description="Run a verb by name with JSON params. Refusals come back as ok=false."
        + _alias("robot_run_verb")
    )
    async def duck_run_verb(name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return await me().run(name, params)

    @mcp.tool(
        description="Capture the duck's camera frame (PNG) plus a detection summary."
        + _alias("robot_observe"),
        structured_output=False,
    )
    async def duck_get_frame() -> list[str | Image]:
        session = me()
        img = await session.transport.get_frame()
        if img is None:
            return ["this transport has no camera"]
        session.frames += 1
        dets = session.detector.detect(img) if session.detector else []
        return [f"camera: {summarize_detections(dets)}", Image(data=png_bytes(img), format="png")]

    @mcp.tool(
        description="The duck's state: posture, policy, battery, pose (sim), budget status."
        + _alias("robot_run_verb(verb='report_state')")
    )
    async def duck_get_state() -> dict[str, Any]:
        session = me()
        state = (await session.transport.get_state()).model_dump()
        state["budget"] = session.executor.budget.status() if session.executor.budget else None
        state["transport"] = backend_name(session.transport)
        state["robot"] = session.name
        state["manifest_id"] = session.manifest.id if session.manifest else None
        state["dry_run"] = dry_run
        return state

    @mcp.tool(
        description="Walk for a duration: vx forward m/s, vy left m/s, wz rad/s (+ = left)."
        + _alias("robot_run_verb(verb='move')")
    )
    async def duck_set_velocity(
        vx: float = 0.15, vy: float = 0.0, wz: float = 0.0, duration_s: float = 1.0
    ) -> dict[str, Any]:
        return await me().run("walk", {"vx": vx, "vy": vy, "wz": wz, "duration_s": duration_s})

    @mcp.tool(
        description="Stop the duck immediately. Always allowed."
        + _alias("robot_run_verb(verb='stop')")
    )
    async def duck_stop() -> dict[str, Any]:
        return await me().run("stop", {})

    @mcp.tool(
        description="Make a duck sound; optional text is mapped to one of the robot's seven tones."
        + _alias("robot_run_verb(verb='quack')")
    )
    async def duck_quack(text: str | None = None) -> dict[str, Any]:
        return await me().run("quack", {"text": text})

    @mcp.tool(
        description="Load a .duck file: adopt its allowlist and budgets; get its instructions."
        + _alias("robot_load_duckfile")
    )
    async def duck_load_duckfile(path: str) -> dict[str, Any]:
        return me().load(path)

    return mcp, fleet


def build_server(
    transport: DuckTransport,
    *,
    duckfile: str | None = None,
    dry_run: bool = False,
    yes: bool = False,
    registry: VerbRegistry | None = None,
    detector: Detector | None = None,
    heartbeat_period_s: float = 0.5,
) -> tuple[MCPServer, RobotSession]:
    """One robot, the 0.3 entry point: a fleet of one named after its adapter."""
    name = adapter_name(transport) or "duck"
    mcp, fleet = build_fleet_server(
        {name: transport},
        duckfile=duckfile,
        dry_run=dry_run,
        yes=yes,
        registry=registry,
        detector=detector,
        heartbeat_period_s=heartbeat_period_s,
    )
    return mcp, fleet.sessions[name]


def serve(
    transport: str | None = None,
    duckfile: str | None = None,
    seed: int | None = None,
    address: str | None = None,
    camera_url: str | None = None,
    token: str | None = None,
    dry_run: bool = False,
    yes: bool = False,
    *,
    robot: str | None = None,
    robots: str | None = None,
    warn: Any = None,
) -> None:
    from quackd.adapters.factory import (
        RobotSpec,
        describe,
        make_adapter,
        parse_robots,
        resolve_robot,
    )

    if robots and (robot or transport):
        raise SystemExit("choose one: --robots name=<adapter>:<backend>,... or --robot/--transport")
    probe: DuckFile | None = None
    default = None
    if duckfile:
        probe = load_duck(duckfile)
        if probe.frontmatter.flock is not None:
            raise SystemExit(
                "flock ducks are not available over MCP yet (the MCP client is one pilot, "
                "a flock needs a coordinator). Run it with: quackd run " + duckfile
            )
        if isinstance(probe.frontmatter.robots, str):
            default = probe.frontmatter.robots
    specs: list[RobotSpec] = (
        parse_robots(robots)
        if robots
        else [resolve_robot(robot, transport, duck_default=default, warn=warn)]
    )
    manifests = {spec.name or describe(spec).id: describe(spec) for spec in specs}
    if probe is not None:
        # the contract lands on the default robot: refuse now, with the validator's words
        target = _pick_default(
            {name: _Probe(spec) for name, spec in zip(manifests, specs, strict=True)}
        )
        problems = validate_duck(probe, [manifests[target]])
        if problems:
            raise SystemExit(
                f"{duckfile} cannot run on {target} ({manifests[target].model}): "
                + "; ".join(p.message for p in problems)
            )
    logging.basicConfig(
        stream=sys.stderr, level=logging.INFO, format="quackd-mcp %(levelname)s %(message)s"
    )
    adapters = {
        name: make_adapter(
            spec,
            seed=seed if seed is not None else 0,
            address=address,
            camera_url=camera_url,
            token=token,
        )
        for name, spec in zip(manifests, specs, strict=True)
    }
    mcp, _fleet = build_fleet_server(adapters, duckfile=duckfile, dry_run=dry_run, yes=yes)
    mcp.run(transport="stdio")


class _Probe:
    """Enough of an adapter for `_pick_default` to choose before anything is built."""

    def __init__(self, spec: Any) -> None:
        self.name = spec.adapter
        self.backend = spec.backend


if __name__ == "__main__":  # pragma: no cover
    serve()


__all__ = [
    "TOOL_NAMES",
    "DuckSession",
    "Fleet",
    "RobotSession",
    "build_fleet_server",
    "build_server",
    "serve",
]
