# The `.duck` file — spec v0 (normative)

A `.duck` file is a task for an LLM-piloted duck. It is deliberately **SKILL.md-shaped**:
YAML frontmatter between `---` fences, then a Markdown body. The frontmatter is a contract
the executor enforces; the body is the prompt. **The LLM is never trusted to self-police.**

Machine-readable schema: [`../quackd/duckfile/schema.json`](../quackd/duckfile/schema.json)
(generated from `quackd/duckfile/schema.py`; a test keeps them in sync).

## File shape

```
# optional comment lines above the first fence are allowed
---
<YAML mapping>
---
<Markdown body — must be non-empty>
```

Encoding UTF-8. The first non-blank, non-comment line must be `---`.

## Frontmatter fields

| Field | Type | Required | Enforced by | Meaning |
|---|---|---|---|---|
| `duck` | `0` | yes | parser | Spec version. Only `0` exists. |
| `name` | slug `^[a-z0-9][a-z0-9-]{0,63}$` | yes | parser | Identifier; run directories and the fake pilot's strategies key on it. |
| `description` | string | yes | — | One human-facing line. Shown in the system prompt. |
| `author` | string | no | — | Credit. |
| `verbs.allow` | list of verb names, ≥ 1, unique | yes | **executor** | The only verbs the LLM may call. `stop` is always allowed. Unknown names fail `quackd validate`. |
| `verbs.confirm` | list ⊆ `allow` | no (default `[]`) | **executor** | Verbs that prompt a human y/N before running (`--yes` auto-accepts; MCP refuses unless `--yes`). |
| `budgets.max_steps` | int 1–1000 (default 40) | no | **executor** | Maximum verb executions. |
| `budgets.max_minutes` | number > 0 ≤ 180 (default 5) | no | **loop** | Transport-clock cap (sim time in `sim2d`, wall-clock on hardware). |
| `budgets.max_llm_calls` | int 1–2000 (default 40) | no | **loop** | Maximum provider calls (re-prompts count). |
| `success` | list of strings, ≥ 1 | yes | LLM (+ ground truth in sim tests) | Criteria the model judges itself against via `declare_success(reason)`. |
| `abort_when` | list of strings | no | **executor** for two phrasings; LLM otherwise | See below. |
| `persona` | string | no | — | Tone. Inserted verbatim into the system prompt. |
| `providers` | list of strings | no | — | Tested-with, **not** a restriction. |
| `learned_verbs` | list of `{name, policy, description?, metadata?}` | no | `validate` rejects non-empty in v0.1 | Reserved for v2 ([learned-verbs.md](learned-verbs.md)). |
| `flock` | mapping, see below | no | **coordinator** | Cooperating ducks (v0.3, simulator only). Absent means a single duck. |

### `flock` — cooperating ducks (v0.3, simulator only)

Added in spec v0 by quackd 0.3.0 as an optional field. Older quackd versions refuse files
that use it (strict parsing), which is the correct failure: they cannot honour the block.
A flock duck with a non-empty `verbs.confirm` fails `quackd validate` (there is no per-duck
terminal to prompt on). Full semantics: [flock.md](flock.md).

| Field | Type | Default | Enforced by | Meaning |
|---|---|---|---|---|
| `flock.members` | int 2–4, or list of 2–4 unique slugs | 3 | coordinator | Member count (named `duck-0`…) or explicit names. `--flock N` overrides. |
| `flock.allocation.method` | `auction` | `auction` | coordinator | Contract Net is the only method in v0.3. |
| `flock.allocation.bid` | `ball_distance` | `ball_distance` | coordinator | Lower camera-estimated distance wins. |
| `flock.allocation.tie_break` | `duck_id` | `duck_id` | coordinator | Lexicographic member name. |
| `flock.allocation.hysteresis_pct` | 0–100 | 20 | coordinator | A challenger must bid this much lower to unseat the current claimant. |
| `flock.allocation.claim_lease_s` | 0–60 | 6 | coordinator | Longest a claim may be held before re-auction (sim clock). A fixed fuse from the grant, not a progress timer. |
| `flock.safety.min_separation_m` | 0.1–2.0 | 0.4 | coordinator | Non-kickers keep at least this far from the action. |
| `flock.safety.one_claimant` | bool | true | coordinator | At most one duck approaches the ball. Always enforced in v0.3, `false` is rejected at validation. |
| `flock.safety.per_duck_heartbeat_s` | 0–10 | 1.0 | coordinator | Bus heartbeat period; the watchdog presumes a duck dead after 3×. |
| `flock.search.partition` | `heading` | `heading` | coordinator | Each duck owns a heading sector. |
| `flock.search.restart_s` | 0–120 | 8 | member | Re-scan the sector when nothing was found for this long. |

Unknown keys anywhere are errors (`extra="forbid"`).

### `abort_when` — what is enforced

Two phrasings are recognised (case-insensitive) and enforced by the executor:

- `Battery below N%` (also `under`, `<`) — before every verb, if the transport reports
  `battery_percent < N`, the run aborts.
- `Same verb fails N times in a row` — N consecutive failed results of one verb abort the run.

Every other entry is handed to the LLM under *"Abort conditions you must respect yourself"*.
The spec says this plainly rather than pretending prose is policy.

### Verb names

Anything in `quackd list-verbs`: built-ins `walk sit stand kick grab stand_up stop quack
gaze get_frame`, composites `search_scan walk_to approach_and`, plus any registered learned
verb. Params and ranges come from the registry, not the `.duck` file.

## Body

Free Markdown, non-empty, placed verbatim at the end of the system prompt under
*"Task file: `<name>` — `<description>`"*. Conventions the starters follow:

- `# Task` — one or two sentences of intent.
- `## Strategy` — a numbered plan naming verbs in backticks.
- `## Notes` — failure modes and what to do about them (verify-and-retry, when to give up).

The body cannot widen the contract: a verb mentioned in the body but absent from `allow`
is refused at runtime and the LLM is told so.

## Runtime semantics

- The loop ends with one of `success`, `failure` (the LLM's declaration), `budget`, or
  `aborted` (heartbeat, kill switch, enforced `abort_when`). The duck is stopped in every
  case and the transport closed.
- `--max-steps` on the CLI overrides `budgets.max_steps` for one run.
- `--dry-run` executes read-only verbs (`get_frame`) and logs everything else without
  sending an intent.

## Validation

`quackd validate <files or globs or bundled names>` prints a table and exits 1 on any
failure, with a path and a field-level reason. Checks: parse, schema, unknown verbs,
`learned_verbs` empty.

## Resolution

`quackd run x` tries `x` as a path, then `x` / `x.duck` among the bundled starters
(`ducks/` in a checkout, `quackd/ducks/` inside the wheel).

## Versioning

`duck: 0` is this document. A future `duck: 1` may change the role of the body (for
instance a structured strategy); v0 files keep parsing because the version is explicit and
the parser is strict. ([ADR-0005](adr/0005-duck-spec-v0.md))
