# docs/assets

| File | What it is | How it was made |
|---|---|---|
| `hero.gif` | The README hero: `find-and-kick` in the built-in `sim2d` simulator. Left: world view. Right: what the duck's camera sees. | `quackd record find-and-kick --provider fake --seed 3` — **the scripted pilot, not an LLM** (see ADR-0013). Real sim, real perception, real safety layer; the decisions are a rule. |
| `transcript-example.jsonl` | The transcript of that run: system prompt, each observation, each tool call, each verb result, token counts. | Copied from `runs/<timestamp>/transcript.jsonl`. |

To replace with a real-model recording (the intended final state):

```
quackd record find-and-kick --provider anthropic --seed 3
cp runs/<timestamp>/run.gif docs/assets/hero.gif
cp runs/<timestamp>/transcript.jsonl docs/assets/transcript-example.jsonl
```

…then edit the README caption and this table. No Pollen Robotics assets live here, ever.
