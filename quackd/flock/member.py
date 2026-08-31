"""One duck in a flock: a role-driven state machine, not an LLM loop.

The member owns its duck's `Executor`, so the `.duck` allowlist, budgets, machine-enforced
abort rules and per-duck transcript apply exactly as in a solo run. Roles arrive over the
bus (SEARCH a wedge, KICK, YIELD, STOP); a role change *preempts* an in-flight composite
verb via `FlockPreempted`, which subclasses `SafetyStop` so the executor re-raises it
without recording a failure — being retasked is not a mistake.
"""

from __future__ import annotations

import contextlib
import math
from typing import TYPE_CHECKING, Any

from quackd.duckfile.schema import DuckFrontmatter
from quackd.flock.bus import Bus
from quackd.flock.messages import (
    BidMsg,
    FlockMessage,
    FlockTask,
    HbMsg,
    ResultMsg,
    RoleMsg,
)
from quackd.perception.base import Detector
from quackd.safety import (
    Aborted,
    Budget,
    BudgetExceeded,
    Executor,
    Heartbeat,
    SafetyStop,
    allow_all,
)
from quackd.transport.sim2d import Sim2DTransport
from quackd.verbs.registry import VerbResult, default_registry

if TYPE_CHECKING:
    from quackd.flock.transcript import FlockTranscript

MEMBER_TICK_S = 0.05
TURN_RATE = 1.0  # rad/s, matches the composite verbs' scanning rate


class FlockPreempted(SafetyStop):
    """The flock changed this duck's role mid-verb. Not a failure, just a redirect."""


