# docs/assets

| File | What it is | How it was made |
|---|---|---|
| `logo.svg` | The quackd mark + wordmark (a geometric duck with a small "brain" spark). Our own design. | Hand-written SVG. |
| `social-preview.png` | 1280×640 card for GitHub's *Settings → Social preview* (no API for this — upload it once by hand) and for link previews. | Generated with Pillow from the logo geometry and a `sim2d` frame (script in the commit that added it; regenerate by re-running it). |
| `hero.gif` | The README hero: `find-and-kick` in the built-in `sim2d` simulator. Left: world view. Right: what the duck's camera sees. | `quackd record find-and-kick --provider fake --seed 3 --gif-size 320` — **the scripted pilot, not an LLM** (see ADR-0013). Real sim, real perception, real safety layer; the decisions are a rule. |
| `transcript-example.jsonl` | The transcript of that run: system prompt, each observation, each tool call, each verb result, token counts. | Copied from `runs/<timestamp>/transcript.jsonl`. |

To replace the hero with a real-model recording (the intended final state):

```
quackd record find-and-kick --provider anthropic --seed 3 --gif-size 320
cp runs/<timestamp>/run.gif docs/assets/hero.gif
cp runs/<timestamp>/transcript.jsonl docs/assets/transcript-example.jsonl
```

…then edit the README caption and this table. No Pollen Robotics assets live here, ever.
