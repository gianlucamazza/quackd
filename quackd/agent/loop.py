"""observe → think → enforce → act, until success, failure, budget, or abort.

This is the deliberation loop. It owns nothing clever: perception is a detector, safety is
the executor, memory is the transcript. What it does own is the *shape* of a turn — one
observation in, exactly one tool call out — and the honest bookkeeping of why a run ended.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from PIL import Image

from quackd.agent.prompts import (
    META_TOOL_NAMES,
    META_TOOLS,
    build_observation_text,
    build_system_prompt,
    observation_features,
)
from quackd.agent.providers.base import (
    Decision,
    Exchange,
    LLMProvider,
    Observation,
    ToolCall,
    Usage,
)
from quackd.agent.transcript import Transcript, new_run_dir, png_bytes
from quackd.duckfile.schema import DuckFile
from quackd.perception.base import Detection, Detector
from quackd.safety import (
    Aborted,
    Budget,
    BudgetExceeded,
    ConfirmDenied,
    ConfirmFn,
    Executor,
    Heartbeat,
    SafetyStop,
    VerbNotAllowed,
    deny_all,
)
from quackd.transport.base import DuckTransport
from quackd.verbs.registry import VerbRegistry, VerbResult, default_registry

Outcome = Literal["success", "failure", "budget", "aborted", "error"]


@dataclass
class RunConfig:
    duck: DuckFile
    provider: LLMProvider
    transport: DuckTransport
    registry: VerbRegistry = field(default_factory=default_registry)
    detector: Detector | None = None
    dry_run: bool = False
    confirm: ConfirmFn = deny_all
    runs_dir: str | Path = "runs"
    run_dir: Path | None = None
    max_steps: int | None = None
    heartbeat_period_s: float = 0.5
    log: Any = lambda _m: None
    on_frame: Any = None
    """Optional callback (img, caption) for a recorder (M2). Called on every captured frame."""
    keep_images_for_last_n: int = 2


@dataclass
class RunResult:
    outcome: Outcome
    reason: str
    steps: int
    llm_calls: int
    usage: Usage
    run_dir: Path
    final_state: dict[str, Any] = field(default_factory=dict)
    gif_path: Path | None = None

    @property
    def ok(self) -> bool:
        return self.outcome == "success"


class AgentLoop:
    def __init__(self, cfg: RunConfig) -> None:
        self.cfg = cfg
        self.duck = cfg.duck
        self.fm = cfg.duck.frontmatter
        if cfg.max_steps is not None:
            self.fm = self.fm.model_copy(
                update={"budgets": self.fm.budgets.model_copy(update={"max_steps": cfg.max_steps})}
            )
        self.run_dir = cfg.run_dir or new_run_dir(cfg.runs_dir, self.fm.name)
        self.transcript = Transcript(self.run_dir)
        self.budget = Budget(self.fm.budgets, now=cfg.transport.now)
        self.executor = Executor(
            registry=cfg.registry,
            transport=cfg.transport,
            contract=self.fm,
            budget=self.budget,
            detector=cfg.detector,
            dry_run=cfg.dry_run,
            confirm=cfg.confirm,
            log=cfg.log,
            on_frame=self._on_frame,
        )
        self.heartbeat = Heartbeat(
            cfg.transport, self.executor.abort, period_s=cfg.heartbeat_period_s, log=cfg.log
        )
        self.history: list[Exchange] = []
        self.usage = Usage()

    # ── frames ──────────────────────────────────────────────────────────────────────

    def _on_frame(self, img: Image.Image, caption: str) -> None:
        self.transcript.save_frame(img, caption)
        if self.cfg.on_frame is not None:
            self.cfg.on_frame(img, caption)

    async def _observe(
        self, last_verb: str | None, last_result: VerbResult | None
    ) -> tuple[Observation, Image.Image | None]:
        state = await self.cfg.transport.get_state()
        img = await self.cfg.transport.get_frame()
        detections: list[Detection] = []
        if img is not None:
            if self.cfg.detector is not None:
                detections = self.cfg.detector.detect(img)
            self._on_frame(img, f"step {self.budget.steps}: {last_verb or 'start'}")
        text = build_observation_text(
            step=self.budget.steps,
            max_steps=self.fm.budgets.max_steps,
            state=state,
            detections=detections,
            last_verb=last_verb,
            last_result=last_result,
            budget_status=self.budget.status(),
        )
        features = observation_features(
            state=state,
            detections=detections,
            last_verb=last_verb,
            last_result=last_result,
            allowed=self.executor.allowed,
        )
        image = png_bytes(img) if (img is not None and self.cfg.provider.supports_vision) else None
        return Observation(text=text, image_png=image, features=features), img

    def _history_for_provider(self) -> list[Exchange]:
        """Older images are dropped to keep context small; the last N keep theirs."""
        n = self.cfg.keep_images_for_last_n
        out: list[Exchange] = []
        for i, ex in enumerate(self.history):
            if ex.observation.image_png is not None and i < len(self.history) - n:
                ex = ex.model_copy(
                    update={"observation": ex.observation.model_copy(update={"image_png": None})}
                )
            out.append(ex)
        return out

    # ── the loop ────────────────────────────────────────────────────────────────────

    async def run(self) -> RunResult:
        cfg = self.cfg
        tools = cfg.registry.tool_schemas(self.fm.verbs.allow) + META_TOOLS
        system = build_system_prompt(
            self.duck, [cfg.registry.get(n) for n in self.fm.verbs.allow], cfg.transport.name
        )
        self.transcript.write(
            "run_start",
            duck=self.fm.name,
            duck_path=self.duck.path,
            provider=cfg.provider.name,
            model=cfg.provider.model,
            transport=cfg.transport.name,
            dry_run=cfg.dry_run,
            contract=self.fm.model_dump(),
            system_prompt=system,
            tools=[t["name"] for t in tools],
        )
        outcome: Outcome = "error"
        reason = "loop exited unexpectedly"
        last_verb: str | None = None
        last_result: VerbResult | None = None
        retry_prompted = False

        await cfg.transport.connect()
        self.budget.start()
        self.heartbeat.start()
        try:
            while True:
                await asyncio.sleep(0)  # let the heartbeat and kill switch run
                if self.executor.abort.is_set():
                    raise Aborted(
                        str(self.heartbeat.failure) if self.heartbeat.failure else "kill switch"
                    )
                obs, _ = await self._observe(last_verb, last_result)
                if self.history and self.history[-1].decision is not None:
                    obs = obs.model_copy(
                        update={"tool_call_id": self.history[-1].decision.tool_call.id}
                    )
                self.history.append(Exchange(observation=obs))
                self.transcript.write(
                    "observation",
                    step=self.budget.steps,
                    text=obs.text,
                    has_image=obs.image_png is not None,
                    features=obs.features,
                )

                self.budget.note_llm_call()
                turn = await cfg.provider.step(system, self._history_for_provider(), tools)
                self.usage = self.usage + turn.usage
                self.transcript.write(
                    "llm",
                    step=self.budget.steps,
                    provider=cfg.provider.name,
                    model=cfg.provider.model,
                    text=turn.text,
                    tool_calls=[tc.model_dump() for tc in turn.tool_calls],
                    usage=turn.usage.model_dump(),
                    stop_reason=turn.stop_reason,
                )
                self.budget.check_time()

                if not turn.tool_calls:
                    if not retry_prompted:
                        retry_prompted = True
                        self.history[-1].decision = None
                        self.history.append(
                            Exchange(
                                observation=Observation(
                                    text="You must call exactly one tool. Choose now.",
                                    features=obs.features,
                                )
                            )
                        )
                        self.transcript.write(
                            "enforce",
                            step=self.budget.steps,
                            issue="no_tool_call",
                            action="re-prompt",
                        )
                        continue
                    outcome, reason = "failure", "the model produced no tool call twice in a row"
                    break
                retry_prompted = False
                if len(turn.tool_calls) > 1:
                    self.transcript.write(
                        "enforce",
                        step=self.budget.steps,
                        issue="multiple_tool_calls",
                        action="first_only",
                    )
                call: ToolCall = turn.tool_calls[0]
                self.history[-1].decision = Decision(tool_call=call, text=turn.text, raw=turn.raw)

                if call.name in META_TOOL_NAMES:
                    outcome = "success" if call.name == "declare_success" else "failure"
                    reason = str(call.arguments.get("reason", ""))
                    self.transcript.write(
                        "declare", step=self.budget.steps, outcome=outcome, reason=reason
                    )
                    break

                last_verb = call.name
                try:
                    last_result = await self.executor.run_verb(
                        call.name, call.arguments, source="agent"
                    )
                except VerbNotAllowed as e:
                    last_result = VerbResult.fail(str(e))
                except ConfirmDenied as e:
                    last_result = VerbResult.fail(f"{e}; choose something else or declare_failure")
                self.transcript.write(
                    "verb",
                    step=self.budget.steps,
                    name=call.name,
                    params=call.arguments,
                    ok=last_result.ok,
                    summary=last_result.summary,
                    data=last_result.data,
                )
        except BudgetExceeded as e:
            outcome, reason = "budget", str(e)
        except Aborted as e:
            outcome, reason = "aborted", str(e)
        except SafetyStop as e:
            outcome, reason = "aborted", str(e)
        finally:
            await self.heartbeat.stop()
            with contextlib.suppress(Exception):
                await cfg.transport.stop()
            final_state: dict[str, Any] = {}
            with contextlib.suppress(Exception):
                final_state = (await cfg.transport.get_state()).model_dump()
            with contextlib.suppress(Exception):
                await cfg.transport.close()
            summary = {
                "duck": self.fm.name,
                "outcome": outcome,
                "reason": reason,
                "steps": self.budget.steps,
                "llm_calls": self.budget.llm_calls,
                "elapsed_s": round(self.budget.elapsed_s, 2),
                "usage": self.usage.model_dump(),
                "provider": cfg.provider.name,
                "model": cfg.provider.model,
                "transport": cfg.transport.name,
                "dry_run": cfg.dry_run,
                "final_state": final_state,
            }
            self.transcript.write("run_end", **summary)
            self.transcript.write_summary(summary)
            self.transcript.close()
        return RunResult(
            outcome=outcome,
            reason=reason,
            steps=self.budget.steps,
            llm_calls=self.budget.llm_calls,
            usage=self.usage,
            run_dir=self.run_dir,
            final_state=final_state,
        )


async def run_duck(cfg: RunConfig) -> RunResult:
    return await AgentLoop(cfg).run()
