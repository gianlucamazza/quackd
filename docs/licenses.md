# Licenses

| What | License | Our relationship |
|---|---|---|
| quackd (this repository) | [Apache-2.0](../LICENSE) | Ours. `NOTICE` credits upstream. |
| [microduck](https://github.com/pollen-robotics/microduck) — the onboard daemon stack, `duck-ipc-proto` | Apache-2.0 | We interoperate with its JSON-RPC contract. We copy method names and enum values (facts), not code. |
| [microduck_rl](https://github.com/pollen-robotics/microduck_rl) — training stack, ONNX policies | code Apache-2.0 | We cite the policy contract (`obs[61] → act[14]`, 50 Hz). Nothing vendored. |
| microduck_rl **3D model files** (meshes) | **CC BY-NC-SA** | **Never vendored.** If a future MuJoCo backend needs them, it fetches them from upstream at runtime into a user cache, prints the license, and stays optional. Non-commercial + share-alike terms apply to *that* asset use, not to quackd's code. |
| Pollen Robotics / Microduck / Hugging Face names and logos | trademarks | Nominative use only. No logos, videos or brand assets in this repo. quackd is unofficial and says so in README and NOTICE. |
| [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) | MIT | dependency |
| typer, rich, pydantic, numpy, Pillow, opencv-python-headless, python-dotenv | MIT / BSD / Apache | dependencies (see `uv.lock`) |
| ultralytics (optional `[yolo]`) | AGPL-3.0 | optional extra, lazily imported, never required; if you ship a product on it, read its license |
| pygame (optional `[live]`) | LGPL | optional extra |
| [reachy_mini](https://github.com/pollen-robotics/reachy_mini) (optional `[reachy]`) | Apache-2.0 | optional extra, imported only inside `connect()`. We cite method names read at a pinned commit (facts), not code. See [adapters/reachy_mini.md](adapters/reachy_mini.md) |
| [LeRobot](https://github.com/huggingface/lerobot) (optional `[lerobot]`) | Apache-2.0 | optional extra, Python 3.12 or newer, pulls torch. Imported only inside `connect()`. See [adapters/lerobot.md](adapters/lerobot.md) |
| [roslibpy](https://github.com/gramaziokohler/roslibpy) (optional `[rosbridge]`) | MIT | optional extra. The protocol it speaks is [rosbridge_suite](https://github.com/RobotWebTools/rosbridge_suite) (BSD-3-Clause) and the message shapes are [common_interfaces](https://github.com/ros2/common_interfaces) (Apache-2.0). Names only, nothing vendored |
| python-zeroconf (optional `[lan]`) | **LGPL-2.1** | optional extra for `quackd discover` / `announce`, imported lazily and never on the default path. Dynamic linking as a library; if you redistribute, read its terms |
| paho-mqtt (optional `[lan]`) | EPL-2.0 / EDL-1.0 | optional extra for the MQTT flock bus, imported lazily |

Contributions are accepted under Apache-2.0 (see `LICENSE` §5). Do not submit code or
assets you do not have the right to license that way — including upstream meshes.
