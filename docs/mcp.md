# Pilot the duck from Claude (MCP)

`quackd serve-mcp` exposes the duck as [Model Context Protocol](https://modelcontextprotocol.io)
tools over stdio. Claude Code or Claude Desktop becomes the pilot; quackd's executor still
sits between the model and the duck (allowlist, budgets, confirm gates, heartbeat).

Works with the built-in simulator out of the box — no hardware, no extra install.

## Tools

| Tool | What it does |
|---|---|
| `duck_list_verbs` | Every verb the connected robot provides: params, safety class, `canonical` name and `aliases`, whether it is `core`, and whether the current contract allows it. Call this first. |
| `duck_run_verb(name, params)` | Run any verb (`search_scan`, `go_to` or its alias `walk_to`, `kick`, `grab`, `gaze`, …). Refusals come back as `ok: false`. |
| `duck_get_frame` | The camera frame as a PNG image plus a one-line detection summary. |
| `duck_get_state` | Posture, policy, battery, pose (sim), budget status. |
| `duck_set_velocity(vx, vy, wz, duration_s)` | Walk (feeds the robot's deadman for you). |
| `duck_stop` | Stop. Always allowed. |
| `duck_quack(text?)` | One of the robot's seven duck sounds, picked from your text. |
| `duck_load_duckfile(path)` | Adopt a `.duck` contract: allowlist + budgets are enforced from then on; the body is returned as instructions. |

Without a loaded `.duck`, every verb that is not `dangerous` is allowed and there are no
budgets. Load one to get the guard rails.

## Claude Code

Verified against the current docs (`code.claude.com/docs/en/mcp`, 2026-08). Two options.

**1. One command** (local scope by default; `--scope project` shares it via `.mcp.json`):

```bash
claude mcp add quackd -- uvx quackd serve-mcp --robot microduck:sim2d
```

**2. Project file** — commit a `.mcp.json` at the repo root:

```json
{
  "mcpServers": {
    "quackd": {
      "command": "uvx",
      "args": ["quackd", "serve-mcp", "--robot", "microduck:sim2d"]
    }
  }
}
```

(`--transport sim2d` still works for one release; it is the same thing with a warning.)

(No `"type"` key: Claude Code reads an entry with `command` as a stdio server.)

Then in Claude Code: *"List the duck's verbs, then find the ball and kick it."*

## Claude Desktop

Edit `claude_desktop_config.json` — Settings → Developer → *Edit Config*:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "quackd": {
      "command": "uvx",
      "args": ["quackd", "serve-mcp", "--robot", "microduck:sim2d"]
    }
  }
}
```

Restart Claude Desktop completely. The duck appears under *Connectors → Manage connectors*.

> **Windows note.** Desktop apps often do not see your shell `PATH`. If the server does not
> start, replace `"uvx"` with its absolute path (`where uvx` in a terminal, e.g.
> `C:\\Users\\you\\.local\\bin\\uvx.exe`). Server stderr lands in
> `%APPDATA%\Claude\logs\mcp-server-quackd.log` (macOS: `~/Library/Logs/Claude/`).

## Useful flags

```
quackd serve-mcp --robot microduck:sim2d --seed 7    # a different world
quackd serve-mcp --duckfile find-and-kick            # start with a contract loaded
quackd serve-mcp --dry-run                           # intents are logged, never sent
quackd serve-mcp --yes                               # allow confirm-gated verbs (no terminal to ask)
quackd serve-mcp --robot microduck:jsonrpc --address tcp://127.0.0.1:9870   # real robot, experimental
```

## The two-minute script

1. `claude mcp add quackd -- uvx quackd serve-mcp --robot microduck:sim2d` (≈20 s, first run downloads quackd)
2. Open Claude Code in any folder and ask: **"Use the quackd tools. List the verbs, grab a frame, then find the ball and kick it. Quack when you're done."**
3. Watch it call `duck_list_verbs` → `duck_get_frame` → `duck_run_verb("search_scan")` → `duck_run_verb("walk_to")` → `duck_run_verb("kick")` → `duck_quack`.
4. Ask: **"Load ducks/patrol-and-quack.duck and follow it."** — now the allowlist and budgets apply, and the model has the task body as instructions.

## Safety in an MCP session

- The heartbeat runs for the whole session; if the transport fails, every later call
  returns `ok: false` and the duck has already been stopped.
- Confirm-gated verbs are **refused** unless the server was started with `--yes`, because
  there is no terminal to ask on. The refusal text tells the model why.
- On hardware, the gamepad wins: upstream arbitrates authority, quackd does not fight it.
