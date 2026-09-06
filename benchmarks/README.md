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
outcome, model-claim success, available simulator ground truth, latency, calls, token usage,
failure class and affective-state presence. New artifacts use the `quackd-live-v3` schema and
resume rejects a different provider/model/scenario matrix. Use
`--resume` with the same output path after an interruption; quota exhaustion is recorded and is
not retried. The default scenarios test basic navigation and reporting. For the targeted
context experiment, select `fetch`, `follow-me` and `patrol-and-quack` explicitly; these tasks
exercise recovery, persistence and repeated observations. Add `--full-task-budget` for these
scenarios so their `.duck` budgets are respected instead of the standard 12-step cap. Treat the
output as an experiment, not as evidence of a default quality improvement.

DeepSeek uses the same runner with `--provider deepseek` and the `DEEPSEEK_API_KEY` environment
variable; its default model is `deepseek-v4-pro`.

The promotion gate requires a positive paired success delta with a 95% paired-bootstrap confidence interval,
no more than 5% median token/cost growth, no more than 5% median latency growth, and no new
budget or safety failures, replicated in two independent live sessions.

## Retained verification evidence

New runs retain transcripts and frames in `<output-stem>.runs/`, with an isolated
directory for every attempt, including retries. Keep this directory with the JSON
artifact. `verified_success` is independent of `model_claim_success`; `null` means
the checker lacks evidence or does not support the scenario. Per-scenario reports
count false claims and unknown results. Resume also requires matching timeout and
retry settings. Baseline/context order alternates by seed and repeat.

The claim-based bootstrap remains exploratory. `verified_comparisons` reports
per-scenario paired differences using seed-cluster resampling (10,000 draws, RNG seed
0). Repeats stay together. Unknown pairs are counted separately; a single cluster
has no confidence interval. Degenerate intervals do not establish equivalence or
qualify for promotion.

Targeted checks require actual movement, not just successful tool returns. Fetch
requires a held ball and at least 0.5 m reduction in distance to the initial pose.
Patrol encounters are consecutive observation frames containing a person or pet,
separated by a frame without either. Following requires three translating approaches.
The default simulator has a stationary person. Use `--sim-profile targeted-v1` for
the targeted matrix: one Microduck, fixed feasible fetch geometry, a person moving
at 0.04 m/s along a 0.9 m segment with ten-second endpoint pauses, and two simulated
seconds at rest before each observation. The seed rotates the geometry. Trajectories
use simulated time, never API latency. The profile is refused on hardware and flocks.
Tick telemetry checks the 0.4 m following distance; detection events include frames
captured inside verbs. Reference controllers exercise all three tasks on ten seeds.

V3 artifacts include source-content digests and profile/configuration identity.
Resume validates compatibility before contacting the provider; old artifacts require
a new run. Every attempt records observed usage and its completeness. Totals include
available transcript usage after interruption, but an in-flight request may still be
billed without reported usage. Incomplete totals cannot support a cost gate.

Run `python -m benchmarks.live_cloud --report-only --output <artifact.json>` to
recompute verified comparisons without provider calls. Quota exhaustion stops the
campaign with a partial checkpoint. Model failures do not stop the remaining matrix.
