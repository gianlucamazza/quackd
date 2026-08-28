# Licenses

| What | License | Our relationship |
|---|---|---|
| quackd (this repository) | [Apache-2.0](../LICENSE) | Ours. `NOTICE` credits upstream. |
| [microduck](https://github.com/pollen-robotics/microduck) — the onboard daemon stack, `duck-ipc-proto` | Apache-2.0 | We interoperate with its JSON-RPC contract. We copy method names and enum values (facts), not code. |
| [microduck_rl](https://github.com/pollen-robotics/microduck_rl) — training stack, ONNX policies | code Apache-2.0 | We cite the policy contract (`obs[61] → act[14]`, 50 Hz). Nothing vendored. |
| microduck_rl **3D model files** (meshes) | **CC BY-NC-SA** | **Never vendored.** If a future MuJoCo transport needs them, it fetches them from upstream at runtime into a user cache, prints the license, and stays optional. Non-commercial + share-alike terms apply to *that* asset use, not to quackd's code. |
| Pollen Robotics / Microduck / Hugging Face names and logos | trademarks | Nominative use only. No logos, videos or brand assets in this repo. quackd is unofficial and says so in README and NOTICE. |
| [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) | MIT | dependency |
| typer, rich, pydantic, numpy, Pillow, opencv-python-headless, python-dotenv | MIT / BSD / Apache | dependencies (see `uv.lock`) |
| ultralytics (optional `[yolo]`) | AGPL-3.0 | optional extra, lazily imported, never required; if you ship a product on it, read its license |
| pygame (optional `[live]`) | LGPL | optional extra |

Contributions are accepted under Apache-2.0 (see `LICENSE` §5). Do not submit code or
assets you do not have the right to license that way — including upstream meshes.
