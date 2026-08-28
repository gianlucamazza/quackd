# Contributing to quackd

Thanks for taking a toy duck seriously. Two kinds of contribution matter most: **new
`.duck` files** (the community funnel) and **new verbs** (the vocabulary). Both are small.

## Dev setup

```bash
git clone https://github.com/rokbenko/quackd && cd quackd
uv sync --extra dev            # add --extra anthropic etc. if you want a real provider
uv run pre-commit install
uv run pytest                  # ~15 s, no network, no keys
uv run ruff check . && uv run ruff format --check . && uv run mypy
```

Windows, macOS and Linux are all first-class. Tests must never touch the network.

## Submit a `.duck`

1. Copy a starter from [`ducks/`](ducks/) and edit the frontmatter + body.
   Spec: [docs/duck-spec.md](docs/duck-spec.md).
2. `uv run quackd validate ducks/your-duck.duck` — it must pass.
3. Run it at least once: `uv run quackd run ducks/your-duck.duck --provider fake`
   (the scripted pilot only knows the starters, so for a new duck use a real provider if
   you have a key, or add a strategy to `quackd/agent/providers/fake.py`).
4. Open a PR. In the description say what it does, which providers you tried, and what
   failed. Ducks that mostly fail are still welcome if the file says so — that is data.

Checklist: `duck: 0` · slug name · `allow` lists only registered verbs (`quackd list-verbs`)
· `confirm` ⊆ `allow` · at least one `success` line · `abort_when` uses the two enforced
phrasings if you want them enforced · body starts with `# Task`.

## Add a verb

1. Decide the kind. **Built-in** = maps 1:1 to a shipped robot behaviour (needs a VERIFIED
   upstream method in `quackd/transport/upstream_api.py`). **Composite** = plain Python over
   built-ins + perception, no new upstream dependency. **Learned** = v2, see
   [docs/learned-verbs.md](docs/learned-verbs.md).
2. Write a pydantic params model (`extra="forbid"`, ranges on every number) and an
   `async def my_verb(ctx: VerbContext, p: MyParams) -> VerbResult`. Use
   `ctx.transport.send_intent(...)`, `ctx.transport.sleep(...)`, `ctx.detector`, and
   `ctx.on_frame(img, caption)` for the GIF. Never call an LLM from a verb.
3. Register it in `register_builtins` / `register_composites` with a one-line LLM-facing
   description, a `timeout_s`, a `safety_class` (`safe` · `confirm` · `dangerous`), and a
   `done_condition`.
4. Add a test: on `MockTransport` for intent sequences, on `Sim2DTransport` for behaviour.
5. If the verb needs an upstream method we have not verified, add it to `upstream_api.py`
   as `UNVERIFIED` with a note and a row in `docs/transport-status.md`. Never invent one.
6. Mention it in `docs/architecture.md` and `CHANGELOG.md` (Unreleased).

## Working agreements

- **Conventional Commits** (`feat:`, `fix:`, `docs:`, `chore:`, `test:`).
- Consequential decisions get a short ADR in `docs/adr/` (copy the shape of an existing one).
- Every module opens with a docstring saying *why it exists*.
- Keep the default install light: provider SDKs and YOLO stay optional extras.
- No Pollen Robotics assets — no logos, meshes, or videos — ever.
- Tone: confident, playful, honest about status.

## Reporting bugs and proposing verbs

Use the issue templates. `quackd doctor` output and the relevant `transcript.jsonl` lines
turn a vague bug into a fixable one.
