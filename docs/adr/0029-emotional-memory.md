# ADR 0029: Optional affective state and emotional recall

## Status

Experimental.

## Decision

quackd integrates `emotional-memory` in two independent opt-in layers. The lightweight
`--emotional-state` layer stores per-robot PAD affect and mood decay. The heavier
`--emotional-memory` layer ranks the robot's existing notes and episodes for the current
task. Both remain advisory: they cannot create tools, widen safety permissions, change
budgets or confirmations, or issue transport commands.

The plain JSONL managed by `RobotMemory` remains the canonical, human-editable record.
Every entry has a stable ID and may carry the affective snapshot present when it was
written. An emotional-memory SQLite index is derived from those rows, namespaced by
embedding backend, model and ranking mode, and rebuilt when its source digest changes.
Deleting an index never deletes the JSONL source.

The agent retrieves at most twice per run: once from the task description and once after
the first failed verb. MCP keeps the unfiltered `robot_recall()` behavior and accepts an
optional query for ranked recall. Local sentence-transformers and explicit
OpenAI-compatible embedding endpoints are separate experimental backends.

The affective runtime remains the only owner of live PAD state. Indexing and retrieval may
read its snapshot but never feed state transitions back into the robot runtime.

## Validation boundary

Offline validation uses fake embedders, fake providers, deterministic simulator seeds and
observation-based outcome verifiers. Paid embedding or chat calls, hardware acceptance and
claims of behavioral benefit remain separate gates. Affective ranking must outperform a
semantic-only ablation before it can be enabled by default.
