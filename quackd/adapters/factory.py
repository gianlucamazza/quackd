"""`--robot <adapter>:<backend>` -> a `RobotAdapter`, plus everything the CLI needs to talk
about adapters without connecting to one (static manifests, the status table).

`--transport X` is a deprecated alias of `--robot microduck:X` for exactly one release
(one stderr line per process, a `DeprecationWarning`); it is resolved here and nowhere
else. Adapter packages are imported lazily, so listing adapters never imports an SDK.
"""

from __future__ import annotations

import importlib
import importlib.util
import re
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from quackd.adapters.base import AdapterError, RobotAdapter
from quackd.adapters.manifest import RobotManifest
from quackd.verbs.registry import VerbRegistry, registry_from_manifest

DEFAULT_ROBOT = "microduck:sim2d"

# name -> (backends, status line, pip extra for the SDK backends, SDK import to probe)
_ADAPTERS: dict[str, tuple[tuple[str, ...], str, str | None, str | None]] = {
    "microduck": (
        ("sim2d", "mock", "jsonrpc", "websocket"),
        "✅ built-in: sim2d (default), mock · 🧪 jsonrpc · ⏳ websocket",
        None,
        None,
    ),
    "reachy_mini": (
        ("sim2d", "mock", "sdk"),
        "✅ built-in: sim2d, mock · 🧪 sdk (verified names, never run on a robot)",
        "quackd[reachy]",
        "reachy_mini",
    ),
    "lerobot": (
        ("mock", "real"),
        "✅ built-in: mock · 🧪 real (verified names, never run on an arm; Python 3.12+)",
        "quackd[lerobot]",
        "lerobot",
    ),
    "rosbridge": (
        ("mock", "ws"),
        "✅ built-in: mock · 🧪 ws via roslibpy (verified names, never run against a bridge)",
        "quackd[rosbridge]",
        "roslibpy",
    ),
}
ADAPTER_NAMES = tuple(_ADAPTERS)
BACKENDS = {name: info[0] for name, info in _ADAPTERS.items()}
ADAPTER_STATUS = {name: info[1] for name, info in _ADAPTERS.items()}
ADAPTER_EXTRAS = {name: info[2] for name, info in _ADAPTERS.items() if info[2]}

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


@dataclass(frozen=True)
class RobotSpec:
    adapter: str
    backend: str
    name: str | None = None
    """The member or fleet name (`duck=microduck:sim2d`), which becomes the manifest id."""

    @property
    def key(self) -> str:
        return f"{self.adapter}:{self.backend}"

    @property
    def robot_id(self) -> str | None:
        """The manifest id to ask for: the fleet name, or the adapter's own default."""
        return self.name


def parse_robot_spec(text: str) -> RobotSpec:
    """`microduck:sim2d`, or `microduck` (its first backend). Unknown names list the choices."""
    text = text.strip().lower()
    adapter, _, backend = text.partition(":")
    if adapter not in _ADAPTERS:
        raise AdapterError(f"unknown adapter {adapter!r}; choose one of {', '.join(ADAPTER_NAMES)}")
    backends = BACKENDS[adapter]
    backend = backend or backends[0]
    if backend not in backends:
        raise AdapterError(
            f"unknown backend {backend!r} for {adapter}; choose one of {', '.join(backends)}"
        )
    return RobotSpec(adapter, backend)


def parse_robots(text: str) -> list[RobotSpec]:
    """`duck=microduck:sim2d,reachy=reachy_mini:mock` -> named specs, order preserved."""
    specs: list[RobotSpec] = []
    for item in [part.strip() for part in text.split(",") if part.strip()]:
        name, sep, spec_text = item.partition("=")
        if not sep or not _NAME_RE.match(name.strip()):
            raise AdapterError(f"{item!r} is not name=<adapter>:<backend> (name is a slug)")
        if any(s.name == name.strip() for s in specs):
            raise AdapterError(f"duplicate robot name {name.strip()!r}")
        spec = parse_robot_spec(spec_text)
        specs.append(RobotSpec(spec.adapter, spec.backend, name.strip()))
    if not specs:
        raise AdapterError("--robots needs at least one name=<adapter>:<backend>")
    return specs


_warned: set[str] = set()


def warn_once(key: str, message: str, *, echo: Callable[[str], None] | None = None) -> None:
    """A `DeprecationWarning` plus one visible line per process for `key`."""
    if key in _warned:
        return
    _warned.add(key)
    warnings.warn(message, DeprecationWarning, stacklevel=3)
    if echo is not None:
        echo(message)


def reset_warnings() -> None:
    """Tests run many CLI invocations in one process; each should see the line once."""
    _warned.clear()


def resolve_robot(
    robot: str | None,
    transport: str | None,
    *,
    duck_default: str | None = None,
    warn: Callable[[str], None] | None = None,
) -> RobotSpec:
    """`--robot` wins; `--transport X` means `microduck:X` with a deprecation line; neither
    means the duck's `robots:` default, then `microduck:sim2d`."""
    if robot and transport:
        spec = parse_robot_spec(robot)
        if spec.key != f"microduck:{transport.strip().lower()}":
            raise AdapterError(
                f"choose one: --robot {spec.key} or --transport {transport} (they disagree)"
            )
        return spec
    if robot:
        return parse_robot_spec(robot)
    if transport:
        spec = parse_robot_spec(f"microduck:{transport}")
        warn_once(
            "cli.transport",
            f"deprecated: --transport {spec.backend} is now --robot {spec.key} "
            "(the old flag is removed in 0.5)",
            echo=warn,
        )
        return spec
    if duck_default:
        return parse_robot_spec(duck_default)
    return parse_robot_spec(DEFAULT_ROBOT)


def _module(adapter: str) -> Any:
    return importlib.import_module(f"quackd.adapters.{adapter}")


def describe(spec: RobotSpec) -> RobotManifest:
    """The static manifest: no SDK import, no socket. What `validate` and `announce` use."""
    return _module(spec.adapter).describe(spec.backend, spec.robot_id)


def registry_for(spec: RobotSpec) -> VerbRegistry:
    """The vocabulary of a robot that is not connected (`list-verbs --robot`, `--goal`)."""
    module = _module(spec.adapter)
    return registry_from_manifest(
        describe(spec), implementations=module.implementations(), conditions=module.conditions()
    )


def make_adapter(
    spec: RobotSpec | str,
    *,
    seed: int | None = None,
    address: str | None = None,
    live: bool = False,
    camera_url: str | None = None,
) -> RobotAdapter:
    if isinstance(spec, str):
        spec = parse_robot_spec(spec)
    adapter: RobotAdapter = _module(spec.adapter).make(
        spec.backend,
        robot_id=spec.robot_id,
        seed=seed,
        address=address,
        live=live,
        camera_url=camera_url,
    )
    return adapter


def list_adapters() -> list[dict[str, Any]]:
    """Rows for `quackd list-adapters` and `doctor`, without importing any SDK."""
    rows = []
    for name, (backends, status, extra, probe) in _ADAPTERS.items():
        installed = True if probe is None else importlib.util.find_spec(probe) is not None
        rows.append(
            {
                "name": name,
                "backends": list(backends),
                "status": status,
                "extra": extra or "built-in",
                "installed": installed,
            }
        )
    return rows
