"""A backend name → a `DuckTransport`.

The default is the simulator, because the north-star demo needs no hardware. The two
robot-facing transports are reachable only by name, which is how the "no UNVERIFIED
upstream call without `--robot microduck:jsonrpc|websocket`" promise is kept.
"""

from __future__ import annotations

from quackd.transport.base import DuckTransport, TransportError

TRANSPORT_NAMES = ("sim2d", "mock", "jsonrpc", "websocket")
TRANSPORT_STATUS = {
    "sim2d": "✅ built-in simulator (default)",
    "mock": "✅ scripted, for tests",
    "jsonrpc": "🧪 experimental — real robot over robotd's unix socket (or a TCP forward)",
    "websocket": "⏳ stub — tracks upstream architecture.md §5.3, not shipped upstream",
}


def make_transport(
    name: str,
    *,
    seed: int | None = None,
    address: str | None = None,
    live: bool = False,
    camera_url: str | None = None,
) -> DuckTransport:
    name = name.lower()
    if name == "sim2d":
        from quackd.transport.sim2d import Sim2DTransport

        return Sim2DTransport(seed=seed if seed is not None else 0, live=live)
    if name == "mock":
        from quackd.transport.mock import MockTransport

        return MockTransport()
    if name == "jsonrpc":
        from quackd.transport.jsonrpc_unix import JsonRpcUnixTransport

        return JsonRpcUnixTransport(address=address, camera_url=camera_url)
    if name == "websocket":
        from quackd.transport.websocket_stub import WebSocketTransport

        return WebSocketTransport(address=address)
    raise TransportError(f"unknown transport {name!r}; choose one of {', '.join(TRANSPORT_NAMES)}")
