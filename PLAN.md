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

## M3 — The brain ✅

- ✅ Providers: anthropic (Messages API, adaptive thinking default, one tool call via `tool_choice any + disable_parallel_tool_use`, thinking blocks replayed, refusal handling, server-side fallbacks with SDK-age fallback), openai, grok (xAI endpoint), gemini; lazy imports, clear missing-extra / missing-key errors
- ✅ Prompts carry the contract; confirm gates (`typer.confirm`, `--yes`), budgets, `--dry-run` live in the CLI
- ✅ Offline provider tests against stubbed clients (request mapping, response parsing, refusal, error chain); 98 tests
- ✅ Hero GIF `docs/assets/hero.gif` + `transcript-example.jsonl` — ADR-0013: **scripted-pilot recording, labelled**
- ⏸ Real-provider hero recording — blocked on an API key. Unblock: `quackd record find-and-kick --provider anthropic --seed 3`, copy `run.gif` + `transcript.jsonl` into `docs/assets/`, drop the label
- ⏸ Verify non-Anthropic default model IDs (`gpt-5`, `grok-4`, `gemini-2.5-pro`) against vendor docs; all overridable via `QUACKD_MODEL`

## M4 — The socket ✅

- ✅ `mcp_server.py` (MCP SDK v2 `MCPServer`, stdio, lifespan-managed transport + heartbeat), eight `duck_*` tools through the shared Executor, `duck_get_frame` returns `Image` content; `--yes` for confirm gates
- ✅ `transport/jsonrpc_unix.py` (EXPERIMENTAL: hello handshake with API-version check, NDJSON, `robot.move` notifications, `robot.health` heartbeat, `unix://` + `tcp://` addresses) + fake-robotd TCP tests
- ✅ `transport/websocket_stub.py` (STUB that points at upstream's draft)
- ✅ `quackd doctor` (core deps, providers/keys masked, extras, transports, UNVERIFIED assumptions)
- ✅ `docs/mcp.md` with verified Claude Code (`claude mcp add`, `.mcp.json`) and Claude Desktop config; 2-minute script; Windows note
- ✅ In-process MCP client tests over memory streams (tool list, image content, contract enforcement, budgets, dry-run, confirm gate)

## M5 — The launch surface ⬜

- ⬜ README per brief §7; LAUNCH.md per §8; CONTRIBUTING.md
- ⬜ docs: architecture, duck-spec, transport-status, safety, learned-verbs, licenses, faq
- ⬜ CHANGELOG 0.1.0; tag `v0.1.0`
- ⬜ Definition of done: stranger with `uv` reaches the north-star demo from README alone;
  no UNVERIFIED upstream call reachable without `--transport jsonrpc|websocket`
