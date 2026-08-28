# Security Policy

## What "security" means for a robot brain

quackd sends *intents* to a robot. The robot's own daemon (`robotd`) is the safety
authority — it clamps velocities, detects falls, and stops the robot when commands stall.
quackd adds a second layer on the client side: verb allowlists, confirm gates, budgets,
a heartbeat, and a kill switch (see `docs/safety.md`). A bug that lets an LLM or an MCP
client bypass that layer is a security issue.

Also in scope:

- API keys leaking into transcripts, GIFs, logs, or run directories.
- The MCP server executing verbs a loaded `.duck` contract does not allow.
- Anything that lets a `.duck` file (untrusted input — people will share them) execute
  code, read files, or reach the network.

## Reporting

Please **do not** open a public issue for vulnerabilities. Email
**ksjeno@gmail.com** with "quackd security" in the subject, or use GitHub's private
vulnerability reporting on the repository if enabled. You will get an acknowledgement
within 72 hours.

## Supported versions

Only the latest released minor version receives fixes.
