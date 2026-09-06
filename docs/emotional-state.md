# Affective runtime state

quackd can keep a small runtime affective state for each `adapter:backend` using the
optional `emotional-memory` library. It is disabled by default:

```bash
uvx --from "quackd[emotional]" quackd run hello-world \
  --provider fake --emotional-state
```

The experimental `--emotional-context` flag additionally exposes the snapshot to the
model and requires `--emotional-state`. It is disabled by default and is intended only for
controlled A/B evaluation.

The state uses valence, arousal and dominance with mood decay. Successful and failed verb
results and run outcomes update it. The current snapshot is written to
`summary.json`/`transcript.jsonl` as an `affective` event.

State is stored separately from the text memory under `~/.quackd/affective/`, one SQLite
file per robot. Override it with `--emotional-dir`. `--no-memory` and `--dry-run` keep the
state in memory only. An appraisal engine can be injected by library users; its failure
falls back to the deterministic event mapping and never aborts a robot run.

CI runs the affective benchmark only in the job that installs `quackd[emotional]`; the
default dependency job remains independent of the optional extra.

The affective layer is passive and advisory. It is not inserted into the model prompt and
does not update on every camera observation in the standard agent loop. With the experimental
context flag, a cached snapshot is exposed only after operational events; it cannot add verbs,
widen an allowlist, change budgets, skip confirmation, or issue motor commands. MCP exposes the
current snapshot in `robot_list` when started with `--emotional-state`.

## Full emotional recall

The heavier experiment uses `emotional-memory` for encode/retrieve, affect-aware ranking,
resonance and reconsolidation while keeping quackd's JSONL file authoritative:

```bash
uvx --from "quackd[emotional-local]" quackd run find-and-kick \
  --provider openai --emotional-state --emotional-memory
```

The default local model is `all-MiniLM-L6-v2`. A remote OpenAI-compatible embeddings
endpoint is explicit and reads its key from an environment variable, never a persisted
flag:

```bash
quackd run find-and-kick --emotional-state --emotional-memory \
  --emotional-embedding openai-compatible \
  --emotional-embedding-model example-embedding-model \
  --allow-remote-memory \
  --emotional-embedding-api-key-env EMBEDDING_API_KEY
```

`--allow-remote-memory` is explicit consent to send note and episode text to that endpoint.
Run evidence records the endpoint digest and model, never the key or its value.

Use `--emotional-ranking semantic` as the ablation lane. Indexes live under
`~/.quackd/emotional-memory/` by default and are derived caches: editing, adding or deleting
JSONL rows changes the source digest and rebuilds the index. At most five memories enter the
prompt at run start; one additional retrieval may appear after the first failed verb.
Existing vectors are reused and only new text is embedded in batches. Configuration errors
fail before connecting to the robot; a transient recall error falls back to chronological
memory and records the run as `degraded`.

Over MCP, `robot_recall()` retains the ordinary chronological view and
`robot_recall(query="...")` returns ranked memories with source IDs and score breakdowns.

The affective benchmark reports paired latency medians/p95 and prompt/feature sizes. The
feature is retained only as an opt-in observability layer until an A/B evaluation shows a
quality benefit.
