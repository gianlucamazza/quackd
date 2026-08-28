# Safety

A biped falls in 0.3 s; an LLM answers in 3 s. Everything here follows from that.

## Layers

| Layer | Owner | What it guarantees |
|---|---|---|
| Body | upstream `robotd` (50 Hz, onboard) | Joint and thermal clamps, fall detection, and a **deadman**: velocity goes to zero when `robot.move` notifications stop. It is the sole safety authority; clients send intents, never motor writes. |
| Conversation | quackd `Executor` | The LLM and MCP clients can only do what the `.duck` allows, as often as the budget allows, with a human in the loop where the contract says so. |
| Session | quackd `Heartbeat` + `KillSwitch` | A dead transport or a worried human ends in a `stop` intent. |

## The executor (mirrors upstream's own rules)

Every verb call — from the agent loop or an MCP session — passes `Executor.run_verb`, in
this order: abort flag → **allowlist** (`verbs.allow`; `stop` always allowed) → param
validation (errors are feedback to the model, not crashes) → **confirm gate**
(`verbs.confirm` or `safety_class` ∈ {confirm, dangerous}; y/N in the terminal, `--yes` to
auto-accept, MCP refuses unless `--yes`) → **budgets** (`max_steps` here; `max_llm_calls`
and `max_minutes` in the loop) → machine-enforced **`abort_when`** (battery threshold,
consecutive failures) → **preconditions** (not fallen, not sitting) → `--dry-run` → execute
with a **timeout**. A verb that times out or raises stops the duck and reports a failure.

## Heartbeat

A task pings `transport.heartbeat()` every 500 ms (`robot.health` on hardware, a liveness
check in sim). One failure → `stop` intent → abort flag → the loop ends with
`outcome: aborted`. Upstream's own rationale: "LLMs stall mid-inference".

## Kill switch

Ctrl-C and `q` (when stdin is a terminal) set the same abort flag; the loop's `finally`
always sends `stop` and closes the transport. Works on Windows (signal handler, not
`loop.add_signal_handler`).

## Dry run

`--dry-run` prints every intent a model *would* send and sends nothing. Read-only verbs
(`get_frame`) still run. Use it the first time you point a new `.duck` at hardware.

## On hardware

- **Run on the floor, not a table.** A 25 cm biped and a table edge do not mix.
- **Keep pets and kids clear of `kick`** (and `grab`, and `roulade`).
- **The gamepad preempts remote control.** Upstream arbitrates authority; there is no
  stop button because releasing the sticks stops the robot via the deadman. quackd does not
  try to out-rank the pad.
- quackd never sends `robot.relax` (torque off — the robot collapses) or `robot.init`
  (moves every joint). Use `robotctl` for those, with the robot on its stand.
- Start with `--dry-run`, then a `.duck` whose `allow` is `[quack, gaze, stop]`, then walk.
- **You are responsible for your robot.**

## What quackd does not protect against

A model that is *allowed* to `walk` can walk into a wall; the sim has walls, your living
room has stairs. The allowlist is your tool: a `.duck` for a new space should start small.
Report anything that lets a model bypass the executor — see [`SECURITY.md`](../SECURITY.md).