class FlockMember:
    def __init__(
        self,
        name: str,
        contract: DuckFrontmatter,
        transport: Sim2DTransport,
        detector: Detector,
        bus: Bus,
        transcript: FlockTranscript,
        task: FlockTask,
        *,
        hb_period_s: float = 1.0,
        frame_stride: int = 4,
        dry_run: bool = False,
    ) -> None:
        self.name = name
        self.transport = transport
        self.bus = bus
        self.task = task
        self.hb_period_s = hb_period_s
        self._member_transcript = transcript.member(name)
        self._frame_stride = frame_stride
        self._frame_counter = 0
        self.budget = Budget(contract.budgets, now=transport.now)
        self.executor = Executor(
            registry=default_registry(),
            transport=transport,
            contract=contract,
            budget=self.budget,
            detector=detector,
            dry_run=dry_run,
            confirm=allow_all,  # a flock has no per-duck terminal; validate enforces confirm=[]
            log=lambda m: transcript.write("member_log", duck=name, message=m),
            on_frame=self._on_frame,
        )
        self.heartbeat = Heartbeat(transport, self.executor.abort)
        self.sub = bus.subscribe(name)
        transport.post_sleep = self._control_check
        self.flock_transcript = transcript
        self.role: RoleMsg | None = None
        self._pending: list[FlockMessage] = []
        self._preempt = False
        self._done = False
        self._acted_for_role = False
        self._searched_at: float | None = None
        self._bid: BidMsg | None = None
        self._last_hb = -1e9
        self.steps = 0
        self.verbs_failed = 0
        self.final_status = "running"

    # ── frames (strided so a flock does not write 3x the frames of a solo run) ──────

    def _on_frame(self, img: Any, caption: str) -> None:
        self._frame_counter += 1
        if self._frame_counter % self._frame_stride == 1:
            self._member_transcript.save_frame(img, caption)

    # ── bus plumbing ────────────────────────────────────────────────────────────────

    def _ingest(self) -> None:
        for msg in [*self._pending, *self.sub.drain()]:
            if msg.kind == "ROLE" and msg.duck == self.name:
                is_new = (
                    self.role is None
                    or msg.role != self.role.role
                    or msg.wedge != self.role.wedge
                    or msg.retreat != self.role.retreat
                )
                # a repeated retreat order is always actionable: we are still too close
                if is_new or msg.retreat:
                    self.role = msg
                    self._acted_for_role = False
                    self._searched_at = None
                if msg.role == "STOP":
                    self._done = True
        self._pending.clear()

    def _control_check(self) -> None:
        """Runs after EVERY sim sleep, including inside composite verbs."""
        self._maybe_hb()  # a duck mid-verb must still sound alive to the watchdog
        fresh = self.sub.drain()
        if fresh:
            self._pending.extend(fresh)
        if self.executor.abort.is_set():
            raise Aborted("flock abort")
        for msg in self._pending:
            if (
                msg.kind == "ROLE"
                and msg.duck == self.name
                and (self.role is None or msg.role != self.role.role)
            ):
                raise FlockPreempted(f"{self.name}: role change to {msg.role}")

    def _publish(self, msg: FlockMessage) -> None:
        self.bus.publish(msg)

    def _maybe_hb(self) -> None:
        now = self.transport.now()
        if now - self._last_hb < self.hb_period_s:
            return
        self._last_hb = now
        self._publish(
            HbMsg(
                t=now,
                src=self.name,
                task_id=self.task.task_id,
                role=self.role.role if self.role else "IDLE",
                steps=self.steps,
            )
        )

    # ── the loop ────────────────────────────────────────────────────────────────────

    async def run(self) -> None:
        try:
            # inside the try: a failed connect must still hit the finally below, or a
            # half-registered duck would freeze the lockstep clock for the whole flock
            await self.transport.connect()
            self.heartbeat.start()
            self.budget.start()
            while not self._done:
                self._ingest()
                if self._done:
                    break
                self._maybe_hb()
                try:
                    await self._act()
                except FlockPreempted:
                    with contextlib.suppress(Exception):
                        await self.transport.stop()
                    continue  # _ingest will pick up the new role
                try:
                    await self.transport.sleep(MEMBER_TICK_S)
                except FlockPreempted:
                    continue
            self.final_status = "stopped"
        except BudgetExceeded as e:
            self.final_status = "budget"
            self._result("budget", str(e))
        except Aborted as e:
            self.final_status = "aborted"
            self._result("aborted", str(e))
        except Exception as e:
            # a crashed member must still tell the flock it is gone, not just vanish
            self.final_status = "error"
            with contextlib.suppress(Exception):
                self._result("aborted", f"member error: {e}")
        finally:
            with contextlib.suppress(Exception):
                await self.transport.stop()
            await self.heartbeat.stop()
            self.sub.close()
            with contextlib.suppress(Exception):
                await self.transport.close()  # unregisters from the clock: never wedge time
            self.flock_transcript.write(
                "member_end", duck=self.name, status=self.final_status, steps=self.steps
            )

    def _result(self, status: str, detail: str = "", ball_moved_m: float | None = None) -> None:
        self._publish(
            ResultMsg(
                t=self.transport.now(),
                src=self.name,
                task_id=self.task.task_id,
                status=status,  # type: ignore[arg-type]
                detail=detail,
                ball_moved_m=ball_moved_m,
            )
        )

    async def _verb(self, name: str, params: dict[str, Any]) -> VerbResult:
        from quackd.safety import ConfirmDenied, VerbNotAllowed

        self.steps += 1
        try:
            result = await self.executor.run_verb(name, params, source="agent")
        except (VerbNotAllowed, ConfirmDenied) as e:
            # a contract refusal is feedback, not a member crash (mirrors the solo loop)
            result = VerbResult.fail(str(e))
        if not result.ok:
            self.verbs_failed += 1
        self.flock_transcript.write(
            "verb",
            duck=self.name,
            name=name,
            params=params,
            ok=result.ok,
            summary=result.summary,
        )
        return result

    # ── roles ───────────────────────────────────────────────────────────────────────

    async def _act(self) -> None:
        role = self.role
        if role is None or (self._acted_for_role and role.role != "SEARCH"):
            return
        if role.role == "SEARCH":
            await self._act_search(role)
        elif role.role == "KICK":
            self._acted_for_role = True
            await self._act_kick()
        elif role.role == "YIELD":
            self._acted_for_role = True
            await self._act_yield(role)

    async def _act_search(self, role: RoleMsg) -> None:
        now = self.transport.now()
        restart_due = (
            self._searched_at is not None and now - self._searched_at >= self.task.restart_s
        )
        if self._acted_for_role and not restart_due:
            return
        self._acted_for_role = True
        self._searched_at = now
        wedge = role.wedge
        if wedge is not None and self.executor.is_allowed("walk"):
            state = await self.transport.get_state()
            theta = state.theta or 0.0
            target = math.radians(wedge.start_deg)
            dtheta = math.atan2(math.sin(target - theta), math.cos(target - theta))
            if abs(dtheta) > 0.1:
                await self._verb(
                    "walk",
                    {
                        "vx": 0.0,
                        "wz": TURN_RATE if dtheta >= 0 else -TURN_RATE,
                        "duration_s": min(abs(dtheta) / TURN_RATE, 6.5),
                    },
                )
            max_steps = max(1, min(16, math.ceil(wedge.width_deg / self.task.step_deg)))
        else:
            max_steps = 8
        result = await self._verb(
            "search_scan",
            {"target": self.task.target, "step_deg": self.task.step_deg, "max_steps": max_steps},
        )
        if result.ok:
            detections = result.data.get("detections") or []
            dist = detections[0].get("est_distance_m") if detections else None
            bearing = detections[0].get("bearing_deg") if detections else None
            # only a role preemption may be swallowed here: Aborted/BudgetExceeded must
            # propagate so a dying duck ends with a RESULT instead of placing a bid
            with contextlib.suppress(FlockPreempted):
                await self._verb("quack", {"text": "quack! ball!"})  # the theatrical sighting
            self._bid = BidMsg(
                t=self.transport.now(),
                src=self.name,
                task_id=self.task.task_id,
                ball_dist_m=float(dist) if dist is not None else 9.9,
                bearing_deg=float(bearing) if bearing is not None else 0.0,
            )
            self._publish(self._bid)
        else:
            self._result("search_empty", result.summary)

    async def _act_kick(self) -> None:
        approach = await self._verb(
            "walk_to", {"target": self.task.target, "stop_distance": self.task.stop_distance}
        )
        if not approach.ok:
            self._result("miss", f"approach failed: {approach.summary}")
            return
        kick = await self._verb("kick", {"leg": self.task.kick_leg})
        moved = kick.data.get("ball_moved_m")
        state = await self.transport.get_state()
        total = float(state.extras.get("ball_displacement_m") or 0.0)
        # the contract's criterion is total displacement, so a rally of short kicks counts
        if kick.ok and (
            (moved is not None and moved >= self.task.success_moved_m)
            or total >= self.task.success_moved_m
        ):
            self._result("kicked", kick.summary, ball_moved_m=float(moved or total))
        else:
            self._result("miss", kick.summary, ball_moved_m=moved)

    async def _act_yield(self, role: RoleMsg) -> None:
        await self._verb("stop", {})
        # back off on a coordinator retreat order (measured from world ground truth), or
        # as blind courtesy when our own last ball estimate was inside the ring
        if role.retreat or (self._bid is not None and self._bid.ball_dist_m < role.min_sep_m):
            await self._verb("walk", {"vx": -0.1, "duration_s": 1.5})
            self._bid = None
