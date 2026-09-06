# Emotional-memory experiment ledger

This ledger separates completed evidence from partial or obsolete artifacts. Simulator
verification is not hardware acceptance, and model-declared success is not ground truth.

## Completed

- Offline affective runtime: 80/80 runs, no outcome/step/call mismatch, about 10.49%
  median wall overhead. This establishes stability, not behavioral value.
- OpenAI context A/B: 99/120 baseline successes and 98/120 context successes, with higher
  context tokens. No benefit demonstrated.
- DeepSeek standard A/B: 240/240 claimed successes. The scenarios saturated and cannot
  distinguish the conditions.
- `targeted-v1` smoke: six runs with retained observation evidence. Several model claims
  were rejected, confirming that independent verification is necessary. A smoke is not a
  promotion experiment.
- Full-memory plumbing: deterministic semantic and affective lanes exercise stable JSONL
  IDs, source digests, index rebuilds and score evidence. Deterministic retrieval quality
  is not evidence for either real embedding backend.

## Partial and non-resumable

- `/tmp/quackd-targeted-v1-matrix.json` stopped at 13/180 rows, all in `fetch`. No process
  remains active and neither `follow-me` nor `patrol-and-quack` was sampled. Preserve it as
  historical evidence; do not resume it after the full-memory/schema changes.
- Older `quackd-live-openai`/v2 artifacts predate independent verification and cannot
  support promotion.

## Next paid gates

Run local and OpenAI-compatible embedding lanes separately, then cross-run behavioral
smokes comparing chronological, semantic, affective, and affective-plus-PAD recall. Only a
complete verified matrix with source/model provenance may advance to replication. Paid
embedding or chat calls require an explicit budget authorization.
