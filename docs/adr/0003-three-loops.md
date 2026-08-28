# ADR-0003: Three loops, three rates, three owners

**Status:** accepted · **Date:** 2026-08-28

## Context

An LLM takes 1–10 s to answer. A biped falls over in 0.3 s. Upstream's own architecture
note says it plainly: "LLM latency means the agent is a *high-level* controller", and
`robotd` stops the robot itself if commands stall ("LLMs stall mid-inference").

## Decision

| Loop | Rate | Where | Owner |
|---|---|---|---|
| Reflexes | 50 Hz | onboard `robotd` | RL policies: balance, gait, stand-up. quackd never touches this. |
| Steering | 5–20 Hz | quackd process | perception + composite verbs (`walk_to` closes the approach loop from detections). |
| Deliberation | ~0.2–1 Hz | LLM | reads a frame summary + state, picks the next **verb**, judges success. |

The LLM decides **what**; the steering loop decides **how to get there**; the RL policies
keep the duck **upright**. Concretely:

- The LLM's only output is one tool call per turn (`quackd/agent/loop.py` enforces it).
- Composite verbs never call the LLM. `walk_to` runs a 10 Hz detect→steer loop in Python.
- Built-in verbs are intents (`robot.move`, `robot.do`), never joint targets.
- The transport owns time (`now()`/`sleep()`), so the steering loop runs at sim speed in the
  simulator and at real time on hardware without changing verb code.

## Consequences

- A slow or stalled LLM degrades the *task*, not the *safety*: the last verb finishes or
  times out, the duck stops, upstream's deadman stops it anyway.
- Perception must be cheap enough for 10 Hz on a laptop — hence a colour-blob detector by
  default (ADR-0008), not a VLM call per frame.
- Learned verbs (v2) slot into the steering tier, not the deliberation tier: they are things
  the LLM *calls*, not things it *is*.
