# Adapter status — what has run against its real target, and what has not

quackd never silently invents an upstream API. Every method name, socket path, topic,
message type, enum or convention it relies on lives in one file per upstream, tagged
**VERIFIED** (read from upstream source on the date given, link given) or **UNVERIFIED**
(designed upstream but not shipped, or an assumption of ours, with what quackd does about
it). A test proves UNVERIFIED names are only reachable from the experimental backends.
`quackd doctor` prints every UNVERIFIED list on your machine.

| Adapter | `--robot` | Status | Upstream file | Page |
|---|---|---|---|---|
| Microduck | `microduck:sim2d` | ✅ default | | this page |
| | `microduck:mock` | ✅ | | |
| | `microduck:jsonrpc` | 🧪 experimental: every method VERIFIED, never run on a duck | [`quackd/transport/upstream_api.py`](../quackd/transport/upstream_api.py) | |
| | `microduck:websocket` | ⏳ stub: raises with a link until upstream ships it | | |
| Reachy Mini | `reachy_mini:sim2d` | ✅ `reachy-spotter` 10 of 10 seeds | | [adapters/reachy_mini.md](adapters/reachy_mini.md) |
| | `reachy_mini:mock` | ✅ | | |
| | `reachy_mini:sdk` | 🧪 every SDK name VERIFIED at a pinned commit and the 1.10.0 wheel, never run on a robot | [`quackd/adapters/reachy_mini/upstream_api.py`](../quackd/adapters/reachy_mini/upstream_api.py) | |
| LeRobot | `lerobot:mock` | ✅ | | [adapters/lerobot.md](adapters/lerobot.md) |
| | `lerobot:real` | 🧪 every LeRobot name VERIFIED at a pinned commit, exercised with a fake arm, never run on an arm (Python 3.12+) | [`quackd/adapters/lerobot/upstream_api.py`](../quackd/adapters/lerobot/upstream_api.py) | |
| rosbridge | `rosbridge:mock` | ✅ | | [adapters/rosbridge.md](adapters/rosbridge.md) |
| | `rosbridge:ws` | 🧪 every roslibpy, rosbridge and message name VERIFIED at pinned commits, exercised with fake topics, never run against a bridge | [`quackd/adapters/rosbridge/upstream_api.py`](../quackd/adapters/rosbridge/upstream_api.py) | |
| Open Duck Mini v2 | `open_duck:sim2d` | ✅ | | [adapters/open_duck.md](adapters/open_duck.md) |
| | `open_duck:mock` | ✅ | | |

**Flocks** (`--flock`, `flock.roles`) run N in-process views of one simulated world on
one lockstep clock. The MQTT bus implements the same `Bus` protocol and was exercised
once against a local broker ([lan.md](lan.md)); a flock across machines also needs a
clock across machines, which does not exist yet.

The rest of this page is the Microduck's table; the other adapters keep theirs on their
own pages.

## Microduck

