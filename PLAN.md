# PLAN.md — quackd v0.1.0

The task DAG per milestone. Updated as work lands. Decisions live in `docs/adr/`.

Legend: ✅ done · 🔨 in progress · ⬜ todo · ⏸ blocked (with reason)

## M0 — Identity & scaffold 🔨

- ✅ Verify name: PyPI `quackd` free (404, 2026-08-28); repo `rokbenko/quackd` owned → ADR-0002
- ✅ ADR-0001 language/tooling
- ✅ `pyproject.toml` (uv, hatchling, extras: anthropic/openai/gemini/grok/all/yolo/live/dev)
- ✅ Package skeleton with "why it exists" docstrings; `quackd --help`, `--version`
- ✅ LICENSE (Apache-2.0), NOTICE, CODE_OF_CONDUCT, SECURITY, CHANGELOG, .env.example, .gitignore
- ✅ CI (ruff · mypy · pytest · validate ducks; 3.11/3.12 × ubuntu/macos), pre-commit, dependabot, issue/PR templates
- ✅ `uv sync --extra dev` green locally; `mcp` tree ≈ 15 MB → stays core (ADR-0009)
- ✅ Five starter `.duck` files written (needed by the wheel's force-include; validated in M1)
- ✅ Commit `chore: scaffold quackd v0.1.0 skeleton (M0)`

## M1 — Contract & registry ✅

- ✅ `duckfile/schema.py` (pydantic), `parser.py`, `schema.json` export (`python -m quackd.duckfile.export`), `quackd validate`
- ✅ `verbs/registry.py`, `builtin.py`, `composite.py` (registered stubs → M2), `learned.py` (interface only)
- ✅ `transport/base.py`, `mock.py`, `upstream_api.py` (VERIFIED/UNVERIFIED, from duck-ipc-proto API v16)
- ✅ `safety.py`: Budget, Executor (allowlist · confirm · dry-run · machine-enforced abort_when), Heartbeat, KillSwitch
- ✅ `agent/loop.py`, `prompts.py`, `providers/{base,fake,factory}.py`, `transcript.py`
- ✅ Five starter `.duck` files validate
- ✅ Tests (61): parser + invalid fixtures, schema sync, registry, learned dummy, executor rules, heartbeat, loop golden, CLI
- ✅ ADR-0003…0006, 0011, 0012
- ✅ ✅-criterion: `quackd run hello-world --provider fake --transport mock` writes a transcript + summary

## M2 — The world ✅

- ✅ `sim2d/world.py` (20 Hz, seeded noise, deadman, kick cone, unreliable scoop), `render.py` (top-down + perspective duck-cam), `recorder.py` (GIF via tick hook), `live.py` (optional pygame)
- ✅ `transport/sim2d.py`; `perception/color_blob.py` (HSV + bearing/distance geometry), `yolo.py` (lazy extra)
- ✅ Composite `search_scan`, `walk_to` (10 Hz closed loop), `approach_and`; FakeLLM find-and-kick strategy
- ✅ `quackd record`, `quackd list-verbs`
- ✅ Acceptance: find-and-kick succeeds on **10/10** seeds 0–9 (ground truth checked), ~1–2 s wall-clock each; `run.gif` in `runs/`
- ✅ ADR-0007, ADR-0008; 83 tests

## M3 — The brain ⬜

- ⬜ Providers: anthropic (first), openai, gemini, grok; one-tool-call-per-turn; vision blocks
- ⬜ Prompts; confirm gates; budgets; `--dry-run`
- ⬜ Offline provider tests (stubbed clients)
- ⬜ Hero GIF in `docs/assets/` — ADR-0013: fake-provider recording committed and labeled;
  real-provider recording ⏸ blocked on an API key (`quackd record ducks/find-and-kick.duck --provider anthropic`)

## M4 — The socket ⬜

- ⬜ `mcp_server.py` (MCP SDK v2, stdio), shared Executor, `duck_get_frame` image content
- ⬜ `quackd doctor`
- ⬜ `docs/mcp.md` with verified Claude Code / Claude Desktop config; 2-minute script
- ⬜ In-process MCP client tests

## M5 — The launch surface ⬜

- ⬜ README per brief §7; LAUNCH.md per §8; CONTRIBUTING.md
- ⬜ docs: architecture, duck-spec, transport-status, safety, learned-verbs, licenses, faq
- ⬜ CHANGELOG 0.1.0; tag `v0.1.0`
- ⬜ Definition of done: stranger with `uv` reaches the north-star demo from README alone;
  no UNVERIFIED upstream call reachable without `--transport jsonrpc|websocket`
