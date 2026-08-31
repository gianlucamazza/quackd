"""The blackboard: a tiny pub/sub bus every flock message crosses exactly once.

In-process only in v0.3 (the `Bus` protocol is the seam a LAN/MQTT bridge would fill
later). One hard rule keeps the lockstep clock alive: **nobody ever awaits the bus**.
Publishing is a synchronous fan-out to per-subscriber queues; consumers drain between
sim sleeps. A participant blocked on a queue would not be asleep on the clock, and the
whole flock's time would stop.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from typing import Protocol

from quackd.flock.messages import FlockMessage


class Subscription:
    def __init__(self, subscriber_id: str, on_close: Callable[[Subscription], None]) -> None:
        self.subscriber_id = subscriber_id
        self._queue: deque[FlockMessage] = deque()
        self._on_close = on_close
        self.closed = False

    def _push(self, msg: FlockMessage) -> None:
        if not self.closed:
            self._queue.append(msg)

    def drain(self) -> list[FlockMessage]:
        """Everything queued, non-blocking, publish order preserved."""
        out = list(self._queue)
        self._queue.clear()
        return out

    def close(self) -> None:
        self.closed = True
        self._queue.clear()
        self._on_close(self)


class Bus(Protocol):
    def publish(self, msg: FlockMessage) -> None: ...

    def subscribe(self, subscriber_id: str) -> Subscription: ...


class InProcessBus:
    def __init__(self, *, tap: Callable[[FlockMessage], None] | None = None) -> None:
        self._subs: list[Subscription] = []
        self._tap = tap
        self.published = 0

    def publish(self, msg: FlockMessage) -> None:
        self.published += 1
        if self._tap is not None:
            self._tap(msg)
        for sub in self._subs:
            if sub.subscriber_id != msg.src:  # no echo to the sender
                sub._push(msg)

    def subscribe(self, subscriber_id: str) -> Subscription:
        sub = Subscription(subscriber_id, self._subs.remove)
        self._subs.append(sub)
        return sub
