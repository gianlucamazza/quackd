# Targeted verification smoke, 2026-09-05

DeepSeek `deepseek-v4-pro`, seed 0, one repeat, full task budgets, both context
conditions. Six runs completed; five model claims succeeded, three passed the
observation-based verifier. This is exploratory and not a promotion experiment.

| Task | Baseline verified | Context verified | Evidence |
| --- | --- | --- | --- |
| fetch | false | true | Context held the ball and returned 0.598 m toward start |
| follow-me | false | false | Both claimed success after only one translating approach |
| patrol-and-quack | true | true | Three translating legs and completed announcements |

Both fetch conditions retried after a timeout. Token fields count the final attempt,
while wall time includes retries; these must not be interpreted as total monetary
cost. The full 180-run matrix is deferred: the simulator's person is stationary,
making repeated no-op approaches an inadequate following experiment. The next
experiment needs a deterministic moving-person scenario, then another smoke.

Local artifacts: `/tmp/quackd-verified-smoke.json` and its `.runs` sibling retain
transcripts, frames and summaries for every attempt. The smoke runner started with
the initial verifier; subsequent visibility hardening must be applied when replaying
its retained evidence. No raw evidence is published by this report.

Validation: full local suite passed (two optional skips), Ruff, mypy, ten task
contracts and package build passed. GitHub exposed no active workflow; CodeRabbit
reported a skipped review for the base branch. These are not remote CI passes.

Remaining work: dynamic following fixture, clustered verified-outcome intervals,
strict row-field schema validation, complete attempt-level usage aggregation, full
matrix and any conditional replication. Emotional context remains experimental.