Read: 2026-08-28. Upstream contract: `duck-ipc-proto` **API v16** (`API_VERSION`),
JSON-RPC 2.0, one object per line (NDJSON), one unix socket per service.
Sources: [duck-ipc-proto/src/lib.rs](https://github.com/pollen-robotics/microduck/blob/main/duck-ipc-proto/src/lib.rs) ·
[architecture.md](https://github.com/pollen-robotics/microduck/blob/main/docs/design/architecture.md) (draft, 2026-07-22) ·
[robotd-design.md](https://github.com/pollen-robotics/microduck/blob/main/docs/design/robotd-design.md) ·
[remote-webrtc.md](https://github.com/pollen-robotics/microduck/blob/main/docs/design/remote-webrtc.md) ·
[roadmap.md](https://github.com/pollen-robotics/microduck/blob/main/docs/project/roadmap.md) (2026-08-26).

`--transport X` is a deprecated alias of `--robot microduck:X` (removed in 0.5).

### VERIFIED (read from upstream source)

| Thing | Value | Used for |
|---|---|---|
| API version | `16` | `hello` handshake; mismatch → we refuse rather than guess |
| Framing | `NDJSON: one JSON-RPC 2.0 object per line` | wire |
| Runtime dir | env `DUCK_RUNTIME_DIR` overrides `/run` | socket path |
| Sockets | `/run/robotd.sock`, `/run/configd.sock`, `/run/updaterd.sock`, `/run/padd/pad.sock` (pad.input only), `/run/tofd/tof.sock` (tof.stream only) | addresses |
| `hello` | params `{api_version}` → `{api_version, daemon_version?, revision?}` | connect |
| `robot.move` | **notification** `{vx, vy, vyaw}` m/s, rad/s, trunk frame, x forward, y left, +vyaw left | `move`, `go_to`, `search_scan` (re-sent every 100 ms) |
| `robot.stop` | request; zero velocity, *not* limp | `stop`, every run's final stop |
| `robot.head` | notification `{neck_pitch, head_pitch, head_yaw, head_roll}` | (not used; `robot.look` preferred) |
| `robot.look` | request `{x, y, z, neck_pitch}` → `{head, clamped}` | `gaze`, re-centering before steering |
| `robot.do` | request `{skill}` → `{accepted, reason?}`; skills `ground_pick | kick_left | kick_right | sit_toggle | roulade` | `kick`, `grab`, `sit`/`stand` |
| `robot.pose` | notification `{z, roll, pitch, active}` | `pose` intent (no verb yet) |
| `robot.enable` | request `{on, toggle?}` | `stand_up` |
| `robot.init` / `robot.relax` | torque on + ramp / torque **off** (collapse) | **never sent by quackd** |
| `robot.sound` | request `{tag, hold?}`; tags `alarm | greet | inquire | peck | chirp | coo | wheee` — no TTS | `quack` and `say` (text → tag) |
| `robot.subscribe` → `robot.state` | request `{hz?}`, then notifications `{t, move{requested,applied,limited_by}, head[4], policy, safety{fallen,limp,gravity,gain?}, loop{hz,..}, joints[15], targets, odom, ...}` | state |
| `robot.health` | request → `{healthy, degraded?, reason?, battery{volts,percent}?, motors?}` | heartbeat every 500 ms; battery abort |
| `robot.mode` / `robot.setMode` | `{mode: walk|roller}` | (not used yet) |
| `tof.stream` → `tof.frame` | 8×8 depth on tofd's socket | (not used yet) |
| `pad.input` | gamepad raw tap; the pad is the authority | documented, not used |
| `robotd intent deadman` | velocity zeroes when intents stop; "stop is not limp" | why `move` re-sends |

### UNVERIFIED (designed, assumed, or missing upstream) — and what we do

| Thing | Status upstream | What quackd does |
|---|---|---|
| `robot.state.policy == 'sit' means sitting` | assumption: the state frame names the active policy; we assume a sitting robot's name contains `sit` | `jsonrpc` infers posture from it and lists the assumption in `extras.assumptions`; `sit`/`stand` verbs read posture first |
| `WebSocket agent gateway` | architecture.md §5.3 designs "open a WebSocket, poll a frame, send intents"; roadmap M5 in progress, not shipped | `--robot microduck:websocket` is a stub that raises with the links |
| `get_frame` | §5.3: "JPEG on demand, or 1–2 fps push"; not in duck-ipc-proto | not called anywhere; the stub will use it when it exists |
| `camera snapshot over a unix socket` | today the camera reaches clients only through `mediad`'s WebRTC `control` datachannel; no socket-level frame method | `jsonrpc.get_frame()` returns `None` unless `--camera-url` points at an HTTP snapshot you provide |
| `mediad feature events ('ball at (x,y)', 'person detected')` | designed ("features, not frames"), not built | our `Detector` protocol is the stand-in; a socket-reading detector slots in later |
| `stand_up` | no such RPC; `robotd` recovers from falls itself (limp → settle → ramp → standing policy) | `stand_up` sends `robot.enable {on: true}` and checks `safety.fallen` afterwards |

### What we do not touch

`robot.init` (moves every joint), `robot.relax` (the robot collapses), `system.*`, `net.*`,
`update.*`. The gamepad (`padd`) keeps authority on hardware; quackd does not arbitrate.
The same principle holds on every adapter: `disable_motors` is never sent to a Reachy,
`disable_torque` never to an arm, and a base over rosbridge gets a zero Twist, not silence.

## How to help

Ran `--robot microduck:jsonrpc` against a real duck, `reachy_mini:sdk` against a Reachy
Mini (or its `--mockup-sim` daemon), `lerobot:real` against an arm, or `rosbridge:ws`
against a bridge? Open an issue with `quackd doctor` output and the first lines of
`transcript.jsonl`. Every row above that flips from 🧪/⏳ to ✅ is one line in an
`upstream_api.py` and one row here.
