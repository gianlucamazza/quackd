# Security Policy

## What "security" means for a robot brain

quackd sends *intents* to a robot. How much of the stopping the robot itself does depends
on the body, and each adapter declares it in its manifest's `safety_authority`
(see `docs/safety.md`). On a Microduck, `robotd` is the safety authority: it clamps
velocities, detects falls, and zeroes motion when commands stall. On the other three
bodies shipped in 0.4 there is no deadman we verified — a Reachy Mini and a rosbridge base
declare `native: none`, and a LeRobot arm has a torque limit but holds its last goal — so
quackd's own heartbeat and `stop` are the only thing that stops them. That makes the
client-side layer (verb allowlists, confirm gates, budgets, the heartbeat, the kill switch)
security-relevant, not just a convenience. A bug that lets an LLM or an MCP client bypass
it is a security issue.

Also in scope:

- API keys leaking into transcripts, GIFs, logs, or run directories.
- The MCP server executing verbs a loaded `.duck` contract does not allow.
- Anything that lets a `.duck` file (untrusted input — people will share them) execute
  code, read files, or reach the network.
- An adapter sending a body's "go limp" call (`robot.relax`, `disable_motors`,
  `disable_torque`) as if it were `stop`. Stop means stop, never collapse.
- The LAN surfaces behind `quackd[lan]`: zeroconf TXT records advertise a robot's identity
  to anything on the network, and the MQTT flock bus carries messages that command robots
  with no authentication of its own. Both are off by default and neither has a threat model
  yet, so treat them as trusted-network only.

## Reporting

Please **do not** open a public issue for vulnerabilities. Email
**ksjeno@gmail.com** with "quackd security" in the subject, or use GitHub's private
vulnerability reporting on the repository if enabled. You will get an acknowledgement
within 72 hours.

## Supported versions

Only the latest released minor version receives fixes.
