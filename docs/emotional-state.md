# Affective runtime state

quackd can keep a small runtime affective state for each `adapter:backend` using the
optional `emotional-memory` library. It is disabled by default:

```bash
uvx --from "quackd[emotional]" quackd run hello-world \
  --provider fake --emotional-state
```

The state uses valence, arousal and dominance with mood decay. Successful and failed verb
results, observations, and run outcomes update it. The current snapshot is included in the
observation sent to the model and in `summary.json`/`transcript.jsonl` as an `affective`
event.

State is stored separately from the text memory under `~/.quackd/affective/`, one SQLite
file per robot. Override it with `--emotional-dir`. `--no-memory` and `--dry-run` keep the
state in memory only. An appraisal engine can be injected by library users; its failure
falls back to the deterministic event mapping and never aborts a robot run.

CI runs the affective benchmark only in the job that installs `quackd[emotional]`; the
default dependency job remains independent of the optional extra.

The affective layer is passive and advisory. It is not inserted into the model prompt and
does not update on every camera observation in the standard agent loop. It records
operational verb outcomes and the final run outcome. It cannot add verbs, widen an
allowlist, change budgets, skip confirmation, or issue motor commands. MCP exposes the
current snapshot in `robot_list` when started with `--emotional-state`.

The affective benchmark reports paired latency medians/p95 and prompt/feature sizes. The
feature is retained only as an opt-in observability layer until an A/B evaluation shows a
quality benefit.
