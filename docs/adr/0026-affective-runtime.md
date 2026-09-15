# ADR 0026: Optional affective runtime state

## Status

Accepted.

## Decision

quackd integrates `emotional-memory` as an optional, per-robot runtime state. The default
installation and default CLI behavior remain unchanged. The state stores PAD affect and
mood decay in SQLite, is surfaced in run artifacts and MCP, and may receive an optional
appraisal result from library callers. It is passive by default: it is not sent to the model
and standard loop observations do not update it.

The affective layer is advisory only: it cannot create tools, widen safety permissions,
change budgets or confirmations, or issue transport commands. Flock mode remains outside
this first integration because it needs an explicit coordinator/state ownership model.

## Validation boundary

Offline validation uses the fake provider, simulator, deterministic seeds, unit tests, and
the reproducible benchmark under `benchmarks/`. Real provider and hardware acceptance
remain separate gates and require explicit credentials or connected hardware.
