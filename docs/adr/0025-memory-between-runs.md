# ADR-0025: Memory between runs: one JSONL file per robot, notes the model chooses and episodes quackd writes

**Status:** accepted · **Date:** 2026-09-03 · Extends ADR-0017 (the manifest is the vocabulary; memory is not a verb) · Documented in [docs/memory.md](../memory.md)

## Context

Every run started from nothing. The transcript recorded each prompt, tool call and frame
and no later run ever read it, so a pilot that had found the ball behind the sofa three
times searched the whole room a fourth time. The README listed this among the honest
limitations. Two things were wanted: a place for the model to keep a fact on purpose, and
a record of how earlier runs ended that the next run sees without anyone curating it.

The obvious bigger designs were rejected for now: a vector store (an embedding model in
the default install, a second thing to keep in sync, and nothing to search yet at the scale
of a toy duck), a shared memory across bodies (a note about the cartoon arena is wrong for
a living room), and feeding the whole last transcript back (context cost, and the model
would relive a run instead of remembering its lesson).

## Decision

- **One append-only JSONL file per robot, keyed `adapter:backend`.** `~/.quackd/memory/`
  by default, `--memory-dir` or `QUACKD_MEMORY_DIR` otherwise. The simulator and a real
  duck never share a file. The file is meant to be read and edited by hand; a line that is
  not JSON is skipped, not fatal. It is capped at 400 entries and drops the oldest
  *episodes* first, because notes were chosen on purpose.
- **Two kinds of entry.** A *note* is one short sentence the model saved with the new
  `remember` tool (or a human with `quackd memory add`); the same sentence twice refreshes
  the old note instead of duplicating it. An *episode* is written by the loop at the end of
  every non-dry run: outcome, reason, step count and the last few verb results.
- **`remember` is a meta tool, not a verb.** It sits next to `declare_success` and
  `declare_failure`, costs an LLM call but not a step, moves nothing, and is offered only
  when memory is on. It is not in any manifest or allowlist, so ADR-0017's rule that the
  vocabulary comes from the manifest still holds for everything that touches the body.
- **The prompt carries the newest entries**, up to 20 notes and 5 episodes, under one
  heading, with one paragraph saying how to add to them. Memory off means no heading, no
  tool, no episode: the prompt is byte-for-byte what it was.
- **The starter ducks ask for it inside the strategy.** A prompt-level hint alone was
  ignored by a 14B local model; a `remember` in the last numbered step is followed. The
  flock ducks are unchanged because the coordinator does not run the deliberation loop.
- **Over MCP the same file sits behind `robot_recall` and `robot_remember`**, one memory
  per robot in the fleet, so a note saved from Claude Desktop is read by the next
  `quackd run` and the other way round.
- **Memory is never trusted by the executor.** A note is text the model wrote. The
  allowlist, budgets and confirmation gates read the contract, as before.

## Consequences

- A run's provenance still shows every fact it saved: `memory` events in the transcript,
  and `run_start` records how much memory the prompt was given.
- Tests must isolate `QUACKD_MEMORY_DIR` (the conftest does, for every test), because the
  CLI's default is the developer's home directory.
- Learned verbs (ADR-0019 territory, unshipped) are unaffected: memory changes what the
  pilot knows, not what the body can do.
