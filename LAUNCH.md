# LAUNCH.md — how quackd goes public

Internal. Write it, don't publish it. Everything here serves one demo: a stranger with `uv`
watches a simulated duck find a ball and kick it, driven by an LLM, in under a minute.

## Positioning per channel

| Channel | One line |
|---|---|
| GitHub | Pilot Pollen Robotics' $399 Microduck biped with any LLM via `.duck` skill files and MCP. Built-in simulator — no hardware needed. |
| Hacker News | A `.duck` file is a SKILL.md for a robot: the frontmatter is enforced, the body is the prompt, the executor never trusts the model. |
| X / Twitter | Give your Microduck a brain. Any LLM, one `.duck` file. 🦆🧠 |
| Pollen Discord | We built the brain daemon that was missing from `robotd / mediad / padd / tofd` — and we'd like you to tell us what we got wrong about the socket API. |
| Robotics / RL folks | Three loops: 50 Hz RL reflexes onboard, 10 Hz steering in Python, ~0.5 Hz LLM deliberation. The registry hook for learned verbs is the v2 story. |
| Local-LLM folks (r/LocalLLaMA, llama.cpp / vLLM / Ollama Discords) | Your own model pilots a robot, no API key: `quackd run find-and-kick --provider ollama`. Weak tool callers get a JSON text fallback. We have not benchmarked local models yet, so a transcript is a contribution. |

## Show HN title candidates

1. **Show HN: Pilot Hugging Face's $399 robot duck with any LLM (no hardware needed)**
2. Show HN: quackd – a SKILL.md-style file format that makes an LLM drive a biped robot, safely
3. Show HN: I gave a $399 open-source robot duck a brain (Claude/OpenAI/Gemini, MCP, built-in sim)

First comment (post immediately): what it is in three sentences, the three-loop table, the
honesty paragraph (sim now, hardware transport experimental until Christmas), and the ask
("add a `.duck` to `ducks/`").

## X thread (7 posts)

1. **Hook + GIF.** "I gave a $399 robot duck a brain. Here's Claude finding a ball and kicking it — in a simulator you can run in 60 seconds. 🧵" *(hero.gif)*
2. **What.** quackd: pilot Pollen Robotics' Microduck with any LLM. One `.duck` file per task. Any provider. MCP so Claude Code/Desktop can drive it interactively. Apache-2.0.
3. **Three loops.** The LLM decides *what*, a 10 Hz Python loop decides *how*, the robot's 50 Hz RL policies keep it upright. LLM latency never touches balance. *(three-loop table image)*
4. **The `.duck` file.** Screenshot of `find-and-kick.duck`. "Frontmatter is a contract the executor enforces — allowlist, budgets, confirm gates. The body is the prompt. The model is never trusted to self-police."
5. **MCP demo.** Short screen capture: `claude mcp add quackd -- uvx quackd serve-mcp`, then "make the duck patrol my desk". Same safety layer applies.
6. **Roadmap tease.** "v2: learned verbs. An LLM writes a reward (DrEureka-style), the training stack produces a policy, and it registers as one more verb the LLM can call. The hook exists today; the loop doesn't. Yet."
7. **CTA.** "It's sim-first and honest about it — the hardware transport ships experimental until Microducks arrive at Christmas. If you write a `.duck`, PR it to `ducks/`. Repo: github.com/rokbenko/quackd"

## Pollen Discord post (draft)

> Hi all — long-time fan, first-time duck-brain author. I've been building **quackd**, an
> unofficial "brain daemon" for Microduck: any LLM drives the robot through a small verb
> vocabulary defined in a `.duck` file, with a built-in 2D sim so it works before hardware
> ships. Demo GIF attached (sim, scripted pilot; real-model runs need a key).
>
> Two things I'd really value from the people who built the real thing:
> 1. **Transport assumptions.** I read `duck-ipc-proto` (API v16) and mapped verbs to
>    `robot.move` (as notifications, feeding the deadman), `robot.do{skill}`, `robot.look`,
>    `robot.sound{tag}`, `robot.health` as the heartbeat. Everything I couldn't verify is
>    tagged UNVERIFIED in one file — mainly: how to read posture from `robot.state.policy`,
>    and that there's no socket-level camera snapshot yet. Corrections very welcome.
> 2. **The WebSocket agent surface** from architecture.md §5.3 — I have a stub waiting for
>    it. If the design changes, I'd rather track it than guess.
>
> No Pollen assets are used (no meshes, no logos), Apache-2.0 like upstream, and the
> README says "unofficial" up top. Thank you for building the duck. Repo: <link>

Post this **before** HN/X. Maintainers first, publicity second.

## GIF shot list

1. **find-and-kick (sim).** `quackd record find-and-kick --provider anthropic --seed 3` once a key is available; keep the scripted one labelled until then. 720 px wide, ≤ 3 MB, ≤ 25 s.
2. **Claude Desktop piloting via MCP.** Screen capture: connector listed → "list the duck's verbs" → "find the ball and kick it" → the sim GIF frames from `runs/`. Crop to the chat + the run's GIF side by side.
3. **validate fail-fast.** Terminal: a `.duck` with `confirm: [kick]` but `kick` not in `allow` → the red field-level error → fix → green. 10 s.
4. (Optional) `quackd doctor` on a machine with no keys, showing the honesty table.

## Timing

- **Now: sim-first launch.** Discord post → 24 h → Show HN (Tue–Thu, 8–10 am ET) → X thread the same hour.
- **Second beat: Christmas 2026**, when Microducks ship: "it works on the real duck" — a hardware run of the same five ducks, `jsonrpc` flipped to ✅, and the WebSocket transport if upstream shipped it. Re-post to the same channels; that's the launch that earns v1.

## Metrics that matter

- Stars are vanity.
- `.duck` PRs from strangers are the real KPI. Secondary: issues that correct an UNVERIFIED
  row (that means a maintainer read `transport-status.md`), and MCP-session screenshots.
- Track: PRs to `ducks/` per week, unique authors, time-to-first-response (< 24 h).
