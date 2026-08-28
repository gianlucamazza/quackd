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
