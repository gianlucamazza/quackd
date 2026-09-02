# Safety

A biped falls in 0.3 s; an LLM answers in 3 s. Everything here follows from that.

## Layers

| Layer | Owner | What it guarantees |
|---|---|---|
| Body | the robot's own controller (the Microduck's `robotd` at 50 Hz, onboard) | Joint and thermal clamps, fall detection, and, on the Microduck, a **deadman**: velocity goes to zero when `robot.move` notifications stop. The body is the sole safety authority; clients send intents, never motor writes. What each body offers is declared in its manifest's `safety_authority` and is not the same everywhere (see "On other bodies"). |
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
(`observe`, alias `get_frame`, and `report_state`) still run. Use it the first time you
point a new `.duck` at hardware.

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

## On other bodies

Since 0.4 quackd drives more than the duck, and the honest answer to "what stops it when
quackd goes quiet" differs per body. Each manifest says so
(`safety_authority: {native, deadman}`), and `stop` always means stop, never collapse:

| Body | Native authority | What `stop` does | Never sent |
|---|---|---|---|
| Microduck (`microduck:*`) | `robotd_deadman`: velocity zeroes when intents stop | `robot.stop` | `robot.relax`, `robot.init` |
| Reachy Mini (`reachy_mini:*`) | `none`: no client deadman or e-stop was verified; quackd's heartbeat is the authority | `cancel_move` | `disable_motors` (limp) |
| LeRobot arm (`lerobot:*`) | `torque_limit`: the gripper's torque and current caps, plus `max_relative_target` when configured; no deadman, a position-controlled arm holds its goal | re-sends the present position as the goal (hold) | `disable_torque` (LeRobot's own `disconnect()` does, by its default, at the end of a session) |
| rosbridge base (`rosbridge:*`) | `none`: neither rosbridge nor the driver has a deadman we verified | publishes a zero Twist; quackd also re-sends the Twist at 10 Hz while a verb runs | silence |

The verbs a body lacks are not gated, they do not exist: a head cannot `kick`, an arm
cannot `move`, a base cannot `say`, and `validate --robot` says so before a run starts.
`pick` on the arm and `wake_up` on the head are confirm-gated in their manifests because
they move the whole body under a controller quackd does not write.

## What quackd does not protect against

A model that is *allowed* to `walk` can walk into a wall; the sim has walls, your living
room has stairs. The allowlist is your tool: a `.duck` for a new space should start small.
Report anything that lets a model bypass the executor — see [`SECURITY.md`](../SECURITY.md).
