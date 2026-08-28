# FAQ

**Why is the simulator a cartoon?** Because the demo tests the *agent loop* — search,
approach, act, verify — not contact dynamics. Upstream's real simulator needs a GPU and
CC BY-NC-SA meshes we will not vendor. `sim2d` runs anywhere in seconds and the same
detector works on its duck-cam and on a real camera. ([ADR-0007](adr/0007-sim2d-cartoon.md))

**Does `uvx quackd run … --provider anthropic` work with no extras?** The default install
is light on purpose (no vendor SDKs). Use `uvx --from "quackd[anthropic]" quackd run …`, or
`uv pip install "quackd[anthropic]"`. Without the extra, quackd prints exactly that command.
`--provider fake` needs nothing.

**Which models are the defaults?** `anthropic` → `claude-opus-5`; `openai` → `gpt-5`;
`gemini` → `gemini-2.5-pro`; `grok` → `grok-4`. The non-Anthropic IDs were not verified
against vendor docs at release (no keys in CI) — override with `--model` or `QUACKD_MODEL`
if yours differs. Anthropic extras: `QUACKD_EFFORT` (default `medium`) and
`QUACKD_ANTHROPIC_FALLBACKS=0` to disable server-side refusal fallbacks.

**How does the LLM "see"?** Providers with vision get the duck-cam PNG for the last two
turns; every provider gets a text line like `ball at bearing 12° left, ~0.80 m` from the
detector. Composite verbs steer on detections at 10 Hz and never wait for the model.

**How do I tune the detector for a real orange ball?** `ColorBlobDetector` takes
`targets=(Target("ball", HSVRange(h_lo, h_hi, s_lo, v_lo), size_m=radius, round=True), …)`
in OpenCV HSV (H 0–180). Photograph the ball under your light, sample its hue, give ±8, and
set `fov_deg=62` for the IMX219. Distance comes from apparent size: measure the pixel radius
at 1 m once and adjust `size_m` until it reads 1.00. Or install `quackd[yolo]` and use
`YoloDetector`.

**Who decides the run succeeded?** The LLM, via `declare_success(reason)` — that is the
honest state of the art. In `sim2d` the run summary also records ground truth
(`ball_displacement_m`) and the tests check the claim against it.

**Why can't the duck say words?** Upstream has seven duck sounds and no TTS. `quack(text)`
maps your text to the closest tone (`greet`, `inquire`, `alarm`, `wheee`, …) and logs the
text.

**What does it cost?** A `find-and-kick` run is 3–8 model turns, each a few thousand input
tokens (mostly the system prompt and one image) and a short tool call. `transcript.jsonl`
records usage per turn.

**Windows?** Fully supported for sim, MCP and development. The real-robot `unix://` socket
is POSIX-only; forward it with `ssh -L 9870:/run/robotd.sock <robot>` and use
`--address tcp://127.0.0.1:9870`.

**Can I run it on my Microduck today?** `--transport jsonrpc` speaks the verified
`duck-ipc-proto` v16 vocabulary but has never touched hardware. Start with `--dry-run`,
read [transport-status.md](transport-status.md), and tell us what happened.

**Why "quackd"?** Upstream names its daemons `robotd`, `mediad`, `padd`, `tofd`… the brain
daemon was missing. ([ADR-0002](adr/0002-name.md))
