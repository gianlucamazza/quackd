# Benchmarks

`affective_runtime.py` runs the same deterministic simulator scenarios with affective
state disabled and enabled, across seeds `0..9`. It uses the fake provider, never reads
API keys, and writes only the requested JSON artifact.

```bash
uv run --extra emotional python benchmarks/affective_runtime.py \
  --repeats 3 \
  --output /tmp/quackd-affective-benchmark.json
```

The artifact contains one row per scenario/seed/toggle with process success, wall time,
run outcome, step/LLM counts, payload sizes, and the final PAD/mood snapshot. It also
reports latency medians/p95, paired mismatches and overhead versus disabled. Compare medians by toggle;
affect is an observability signal, not a safety or success criterion. Do not compare
results across machines without recording the Python/platform metadata in the artifact.

## Live cloud benchmark

This command performs real OpenAI calls and is never part of the offline CI job:

```bash
uv run --extra openai --extra emotional python benchmarks/live_cloud.py \
  --model gpt-5.6-luna --seed 0 --seed 1 --seed 2 \
  --output /tmp/quackd-live-openai.json
```

It checks `/v1/models` first, runs only the simulator with `--yes` (never hardware), and records model,
outcome, latency, calls, token usage and affective-state presence. `gpt-5.6-sol` is the quality
lane; use it explicitly for the acceptance run after the `gpt-5.6-luna` pilot passes.
