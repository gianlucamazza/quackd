# ADR-0004: Everything the LLM can do is a verb in one registry

**Status:** accepted · **Date:** 2026-08-28

## Context

Four things need the same list of actions: the LLM's tool definitions, the `.duck`
allowlist, the MCP tool list, and — in v2 — learned ONNX policies. Four lists drift; one
does not.

## Decision

A `Verb` (`quackd/verbs/registry.py`) is data plus one coroutine:

```
name · description (LLM-facing) · params: pydantic model · execute(ctx, params) -> VerbResult
timeout_s · safety_class: safe|confirm|dangerous · preconditions · done_condition · kind
```

- **Built-in verbs** (`verbs/builtin.py`) map 1:1 to shipped behaviours: `walk`, `sit`,
  `stand`, `kick`, `grab`, `stand_up`, `stop`, `quack`, `gaze`, `get_frame`.
- **Composite verbs** (`verbs/composite.py`) are plain Python over built-ins + perception:
  `search_scan`, `walk_to`, `approach_and`. They call other verbs through `ctx.run_verb`, so
  the executor's allowlist and budgets still apply inside a composite.
- **Learned verbs** (`verbs/learned.py`) are a reserved extension point: `LearnedVerbSpec`
  (ONNX path + metadata) + `register_learned_verb()`. Interface, dummy test and docs only.
- `Verb.tool_schema()` emits the provider-neutral `{name, description, input_schema}` shape
  (Anthropic's), which every provider translates. `additionalProperties: false` always.
- Execution policy (allowlist, confirm, budget, dry-run) lives in `quackd/safety.py`, never
  in a verb. A verb that raises is caught, the duck is stopped, and the LLM is told.

## Consequences

- Adding a verb is one function + one `registry.register(...)` — CONTRIBUTING documents it.
- `quackd list-verbs`, the MCP server and the system prompt are all views of the registry.
- Param validation errors are returned to the LLM as a failed `VerbResult`, not raised: a
  wrong argument is feedback, not a crash.
