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
  --model gpt-5.6-sol --seed 0 --seed 1 --seed 2 --repeats 3 \
  --output /tmp/quackd-live-openai.json
```

It checks `/v1/models` first, runs only the simulator with `--yes` (never hardware), and compares
baseline runs against the explicit `--emotional-context` lane over 10 seeds and 3 repeats by
default. Transient API connection, timeout and rate-limit failures are retried twice and
reported separately. Each run has a 180-second timeout by default. It records model, repeat,
outcome, latency, calls, token usage, failure class and affective-state presence. Use
`--resume` with the same output path after an interruption; quota exhaustion is recorded and is
not retried. The default scenarios test basic navigation and reporting. For the targeted
context experiment, select `fetch`, `follow-me` and `patrol-and-quack` explicitly; these tasks
exercise recovery, persistence and repeated observations. Add `--full-task-budget` for these
scenarios so their `.duck` budgets are respected instead of the standard 12-step cap. Treat the
output as an experiment, not as evidence of a default quality improvement.

DeepSeek uses the same runner with `--provider deepseek` and the `DEEPSEEK_API_KEY` environment
variable; its default model is `deepseek-v4-pro`.

The promotion gate requires a positive paired success delta with a 95% confidence interval,
no more than 5% median token/cost growth, no more than 5% median latency growth, and no new
budget or safety failures, replicated in two independent live sessions.
