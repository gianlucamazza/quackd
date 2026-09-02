# Pilot the robot from Claude (MCP)

`quackd serve-mcp` exposes a robot, or a fleet of them, as
[Model Context Protocol](https://modelcontextprotocol.io) tools over stdio. Claude Code or
Claude Desktop becomes the pilot; quackd's executor still sits between the model and every
robot (allowlist, budgets, confirm gates, heartbeat), one executor per robot.

Works with the built-in simulator out of the box — no hardware, no extra install.

## Tools

Six fleet tools (0.4). `robot` is the name from `--robots name=<adapter>:<backend>`; omit
it (or pass `null`) to address the default robot, which is the only robot when there is
one, else the first Microduck, else the first declared.

| Tool | What it does |
|---|---|
| `robot_list` | Every robot this server fronts: name, adapter, backend, vendor, model, embodiment, mobility, manifest id and digest, loaded contract, health, and which one is the default. Call this first. |
| `robot_list_verbs(robot?)` | That robot's verbs from its own manifest: params, safety class, `canonical` name and `aliases`, whether it is `core`, and whether its current contract allows it. |
| `robot_run_verb(robot?, verb, params?)` | Run any verb through that robot's executor (`search_scan`, `go_to` or its alias `walk_to`, `kick`, `gaze`, `express`, …). Refusals come back as `ok: false`, and a verb the manifest does not list is a refusal too. |
| `robot_observe(robot?)` | The `observe` verb through the executor (it counts against the budget), returning the camera frame as a PNG image plus a one-line detection summary. |
| `robot_say(robot?, text)` | The `say` verb: tones on a Microduck, an expressive sound on a Reachy Mini. A robot without a `sound` intent refuses with `ok: false`. |
| `robot_load_duckfile(robot?, path)` | Adopt a `.duck` contract on one robot: its `requires` (or, for `duck: 0`, its allowlist) is checked against that robot's manifest first, then allowlist and budgets are enforced for that robot only; the body is returned as instructions. Flock ducks are refused. |

The eight 0.3 tools stay as aliases that target the default robot. Each description ends
with a deprecation note; they are removed in 0.5.

| Alias | Same as |
|---|---|
| `duck_list_verbs` | `robot_list_verbs` on the default robot |
| `duck_run_verb(name, params)` | `robot_run_verb` on the default robot |
| `duck_get_frame` | a raw frame plus detections, not through the executor (kept as it was in 0.3) |
| `duck_get_state` | posture, policy, battery, pose (sim), budget status of the default robot |
| `duck_set_velocity(vx, vy, wz, duration_s)` | `robot_run_verb(verb="move", ...)` (feeds the robot's deadman for you) |
| `duck_stop` | `robot_run_verb(verb="stop")`, always allowed |
| `duck_quack(text?)` | `robot_run_verb(verb="quack", ...)`, a Microduck verb, so a Reachy refuses it |
| `duck_load_duckfile(path)` | `robot_load_duckfile` on the default robot |

Without a loaded `.duck`, every verb that is not `dangerous` is allowed and there are no
budgets. Load one to get the guard rails. Contracts, budgets and abort flags are per
robot: loading a contract on `duck` changes nothing for `reachy`.

Simulated robots in one fleet each get their own world; a shared arena over MCP is future
work (a flock needs a coordinator, and one MCP pilot is not one). Run a heterogeneous task
with `quackd run reachy-spots-duck-kicks` instead ([flock.md](flock.md)).

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
quackd serve-mcp --robots duck=microduck:sim2d,reachy=reachy_mini:mock       # a fleet: robot_* tools, one executor each
```

## The two-minute script

1. `claude mcp add quackd -- uvx quackd serve-mcp --robot microduck:sim2d` (≈20 s, first run downloads quackd)
2. Open Claude Code in any folder and ask: **"Use the quackd tools. List the verbs, grab a frame, then find the ball and kick it. Quack when you're done."**
3. Watch it call `robot_list` → `robot_list_verbs` → `robot_observe` → `robot_run_verb("search_scan")` → `robot_run_verb("go_to")` → `robot_run_verb("kick")` → `robot_say` (or the `duck_*` spellings, which do the same thing).
4. Ask: **"Load ducks/patrol-and-quack.duck and follow it."** — now the allowlist and budgets apply, and the model has the task body as instructions.

## Safety in an MCP session

- One heartbeat per robot runs for the whole session; if a robot's transport fails, every
  later call to that robot returns `ok: false` and that robot has already been stopped.
  The other robots in the fleet carry on.
- Every robot connects at startup, in the order given; if one cannot, the server stops
  and disconnects the ones that did, rather than fronting a fleet with a hole in it.
- Confirm-gated verbs are **refused** unless the server was started with `--yes`, because
  there is no terminal to ask on. The refusal text tells the model why.
- On hardware, the gamepad wins: upstream arbitrates authority, quackd does not fight it.
