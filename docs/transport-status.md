# Transport status — what upstream has shipped, what is a draft, and what we do about it

quackd never silently invents an upstream API. Every method name, socket path, enum or
convention we rely on lives in one file, [`quackd/transport/upstream_api.py`](../quackd/transport/upstream_api.py),
tagged **VERIFIED** (read from upstream source on the date below, link given) or
**UNVERIFIED** (designed upstream but not shipped, or an assumption of ours). A test proves
UNVERIFIED names are only reachable from the experimental and stub transports. `quackd
doctor` prints the UNVERIFIED list on your machine.

Read: 2026-08-28. Upstream contract: `duck-ipc-proto` **API v16** (`API_VERSION`),
JSON-RPC 2.0, one object per line (NDJSON), one unix socket per service.
Sources: [duck-ipc-proto/src/lib.rs](https://github.com/pollen-robotics/microduck/blob/main/duck-ipc-proto/src/lib.rs) ·
[architecture.md](https://github.com/pollen-robotics/microduck/blob/main/docs/design/architecture.md) (draft, 2026-07-22) ·
[robotd-design.md](https://github.com/pollen-robotics/microduck/blob/main/docs/design/robotd-design.md) ·
[remote-webrtc.md](https://github.com/pollen-robotics/microduck/blob/main/docs/design/remote-webrtc.md) ·
[roadmap.md](https://github.com/pollen-robotics/microduck/blob/main/docs/project/roadmap.md) (2026-08-26).

## Our transports

| `--transport` | Status | What it is |
|---|---|---|
| `sim2d` | ✅ default | Built-in cartoon world; no upstream dependency. |
| `mock` | ✅ | Scripted, for tests. |
| `jsonrpc` | 🧪 experimental | The real robot over `robotd`'s socket (`unix:///run/robotd.sock`) or an SSH-forwarded TCP port. Every method it uses is VERIFIED below; the whole has never run on hardware. |
| `websocket` | ⏳ stub | Tracks architecture.md §5.3. Raises with a link until upstream ships it. |

## VERIFIED (read from upstream source)

| Thing | Value | Used for |
|---|---|---|
| API version | `16` | `hello` handshake; mismatch → we refuse rather than guess |
| Framing | `NDJSON: one JSON-RPC 2.0 object per line` | wire |
| Runtime dir | env `DUCK_RUNTIME_DIR` overrides `/run` | socket path |
| Sockets | `/run/robotd.sock`, `/run/configd.sock`, `/run/updaterd.sock`, `/run/padd/pad.sock` (pad.input only), `/run/tofd/tof.sock` (tof.stream only) | addresses |
| `hello` | params `{api_version}` → `{api_version, daemon_version?, revision?}` | connect |
| `robot.move` | **notification** `{vx, vy, vyaw}` m/s, rad/s, trunk frame, x forward, y left, +vyaw left | `walk`, `walk_to`, `search_scan` (re-sent every 100 ms) |
| `robot.stop` | request; zero velocity, *not* limp | `stop`, every run's final stop |
| `robot.head` | notification `{neck_pitch, head_pitch, head_yaw, head_roll}` | (not used; `robot.look` preferred) |
| `robot.look` | request `{x, y, z, neck_pitch}` → `{head, clamped}` | `gaze`, re-centering before steering |
| `robot.do` | request `{skill}` → `{accepted, reason?}`; skills `ground_pick | kick_left | kick_right | sit_toggle | roulade` | `kick`, `grab`, `sit`/`stand` |
| `robot.pose` | notification `{z, roll, pitch, active}` | `pose` intent (no verb yet) |
| `robot.enable` | request `{on, toggle?}` | `stand_up` |
| `robot.init` / `robot.relax` | torque on + ramp / torque **off** (collapse) | **never sent by quackd** |
| `robot.sound` | request `{tag, hold?}`; tags `alarm | greet | inquire | peck | chirp | coo | wheee` — no TTS | `quack` (text → tag) |
| `robot.subscribe` → `robot.state` | request `{hz?}`, then notifications `{t, move{requested,applied,limited_by}, head[4], policy, safety{fallen,limp,gravity,gain?}, loop{hz,..}, joints[15], targets, odom, ...}` | state |
| `robot.health` | request → `{healthy, degraded?, reason?, battery{volts,percent}?, motors?}` | heartbeat every 500 ms; battery abort |
| `robot.mode` / `robot.setMode` | `{mode: walk|roller}` | (not used yet) |
| `tof.stream` → `tof.frame` | 8×8 depth on tofd's socket | (not used yet) |
| `pad.input` | gamepad raw tap; the pad is the authority | documented, not used |
| `robotd intent deadman` | velocity zeroes when intents stop; "stop is not limp" | why `walk` re-sends |

## UNVERIFIED (designed, assumed, or missing upstream) — and what we do

| Thing | Status upstream | What quackd does |
|---|---|---|
| `robot.state.policy == 'sit' means sitting` | assumption: the state frame names the active policy; we assume a sitting robot's name contains `sit` | `jsonrpc` infers posture from it and lists the assumption in `extras.assumptions`; `sit`/`stand` verbs read posture first |
| `WebSocket agent gateway` | architecture.md §5.3 designs "open a WebSocket, poll a frame, send intents"; roadmap M5 in progress, not shipped | `--transport websocket` is a stub that raises with the links |
| `get_frame` | §5.3: "JPEG on demand, or 1–2 fps push"; not in duck-ipc-proto | not called anywhere; the stub will use it when it exists |
| `camera snapshot over a unix socket` | today the camera reaches clients only through `mediad`'s WebRTC `control` datachannel; no socket-level frame method | `jsonrpc.get_frame()` returns `None` unless `--camera-url` points at an HTTP snapshot you provide |
| `mediad feature events ('ball at (x,y)', 'person detected')` | designed ("features, not frames"), not built | our `Detector` protocol is the stand-in; a socket-reading detector slots in later |
| `stand_up` | no such RPC; `robotd` recovers from falls itself (limp → settle → ramp → standing policy) | `stand_up` sends `robot.enable {on: true}` and checks `safety.fallen` afterwards |

## What we do not touch

`robot.init` (moves every joint), `robot.relax` (the robot collapses), `system.*`, `net.*`,
`update.*`. The gamepad (`padd`) keeps authority on hardware; quackd does not arbitrate.

## How to help

Ran `--transport jsonrpc` against a real duck? Open an issue with `quackd doctor` output and
the first lines of `transcript.jsonl`. Every row above that flips from 🧪/⏳ to ✅ is one
line in `upstream_api.py` and one row here.
