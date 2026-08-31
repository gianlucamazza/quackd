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

## M5 — The launch surface ✅

- ✅ README per brief §7 (hero GIF, quickstart, three loops + Mermaid, provider matrix, `.duck` in 20 lines, status table, roadmap, credits, safety, disclaimer)
- ✅ LAUNCH.md per §8; CONTRIBUTING.md (add a verb / submit a duck); project `.mcp.json`
- ✅ docs: architecture, duck-spec, transport-status, safety, learned-verbs, licenses, faq, mcp
- ✅ `tests/test_docs.py` keeps transport-status.md and README in sync with the code
- ✅ CHANGELOG 0.1.0; tag `v0.1.0`
- ✅ Definition of done: `uvx quackd run find-and-kick --provider fake` from README alone; `tests/test_upstream_api.py` proves no UNVERIFIED ref is reachable outside `jsonrpc`/`websocket`/`doctor`

## Open after v0.1.0

- ⏸ Real-model hero recording (needs an API key) — `quackd record find-and-kick --provider anthropic --seed 3`
- ⏸ Verify `gpt-5` / `grok-4` / `gemini-2.5-pro` default IDs against vendor docs
- ⏸ Run `--transport jsonrpc` against a real Microduck (Christmas 2026) and flip rows in `docs/transport-status.md`
- ✅ Published `quackd 0.1.0` to PyPI (2026-08-28); `uvx quackd --version` resolves
- ✅ v0.2.0 (2026-08-29): local and open-source LLM providers, `--goal`, README rewrite, logo
- ⏸ v0.2.0 PyPI publish needs `UV_PUBLISH_TOKEN` again (the line was removed from `.env` after 0.1.0)
- ⏸ First transcript from a live local server (Ollama, vLLM, llama.cpp) — none available on the dev machine
- ✅ v0.3.0 (2026-08-31): flock mode — multi-duck sim, lockstep clock, in-process bus, Contract Net auction, one planner LLM call, 10/10 seeded acceptance (ADR-0015/0016); hardened by a 69-agent adversarial review, 24 confirmed findings fixed pre-release
- ⏸ Flock future work: MQTT/LAN bus behind the same Bus protocol, hardware flocks when Microducks ship, real-provider planner recording
- ✅ Pushed `main` + `v0.1.0`; repo public; About/Topics/homepage set; GitHub Release created
- ⏸ Upload `docs/assets/social-preview.png` under Settings → Social preview (no API for it)
