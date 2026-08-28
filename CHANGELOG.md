# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `quackd serve-mcp`: the duck as MCP tools over stdio (Claude Code / Claude Desktop),
  behind the same safety executor; `docs/mcp.md` with verified client config. (M4)
- `quackd doctor`; experimental `jsonrpc` transport for the real robot (verified method
  names, fake-robotd tests); `websocket` stub tracking upstream's draft. (M4)
- Providers: `anthropic` (Claude, adaptive thinking, one tool call per turn, refusal
  handling), `openai`, `grok` (xAI OpenAI-compatible), `gemini` — all optional extras with
  lazy imports; `QUACKD_MODEL` / `QUACKD_EFFORT` overrides. (M3)
- README hero GIF and example transcript under `docs/assets/` (scripted pilot, labelled). (M3)
- `sim2d`: built-in 2D simulator (deterministic under `--seed`, deadman, kick cone,
  open-loop scoop), top-down + first-person duck-cam renders, GIF recorder, optional
  `--live` pygame window. (M2)
- Perception: `ColorBlobDetector` (HSV, bearing + distance from apparent size) and a lazy
  `YoloDetector` extra; composite verbs `search_scan`, `walk_to`, `approach_and`. (M2)
- `quackd record` and `quackd list-verbs`. (M2)
- `.duck` spec v0: strict pydantic frontmatter, generated `schema.json`, `quackd validate`
  with fail-fast field-level errors; five starter ducks bundled in the wheel. (M1)
- Verb registry with built-ins (`walk`, `sit`, `stand`, `kick`, `grab`, `stand_up`, `stop`,
  `quack`, `gaze`, `get_frame`), composite stubs, and the reserved learned-verb interface. (M1)
- Safety executor: allowlist, confirm gates, budgets, dry-run, machine-enforced
  `abort_when`, heartbeat, kill switch. (M1)
- Agent loop with transcript/summary per run, scripted `fake` provider, mock transport,
  and `upstream_api.py` with VERIFIED/UNVERIFIED upstream constants. (M1)
- Project scaffold: package, CLI skeleton, CI (ruff + mypy + pytest on 3.11/3.12,
  ubuntu + macos), pre-commit, licenses, community files. (M0)

[Unreleased]: https://github.com/rokbenko/quackd/compare/v0.1.0...HEAD
