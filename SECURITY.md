# Security Policy

## What "security" means for a robot brain

quackd sends *intents* to a robot. How much of the stopping the robot itself does depends
on the body, and each adapter declares it in its manifest's `safety_authority`
(see `docs/safety.md`). On a Microduck, `robotd` is the safety authority: it clamps
velocities, detects falls, and zeroes motion when commands stall. On an Open Duck Mini the
deadman is quackd's own daemon, running on the robot and zeroing the velocity inside the
50 Hz loop, so it is code we ship and therefore code we are answerable for. On the other
three bodies there is no deadman we verified: a Reachy Mini and a rosbridge base declare
`native: none`, and a LeRobot arm has a torque limit but holds its last goal, so quackd's
own heartbeat and `stop` are the only thing that stops them. That makes the client-side
layer (verb allowlists, confirm gates, budgets, the heartbeat, the kill switch)
security-relevant, not just a convenience. A bug that lets an LLM or an MCP client bypass
it is a security issue.

Since 0.5 quackd also ships code that runs **on a robot**, which is a different kind of
surface from everything above. `bridge/open_duck/` holds two daemons for an Open Duck Mini
v2's Raspberry Pi, and they are in scope in their own right.

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
- **The bridge daemon** (`bridge/open_duck/quackd_duck_bridge.py`), a TCP listener on port
  9871 that walks a 42 cm biped. It binds loopback by default and compares a token with
  `hmac.compare_digest`, but a token is only required if one is configured, and binding it
  wide only warns. Anything that lets an unauthenticated peer move the robot, defeat the
  300 ms deadman, exceed the clamps, or reach past the seven floats the protocol exposes is
  a security issue. Going limp is currently unreachable by construction, and it should stay
  that way: there is no method in the protocol that touches torque.
- **The camera daemon** (`bridge/open_duck/quackd_duck_camd.py`), an HTTP server on port
  9872 that serves a live view of wherever the robot is, with **no authentication at all**.
  It binds loopback by default and warns when told otherwise. Reach it through an ssh
  tunnel. If you bind it wide, everyone on that network can watch your home.
- The recommended deployment for both is `ssh -L 9871:127.0.0.1:9871 -L 9872:127.0.0.1:9872`
  rather than exposing either port.

## Reporting

Please **do not** open a public issue for vulnerabilities. Email
**ksjeno@gmail.com** with "quackd security" in the subject, or use GitHub's private
vulnerability reporting on the repository if enabled. You will get an acknowledgement
within 72 hours.

## Supported versions

Only the latest released minor version receives fixes.

The on-robot daemons carry their own versions (`BRIDGE_VERSION`, `CAMD_VERSION`) and live
on someone else's Raspberry Pi, so they can drift from the quackd that talks to them. The
handshake carries both and refuses a protocol mismatch rather than guessing, but a daemon
you installed months ago is a daemon that has not had your fixes. `quackd doctor --robot
open_duck:bridge --address ...` prints what your robot is actually running.
