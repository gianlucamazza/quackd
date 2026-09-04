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

The affective layer is advisory. It cannot add verbs, widen an allowlist, change budgets,
skip confirmation, or issue motor commands. MCP exposes the current snapshot in
`robot_list` when started with `--emotional-state`.
